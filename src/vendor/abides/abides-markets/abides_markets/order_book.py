import logging
import sys
import warnings
from copy import deepcopy
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np
import pandas as pd
from abides_core import Agent, NanosecondTime
from abides_core.utils import str_to_ns, ns_date
from .messages.orderbook import OrderAcceptedMsg, OrderExecutedMsg, OrderCancelledMsg, OrderPartialCancelledMsg, OrderModifiedMsg, OrderReplacedMsg
from .orders import LimitOrder, MarketOrder, Order, Side
from .price_level import PriceLevel
logger = logging.getLogger(__name__)

class OrderBook:
    """Basic class for an order book for one symbol, in the style of the major US Stock Exchanges.

    An OrderBook requires an owning agent object, which it will use to send messages
    outbound via the simulator Kernel (notifications of order creation, rejection,
    cancellation, execution, etc).

    Attributes:
        owner: The agent this order book belongs to.
        symbol: The symbol of the stock or security that is traded on this order book.
        bids: List of bid price levels (index zero is best bid), stored as a PriceLevel object.
        asks: List of ask price levels (index zero is best ask), stored as a PriceLevel object.
        last_trade: The price that the last trade was made at.
        book_log: Log of the full order book depth (price and volume) each time it changes.
        book_log2: TODO
        quotes_seen: TODO
        history: A truncated history of previous trades.
        last_update_ts: The last timestamp the order book was updated.
        buy_transactions: An ordered list of all previous buy transaction timestamps and quantities.
        sell_transactions: An ordered list of all previous sell transaction timestamps and quantities.
    """

    def __init__(self, owner: Agent, symbol: str) -> None:
        """Creates a new OrderBook class instance for a single symbol.

        Arguments:
            owner: The agent this order book belongs to, usually an `ExchangeAgent`.
            symbol: The symbol of the stock or security that is traded on this order book.
        """
        self.owner: Agent = owner
        self.symbol: str = symbol
        self.bids: List[PriceLevel] = []
        self.asks: List[PriceLevel] = []
        self.last_trade: Optional[int] = None
        self.book_log2: List[Dict[str, Any]] = []
        self.quotes_seen: Set[int] = set()
        self.history: List[Dict[str, Any]] = []
        self.last_update_ts: Optional[NanosecondTime] = self.owner.mkt_open
        self.buy_transactions: List[Tuple[NanosecondTime, int]] = []
        self.sell_transactions: List[Tuple[NanosecondTime, int]] = []

    def handle_limit_order(self, order: LimitOrder, quiet: bool=False) -> None:
        """Matches a limit order or adds it to the order book.

        Handles partial matches piecewise,
        consuming all possible shares at the best price before moving on, without regard to
        order size "fit" or minimizing number of transactions.  Sends one notification per
        match.

        Arguments:
            order: The limit order to process.
            quiet: If True messages will not be sent to agents and entries will not be added to
                history. Used when this function is a part of a more complex order.
        """
        if order.symbol != self.symbol:
            warnings.warn(f'{order.symbol} order discarded. Does not match OrderBook symbol: {self.symbol}')
            return
        if order.quantity <= 0 or int(order.quantity) != order.quantity:
            warnings.warn(f'{order.symbol} order discarded. Quantity ({order.quantity}) must be a positive integer.')
            return
        if order.limit_price < 0 or int(order.limit_price) != order.limit_price:
            warnings.warn(f'{order.symbol} order discarded. Limit price ({order.limit_price}) must be a positive integer.')
            return
        executed: List[Tuple[int, int]] = []
        while True:
            stp_policy = getattr(self.owner, 'stp_policy', None)
            if stp_policy:
                opp = self.asks if order.side.is_bid() else self.bids
                if opp and opp[0].order_is_match(order):
                    resting = opp[0].peek()[0]
                    if resting.agent_id == order.agent_id:
                        if stp_policy == 'cancel_oldest' and self.cancel_order(resting, quiet=quiet):
                            continue
                        if stp_policy != 'cancel_oldest':
                            if not quiet:
                                self.owner.send_message(order.agent_id, OrderCancelledMsg(deepcopy(order)))
                            break
            matched_order = self.execute_order(order)
            if matched_order is not None:
                assert matched_order.fill_price is not None
                executed.append((matched_order.quantity, matched_order.fill_price))
                if order.quantity <= 0:
                    break
            else:
                self.enter_order(deepcopy(order), quiet=quiet)
                if logger.isEnabledFor(10):
                    logger.debug('ACCEPTED: new order {}', order)
                if logger.isEnabledFor(10):
                    logger.debug('SENT: notifications of order acceptance to agent {} for order {}', order.agent_id, order.order_id)
                if not quiet:
                    self.owner.send_message(order.agent_id, OrderAcceptedMsg(order))
                break
        if self.bids:
            self.owner.logEvent('BEST_BID', '{},{},{}'.format(self.symbol, self.bids[0].price, self.bids[0].total_quantity))
        if self.asks:
            self.owner.logEvent('BEST_ASK', '{},{},{}'.format(self.symbol, self.asks[0].price, self.asks[0].total_quantity))
        if len(executed) > 0:
            trade_qty = 0
            trade_price = 0
            for q, p in executed:
                if logger.isEnabledFor(10):
                    logger.debug('Executed: {} @ {}', q, p)
                trade_qty += q
                trade_price += p * q
            avg_price = int(round(trade_price / trade_qty))
            if logger.isEnabledFor(10):
                logger.debug(f'Avg: {trade_qty} @ ${avg_price:0.4f}')
            self.owner.logEvent('LAST_TRADE', f'{trade_qty},${avg_price:0.4f}')
            self.last_trade = avg_price

    def handle_market_order(self, order: MarketOrder) -> None:
        """Takes a market order and attempts to fill at the current best market price.

        Arguments:
            order: The market order to process.
        """
        if order.symbol != self.symbol:
            warnings.warn(f'{order.symbol} order discarded. Does not match OrderBook symbol: {self.symbol}')
            return
        if order.quantity <= 0 or int(order.quantity) != order.quantity:
            warnings.warn(f'{order.symbol} order discarded.  Quantity ({order.quantity}) must be a positive integer.')
            return
        order = deepcopy(order)
        while order.quantity > 0:
            stp_policy = getattr(self.owner, 'stp_policy', None)
            if stp_policy:
                opp = self.asks if order.side.is_bid() else self.bids
                if opp and opp[0].peek()[0].agent_id == order.agent_id:
                    if stp_policy == 'cancel_oldest' and self.cancel_order(opp[0].peek()[0]):
                        continue
                    if stp_policy != 'cancel_oldest':
                        self.owner.send_message(order.agent_id, OrderCancelledMsg(deepcopy(order)))
                        break
            if self.execute_order(order) is None:
                break

    def execute_order(self, order: Order) -> Optional[Order]:
        """Finds a single best match for this order, without regard for quantity.

        Returns the matched order or None if no match found.  DOES remove,
        or decrement quantity from, the matched order from the order book
        (i.e. executes at least a partial trade, if possible).

        Arguments:
            order: The order to execute.
        """
        book = self.asks if order.side.is_bid() else self.bids
        if len(book) == 0:
            return None
        elif isinstance(order, LimitOrder) and (not book[0].order_is_match(order)):
            return None
        elif order.tag in ['MR_preprocess_ADD', 'MR_preprocess_REPLACE']:
            self.owner.logEvent(order.tag + '_POST_ONLY', {'order_id': order.order_id})
            return None
        else:
            is_ptc_exec = False
            if order.quantity >= book[0].peek()[0].quantity:
                matched_order, matched_order_metadata = book[0].pop()
                if matched_order.is_price_to_comply:
                    is_ptc_exec = True
                    if matched_order_metadata['ptc_hidden'] == False:
                        raise Exception('Should not be executing on the visible half of a price to comply order!')
                    assert book[1].remove_order(matched_order.order_id) is not None
                    if book[1].is_empty:
                        del book[1]
                if book[0].is_empty:
                    del book[0]
            else:
                book_order, book_order_metadata = book[0].peek()
                matched_order = deepcopy(book_order)
                matched_order.quantity = order.quantity
                book_order.quantity -= matched_order.quantity
                if book_order.is_price_to_comply:
                    is_ptc_exec = True
                    if book_order_metadata['ptc_hidden'] == False:
                        raise Exception('Should not be executing on the visible half of a price to comply order!')
                    book_order_metadata['ptc_other_half'].quantity -= matched_order.quantity
            matched_order.fill_price = matched_order.limit_price
            if order.side.is_bid():
                self.buy_transactions.append((self.owner.current_time, matched_order.quantity))
            else:
                self.sell_transactions.append((self.owner.current_time, matched_order.quantity))
            self.history.append(dict(time=self.owner.current_time, type='EXEC', order_id=matched_order.order_id, agent_id=matched_order.agent_id, oppos_order_id=order.order_id, oppos_agent_id=order.agent_id, side='SELL' if order.side.is_bid() else 'BUY', quantity=matched_order.quantity, price=matched_order.limit_price if is_ptc_exec else None))
            filled_order = deepcopy(order)
            filled_order.quantity = matched_order.quantity
            filled_order.fill_price = matched_order.fill_price
            order.quantity -= filled_order.quantity
            if logger.isEnabledFor(10):
                logger.debug('MATCHED: new order {} vs old order {}', filled_order, matched_order)
            if logger.isEnabledFor(10):
                logger.debug('SENT: notifications of order execution to agents {} and {} for orders {} and {}', filled_order.agent_id, matched_order.agent_id, filled_order.order_id, matched_order.order_id)
            self.owner.send_message(matched_order.agent_id, OrderExecutedMsg(matched_order))
            self.owner.send_message(order.agent_id, OrderExecutedMsg(filled_order))
            if self.owner.book_logging == True:
                self.append_book_log2()
            return matched_order

    def enter_order(self, order: LimitOrder, metadata: Optional[Dict]=None, quiet: bool=False) -> None:
        """Enters a limit order into the OrderBook in the appropriate location.

        This does not test for matching/executing orders -- this function
        should only be called after a failed match/execution attempt.

        Arguments:
            order: The limit order to enter into the order book.
            quiet: If True messages will not be sent to agents and entries will not be added to
                history. Used when this function is a part of a more complex order.
        """
        if order.is_price_to_comply and (metadata is None or metadata == {} or 'ptc_hidden' not in metadata):
            hidden_order = deepcopy(order)
            visible_order = deepcopy(order)
            hidden_order.is_hidden = True
            hidden_order.limit_price += 1 if order.side.is_bid() else -1
            hidden_order_metadata = dict(ptc_hidden=True, ptc_other_half=visible_order)
            visible_order_metadata = dict(ptc_hidden=False, ptc_other_half=hidden_order)
            self.enter_order(hidden_order, hidden_order_metadata, quiet=True)
            self.enter_order(visible_order, visible_order_metadata, quiet=quiet)
            return
        book = self.bids if order.side.is_bid() else self.asks
        if len(book) == 0:
            book.append(PriceLevel([(order, metadata or {})]))
        elif book[-1].order_has_worse_price(order):
            book.append(PriceLevel([(order, metadata or {})]))
        else:
            for i, price_level in enumerate(book):
                if price_level.order_has_better_price(order):
                    book.insert(i, PriceLevel([(order, metadata or {})]))
                    break
                elif price_level.order_has_equal_price(order):
                    book[i].add_order(order, metadata or {})
                    break
        if quiet == False:
            self.history.append(dict(time=self.owner.current_time, type='LIMIT', order_id=order.order_id, agent_id=order.agent_id, side=order.side.value, quantity=order.quantity, price=order.limit_price))
        if self.owner.book_logging == True and quiet == False:
            self.append_book_log2()

    def cancel_order(self, order: LimitOrder, tag: str=None, cancellation_metadata: Optional[Dict]=None, quiet: bool=False) -> bool:
        """Attempts to cancel (the remaining, unexecuted portion of) a trade in the order book.

        By definition, this pretty much has to be a limit order.  If the order cannot be found
        in the order book (probably because it was already fully executed), presently there is
        no message back to the agent.  This should possibly change to some kind of failed
        cancellation message.  (?)  Otherwise, the agent receives ORDER_CANCELLED with the
        order as the message body, with the cancelled quantity correctly represented as the
        number of shares that had not already been executed.

        Arguments:
            order: The limit order to cancel from the order book.
            quiet: If True messages will not be sent to agents and entries will not be added to
                history. Used when this function is a part of a more complex order.

        Returns:
            A bool indicating if the order cancellation was successful.
        """
        book = self.bids if order.side.is_bid() else self.asks
        if not book:
            return False
        for i, price_level in enumerate(book):
            if not price_level.order_has_equal_price(order):
                continue
            cancelled_order_result = price_level.remove_order(order.order_id)
            if cancelled_order_result is not None:
                cancelled_order, metadata = cancelled_order_result
                if price_level.is_empty:
                    del book[i]
                if logger.isEnabledFor(10):
                    logger.debug('CANCELLED: order {}', order)
                if logger.isEnabledFor(10):
                    logger.debug('SENT: notifications of order cancellation to agent {} for order {}', cancelled_order.agent_id, cancelled_order.order_id)
                if cancelled_order.is_price_to_comply:
                    self.cancel_order(metadata['ptc_other_half'], quiet=True)
                if not quiet:
                    self.history.append(dict(time=self.owner.current_time, type='CANCEL', order_id=cancelled_order.order_id, tag=tag, metadata=cancellation_metadata if tag == 'auctionFill' else None))
                    self.owner.send_message(order.agent_id, OrderCancelledMsg(cancelled_order))
                self.last_update_ts = self.owner.current_time
                if self.owner.book_logging == True and quiet == False:
                    self.append_book_log2()
                return True
        return False

    def modify_order(self, order: LimitOrder, new_order: LimitOrder) -> None:
        """Modifies the quantity of an existing limit order in the order book.

        Arguments:
            order: The existing order in the order book.
            new_order: The new order to replace the old order with.
        """
        if order.order_id != new_order.order_id:
            return
        book = self.bids if order.side.is_bid() else self.asks
        for price_level in book:
            if not price_level.order_has_equal_price(order):
                continue
            if price_level.update_order_quantity(order.order_id, new_order.quantity):
                self.history.append(dict(time=self.owner.current_time, type='MODIFY', order_id=order.order_id, new_side=order.side.value, new_quantity=new_order.quantity))
                if logger.isEnabledFor(10):
                    logger.debug('MODIFIED: order {}', order)
                if logger.isEnabledFor(10):
                    logger.debug('SENT: notifications of order modification to agent {} for order {}', new_order.agent_id, new_order.order_id)
                self.owner.send_message(order.agent_id, OrderModifiedMsg(new_order))
                self.last_update_ts = self.owner.current_time
                if self.owner.book_logging == True is not None:
                    self.append_book_log2()

    def partial_cancel_order(self, order: LimitOrder, quantity: int, tag: str=None, cancellation_metadata: Optional[Dict]=None) -> None:
        """cancel a part of the quantity of an existing limit order in the order book.

        Arguments:
            order: The existing order in the order book.
            new_order: The new order to replace the old order with.
        """
        if order.order_id == 19653081:
            print('inside OB partialCancel')
        book = self.bids if order.side.is_bid() else self.asks
        new_order = deepcopy(order)
        new_order.quantity -= quantity
        for price_level in book:
            if not price_level.order_has_equal_price(order):
                continue
            if price_level.update_order_quantity(order.order_id, new_order.quantity):
                self.history.append(dict(time=self.owner.current_time, type='CANCEL_PARTIAL', order_id=order.order_id, quantity=quantity, tag=tag, metadata=cancellation_metadata if tag == 'auctionFill' else None))
                if logger.isEnabledFor(10):
                    logger.debug('CANCEL_PARTIAL: order {}', order)
                if logger.isEnabledFor(10):
                    logger.debug('SENT: notifications of order partial cancellation to agent {} for order {}', new_order.agent_id, quantity)
                self.owner.send_message(order.agent_id, OrderPartialCancelledMsg(new_order))
                self.last_update_ts = self.owner.current_time
                if self.owner.book_logging == True:
                    self.append_book_log2()

    def replace_order(self, agent_id: int, old_order: LimitOrder, new_order: LimitOrder) -> None:
        """Removes an order from the book and replaces it with a new one in one step.

        This is equivalent to calling cancel_order followed by handle_limit_order.

        If the old order cannot be cancelled, the new order is not inserted.

        Arguments:
            agent_id: The ID of the agent making this request - this must be the ID of
                the agent who initially created the order.
            old_order: The existing order in the order book to be cancelled.
            new_order: The new order to be inserted into the order book.
        """
        if self.cancel_order(old_order, quiet=True) == True:
            self.history.append(dict(time=self.owner.current_time, type='REPLACE', old_order_id=old_order.order_id, new_order_id=new_order.order_id, quantity=new_order.quantity, price=new_order.limit_price))
            self.handle_limit_order(new_order, quiet=True)
            if logger.isEnabledFor(10):
                logger.debug('SENT: notifications of order replacement to agent {agent_id} for old order {old_order.order_id}, new order {new_order.order_id}')
            self.owner.send_message(agent_id, OrderReplacedMsg(old_order, new_order))
        if self.owner.book_logging == True:
            self.append_book_log2()

    def append_book_log2(self):
        row = {'QuoteTime': self.owner.current_time, 'bids': np.array(self.get_l2_bid_data(depth=self.owner.book_log_depth)), 'asks': np.array(self.get_l2_ask_data(depth=self.owner.book_log_depth))}
        self.book_log2.append(row)

    def get_l1_bid_data(self) -> Optional[Tuple[int, int]]:
        """Returns the current best bid price and of the book and the volume at this price."""
        if len(self.bids) == 0:
            return None
        index = 0
        while not self.bids[index].total_quantity > 0:
            index += 1
        return (self.bids[0].price, self.bids[0].total_quantity)

    def get_l1_ask_data(self) -> Optional[Tuple[int, int]]:
        """Returns the current best ask price of the book and the volume at this price."""
        if len(self.asks) == 0:
            return None
        index = 0
        while not self.asks[index].total_quantity > 0:
            index += 1
        return (self.asks[index].price, self.asks[index].total_quantity)

    def get_l2_bid_data(self, depth: int=sys.maxsize) -> List[Tuple[int, int]]:
        """Returns the price and total quantity of all limit orders on the bid side.

        Arguments:
            depth: If given, will only return data for the first N levels of the order book side.

        Returns:
            A list of tuples where the first element of the tuple is the price and the second
            element of the tuple is the total volume at that price.

            The list is given in order of price, with the centre of the book first.
        """
        return list(filter(lambda x: x[1] > 0, [(price_level.price, price_level.total_quantity) for price_level in self.bids[:depth]]))

    def get_l2_ask_data(self, depth: int=sys.maxsize) -> List[Tuple[int, int]]:
        """Returns the price and total quantity of all limit orders on the ask side.

        Arguments:
            depth: If given, will only return data for the first N levels of the order book side.

        Returns:
            A list of tuples where the first element of the tuple is the price and the second
            element of the tuple is the total volume at that price.

            The list is given in order of price, with the centre of the book first.
        """
        return list(filter(lambda x: x[1] > 0, [(price_level.price, price_level.total_quantity) for price_level in self.asks[:depth]]))

    def get_l3_bid_data(self, depth: int=sys.maxsize) -> List[Tuple[int, List[int]]]:
        """Returns the price and quantity of all limit orders on the bid side.

        Arguments:
            depth: If given, will only return data for the first N levels of the order book side.

        Returns:
            A list of tuples where the first element of the tuple is the price and the second
            element of the tuple is the list of order quantities at that price.

            The list of order quantities is given in order of priority and the overall list
            is given in order of price, with the centre of the book first.
        """
        return [(price_level.price, [order.quantity for order, _ in price_level.visible_orders]) for price_level in self.bids[:depth]]

    def get_l3_ask_data(self, depth: int=sys.maxsize) -> List[Tuple[int, List[int]]]:
        """Returns the price and quantity of all limit orders on the ask side.

        Arguments:
            depth: If given, will only return data for the first N levels of the order book side.

        Returns:
            A list of tuples where the first element of the tuple is the price and the second
            element of the tuple is the list of order quantities at that price.

            The list of order quantities is given in order of priority and the overall list
            is given in order of price, with the centre of the book first.
        """
        return [(price_level.price, [order.quantity for order, _ in price_level.visible_orders]) for price_level in self.asks[:depth]]

    def get_transacted_volume(self, lookback_period: str='10min') -> Tuple[int, int]:
        """Method retrieves the total transacted volume for a symbol over a lookback
        period finishing at the current simulation time.

        Arguments:
            lookback_period: The period in time from the current time to calculate the
                transacted volume for.
        """
        window_start = self.owner.current_time - str_to_ns(lookback_period)
        buy_transacted_volume = 0
        sell_transacted_volume = 0
        for time, volume in reversed(self.buy_transactions):
            if time < window_start:
                break
            buy_transacted_volume += volume
        for time, volume in reversed(self.sell_transactions):
            if time < window_start:
                break
            sell_transacted_volume += volume
        return (buy_transacted_volume, sell_transacted_volume)

    def get_imbalance(self) -> Tuple[float, Optional[Side]]:
        """Returns a measure of book side total volume imbalance.

        Returns:
            A tuple containing the volume imbalance value and the side the order
            book is in imbalance to.

        Examples:
            - Both book sides have the exact same volume    --> (0.0, None)
            - 2x bid volume vs. ask volume                  --> (0.5, Side.BID)
            - 2x ask volume vs. bid volume                  --> (0.5, Side.ASK)
            - Ask has no volume                             --> (1.0, Side.BID)
            - Bid has no volume                             --> (1.0, Side.ASK)
        """
        bid_vol = sum((price_level.total_quantity for price_level in self.bids))
        ask_vol = sum((price_level.total_quantity for price_level in self.asks))
        if bid_vol == ask_vol:
            return (0, None)
        elif bid_vol == 0:
            return (1.0, Side.ASK)
        elif ask_vol == 0:
            return (1.0, Side.BID)
        elif bid_vol < ask_vol:
            return (1 - bid_vol / ask_vol, Side.ASK)
        else:
            return (1 - ask_vol / bid_vol, Side.BID)

    def get_L1_snapshots(self):
        best_bids = []
        best_asks = []

        def safe_first(x):
            return x[0] if len(x) > 0 else np.array([None, None])
        for d in self.book_log2:
            best_bids.append([d['QuoteTime']] + safe_first(d['bids']).tolist())
            best_asks.append([d['QuoteTime']] + safe_first(d['asks']).tolist())
        best_bids = np.array(best_bids)
        best_asks = np.array(best_asks)
        return {'best_bids': best_bids, 'best_asks': best_asks}

    def bids_padding(self, book, nlevels):
        n = book.shape[0]
        if n == 0:
            return np.zeros((nlevels, 2), dtype=int)
        if n >= nlevels:
            return book[:nlevels, :]
        else:
            lowestprice = book[-1, 0] if len(book.shape) == 2 else book[0]
            npad = nlevels - n
            pad = np.transpose(np.array([-1 + np.arange(lowestprice, lowestprice - npad, -1, dtype=int), np.zeros(npad, dtype=int)]))
            if len(pad.shape) == 1:
                pad = pad.reshape(1, 2)
            return np.concatenate([book, pad])

    def asks_padding(self, book, nlevels):
        n = book.shape[0]
        if n == 0:
            return np.zeros((nlevels, 2), dtype=int)
        if n >= nlevels:
            return book[:nlevels, :]
        else:
            highestprice = book[-1, 0] if len(book.shape) == 2 else book[0]
            npad = nlevels - n
            pad = np.transpose(np.array([1 + np.arange(highestprice, highestprice + npad, 1, dtype=int), np.zeros(npad, dtype=int)]))
            if len(pad.shape) == 1:
                pad = pad.reshape(1, 2)
            return np.concatenate([book, pad])

    def get_L2_snapshots(self, nlevels):
        times, bids, asks = ([], [], [])
        for x in self.book_log2:
            times.append(x['QuoteTime'])
            bids.append(self.bids_padding(x['bids'], nlevels))
            asks.append(self.asks_padding(x['asks'], nlevels))
        bids = np.array(bids)
        asks = np.array(asks)
        times = np.array(times)
        return {'times': times, 'bids': bids, 'asks': asks}

    def get_l3_itch(self):
        history_l3 = pd.DataFrame(self.history)
        history_l3.loc[history_l3.tag == 'auctionFill', 'type'] = 'EXEC'
        history_l3.loc[history_l3.tag == 'auctionFill', 'quantity'] = history_l3.loc[history_l3.tag == 'auctionFill', 'metadata'].apply(lambda x: x['quantity'])
        history_l3.loc[history_l3.tag == 'auctionFill', 'price'] = history_l3.loc[history_l3.tag == 'auctionFill', 'metadata'].apply(lambda x: x['price'])
        history_l3['printable'] = np.nan
        history_l3['stock'] = np.nan
        if not 'REPLACE' in history_l3.type.unique():
            history_l3['new_order_id'] = np.nan
            history_l3['old_order_id'] = np.nan
        history_l3.loc[history_l3.type == 'REPLACE', 'order_id'] = history_l3.loc[history_l3.type == 'REPLACE', 'old_order_id']
        history_l3.loc[history_l3.type == 'EXEC', 'side'] = np.nan
        history_l3['type'] = history_l3['type'].replace({'LIMIT': 'ADD', 'CANCEL_PARTIAL': 'CANCEL', 'CANCEL': 'DELETE', 'EXEC': 'EXECUTE'})
        history_l3['side'] = history_l3['side'].replace({'ASK': 'S', 'BID': 'B'})
        history_l3['time'] = history_l3['time'] - ns_date(history_l3['time'])
        history_l3['price'] = history_l3['price'] * 100
        history_l3 = history_l3[['time', 'stock', 'type', 'order_id', 'side', 'quantity', 'price', 'new_order_id', 'printable']]
        history_l3 = history_l3.rename(columns={'time': 'timestamp', 'order_id': 'reference', 'new_order_id': 'new_reference', 'quantity': 'shares'})
        return history_l3

    def pretty_print(self, silent: bool=True) -> Optional[str]:
        """Print a nicely-formatted view of the current order book.

        Arguments:
            silent:
        """
        assert self.last_trade is not None
        book = '{} order book as of {}\n'.format(self.symbol, self.owner.current_time)
        book += 'Last trades: simulated {:d}, historical {:d}\n'.format(self.last_trade, self.owner.oracle.observe_price(self.symbol, self.owner.current_time, sigma_n=0, random_state=self.owner.random_state))
        book += '{:10s}{:10s}{:10s}\n'.format('BID', 'PRICE', 'ASK')
        book += '{:10s}{:10s}{:10s}\n'.format('---', '-----', '---')
        for quote, volume in self.get_l2_ask_data()[-1::-1]:
            book += '{:10s}{:10s}{:10s}\n'.format('', '{:d}'.format(quote), '{:d}'.format(volume))
        for quote, volume in self.get_l2_bid_data():
            book += '{:10s}{:10s}{:10s}\n'.format('{:d}'.format(volume), '{:d}'.format(quote), '')
        if silent:
            return book
        else:
            print(book)
            return None
