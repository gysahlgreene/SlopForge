import unittest

from slopforge.candidates import reject_candidate


class ReviewActionTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {"assets": {"concept:badge": {
            "id": "badge-id", "name": "badge", "type": "concept", "status": "candidate",
            "candidates": {"selected": None, "items": [
                {"number": 1, "status": "candidate", "approval": None},
                {"number": 2, "status": "candidate", "approval": None},
            ]}}}}

    def test_reject_records_reason_and_leaves_sibling_candidates_selectable(self):
        rejected = reject_candidate(self.manifest, "badge", 1, "wrong silhouette")
        asset = self.manifest["assets"]["concept:badge"]
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["review"]["reason"], "wrong silhouette")
        self.assertEqual(asset["candidates"]["items"][1]["status"], "candidate")

    def test_approved_selected_candidate_cannot_be_rejected(self):
        asset = self.manifest["assets"]["concept:badge"]
        asset["candidates"]["selected"] = 1
        asset["candidates"]["items"][0]["approval"] = "approved"
        with self.assertRaisesRegex(ValueError, "approved candidate"):
            reject_candidate(self.manifest, "badge", 1)


if __name__ == "__main__":
    unittest.main()
