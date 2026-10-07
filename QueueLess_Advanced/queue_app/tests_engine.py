"""Pure-maths tests: run anywhere with  python -m unittest queue_app.tests_engine"""
import unittest

from queue_app import engine


class EngineTests(unittest.TestCase):
    def test_ewma_weights_recent_samples(self):
        self.assertGreater(engine.ewma([5, 5, 5, 20]), engine.ewma([20, 5, 5, 5]))

    def test_outliers_are_clipped(self):
        clean = engine.winsorize([10, 10, 11, 9, 1, 300])
        self.assertLessEqual(max(clean), 33)
        self.assertGreaterEqual(min(clean), 3)

    def test_no_history_falls_back_to_baseline(self):
        s = engine.estimate_service_time([], [], 10, 12)
        self.assertEqual(s["avg"], 12)
        self.assertEqual(s["samples"], 0)

    def test_learns_slower_service(self):
        s = engine.estimate_service_time([8] * 10 + [16] * 6, [9] * 16, 14, 8)
        self.assertGreater(s["avg"], 11)
        self.assertTrue(s["slow"])

    def test_busy_hour_factor(self):
        mins = [10] * 6 + [15] * 4
        hours = [9] * 6 + [11] * 4
        busy = engine.estimate_service_time(mins, hours, 11, 10)["factor"]
        quiet = engine.estimate_service_time(mins, hours, 9, 10)["factor"]
        self.assertGreater(busy, 1.0)
        self.assertLess(quiet, busy)

    def test_more_counters_cut_the_wait(self):
        one = engine.wait_estimate(6, 1, 1, 10, 2)["minutes"]
        two = engine.wait_estimate(6, 1, 2, 10, 2)["minutes"]
        self.assertAlmostEqual(two, one / 2, delta=1)

    def test_range_contains_estimate(self):
        w = engine.wait_estimate(5, 0, 1, 10, 3)
        self.assertLessEqual(w["low"], w["minutes"])
        self.assertGreaterEqual(w["high"], w["minutes"])

    def test_crowd_levels(self):
        self.assertEqual(engine.crowd_levels([1, 5, 10]), ["Low", "Medium", "High"])
        self.assertEqual(engine.crowd_levels([0, 0]), ["Low", "Low"])

    def test_no_show_risk_is_smoothed(self):
        self.assertAlmostEqual(engine.no_show_risk(0, 0), 0.1)
        self.assertGreater(engine.no_show_risk(3, 5), engine.no_show_risk(0, 5))

    def test_staffing_advice(self):
        tips = engine.staffing_advice(40, 8, 1, 2, False)
        self.assertEqual(tips[0][0], "warn")
        self.assertIn("idle counter", tips[0][1])
        self.assertEqual(engine.staffing_advice(5, 1, 1, 1, False)[0][0], "ok")


if __name__ == "__main__":
    unittest.main()
