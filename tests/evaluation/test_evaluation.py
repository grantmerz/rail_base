from unittest.mock import Mock, patch

import os

import numpy as np
import qp

import rail.evaluation.metrics.pointestimates as pe
from rail.core.data import QPHandle, TableHandle,  QPOrTableHandle
from rail.core.stage import RailStage
from rail.utils.path_utils import find_rail_file
from rail.evaluation.evaluator import OldEvaluator
from rail.evaluation.dist_to_dist_evaluator import DistToDistEvaluator
from rail.evaluation.dist_to_point_evaluator import DistToPointEvaluator
from rail.evaluation.point_to_point_evaluator import PointToPointEvaluator
from rail.evaluation.single_evaluator import SingleEvaluator

# values for metrics
OUTRATE = 0.0
KSVAL = 0.367384
CVMVAL = 20.63155
ADVAL_ALL = 82.51480
ADVAL_CUT = 1.10750
CDEVAL = -4.31200
SIGIQR = 0.0045947
BIAS = -0.00001576
OUTRATE = 0.0
SIGMAD = 0.0046489


def _get_files():
    possible_local_file = './examples_data/evaluation_data/data/output_fzboost.hdf5'
    if os.path.exists(possible_local_file):
        pdfs_file = os.path.abspath(possible_local_file)
    else:
        pdfs_file = 'examples_data/evaluation_data/data/output_fzboost.hdf5'
        try:
            os.makedirs(os.path.dirname(pdfs_file))
        except FileExistsError:
            pass
        curl_com = f"curl -o {pdfs_file} https://portal.nersc.gov/cfs/lsst/PZ/output_fzboost.hdf5"
        os.system(curl_com)
    ztrue_file = find_rail_file('examples_data/testdata/test_dc2_validation_9816.hdf5')
    return pdfs_file, ztrue_file

    
def construct_test_ensemble():
    np.random.seed(87)
    nmax = 2.5
    NPDF = 399
    true_zs = np.random.uniform(high=nmax, size=NPDF)
    locs = np.expand_dims(true_zs + np.random.normal(0.0, 0.01, NPDF), -1)
    true_ez = (locs.flatten() - true_zs) / (1.0 + true_zs)
    scales = np.ones((NPDF, 1)) * 0.1 + np.random.uniform(size=(NPDF, 1)) * 0.05
    n_ens = qp.Ensemble(qp.stats.norm, data=dict(loc=locs, scale=scales))  # pylint: disable=no-member
    zgrid = np.linspace(0, nmax, 301)
    grid_ens = n_ens.convert_to(qp.interp_gen, xvals=zgrid)
    return zgrid, true_zs, grid_ens, true_ez


def test_point_metrics():
    zgrid, zspec, pdf_ens, true_ez = construct_test_ensemble()
    zb = pdf_ens.mode(grid=zgrid).flatten()

    ez = pe.PointStatsEz(zb, zspec).evaluate()
    assert np.allclose(ez, true_ez, atol=1.0e-2)
    # grid limits ez vals to ~10^-2 tol

    sig_iqr = pe.PointSigmaIQR(zb, zspec).evaluate()
    assert np.isclose(sig_iqr, SIGIQR)

    bias = pe.PointBias(zb, zspec).evaluate()
    assert np.isclose(bias, BIAS)

    out_rate = pe.PointOutlierRate(zb, zspec).evaluate()
    assert np.isclose(out_rate, OUTRATE)

    sig_mad = pe.PointSigmaMAD(zb, zspec).evaluate()
    assert np.isclose(sig_mad, SIGMAD)


def test_evaluation_stage():
    DS = RailStage.data_store
    _zgrid, zspec, pdf_ens, _true_ez = construct_test_ensemble()
    pdf = DS.add_data("pdf", pdf_ens, QPHandle)
    truth_table = dict(redshift=zspec)
    truth = DS.add_data("truth", truth_table, TableHandle)
    evaluator = OldEvaluator.make_stage(name="Eval")
    evaluator.evaluate(pdf, truth)

    os.remove(
        evaluator.get_output(evaluator.get_aliased_tag("output"), final_name=True)
    )


def test_dist_to_dist_evaluator():
    DS = RailStage.data_store
    DS.__class__.allow_overwrite = True
    pdfs_file, ztrue_file = _get_files()
    stage_dict = dict(
        #metrics=['cvm', 'ks', 'rmse', 'kld', 'ad'],
        metrics=['rmse'],
        _random_state=None,
    )

    ensemble = DS.read_file(key='pdfs_data', handle_class=QPHandle, path=pdfs_file)

    dtd_stage = DistToDistEvaluator.make_stage(name='dist_to_dist', **stage_dict)
    dtd_stage_single = DistToDistEvaluator.make_stage(name='dist_to_dist_single', force_exact=True, **stage_dict)

    dtd_results = dtd_stage.evaluate(ensemble, ensemble)
    dtd_results_single = dtd_stage_single.evaluate(ensemble, ensemble)


def test_dist_to_point_evaluator():
    DS = RailStage.data_store
    DS.__class__.allow_overwrite = True
    pdfs_file, ztrue_file = _get_files()
    stage_dict = dict(
        metrics=['cdeloss', 'pit', 'brier'],
        _random_state=None,
        metric_config={
            'brier': {'limits':(0,3.1)},
        },
        limits=[0., 3.1],
    )

    ensemble = DS.read_file(key='pdfs_data', handle_class=QPHandle, path=pdfs_file)
    ztrue_data = DS.read_file('ztrue_data', TableHandle, ztrue_file)

    dtp_stage = DistToPointEvaluator.make_stage(name='dist_to_point', **stage_dict)
    dtp_stage_single = DistToPointEvaluator.make_stage(name='dist_to_point_single', force_exact=True, **stage_dict)

    dtp_results = dtp_stage.evaluate(ensemble, ztrue_data)
    dtp_results_single = dtp_stage_single.evaluate(ensemble, ztrue_data)

    qp_dict = qp.read_dict(dtp_results_single['single_distribution_summary'].path)
    assert qp_dict['pit'].npdf == 1

    qp_dict_handle = dtp_results_single['single_distribution_summary']
    qp_dict_handle.data = None
    qp_dict_2 = qp_dict_handle.read()
    assert qp_dict_2['pit'].npdf == 1

    qp_dict_handle.data = None

    with qp_dict_handle.open() as qp_dict_data:
        assert qp_dict_data
    
    
def test_point_to_point_evaluator():
    DS = RailStage.data_store
    DS.__class__.allow_overwrite = True
    pdfs_file, ztrue_file = _get_files()
    stage_dict = dict(
        metrics=['point_stats_ez', 'point_stats_iqr', 'point_bias', 'point_outlier_rate', 'point_stats_sigma_mad'],
        _random_state=None,
        hdf5_groupname='photometry',
        point_estimate_key='zmode',
        chunk_size=10000,
    )

    ensemble = DS.read_file(key='pdfs_data', handle_class=QPHandle, path=pdfs_file)
    ztrue_data = DS.read_file('ztrue_data', TableHandle, ztrue_file)

    ptp_stage = PointToPointEvaluator.make_stage(name='point_to_point', **stage_dict)
    ptp_stage_single = PointToPointEvaluator.make_stage(name='point_to_point_single', force_exact=True, **stage_dict)
    
    ptp_results = ptp_stage.evaluate(ensemble, ztrue_data)
    ptp_results_single = ptp_stage_single.evaluate(ensemble, ztrue_data)



def test_single_evaluator():
    DS = RailStage.data_store
    DS.__class__.allow_overwrite = True
    pdfs_file, ztrue_file = _get_files()
    stage_dict = dict(
        metrics=['cvm', 'ks', 'omega', 'kld', 'cdeloss', 'point_stats_ez', 'point_stats_iqr'],
        _random_state=None,
        hdf5_groupname='photometry',
        point_estimates=['zmode'],
        truth_point_estimates=['redshift'],
        chunk_size=1000,
    )
    ensemble_d = DS.add_data('pdfs_data_2', None, QPOrTableHandle, path=pdfs_file)
    ztrue_data_d = DS.add_data('ztrue_data_2', None, QPOrTableHandle, path=ztrue_file)

    single_stage = SingleEvaluator.make_stage(name='single', **stage_dict)
    single_stage_single = SingleEvaluator.make_stage(name='single_single', force_exact=True, **stage_dict)

    single_results = single_stage.evaluate(ensemble_d, ztrue_data_d)
    single_results_single = single_stage_single.evaluate(ensemble_d, ztrue_data_d)
