"""Finite financial examples and refusal controls; no simulator imports."""
import copy
import unittest
from classic_finance_tools import call


class FinanceToolsTests(unittest.TestCase):
    def run_tool(self, name, args):
        result = call({'tool':name,'arguments':args})
        self.assertEqual(result['status'],'ok')
        return result['result']

    def test_quote_microprice_and_depth(self):
        result=self.run_tool('book_features',{'bids':[{'price':100,'quantity':8},{'price':99,'quantity':2}],
            'asks':[{'price':102,'quantity':2},{'price':103,'quantity':3}]})
        self.assertEqual(result['midpoint'],{'numerator':101,'denominator':1})
        self.assertEqual(result['top_microprice'],{'numerator':508,'denominator':5})
        self.assertEqual(result['top_imbalance'],{'numerator':3,'denominator':5})
        self.assertEqual(result['supplied_depth_imbalance'],{'numerator':1,'denominator':3})
        self.assertEqual(result['spread_bps'],{'numerator':20000,'denominator':101})

    def test_locked_book(self):
        result=self.run_tool('book_features',{'bids':[{'price':100,'quantity':1}], 'asks':[{'price':100,'quantity':3}]})
        self.assertTrue(result['locked']); self.assertEqual(result['spread'],0)

    def test_exact_large_vwap(self):
        base=2**60
        result=self.run_tool('vwap',{'trades':[{'price':base,'quantity':2},{'price':base+1,'quantity':1}]})
        self.assertEqual(result['vwap'],{'numerator':3*base+1,'denominator':3})

    def test_split_execution_invariance(self):
        a=self.run_tool('vwap',{'trades':[{'price':101,'quantity':5}]})
        b=self.run_tool('vwap',{'trades':[{'price':101,'quantity':2},{'price':101,'quantity':3}]})
        self.assertEqual(a,b)

    def test_fifo_partial_and_nonmutation(self):
        args={'incoming':{'side':'BID','limit_price':100,'quantity':4}, 'policy':'visible-limit-fifo-self-trade-allowed',
            'opposite_orders':[{'order_id':7,'price':100,'quantity':3,'priority':0},
                {'order_id':8,'price':100,'quantity':3,'priority':1}, {'order_id':9,'price':101,'quantity':5,'priority':2}]}
        before=copy.deepcopy(args); result=self.run_tool('price_time_preview',args)
        self.assertEqual(args,before)
        self.assertEqual(result['fills'],[{'order_id':7,'price':100,'quantity':3},{'order_id':8,'price':100,'quantity':1}])
        self.assertEqual(result['opposite_orders_after'][0]['quantity'],2)
        self.assertEqual(result['filled']+result['remaining'],4)

    def test_sell_multilevel(self):
        result=self.run_tool('price_time_preview',{'incoming':{'side':'ASK','limit_price':100,'quantity':5},
            'policy':'visible-limit-fifo-self-trade-allowed','opposite_orders':[
                {'order_id':1,'price':101,'quantity':3,'priority':2},{'order_id':2,'price':100,'quantity':4,'priority':1}]})
        self.assertEqual(result['notional'],503)
        self.assertEqual(result['vwap'],{'numerator':503,'denominator':5})

    def test_no_cross(self):
        result=self.run_tool('price_time_preview',{'incoming':{'side':'BID','limit_price':99,'quantity':4},
            'policy':'visible-limit-fifo-self-trade-allowed','opposite_orders':[{'order_id':1,'price':100,'quantity':3,'priority':0}]})
        self.assertEqual(result['fills'],[]);self.assertEqual(result['remaining'],4);self.assertIsNone(result['vwap'])

    def test_refuse_ambiguous_and_wrong_variants(self):
        good={'incoming':{'side':'BID','limit_price':100,'quantity':4},'policy':'visible-limit-fifo-self-trade-allowed',
            'opposite_orders':[{'order_id':1,'price':100,'quantity':3,'priority':0}]}
        cases=[]
        stp=copy.deepcopy(good);stp['policy']='stp-newest';cases.append(stp)
        wrong=copy.deepcopy(good);wrong['incoming']['side']=[];cases.append(wrong)
        hidden=copy.deepcopy(good);hidden['opposite_orders'][0]['hidden']=True;cases.append(hidden)
        duplicate=copy.deepcopy(good);duplicate['opposite_orders']*=2;cases.append(duplicate)
        for value in cases:self.assertEqual(call({'tool':'price_time_preview','arguments':value})['status'],'unsupported')

    def test_refuse_invalid_numbers_and_books(self):
        for value in (True,0,-1,1.5,'100',None):
            self.assertEqual(call({'tool':'vwap','arguments':{'trades':[{'price':value,'quantity':1}]}})['status'],'unsupported')
        for bids,asks in (([],[]),([{'price':103,'quantity':1}],[{'price':102,'quantity':1}]),
                          ([{'price':100,'quantity':1},{'price':101,'quantity':1}],[{'price':102,'quantity':1}])):
            self.assertEqual(call({'tool':'book_features','arguments':{'bids':bids,'asks':asks}})['status'],'unsupported')

    def test_dispatch_refusal(self):
        for request in ({'tool':'unknown','arguments':{}},{'tool':[],'arguments':{}},{'tool':'vwap','arguments':{},'extra':1}):
            self.assertEqual(call(request)['status'],'unsupported')


if __name__=='__main__':unittest.main()
