import logging
from typing import Optional
import numpy as np
from abides_core import Message, NanosecondTime
from ..generators import OrderSizeGenerator
from ..messages.query import QuerySpreadResponseMsg
from ..orders import Side
from .trading_agent import TradingAgent
logger = logging.getLogger(__name__)

class NoiseAgent(TradingAgent):
    """
    Noise agent implement simple strategy. The agent wakes up once and places 1 order.
    """

    def __init__(self, id: int, name: Optional[str]=None, type: Optional[str]=None, random_state: Optional[np.random.RandomState]=None, symbol: str='IBM', starting_cash: int=100000, log_orders: bool=False, order_size_model: Optional[OrderSizeGenerator]=None, wakeup_time: Optional[NanosecondTime]=None) -> None:
        super().__init__(id, name, type, random_state, starting_cash, log_orders)
        self.wakeup_time: NanosecondTime = wakeup_time
        self.symbol: str = symbol
        self.trading: bool = False
        self.state: str = 'AWAITING_WAKEUP'
        self.prev_wake_time: Optional[NanosecondTime] = None
        self.size: Optional[int] = self.random_state.randint(20, 50) if order_size_model is None else None
        self.order_size_model = order_size_model

    def kernel_starting(self, start_time: NanosecondTime) -> None:
        super().kernel_starting(start_time)
        self.oracle = self.kernel.oracle

    def kernel_stopping(self) -> None:
        super().kernel_stopping()
        try:
            bid, bid_vol, ask, ask_vol = self.get_known_bid_ask(self.symbol)
        except KeyError:
            self.logEvent('FINAL_VALUATION', self.starting_cash, True)
        else:
            H = int(round(self.get_holdings(self.symbol), -2) / 100)
            if bid and ask:
                rT = int(bid + ask) / 2
            else:
                rT = self.last_trade[self.symbol]
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
        if self.wakeup_time > current_time:
            self.set_wakeup(self.wakeup_time)
            return
        if self.mkt_closed and self.symbol not in self.daily_close_price:
            self.get_current_spread(self.symbol)
            self.state = 'AWAITING_SPREAD'
            return
        if type(self) == NoiseAgent:
            self.get_current_spread(self.symbol)
            self.state = 'AWAITING_SPREAD'
        else:
            self.state = 'ACTIVE'

    def placeOrder(self) -> None:
        buy_indicator = self.random_state.randint(0, 1 + 1)
        bid, bid_vol, ask, ask_vol = self.get_known_bid_ask(self.symbol)
        if self.order_size_model is not None:
            self.size = self.order_size_model.sample(random_state=self.random_state)
        if self.size > 0:
            if buy_indicator == 1 and ask:
                self.place_limit_order(self.symbol, self.size, Side.BID, ask)
            elif not buy_indicator and bid:
                self.place_limit_order(self.symbol, self.size, Side.ASK, bid)

    def receive_message(self, current_time: NanosecondTime, sender_id: int, message: Message) -> None:
        super().receive_message(current_time, sender_id, message)
        if self.state == 'AWAITING_SPREAD':
            if isinstance(message, QuerySpreadResponseMsg):
                if self.mkt_closed:
                    return
                self.placeOrder()
                self.state = 'AWAITING_WAKEUP'

    def get_wake_frequency(self) -> NanosecondTime:
        return self.random_state.randint(low=0, high=100)
