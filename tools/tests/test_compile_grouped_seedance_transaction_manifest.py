import unittest

from tools.compile_grouped_seedance_transaction_manifest import standard_reference_transport


class StandardReferenceTransportTests(unittest.TestCase):
    def test_production_exposes_one_standard_multi_reference_route(self):
        self.assertEqual(
            standard_reference_transport(),
            {
                "mode": "standard_multi_reference",
                "endpoint": "/api/v1/generation/omni-video",
            },
        )


if __name__ == "__main__":
    unittest.main()
