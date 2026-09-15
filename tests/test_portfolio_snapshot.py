import unittest
from trading.portfolio_snapshot import parse_occ_symbol,build_portfolio_snapshot
from trading.types import AccountSnapshot
class T(unittest.TestCase):
 def test_occ(self):
  c=parse_occ_symbol("SPY261030P00650000");self.assertEqual((c.root,c.expiration,c.option_type,c.strike),("SPY","2026-10-30","put",650.0))
 def test_sanitized(self):
  a=AccountSnapshot("SECRET","margin",50000,10000,20000,40000);s=build_portfolio_snapshot(a,[{"symbol":"SPY261030P00650000","quantity":-1}],paper_committed_defined_risk=600);self.assertNotIn("account_id",s["account"]);self.assertEqual(s["broker_positions"][0]["underlying"],"SPY");self.assertAlmostEqual(s["paper_defined_risk_pct_equity"],.012)
