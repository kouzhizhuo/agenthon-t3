"""Exact finance tools for research; never infer or submit trading decisions."""
from fractions import Fraction
import argparse
import json
import sys

MAX_ROWS = 100000


class Unsupported(ValueError):
    pass


def exact_int(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise Unsupported(name + ' requires an exact integer >= ' + str(minimum))
    return value


def fields(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        raise Unsupported('expected fields: ' + ','.join(expected))


def rational(value):
    value = Fraction(value)
    return {'numerator': value.numerator, 'denominator': value.denominator}


def rows(value, expected):
    if type(value) is not list or not value or len(value) > MAX_ROWS:
        raise Unsupported('requires 1..100000 records')
    for row in value:
        fields(row, expected)
    return value


def book_features(arguments):
    fields(arguments, ('bids', 'asks'))
    sides = {}
    for side in ('bids', 'asks'):
        levels = rows(arguments[side], ('price', 'quantity'))
        prices = [exact_int(r['price'], 'price', 1) for r in levels]
        quantities = [exact_int(r['quantity'], 'quantity', 1) for r in levels]
        if len(set(prices)) != len(prices):
            raise Unsupported('aggregate duplicate price levels first')
        if prices != sorted(prices, reverse=side == 'bids'):
            raise Unsupported('book levels must be in best-price order')
        sides[side] = (prices, quantities)
    bid, ask = sides['bids'][0][0], sides['asks'][0][0]
    if bid > ask:
        raise Unsupported('crossed book needs venue-specific handling')
    bq, aq = sides['bids'][1][0], sides['asks'][1][0]
    bt, at = sum(sides['bids'][1]), sum(sides['asks'][1])
    mid = Fraction(bid + ask, 2)
    return {'best_bid': bid, 'best_ask': ask, 'spread': ask - bid,
        'midpoint': rational(mid), 'spread_bps': rational((ask - bid) * 10000 / mid),
        'top_microprice': rational(Fraction(ask * bq + bid * aq, bq + aq)),
        'top_imbalance': rational(Fraction(bq - aq, bq + aq)),
        'supplied_depth_imbalance': rational(Fraction(bt - at, bt + at)),
        'locked': bid == ask, 'price_unit': 'input_minor_unit',
        'interpretation': 'snapshot statistics; no future-price prediction'}


def vwap(arguments):
    fields(arguments, ('trades',))
    trades = rows(arguments['trades'], ('price', 'quantity'))
    notional, quantity = 0, 0
    for trade in trades:
        p = exact_int(trade['price'], 'price', 1)
        q = exact_int(trade['quantity'], 'quantity', 1)
        notional += p * q
        quantity += q
    return {'notional': notional, 'quantity': quantity,
        'vwap': rational(Fraction(notional, quantity)), 'price_unit': 'input_minor_unit'}


def price_time_preview(arguments):
    fields(arguments, ('incoming', 'opposite_orders', 'policy'))
    if type(arguments['policy']) is not str or arguments['policy'] != 'visible-limit-fifo-self-trade-allowed':
        raise Unsupported('supported policy: visible-limit-fifo-self-trade-allowed')
    incoming = arguments['incoming']
    fields(incoming, ('side', 'limit_price', 'quantity'))
    if type(incoming['side']) is not str or incoming['side'] not in ('BID', 'ASK'):
        raise Unsupported('side must be BID or ASK')
    limit = exact_int(incoming['limit_price'], 'limit_price', 1)
    remaining = exact_int(incoming['quantity'], 'quantity', 1)
    orders = rows(arguments['opposite_orders'], ('order_id', 'price', 'quantity', 'priority'))
    keys, ids = [], set()
    for order in orders:
        oid = exact_int(order['order_id'], 'order_id')
        if oid in ids:
            raise Unsupported('duplicate logical IDs require original order-book semantics')
        ids.add(oid)
        price = exact_int(order['price'], 'price', 1)
        exact_int(order['quantity'], 'quantity', 1)
        priority = exact_int(order['priority'], 'priority')
        keys.append((price if incoming['side'] == 'BID' else -price, priority))
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        raise Unsupported('requires an unambiguous original price-time order')
    fills, after, notional = [], [], 0
    for order in orders:
        price, available = order['price'], order['quantity']
        crosses = price <= limit if incoming['side'] == 'BID' else price >= limit
        taken = min(remaining, available) if crosses and remaining else 0
        if taken:
            fills.append({'order_id': order['order_id'], 'price': price, 'quantity': taken})
            remaining -= taken
            notional += taken * price
        if available > taken:
            after.append({**order, 'quantity': available - taken})
    filled = incoming['quantity'] - remaining
    return {'fills': fills, 'filled': filled, 'remaining': remaining,
        'notional': notional, 'vwap': rational(Fraction(notional, filled)) if filled else None,
        'opposite_orders_after': after, 'input_mutated': False,
        'scope': 'one incoming visible limit order; not a full simulator'}


TOOLS = {'book_features': book_features, 'vwap': vwap,
    'price_time_preview': price_time_preview}
SCHEMAS = {
    'book_features': {'description': 'Exact spread, midpoint, microprice and supplied-depth imbalance.',
        'arguments': {'bids': [{'price': 'positive integer minor units', 'quantity': 'positive integer'}],
                      'asks': [{'price': 'positive integer minor units', 'quantity': 'positive integer'}]},
        'conditions': 'nonempty aggregated levels; bids descending, asks ascending; uncrossed or locked'},
    'vwap': {'description': 'Exact quantity-weighted mean; no binary float arithmetic.',
        'arguments': {'trades': [{'price': 'positive integer minor units', 'quantity': 'positive integer'}]},
        'conditions': 'nonempty executed trades, all prices in one unit/currency; excludes fees'},
    'price_time_preview': {'description': 'Read-only fill preview for the explicit basic FIFO policy.',
        'arguments': {'incoming': {'side': 'BID|ASK', 'limit_price': 'positive integer', 'quantity': 'positive integer'},
            'opposite_orders': [{'order_id': 'nonnegative integer', 'price': 'positive integer',
                                 'quantity': 'positive integer', 'priority': 'nonnegative integer'}],
            'policy': 'visible-limit-fifo-self-trade-allowed'},
        'conditions': 'unique logical IDs; unambiguous supplied price-time order; hidden/PTC/STP/auction excluded'},
}


def call(request):
    try:
        fields(request, ('tool', 'arguments'))
        name = request['tool']
        if type(name) is not str or name not in TOOLS:
            raise Unsupported('unknown tool; discover supported tools first')
        return {'status': 'ok', 'tool': name, 'version': 1, 'result': TOOLS[name](request['arguments'])}
    except Unsupported as error:
        return {'status': 'unsupported', 'reason': str(error),
            'next': 'clarify semantics or use the authoritative baseline; do not guess'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--catalog', action='store_true')
    parser.add_argument('--schema', choices=sorted(TOOLS))
    args = parser.parse_args()
    if args.catalog:
        result = [{'tool': name, 'description': SCHEMAS[name]['description']} for name in TOOLS]
    elif args.schema:
        result = SCHEMAS[args.schema]
    else:
        try:
            data = sys.stdin.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024: raise Unsupported('request exceeds2MiB characters')
            def pairs(items):
                result = {}
                for k,v in items:
                    if k in result:raise Unsupported('duplicate JSON key')
                    result[k]=v
                return result
            result = call(json.loads(data, object_pairs_hook=pairs))
        except (ValueError, TypeError, RecursionError) as error:
            result = {'status': 'unsupported', 'reason': str(error)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))


if __name__ == '__main__': main()
