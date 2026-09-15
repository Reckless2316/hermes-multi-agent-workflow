from __future__ import annotations
import tempfile,unittest
from datetime import date
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from trading.config import StrategyConfig,StrategyConfigError
from trading.intake import candidate_id,render_options_intake
from trading.options_engine import choose_expiration,scan_credit_verticals,scan_defined_risk
from trading.portfolio import SizingRejected,size_candidate
from trading.position_manager import manage_credit_position,natural_close_debit
from trading.revalidate import RevalidationRejected,revalidate_for_paper_fill
from trading.tradier import TradierClient,TradierResponse,RateLimitState
from trading.types import AccountSnapshot,ManagementAction,OptionContract,PositionState,StrategyKind,sized_candidate_from_dict
CFG=StrategyConfig.load(ROOT/"strategy/tasty_defined_risk_v1.yaml");AS_OF=date(2026,9,15);EXP="2026-10-30"
def oc(symbol,typ,strike,bid,ask,delta,oi=1000,vol=200,iv=.25):return OptionContract(symbol,"SPY",EXP,typ,float(strike),float(bid),float(ask),volume=vol,open_interest=oi,delta=delta,mid_iv=iv)
def chain():return [oc("SPY261030P00630000","put",630,.9,1.1,-.08),oc("SPY261030P00640000","put",640,1.9,2.1,-.15),oc("SPY261030P00645000","put",645,3.3,3.5,-.20),oc("SPY261030P00650000","put",650,5.2,5.4,-.30),oc("SPY261030C00700000","call",700,5.2,5.4,.30),oc("SPY261030C00705000","call",705,3.3,3.5,.20),oc("SPY261030C00710000","call",710,1.9,2.1,.15),oc("SPY261030C00720000","call",720,.9,1.1,.08)]
def acct(eq=100000,bp=50000):return AccountSnapshot("SECRET","margin",eq,25000,bp,100000)
class ConfigTests(unittest.TestCase):
 def test_live_rejected(self):
  raw={**CFG.raw,"mode":"live"}
  with self.assertRaises(StrategyConfigError):StrategyConfig.from_dict(raw)
 def test_universe_normalized(self):
  raw={**CFG.raw,"universe":{"symbols":[" spy ","qqq"]}};self.assertEqual(StrategyConfig.from_dict(raw).universe,("SPY","QQQ"))
class ScannerTests(unittest.TestCase):
 def test_expiry_target(self):self.assertEqual(choose_expiration(["2026-10-16",EXP,"2026-11-20"],CFG,as_of=AS_OF),EXP)
 def test_verticals(self):
  r=scan_credit_verticals("SPY",chain(),CFG,as_of=AS_OF);c=next(x for x in r if x.strategy==StrategyKind.SHORT_PUT_VERTICAL and x.width==10);self.assertAlmostEqual(c.net_credit,3.1);self.assertAlmostEqual(c.max_loss,690);self.assertTrue(all(g.passed for g in c.gates))
 def test_illiquid_rejected(self):
  b=chain();b[3]=oc("SPY261030P00650000","put",650,5.2,5.4,-.30,oi=1,vol=0);self.assertFalse(any(x.legs[0].strike==650 and x.strategy==StrategyKind.SHORT_PUT_VERTICAL for x in scan_credit_verticals("SPY",b,CFG,as_of=AS_OF)))
 def test_condor(self):self.assertTrue(any(x.strategy==StrategyKind.IRON_CONDOR and len(x.legs)==4 for x in scan_defined_risk("SPY",chain(),CFG,as_of=AS_OF)))
class SizingTests(unittest.TestCase):
 def candidate(self):return next(x for x in scan_defined_risk("SPY",chain(),CFG,as_of=AS_OF) if x.strategy==StrategyKind.SHORT_PUT_VERTICAL and x.width==10)
 def test_one_percent(self):
  s=size_candidate(self.candidate(),acct(),CFG);self.assertEqual(s.contracts,1);self.assertAlmostEqual(s.total_max_loss,690)
 def test_too_small(self):
  with self.assertRaises(SizingRejected):size_candidate(self.candidate(),acct(20000,500),CFG)
class IntakeTests(unittest.TestCase):
 def test_sidecar_and_roundtrip(self):
  s=size_candidate(next(x for x in scan_defined_risk("SPY",chain(),CFG,as_of=AS_OF) if x.strategy==StrategyKind.SHORT_PUT_VERTICAL and x.width==10),acct(),CFG);text=render_options_intake([s],sidecar_path="/tmp/a.json");self.assertIn("sidecar_json: /tmp/a.json",text);self.assertIn(candidate_id(s),text);raw={**s.candidate.to_dict(),"contracts":s.contracts,"risk_budget":s.risk_budget,"total_max_loss":s.total_max_loss,"total_profit_target":s.total_profit_target,"total_buying_power_reduction":s.total_buying_power_reduction};self.assertEqual(sized_candidate_from_dict(raw).candidate.legs[0].option_symbol,s.candidate.legs[0].option_symbol)
class RevalidationTests(unittest.TestCase):
 def approved(self):
  c=next(x for x in scan_defined_risk("SPY",chain(),CFG,as_of=AS_OF) if x.strategy==StrategyKind.SHORT_PUT_VERTICAL and x.width==10);return size_candidate(c,acct(),CFG)
 def test_valid(self):
  a=self.approved();rv=revalidate_for_paper_fill(a,chain(),acct(),CFG,as_of=AS_OF);self.assertEqual(rv.fill_credit,a.candidate.net_credit);self.assertEqual(rv.to_fill_candidate().candidate.legs[0].option_symbol,a.candidate.legs[0].option_symbol)
 def test_deterioration(self):
  a=self.approved();b=chain();b[3]=oc("SPY261030P00650000","put",650,5.0,5.2,-.30)
  with self.assertRaises(RevalidationRejected):revalidate_for_paper_fill(a,b,acct(),CFG,as_of=AS_OF)
 def test_liquidity_failure(self):
  a=self.approved();b=chain();b[3]=oc("SPY261030P00650000","put",650,5.2,5.4,-.30,oi=1,vol=0)
  with self.assertRaises(RevalidationRejected):revalidate_for_paper_fill(a,b,acct(),CFG,as_of=AS_OF)
class ManagementTests(unittest.TestCase):
 def position(self,exp=EXP):return PositionState("p","SPY",StrategyKind.SHORT_PUT_VERTICAL,exp,"x",3,10,1,300,700,.5,21)
 def test_winner(self):self.assertEqual(manage_credit_position(self.position(),current_close_debit=1.4,cfg=CFG,as_of=AS_OF).action,ManagementAction.CLOSE_WINNER)
 def test_21d_loser(self):self.assertEqual(manage_credit_position(self.position("2026-10-06"),current_close_debit=4,cfg=CFG,as_of=AS_OF).action,ManagementAction.REVIEW_ROLL_FOR_CREDIT)
 def test_natural_close(self):self.assertAlmostEqual(natural_close_debit([{"option_symbol":"S","side":"sell_to_open","quantity":1},{"option_symbol":"L","side":"buy_to_open","quantity":1}],{"S":{"bid":1.4,"ask":1.5},"L":{"bid":.45,"ask":.55}}),1.05)
class LedgerTests(unittest.TestCase):
 def test_lifecycle(self):
  from trading.paper_options import OptionsPaperLedger
  c=next(x for x in scan_defined_risk("SPY",chain(),CFG,as_of=AS_OF) if x.strategy==StrategyKind.SHORT_PUT_VERTICAL and x.width==10);s=size_candidate(c,acct(),CFG)
  with tempfile.TemporaryDirectory() as td:
   with OptionsPaperLedger(Path(td)/"l.db") as l:
    pid=l.open_position(s);self.assertEqual(len(l.open_positions()),1)
    with self.assertRaises(ValueError):l.open_position(s)
    self.assertGreater(l.close_position(pid,exit_debit=1.0,reason="T")["realized_pnl"],0);self.assertEqual(l.metrics()["wins"],1)
class FakeTradier(TradierClient):
 def __init__(self,payload):super().__init__("x",account_id="TEST");self.payload=payload
 def _request_json(self,method,path,**kwargs):return TradierResponse(self.payload[path],RateLimitState(120,1,119,None))
class TradierTests(unittest.TestCase):
 def test_read_only_client_blocks_account_post(self):
  from trading.tradier import TradierError
  client=TradierClient("x",account_id="TEST")
  with self.assertRaises(TradierError):client._request_json("POST","/accounts/TEST/orders",body={"symbol":"SPY"})
 def test_market_clock_open(self):
  c=FakeTradier({"/markets/clock":{"clock":{"state":"open","description":"Market is open"}}});self.assertTrue(c.market_is_open())
 def test_market_clock_closed(self):
  c=FakeTradier({"/markets/clock":{"clock":{"state":"closed"}}});self.assertFalse(c.market_is_open())
 def test_single_position(self):self.assertEqual(len(FakeTradier({"/accounts/TEST/positions":{"positions":{"position":{"symbol":"SPY"}}}}).positions()),1)
 def test_chain_without_greeks(self):
  rows=FakeTradier({"/markets/options/chains":{"options":{"option":{"symbol":"SPY261030P00650000","underlying":"SPY","expiration_date":EXP,"option_type":"put","strike":650,"bid":5.2,"ask":5.4,"open_interest":1000,"volume":200}}}}).option_chain("SPY",EXP);self.assertIsNone(rows[0].delta)
if __name__=="__main__":unittest.main()
