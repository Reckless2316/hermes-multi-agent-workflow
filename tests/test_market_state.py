import tempfile,unittest
from pathlib import Path
from trading.market_state import MarketStateStore
class T(unittest.TestCase):
 def test_state(self):
  with tempfile.TemporaryDirectory() as td:
   with MarketStateStore(Path(td)/"s.db") as s:
    s.apply_event({"type":"quote","symbol":"SPY","bid":100,"ask":100.1,"bidsz":5,"asksz":6,"biddate":"1000"});self.assertEqual(s.quote("SPY").bid,100);self.assertTrue(s.quote_is_fresh("SPY"));s.apply_event({"type":"trade","symbol":"SPY","price":"100.05","size":"100","date":"1002"});self.assertEqual(s.trade("SPY").size,100);self.assertEqual(s.stream_status()["connected"],1)
