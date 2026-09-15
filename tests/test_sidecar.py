import json
import tempfile
import unittest
from pathlib import Path
from trading.sidecar import SidecarSelectionError, load_candidate, write_candidate
class SidecarTests(unittest.TestCase):
    def test_exact_candidate_materialization(self):
        payload={"candidates":[{"candidate_id":"a","underlying":"SPY","net_credit":1.0},{"candidate_id":"b","underlying":"QQQ","net_credit":2.0}]}
        with tempfile.TemporaryDirectory() as td:
            sidecar=Path(td)/"scan.json";output=Path(td)/"setup.json";sidecar.write_text(json.dumps(payload));self.assertEqual(load_candidate(sidecar,"b")["underlying"],"QQQ");write_candidate(sidecar,"a",output);self.assertEqual(json.loads(output.read_text())["candidate_id"],"a")
    def test_missing_candidate_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            sidecar=Path(td)/"scan.json";sidecar.write_text(json.dumps({"candidates":[]}))
            with self.assertRaises(SidecarSelectionError):load_candidate(sidecar,"missing")
