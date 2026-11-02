from __future__ import annotations

import unittest

from tools.verda_model_experiment import resources, runtime


class CopyResourceGuardTests(unittest.TestCase):
    def setUp(self):
        self.observed = {
            "current_workers": 8,
            "batch_size": 8,
            "per_worker_peak_bytes": 1_000,
            "per_worker_pids": 10,
            "observed_per_worker_gpu_peak_bytes": 2_000,
        }
        self.limits = {
            "memory_current_bytes": 10_000,
            "memory_limit_bytes": 300_000,
            "pids_current": 100,
            "pids_limit": 1_000,
            "gpu_free_bytes": 50_000,
            "gpu_total_bytes": 100_000,
        }

    def test_twelve_and_sixteen_workers_use_actual_b8_observations(self):
        self.assertEqual(resources.PROSPECTIVE_WORKERS, {2, 4, 8, 12, 16})
        for workers in (12, 16):
            with self.subTest(workers=workers):
                result = resources.evaluate_resource_guard(
                    workers, dict(self.observed), dict(self.limits), 1_000)
                extra_workers = workers - 8
                projected_memory = 10_000 + extra_workers * 1_000 + 1_000
                projected_pids = 100 + extra_workers * 10
                additional_gpu = extra_workers * 2_000 + 1_000
                projected_gpu = 50_000 + additional_gpu
                self.assertTrue(result["allowed"])
                self.assertEqual(
                    runtime.evaluate_resource_guard(
                        workers, dict(self.observed), dict(self.limits), 1_000),
                    result)
                self.assertEqual(result["projected_memory_bytes"], projected_memory)
                self.assertEqual(result["projected_pids"], projected_pids)
                self.assertEqual(result["additional_gpu_bytes"], additional_gpu)
                self.assertEqual(result["projected_gpu_used_bytes"], projected_gpu)
                self.assertEqual(
                    result["required_memory_bytes"],
                    (projected_memory * 5 + 3) // 4)
                self.assertEqual(
                    result["required_pids"],
                    (projected_pids * 5 + 3) // 4)
                self.assertEqual(
                    result["required_gpu_total_bytes"],
                    (projected_gpu * 5 + 3) // 4)

    def test_future_worker_prediction_rejects_old_batch_one_projection(self):
        for batch_size in (1, 8.0, True, None):
            with self.subTest(batch_size=batch_size):
                observed = dict(self.observed, batch_size=batch_size)
                result = resources.evaluate_resource_guard(
                    12, observed, dict(self.limits), 1_000)
                self.assertFalse(result["allowed"])
                self.assertEqual(result["reason"], "actual_b8_observation_required")
                self.assertIsNone(result["projected_memory_bytes"])
                self.assertIsNone(result["projected_gpu_used_bytes"])

    def test_twelve_workers_require_actual_batch_eight_observation(self):
        observed = dict(self.observed, batch_size=4)
        result = resources.evaluate_resource_guard(
            12, observed, dict(self.limits), 1_000)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "actual_b8_observation_required")
        self.assertIsNone(result["projected_memory_bytes"])
        self.assertIsNone(result["required_gpu_total_bytes"])

    def test_non_mapping_observations_or_limits_remain_unknown(self):
        for observed, limits in ((None, dict(self.limits)),
                                 (dict(self.observed), None)):
            with self.subTest(observed=observed, limits=limits):
                result = resources.evaluate_resource_guard(
                    12, observed, limits, 1_000)
                self.assertFalse(result["allowed"])
                self.assertEqual(result["reason"], "resource_data_unknown")
                self.assertIsNone(result["projected_memory_bytes"])

    def test_existing_eight_worker_projection_remains_compatible(self):
        observed = dict(self.observed, current_workers=1, batch_size=1)
        result = resources.evaluate_resource_guard(
            8, observed, dict(self.limits), 1_000)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["workers"], 8)
        self.assertEqual(result["projected_memory_bytes"], 18_000)


if __name__ == "__main__":
    unittest.main()
