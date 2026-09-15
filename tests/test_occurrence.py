import unittest
from trading.occurrence import find_active_occurrence

class OccurrenceTests(unittest.TestCase):
    def test_pending_item_blocks_duplicate(self):
        self.assertEqual(find_active_occurrence("abc", [("old", {"candidate_id":"abc","status":"awaiting_approval"})]), "old")
    def test_approved_history_does_not_permanently_block(self):
        self.assertIsNone(find_active_occurrence("abc", [("old", {"candidate_id":"abc","status":"approved"})]))
    def test_other_candidate_does_not_block(self):
        self.assertIsNone(find_active_occurrence("abc", [("old", {"candidate_id":"def","status":"research"})]))
