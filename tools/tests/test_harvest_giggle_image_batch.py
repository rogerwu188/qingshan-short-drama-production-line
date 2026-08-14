import unittest

from tools.harvest_giggle_image_batch import batch_credit_assignment, explicit_credit


class ExplicitCreditTests(unittest.TestCase):
    def test_finds_nested_numeric_field(self):
        self.assertEqual(explicit_credit({"data": {"billing": {"credits_used": 135}}}), 135)

    def test_does_not_guess_from_unrelated_number(self):
        self.assertIsNone(explicit_credit({"data": {"duration": 15, "task_id": "abc"}}))

    def test_ignores_boolean(self):
        self.assertIsNone(explicit_credit({"credit": True}))

    def test_assigns_uniform_exact_batch_ledger(self):
        source = {
            "credit_reconciliation": {
                "status": "PASS",
                "matched_count": 2,
                "statement_rows": [{"credit": "-11"}, {"credit": "-11"}],
            }
        }
        self.assertEqual(batch_credit_assignment(source, 2)[0], 11)

    def test_refuses_nonuniform_or_count_mismatch(self):
        source = {
            "credit_reconciliation": {
                "status": "PASS",
                "matched_count": 2,
                "statement_rows": [{"credit": "-11"}, {"credit": "-22"}],
            }
        }
        self.assertIsNone(batch_credit_assignment(source, 2)[0])
        self.assertIsNone(batch_credit_assignment(source, 3)[0])


if __name__ == "__main__":
    unittest.main()
