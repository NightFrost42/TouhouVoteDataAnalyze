from __future__ import annotations

import math
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "scripts_pipeline"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from covote_metrics import empty_exact_metrics, exact_2x2_metrics  # noqa: E402


class CoVoteMetricTests(unittest.TestCase):
    def test_exact_cells_follow_official_cn_convention(self) -> None:
        values = exact_2x2_metrics(10, 20, 30, 40)
        self.assertEqual(values["intersection_count"], 10)
        self.assertEqual(values["raw_count"], 10)
        self.assertEqual(values["count_a"], 40)  # m00 + m10
        self.assertEqual(values["count_b"], 30)  # m00 + m01
        self.assertEqual(values["ballots"], 100)
        self.assertAlmostEqual(values["conditional_rate_a_to_b"], 10 / 40)
        self.assertAlmostEqual(values["conditional_rate_b_to_a"], 10 / 30)
        self.assertAlmostEqual(values["cosine"], values["ochiai"])
        self.assertAlmostEqual(values["cosine"], values["cosine_ochiai"])
        self.assertTrue(-1 <= values["phi"] <= 1)
        self.assertTrue(-1 <= values["npmi"] <= 1)
        self.assertEqual(values["metric_status"], "exact_complete_2x2")
        self.assertTrue(values["complete_pair_matrix"])

    def test_zero_intersection_is_observed_zero_not_missing(self) -> None:
        values = exact_2x2_metrics(0, 5, 7, 88)
        self.assertEqual(values["raw_count"], 0)
        self.assertEqual(values["intersection_count"], 0)
        self.assertEqual(values["share"], 0)
        self.assertEqual(values["jaccard"], 0)
        self.assertEqual(values["cosine"], 0)
        self.assertIsNone(values["pmi"])

    def test_zero_marginal_leaves_undefined_metrics_blank(self) -> None:
        values = exact_2x2_metrics(0, 0, 0, 10)
        self.assertEqual(values["count_a"], 0)
        self.assertEqual(values["count_b"], 0)
        for field in ("conditional_rate", "conditional_rate_a_to_b", "conditional_rate_b_to_a", "lift", "cosine", "jaccard", "pmi", "npmi", "phi"):
            self.assertIsNone(values[field], field)

    def test_unordered_metrics_are_invariant_and_directional_rates_swap(self) -> None:
        first = exact_2x2_metrics(10, 20, 30, 40)
        swapped = exact_2x2_metrics(10, 30, 20, 40)

        # Exchanging A and B exchanges the B-only/A-only cells and the two
        # conditional directions, while symmetric metrics remain unchanged.
        self.assertEqual(swapped["m01_b_only"], first["m10_a_only"])
        self.assertEqual(swapped["m10_a_only"], first["m01_b_only"])
        self.assertAlmostEqual(swapped["conditional_rate_a_to_b"], first["conditional_rate_b_to_a"])
        self.assertAlmostEqual(swapped["conditional_rate_b_to_a"], first["conditional_rate_a_to_b"])
        for field in ("share", "lift", "cosine", "ochiai", "jaccard", "pmi", "npmi", "phi"):
            self.assertEqual(swapped[field], first[field], field)

    def test_lift_pmi_npmi_and_phi_match_hand_calculation(self) -> None:
        values = exact_2x2_metrics(20, 10, 30, 40)
        # A=50, B=30, N=100; independence baseline is 15.
        self.assertEqual(values["baseline_count"], 15)
        self.assertAlmostEqual(values["lift"], 20 / 15)
        self.assertAlmostEqual(values["pmi"], math.log(20 / 15))
        self.assertAlmostEqual(values["npmi"], math.log(20 / 15) / -math.log(0.2))
        expected_phi = (20 * 100 - 50 * 30) / math.sqrt(50 * 30 * 50 * 70)
        self.assertAlmostEqual(values["phi"], expected_phi)

    def test_extreme_popularity_difference_keeps_finite_bounds(self) -> None:
        values = exact_2x2_metrics(1, 0, 999, 0)
        self.assertTrue(math.isfinite(values["cosine"]))
        self.assertTrue(0 <= values["cosine"] <= 1)
        self.assertIsNone(values["phi"])  # one marginal is constant, so phi has no denominator.
        self.assertAlmostEqual(values["npmi"], 0.0)

    def test_negative_or_non_integer_cells_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            exact_2x2_metrics(-1, 2, 3, 4)
        with self.assertRaises(ValueError):
            exact_2x2_metrics(1.5, 2, 3, 4)

    def test_incomplete_status_has_no_exact_metrics(self) -> None:
        values = empty_exact_metrics("official_published_leading_list")
        self.assertFalse(values["complete_pair_matrix"])
        self.assertEqual(values["metric_status"], "official_published_leading_list")
        for field in ("m00_both_selected", "m01_b_only", "m10_a_only", "m11_neither_selected", "baseline_count", "excess_count", "cosine", "ochiai", "jaccard", "pmi", "npmi", "phi"):
            self.assertIsNone(values[field], field)

    def test_all_emitted_numeric_values_are_finite(self) -> None:
        values = exact_2x2_metrics(5591, 4141, 3087, 10699)
        self.assertTrue(all(not isinstance(value, float) or math.isfinite(value) for value in values.values()))


if __name__ == "__main__":
    unittest.main()
