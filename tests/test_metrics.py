import unittest

from app.analytics.metrics import drawdown_stats, momentum_delta, rank_horizon, streak


class MetricTests(unittest.TestCase):
    def test_drawdown_reports_high_current_and_maximum(self) -> None:
        stats = drawdown_stats([1000, 1100, 990, 1050], ["d0", "d1", "d2", "d3"])
        self.assertEqual(stats["high_date"], "d1")
        self.assertAlmostEqual(stats["current_drawdown"], 1050 / 1100 - 1)
        self.assertAlmostEqual(stats["max_drawdown"], 990 / 1100 - 1)

    def test_momentum_compares_recent_and_previous_four(self) -> None:
        result = momentum_delta([0.01] * 4 + [0.02] * 4)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertGreater(result["delta"], 0)
        self.assertEqual(result["direction"], "strengthening")

    def test_flat_period_breaks_streak(self) -> None:
        self.assertEqual(streak([0.01, 0.02, 0.0005]), ("flat", 0))
        self.assertEqual(streak([-0.01, -0.02]), ("down", 2))

    def test_rank_requires_two_available_products(self) -> None:
        rows = rank_horizon([("A", 0.04), ("B", 0.02), ("C", None)])
        self.assertEqual(rows, [("A", 0.04, 1), ("B", 0.02, 2)])
        self.assertEqual(rank_horizon([("A", 0.04)]), [])
