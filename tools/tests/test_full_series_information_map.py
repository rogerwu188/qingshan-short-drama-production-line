import unittest

from tools.build_full_series_information_map import build


class FullSeriesInformationMapTests(unittest.TestCase):
    def test_e18_through_e100_are_complete_and_ordered(self):
        payload = build()
        rows = payload["episodes"]
        self.assertEqual(len(rows), 83)
        self.assertEqual(rows[0]["episode"], "E18")
        self.assertEqual(rows[-1]["episode"], "E100")
        self.assertTrue(all(len(row["information_nodes"]) >= 3 for row in rows))
        self.assertTrue(all(row["end_hook"] for row in rows))
        self.assertTrue(all(row["dialogue_line_budget"]["minimum"] >= 29 for row in rows))
        self.assertTrue(all(row["production_allowed"] is False for row in rows))


if __name__ == "__main__":
    unittest.main()
