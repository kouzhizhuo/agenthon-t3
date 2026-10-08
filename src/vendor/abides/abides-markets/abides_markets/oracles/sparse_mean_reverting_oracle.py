import datetime as dt
import logging
from math import exp, sqrt
from typing import Any, Dict, List
import numpy as np
import pandas as pd
from abides_core import NanosecondTime
from .mean_reverting_oracle import MeanRevertingOracle
logger = logging.getLogger(__name__)

class SparseMeanRevertingOracle(MeanRevertingOracle):
    """The SparseMeanRevertingOracle produces a fundamental value time series for
    each requested symbol, and provides noisy observations of the fundamental
    value upon agent request.  This "sparse discrete" fundamental uses a
    combination of two processes to produce relatively realistic synthetic
    "values": a continuous mean-reverting Ornstein-Uhlenbeck process plus
    periodic "megashocks" which arrive following a Poisson process and have
    magnitude drawn from a bimodal normal distribution (overall mean zero,
    but with modes well away from zero).  This is necessary because OU itself
    is a single noisy return to the mean (from a perturbed initial state)
    that does not then depart the mean except in terms of minor "noise".

    Historical dates are effectively meaningless to this oracle.  It is driven by
    the numpy random number seed contained within the experimental config file.
    This oracle uses the nanoseconds portion of the current simulation time as
    discrete "time steps".

    This version of the MeanRevertingOracle expects agent activity to be spread
    across a large amount of time, with relatively sparse activity.  That is,
    agents each acting at realistic "retail" intervals, on the order of seconds
    or minutes, spread out across the day.
    """

    def __init__(self, mkt_open: NanosecondTime, mkt_close: NanosecondTime, symbols: Dict[str, Dict[str, Any]]) -> None:
        self.mkt_open: NanosecondTime = mkt_open
        self.mkt_close: NanosecondTime = mkt_close
        self.symbols: Dict[str, Dict[str, Any]] = symbols
        self.f_log: Dict[str, List[Dict[str, Any]]] = {}
        self.r: Dict[str, pd.Series] = {}
        self.megashocks: Dict[str, List[Dict[str, Any]]] = {}
        then = dt.datetime.now()
        for symbol in symbols:
            s = symbols[symbol]
            if logger.isEnabledFor(10):
                logger.debug('SparseMeanRevertingOracle computing initial fundamental value for {}'.format(symbol))
            self.r[symbol] = (mkt_open, s['r_bar'])
            self.f_log[symbol] = [{'FundamentalTime': mkt_open, 'FundamentalValue': s['r_bar']}]
            ms_time_delta = np.random.exponential(scale=1.0 / s['megashock_lambda_a'])
            mst = self.mkt_open + ms_time_delta
            msv = s['random_state'].normal(loc=s['megashock_mean'], scale=sqrt(s['megashock_var']))
            msv = msv if s['random_state'].randint(2) == 0 else -msv
            self.megashocks[symbol] = [{'MegashockTime': mst, 'MegashockValue': msv}]
        now = dt.datetime.now()
        if logger.isEnabledFor(10):
            logger.debug('SparseMeanRevertingOracle initialized for symbols {}'.format(symbols))
        if logger.isEnabledFor(10):
            logger.debug('SparseMeanRevertingOracle initialization took {}'.format(now - then))

    def compute_fundamental_at_timestamp(self, ts: NanosecondTime, v_adj, symbol: str, pt: NanosecondTime, pv) -> int:
        """
        Arguments:
          ts: A requested timestamp to which we should advance the fundamental.
          v_adj: A value adjustment to apply after advancing time (must pass zero if none).
          symbol: A symbol for which to advance time.
          pt: A previous timestamp.
          pv: A previous fundamental.

        Returns:
          The new value.

        The last two parameters should relate to the most recent time this method was invoked.

        As a side effect, it updates the log of computed fundamental values.
        """
        s = self.symbols[symbol]
        d = ts - pt
        mu = s['r_bar']
        gamma = s['kappa']
        theta = s['fund_vol']
        v = s['random_state'].normal(loc=mu + (pv - mu) * exp(-gamma * d), scale=sqrt(theta ** 2 / (2 * gamma) * (1 - exp(-2 * gamma * d))))
        v += v_adj
        v = max(0, v)
        v = int(round(v))
        for jump in s.get('scheduled_jumps', []):
            if not jump.get('_consumed') and ts >= jump['time_ns']:
                v = max(0, v + int(jump['magnitude']))
                jump['_consumed'] = True
        self.r[symbol] = (ts, v)
        self.f_log[symbol].append({'FundamentalTime': ts, 'FundamentalValue': v})
        return v

    def advance_fundamental_value_series(self, current_time: NanosecondTime, symbol: str) -> int:
        """This method advances the fundamental value series for a single stock symbol,
        using the OU process.  It may proceed in several steps due to our periodic
        application of "megashocks" to push the stock price around, simulating
        exogenous forces."""
        s = self.symbols[symbol]
        pt, pv = self.r[symbol]
        if current_time <= pt:
            return pv
        mst = self.megashocks[symbol][-1]['MegashockTime']
        msv = self.megashocks[symbol][-1]['MegashockValue']
        while mst < current_time:
            v = self.compute_fundamental_at_timestamp(mst, msv, symbol, pt, pv)
            pt, pv = (mst, v)
            mst = pt + int(np.random.exponential(scale=1.0 / s['megashock_lambda_a']))
            msv = s['random_state'].normal(loc=s['megashock_mean'], scale=sqrt(s['megashock_var']))
            msv = msv if s['random_state'].randint(2) == 0 else -msv
            self.megashocks[symbol].append({'MegashockTime': mst, 'MegashockValue': msv})
        v = self.compute_fundamental_at_timestamp(current_time, 0, symbol, pt, pv)
        return v

    def get_daily_open_price(self, symbol: str, mkt_open: NanosecondTime, cents: bool=True) -> int:
        """Return the daily open price for the symbol given.

        In the case of the MeanRevertingOracle, this will simply be the first
        fundamental value, which is also the fundamental mean. We will use the
        mkt_open time as given, however, even if it disagrees with this.
        """
        if logger.isEnabledFor(10):
            logger.debug('Oracle: client requested {} at market open: {}'.format(symbol, self.mkt_open))
        open_price = self.symbols[symbol]['r_bar']
        if logger.isEnabledFor(10):
            logger.debug('Oracle: market open price was was {}'.format(open_price))
        return open_price

    def observe_price(self, symbol: str, current_time: NanosecondTime, random_state: np.random.RandomState, sigma_n: int=1000) -> int:
        """Return a noisy observation of the current fundamental value.

        While the fundamental value for a given equity at a given time step does
        not change, multiple agents observing that value will receive different
        observations.

        Only the Exchange or other privileged agents should use sigma_n==0.

        sigma_n is experimental observation variance.  NOTE: NOT STANDARD DEVIATION.

        Each agent must pass its RandomState object to observe_price.  This ensures that
        each agent will receive the same answers across multiple same-seed simulations
        even if a new agent has been added to the experiment.
        """
        if current_time >= self.mkt_close:
            r_t = self.advance_fundamental_value_series(self.mkt_close - 1, symbol)
        else:
            r_t = self.advance_fundamental_value_series(current_time, symbol)
        if sigma_n == 0:
            obs = r_t
        else:
            obs = int(round(random_state.normal(loc=r_t, scale=sqrt(sigma_n))))
        if logger.isEnabledFor(10):
            logger.debug('Oracle: current fundamental value is {} at {}'.format(r_t, current_time))
        if logger.isEnabledFor(10):
            logger.debug('Oracle: giving client value observation {}'.format(obs))
        return obs
