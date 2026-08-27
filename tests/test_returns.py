import unittest

from app.analytics.returns import (
    chain_nav,
    compound_return,
    infer_external_flow,
    modified_dietz_return,
    product_period_return,
)


class ReturnTests(unittest.TestCase):
    def test_infers_external_flow(self) -> None:
        self.assertEqual(infer_external_flow(110000, 100000, 2000), 8000)

    def test_modified_dietz_uses_half_flow_weight(self) -> None:
        self.assertAlmostEqual(modified_dietz_return(2000, 100000, 8000), 2000 / 104000)

    def test_invalid_denominator_returns_none(self) -> None:
        self.assertIsNone(modified_dietz_return(100, 0, 0))
        self.assertIsNone(product_period_return(100, 0, 1000, True))

    def test_product_return_requires_contiguous_observation(self) -> None:
        self.assertIsNone(product_period_return(100, 10000, 0, False))
        self.assertAlmostEqual(product_period_return(100, 10000, 2000, True), 100 / 11000)

    def test_compound_return_requires_exact_window(self) -> None:
        self.assertAlmostEqual(compound_return([0.1, -0.05], 2), 0.045)
        self.assertIsNone(compound_return([0.1], 2))
        self.assertIsNone(compound_return([0.1, None], 2))

    def test_nav_chain_stops_after_invalid_period(self) -> None:
        self.assertEqual(chain_nav([0.1, -0.05], 1000), [1000, 1100, 1045])
        self.assertEqual(chain_nav([0.1, None, 0.2], 1000), [1000, 1100, None, None])
