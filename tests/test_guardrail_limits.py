import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "app"))

import guardrail_limits  # noqa: E402


class RequestLimitsTests(unittest.TestCase):
    def test_defaults_allow_a_large_server_side_seed(self):
        with patch.dict(os.environ, {}, clear=True):
            limits = guardrail_limits.resolve_request_limits()
        self.assertEqual(limits.seed_entries, 10000)
        self.assertEqual(limits.original_chars, 4096)
        self.assertEqual(limits.aggregate_chars, 1048576)
        self.assertEqual(limits.json_body_bytes, 8388608)

    def test_environment_values_are_clamped_to_hard_ceilings(self):
        environment = {
            guardrail_limits.SEED_ENTRIES_ENV: "999999999999999999999",
            guardrail_limits.ORIGINAL_CHARS_ENV: "999999999999999999999",
            guardrail_limits.AGGREGATE_CHARS_ENV: "999999999999999999999",
            guardrail_limits.JSON_BODY_BYTES_ENV: "999999999999999999999",
        }
        with patch.dict(os.environ, environment):
            limits = guardrail_limits.resolve_request_limits()
        self.assertEqual(limits.seed_entries, 20000)
        self.assertEqual(limits.original_chars, 65536)
        self.assertEqual(limits.aggregate_chars, 2097152)
        self.assertEqual(limits.json_body_bytes, 16777216)

    def test_invalid_or_nonpositive_values_fall_back_to_defaults(self):
        environment = {
            guardrail_limits.SEED_ENTRIES_ENV: "not-an-integer",
            guardrail_limits.ORIGINAL_CHARS_ENV: "0",
            guardrail_limits.AGGREGATE_CHARS_ENV: "-1",
            guardrail_limits.JSON_BODY_BYTES_ENV: "NaN",
        }
        with patch.dict(os.environ, environment):
            limits = guardrail_limits.resolve_request_limits()
        self.assertEqual(limits, guardrail_limits.RequestLimits(10000, 4096, 1048576, 8388608))


if __name__ == "__main__":
    unittest.main()
