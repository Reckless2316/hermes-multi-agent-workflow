import unittest,yaml
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
class T(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.d=yaml.safe_load((ROOT/"triage.yaml").read_text())
 def test_existing_repo_contracts(self):
  d=self.d;self.assertEqual(d["name"],"automated-trading");self.assertEqual(d["board"],"trading");self.assertEqual([x["id"] for x in d["sources"]],["options","swing"]);self.assertEqual({x["skill"] for x in d["sources"]},{"triage-scout-options","triage-scout-swing"});self.assertEqual(d["route"]["map"],{"options_take":"options","swing_take":"swing","wait":"watch","skip":"shelve","no_edge":"shelve"});self.assertEqual(d["rubric"]["threshold"],70);self.assertEqual(sum(x["max"] for x in d["rubric"]["dimensions"]),100);self.assertTrue(d["paths"]["shelve"]["auto"]);self.assertEqual(d["paths"]["options"]["fulfill"][0]["stage"],"materialize_setup")
 def test_classifier_and_roles(self):
  d=self.d;self.assertIn(d["research_lanes"]["classifier_lane"],d["research_lanes"]["lanes"]);roles=set(d["roles"]);used={d["research_lanes"]["role"]}
  for p in d["paths"].values():
   if not isinstance(p,dict):continue
   if p.get("propose"):used.add(p["propose"].get("role","orchestrator"))
   for x in p.get("prep",[])+p.get("fulfill",[]):used.add(x["role"])
  self.assertLessEqual(used,roles)
