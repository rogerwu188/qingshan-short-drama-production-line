import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DISABLED = re.compile(r'["\']run_regression_ci["\']\s*:\s*False\b')


class RegressionCiCannotBeDisabledTest(unittest.TestCase):
    def test_no_production_builder_disables_regression_ci(self):
        offenders = []
        for path in sorted((ROOT / "tools").glob("*.py")):
            if DISABLED.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], f"run_regression_ci=False is forbidden: {offenders}")


if __name__ == "__main__":
    unittest.main()
