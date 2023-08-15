"""
Abstract base classes defining Estimators of individual galaxy redshift uncertainties
"""

from rail.core.common_params import SHARED_PARAMS
from rail.core.data import TableHandle, QPHandle, ModelHandle
from rail.core.stage import RailStage

import gc

from rail.estimation.informer import CatInformer
# for backwards compatibility


class CatEstimator(RailStage):
    """The base class for making photo-z posterior estimates from catalog-like inputs
    (i.e., tables with fluxes in photometric bands among the set of columns)

    Estimators use a generic "model", the details of which depends on the sub-class.

    They take as "input" tabular data, apply the photo-z estimation and
    provide as "output" a QPEnsemble, with per-object p(z).

    """

    name = 'CatEstimator'
    config_options = RailStage.config_options.copy()
    config_options.update(
        chunk_size=10000,
        hdf5_groupname=SHARED_PARAMS['hdf5_groupname'],
        calculated_point_estimates=SHARED_PARAMS['calculated_point_estimates'])
    inputs = [('model', ModelHandle),
              ('input', TableHandle)]
    outputs = [('output', QPHandle)]

    def __init__(self, args, comm=None):
        """Initialize Estimator"""
        RailStage.__init__(self, args, comm=comm)
        self._output_handle = None
        self.model = None

    def open_model(self, **kwargs):
        """Load the mode and/or attach it to this Estimator

        Parameters
        ----------
        model : `object`, `str` or `ModelHandle`
            Either an object with a trained model,
            a path pointing to a file that can be read to obtain the trained model,
            or a `ModelHandle` providing access to the trained model.

        Returns
        -------
        self.model : `object`
            The object encapsulating the trained model.
        """
        model = kwargs.get('model', None)
        if model is None or model == 'None':
            self.model = None
            return self.model
        if isinstance(model, str):
            self.model = self.set_data('model', data=None, path=model)
            self.config['model'] = model
            return self.model
        if isinstance(model, ModelHandle):
            if model.has_path:
                self.config['model'] = model.path
        self.model = self.set_data('model', model)
        return self.model

    def estimate(self, input_data):
        """The main interface method for the photo-z estimation

        This will attach the input_data to this `Estimator`
        (for introspection and provenance tracking).

        Then it will call the run() and finalize() methods, which need to
        be implemented by the sub-classes.

        The run() method will need to register the data that it creates to this Estimator
        by using `self.add_data('output', output_data)`.

        Finally, this will return a QPHandle providing access to that output data.

        Parameters
        ----------
        input_data : `dict` or `ModelHandle`
            Either a dictionary of all input data or a `ModelHandle` providing access to the same

        Returns
        -------
        output: `QPHandle`
            Handle providing access to QP ensemble with output data
        """
        self.set_data('input', input_data)
        self.run()
        self.finalize()
        return self.get_handle('output')

    def run(self):

        self.open_model(**self.config)

        iterator = self.input_iterator('input')
        first = True
        self._initialize_run()
        self._output_handle = None
        for s, e, test_data in iterator:
            print(f"Process {self.rank} running estimator on chunk {s} - {e}")
            self._process_chunk(s, e, test_data, first)
            first = False
            # Running garbage collection manually seems to be needed
            # to avoid memory growth for some estimators
            gc.collect()
        self._finalize_run()

    def _initialize_run(self):
        self._output_handle = None

    def _finalize_run(self):
        self._output_handle.finalize_write()

    def _process_chunk(self, start, end, data, first):
        raise NotImplementedError(f"{self.name}._process_chunk is not implemented")  # pragma: no cover

    def _do_chunk_output(self, qp_dstn, start, end, first):
        if first:
            self._output_handle = self.add_handle('output', data=qp_dstn)
            self._output_handle.initialize_write(self._input_length, communicator=self.comm)
        self._output_handle.set_data(qp_dstn, partial=True)
        self._output_handle.write_chunk(start, end)
