import logging
from typing import Optional
import numpy as np
from abides_core import Message, NanosecondTime
from ..messages.query import QuerySpreadResponseMsg
from ..orders import Side
from .trading_agent import TradingAgent
logger = logging.getLogger(__name__)

class ValueAgent(TradingAgent):

    def __init__(self, id: int, name: Optional[str]=None, type: Optional[str]=None, random_state: Optional[np.random.RandomState]=None, symbol: str='IBM', starting_cash: int=100000, sigma_n: float=10000, r_bar: int=100000, kappa: float=0.05, sigma_s: float=100000, order_size_model=None, lambda_a: float=0.005, log_orders: float=False) -> None:
        super().__init__(id, name, type, random_state, starting_cash, log_orders)
        self.symbol: str = symbol
        self.sigma_n: float = sigma_n
        self.r_bar: int = r_bar
        self.kappa: float = kappa
        self.sigma_s: float = sigma_s
        self.lambda_a: float = lambda_a
        self.trading: bool = False
        self.state: str = 'AWAITING_WAKEUP'
        self.r_t: int = r_bar
        self.sigma_t: float = 0
        self.prev_wake_time: Optional[NanosecondTime] = None
        self.percent_aggr: float = 0.1
        self.size: Optional[int] = self.random_state.randint(20, 50) if order_size_model is None else None
        self.order_size_model = order_size_model
        self.depth_spread: int = 2

    def kernel_starting(self, start_time: NanosecondTime) -> None:
        super().kernel_starting(start_time)
        self.oracle = self.kernel.oracle

    def kernel_stopping(self) -> None:
        super().kernel_stopping()
        H = int(round(self.get_holdings(self.symbol), -2) / 100)
        rT = self.oracle.observe_price(self.symbol, self.current_time, sigma_n=0, random_state=self.random_state)
        surplus = rT * H
        if logger.isEnabledFor(10):
            logger.debug('Surplus after holdings: {}', surplus)
        surplus += self.holdings['CASH'] - self.starting_cash
        surplus = float(surplus) / self.starting_cash
        self.logEvent('FINAL_VALUATION', surplus, True)
        if logger.isEnabledFor(10):
            logger.debug('{} final report.  Holdings: {}, end cash: {}, start cash: {}, final fundamental: {}, surplus: {}', self.name, H, self.holdings['CASH'], self.starting_cash, rT, surplus)

    def wakeup(self, current_time: NanosecondTime) -> None:
        super().wakeup(current_time)
        self.state = 'INACTIVE'
        if not self.mkt_open or not self.mkt_close:
            return
        elif not self.trading:
            self.trading = True
            if logger.isEnabledFor(10):
                logger.debug('{} is ready to start trading now.', self.name)
        if self.mkt_closed and self.symbol in self.daily_close_price:
            return
        delta_time = self.random_state.exponential(scale=1.0 / self.lambda_a)
        self.set_wakeup(current_time + int(round(delta_time)))
        if self.mkt_closed and (not self.symbol in self.daily_close_price):
            self.get_current_spread(self.symbol)
            self.state = 'AWAITING_SPREAD'
            return
        self.cancel_all_orders()
        if type(self) == ValueAgent:
            self.get_current_spread(self.symbol)
            self.state = 'AWAITING_SPREAD'
        else:
            self.state = 'ACTIVE'

    def updateEstimates(self) -> int:
        obs_t = self.oracle.observe_price(self.symbol, self.current_time, sigma_n=self.sigma_n, random_state=self.random_state)
        if logger.isEnabledFor(10):
            logger.debug('{} observed {} at {}', self.name, obs_t, self.current_time)
        if self.prev_wake_time is None:
            self.prev_wake_time = self.mkt_open
        delta = self.current_time - self.prev_wake_time
        r_tprime = (1 - (1 - self.kappa) ** delta) * self.r_bar
        r_tprime += (1 - self.kappa) ** delta * self.r_t
        sigma_tprime = (1 - self.kappa) ** (2 * delta) * self.sigma_t
        sigma_tprime += (1 - (1 - self.kappa) ** (2 * delta)) / (1 - (1 - self.kappa) ** 2) * self.sigma_s
        self.r_t = self.sigma_n / (self.sigma_n + sigma_tprime) * r_tprime
        self.r_t += sigma_tprime / (self.sigma_n + sigma_tprime) * obs_t
        self.sigma_t = self.sigma_n * self.sigma_t / (self.sigma_n + self.sigma_t)
        delta = max(0, self.mkt_close - self.current_time)
        r_T = (1 - (1 - self.kappa) ** delta) * self.r_bar
        r_T += (1 - self.kappa) ** delta * self.r_t
        r_T = int(round(r_T))
        self.prev_wake_time = self.current_time
        if logger.isEnabledFor(10):
            logger.debug('{} estimates r_T = {} as of {}', self.name, r_T, self.current_time)
        return r_T

    def placeOrder(self) -> None:
        r_T = self.updateEstimates()
        bid, bid_vol, ask, ask_vol = self.get_known_bid_ask(self.symbol)
        if bid and ask:
            mid = int((ask + bid) / 2)
            spread = abs(ask - bid)
            if self.random_state.rand() < self.percent_aggr:
                adjust_int = 0
            else:
                adjust_int = self.random_state.randint(0, min(9223372036854775807 - 1, self.depth_spread * spread))
            if r_T < mid:
                buy = False
                p = bid + adjust_int
            elif r_T >= mid:
                buy = True
                p = ask - adjust_int
        else:
            buy = self.random_state.randint(0, 1 + 1)
            p = r_T
        if self.order_size_model is not None:
            self.size = self.order_size_model.sample(random_state=self.random_state)
        side = Side.BID if buy == 1 else Side.ASK
        if self.size > 0:
            self.place_limit_order(self.symbol, self.size, side, p)

    def receive_message(self, current_time: NanosecondTime, sender_id: int, message: Message) -> None:
        super().receive_message(current_time, sender_id, message)
        if self.state == 'AWAITING_SPREAD':
            if isinstance(message, QuerySpreadResponseMsg):
                if self.mkt_closed:
                    return
                self.placeOrder()
                self.state = 'AWAITING_WAKEUP'

    def get_wake_frequency(self) -> NanosecondTime:
        delta_time = self.random_state.exponential(scale=1.0 / self.lambda_a)
        return int(round(delta_time))
