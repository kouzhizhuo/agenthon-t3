import datetime as dt
import logging
from math import sqrt
from typing import Any, Dict, Optional
import numpy as np
import pandas as pd
from abides_core import NanosecondTime
from .oracle import Oracle
logger = logging.getLogger(__name__)

class MeanRevertingOracle(Oracle):
    """The MeanRevertingOracle requires three parameters: a mean fundamental value,
    a mean reversion coefficient, and a shock variance.  It constructs and retains
    a fundamental value time series for each requested symbol, and provides noisy
    observations of those values upon agent request.  The expectation is that
    agents using such an oracle will know the mean-reverting equation and all
    relevant parameters, but will not know the random shocks applied to the
    sequence at each time step.

    Historical dates are effectively meaningless to this oracle.  It is driven by
    the numpy random number seed contained within the experimental config file.
    This oracle uses the nanoseconds portion of the current simulation time as
    discrete "time steps".  A suggestion: to keep wallclock runtime reasonable,
    have the agents operate for only ~1000 nanoseconds, but interpret nanoseconds
    as seconds or minutes."""

    def __init__(self, mkt_open: NanosecondTime, mkt_close: NanosecondTime, symbols: Dict[str, Dict[str, Any]]) -> None:
        self.mkt_open: NanosecondTime = mkt_open
        self.mkt_close: NanosecondTime = mkt_close
        self.symbols: Dict[str, Dict[str, Any]] = symbols
        self.r: Dict[str, pd.Series] = {}
        then = dt.datetime.now()
        for symbol in symbols:
            s = symbols[symbol]
            if logger.isEnabledFor(10):
                logger.debug('MeanRevertingOracle computing fundamental value series for {}', symbol)
            self.r[symbol] = self.generate_fundamental_value_series(symbol=symbol, **s)
        now = dt.datetime.now()
        if logger.isEnabledFor(10):
            logger.debug('MeanRevertingOracle initialized for symbols {}', symbols)
        if logger.isEnabledFor(10):
            logger.debug('MeanRevertingOracle initialization took {}', now - then)

    def generate_fundamental_value_series(self, symbol: str, r_bar: int, kappa: float, sigma_s: float) -> pd.Series:
        """Generates the fundamental value series for a single stock symbol.

        Arguments:
            symbol: The symbold to calculate the fundamental value series for.
            r_bar: The mean fundamental value.
            kappa: The mean reversion coefficient.
            sigma_s: The shock variance.  (Note: NOT STANDARD DEVIATION)

        Because the oracle uses the global np.random PRNG to create the
        fundamental value series, it is important to create the oracle BEFORE
        the agents.  In this way the addition of a new agent will not affect the
        sequence created.  (Observations using the oracle will use an agent's
        PRNG and thus not cause a problem.)
        """
        sigma_s = sqrt(sigma_s)
        date_range = pd.date_range(self.mkt_open, self.mkt_close, closed='left', freq='N')
        s = pd.Series(index=date_range)
        r = np.zeros(len(s.index))
        r[0] = r_bar
        shock = np.random.normal(scale=sigma_s, size=r.shape[0])
        for t in range(1, r.shape[0]):
            r[t] = max(0, kappa * r_bar + (1 - kappa) * r[t - 1] + shock[t])
        s[:] = np.round(r)
        return s.astype(int)

    def get_daily_open_price(self, symbol: str, mkt_open: NanosecondTime, cents: bool=True) -> int:
        """Return the daily open price for the symbol given.

        In the case of the MeanRevertingOracle, this will simply be the first
        fundamental value, which is also the fundamental mean. We will use the
        mkt_open time as given, however, even if it disagrees with this.
        """
        if mkt_open is not None and self.mkt_open is None:
            self.mkt_open = mkt_open
        if logger.isEnabledFor(10):
            logger.debug('Oracle: client requested {symbol} at market open: {}', self.mkt_open)
        open_price = self.r[symbol].loc[self.mkt_open]
        if logger.isEnabledFor(10):
            logger.debug('Oracle: market open price was was {}', open_price)
        return open_price

    def observe_price(self, symbol: str, current_time: NanosecondTime, random_state: np.random.RandomState, sigma_n: int=1000) -> int:
        """Return a noisy observation of the current fundamental value.

        While the fundamental value for a given equity at a given time step does
        not change, multiple agents observing that value will receive different
        observations.

        Only the Exchange or other privileged agents should use noisy=False.

        sigma_n is experimental observation variance.  NOTE: NOT STANDARD DEVIATION.

        Each agent must pass its RandomState object to ``observe_price``.  This
        ensures that each agent will receive the same answers across multiple
        same-seed simulations even if a new agent has been added to the experiment.
        """
        if current_time >= self.mkt_close:
            r_t = self.r[symbol].loc[self.mkt_close - 1]
        else:
            r_t = self.r[symbol].loc[current_time]
        if sigma_n == 0:
            obs = r_t
        else:
            obs = int(round(random_state.normal(loc=r_t, scale=sqrt(sigma_n))))
        if logger.isEnabledFor(10):
            logger.debug('Oracle: current fundamental value is {} at {}', r_t, current_time)
        if logger.isEnabledFor(10):
            logger.debug('Oracle: giving client value observation {}', obs)
        return obs
