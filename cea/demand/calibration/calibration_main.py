"""
===========================
Bayesian calibration routine

based on work of (Patil_et_al, 2010 - #http://www.map.ox.ac.uk/media/PDF/Patil_et_al_2010.pdf) in MCMC in pyMC3
and the works of bayesian calibration of (Kennedy and O'Hagan, 2001)
===========================
J. Fonseca  script development          27.10.16


"""

from __future__ import division

import pandas as pd
import pymc3 as pm
from pymc3.backends import SQLite
import theano.tensor as tt
import theano
from cea.demand import demand_main
import matplotlib.pyplot as plt

import cea.globalvar as gv

__author__ = "Jimeno A. Fonseca"
__copyright__ = "Copyright 2016, Architecture and Building Systems - ETH Zurich"
__credits__ = ["Jimeno A. Fonseca"]
__license__ = "MIT"
__version__ = "0.1"
__maintainer__ = "Daren Thomas"
__email__ = "cea@arch.ethz.ch"
__status__ = "Production"


def calibration_main(locator, weather_path, building_name, variables, building_load, retrieve_results, niter):

    # create function of demand calculation and send to theano
    @theano.compile.ops.as_op(itypes=[tt.dscalar, tt.dscalar, tt.dscalar, tt.dscalar], otypes=[tt.dvector])
    def demand_calculation(phi, err, u_win, u_wall):
        gv.samples = {'U_win': u_win, 'U_wall': u_wall}
        gv.multiprocessing = False
        demand_main.demand_calculation(locator, weather_path, gv)  # simulation
        result = pd.read_csv(locator.get_demand_results_file(building_name), usecols=[building_load]) * (1 + phi + err)
        out = result[building_load].values
        print out, phi, err, u_win, u_wall
        return out

    # import arguments of probability density functions (PDF) of variables and create priors:
    pdf = pd.concat([pd.read_excel(locator.get_uncertainty_db(), group, axis=1) for group in
                     ['THERMAL', 'ARCHITECTURE', 'INDOOR_COMFORT', 'INTERNAL_LOADS']]).set_index('name')

    # import measured data for building and building load:
    obs_data = pd.read_csv(locator.get_demand_measured_file(building_name))[building_load].values

    # create bayesian calibration model in PYMC3
    with pm.Model() as basic_model:

        # add all variables to the model and assign a triangular distribution
        # for this we create a local variable out of the strings included in the list variables
        for variable in variables:
            variable = Triangular('variable', c=pdf.loc[variable, 'mu'], lower=pdf.loc[variable, 'min'],
                                                    upper=pdf.loc[variable, 'max'])

        # get priors for the model inaquacy and the measurement errors.
        phi = pm.Uniform('phi', lower=0, upper=0.01)
        err = pm.Uniform('err', lower=0, upper=0.02)
        sigma = pm.Normal('sigma', sd=1)

        # expected value of outcome
        mu = pm.Deterministic('mu', demand_calculation(phi, err, u_win, u_wall))

        # Likelihood (sampling distribution) of observations
        y_obs = pm.Normal('y_obs', mu=mu, sd=sigma, observed=obs_data)

    if retrieve_results:
        with basic_model:
            trace = pm.backends.text.load(locator.get_calibration_folder())
            pm.traceplot(trace)
            plt.show()
    else:

        with basic_model:
            step = pm.Metropolis()
            trace = pm.sample(niter, step=step)
            pm.backends.text.dump(locator.get_calibration_folder(), trace)
    return


# Create Triangular distributions
from pymc3.distributions.distribution import Continuous, draw_values, generate_samples
from scipy import stats
import numpy as np


class Triangular(Continuous):
    R"""
    Continuous Triangular log-likelihood.

    Parameters
    ----------
    lower : float
        Lower limit.
    c: float
        mode
    upper : float
        Upper limit.
    """

    def __init__(self, lower=0, upper=1, c=0.5, transform='interval',
                 *args, **kwargs):
        super(Triangular, self).__init__(*args, **kwargs)

        self.c = c
        self.lower = lower
        self.upper = upper
        self.mean = c
        self.median = self.mean

    def random(self, point=None, size=None, repeat=None):
        lower, c, upper = draw_values([self.lower, self.c, self.upper],
                                      point=point)
        return generate_samples(stats.triang.rvs, c=c, loc=lower, scale=upper - lower,
                                size=size, random_state=None)


    def logp(self, value):
        c = self.c
        lower = self.lower
        upper = self.upper
        return triang_logp(lower, upper, c, value)


@theano.compile.ops.as_op(itypes=[tt.dscalar, tt.dscalar, tt.dscalar, tt.dscalar], otypes=[tt.dscalar])
def triang_logp(lower, upper, c, value):
    if lower <= value < c:
        return -tt.log(2 * (value - lower) / ((upper - lower) * (c - lower)))
    elif value is c:
        return -tt.log(2 / (upper - lower))
    elif c < value <= upper:
        return -tt.log(2 * (upper - value) / ((upper - lower) * (upper - c)))
    else:
        return -np.inf


def run_as_script():
    import cea.inputlocator as inputlocator
    import cea.globalvar as gv
    gv = gv.GlobalVariables()
    scenario_path = gv.scenario_reference
    locator = inputlocator.InputLocator(scenario_path=scenario_path)
    weather_path = locator.get_default_weather()
    variables = {'U_win':None, 'U_roof':None, 'Ths_setb_C':None,
                 'Ths_set_C':None}  # based on the variables listed in the uncertainty database and selected through a screeing process
    building_name = 'B01'
    building_load = 'Qhsf_kWh'
    retrieve_results = False  # flag to retrieve and analyze results from calibration
    calibration_main(locator, weather_path, building_name, variables, building_load, retrieve_results, niter=100)

if __name__ == '__main__':
    run_as_script()
