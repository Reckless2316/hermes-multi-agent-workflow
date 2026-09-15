import unittest
from datetime import date
from pathlib import Path

from trading.config import StrategyConfig
from trading.duplicates import broker_has_exact_structure
from trading.options_engine import scan_defined_risk
from trading.types import OptionContract, StrategyKind

ROOT=Path(__file__).resolve().parent.parent
CFG=StrategyConfig.load(ROOT/"strategy/tasty_defined_risk_v1.yaml")
EXP="2026-10-30"
def oc(symbol,typ,strike,bid,ask,delta):return OptionContract(symbol,"SPY",EXP,typ,strike,bid,ask,volume=200,open_interest=1000,delta=delta,mid_iv=.25)
def candidate():
 chain=[oc("SPY261030P00640000","put",640,1.9,2.1,-.15),oc("SPY261030P00650000","put",650,5.2,5.4,-.30)]
 return next(x for x in scan_defined_risk("SPY",chain,CFG,as_of=date(2026,9,15)) if x.strategy==StrategyKind.SHORT_PUT_VERTICAL)
class T(unittest.TestCase):
 def test_exact_broker_duplicate(self):
  c=candidate();self.assertTrue(broker_has_exact_structure(c,[{"symbol":c.legs[0].option_symbol,"quantity":-1},{"symbol":c.legs[1].option_symbol,"quantity":1}]))
 def test_partial_overlap_not_called_duplicate(self):
  c=candidate();self.assertFalse(broker_has_exact_structure(c,[{"symbol":c.legs[0].option_symbol,"quantity":-1}]))
