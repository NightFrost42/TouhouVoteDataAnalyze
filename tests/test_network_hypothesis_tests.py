from __future__ import annotations

import math
import unittest

from scripts_pipeline import network_hypothesis_tests as inference


class NetworkInferenceFormulaTests(unittest.TestCase):
    def test_mann_whitney_and_cliffs_delta_count_ties(self) -> None:
        observation = [1.0, 2.0]
        control = [2.0, 3.0]
        self.assertAlmostEqual(inference.mann_whitney_u(observation, control), 0.5)
        self.assertAlmostEqual(inference.cliffs_delta(observation, control), -0.75)

    def test_all_ties_are_zero_effect_and_have_zero_width_ci(self) -> None:
        observation = [4.0, 4.0]
        control = [4.0, 4.0]
        self.assertEqual(inference.mann_whitney_u(observation, control), 2.0)
        self.assertEqual(inference.cliffs_delta(observation, control), 0.0)
        self.assertEqual(
            inference.bootstrap_cliffs_delta_ci(
                observation, control, repetitions=20, seed=11
            ),
            (0.0, 0.0),
        )

    def test_singleton_and_empty_groups_are_explicit(self) -> None:
        self.assertEqual(inference.cliffs_delta([2.0], [1.0]), 1.0)
        self.assertEqual(
            inference.bootstrap_cliffs_delta_ci([2.0], [1.0], repetitions=20, seed=3),
            (1.0, 1.0),
        )
        self.assertIsNone(inference.mann_whitney_u([], [1.0]))
        self.assertEqual(inference.bootstrap_cliffs_delta_ci([], [1.0], repetitions=20), (None, None))

    def test_holm_adjustment_is_step_down_and_keeps_missing_values(self) -> None:
        adjusted = inference.holm_adjust({"a": 0.01, "b": 0.02, "c": 0.2, "d": None})
        self.assertAlmostEqual(adjusted["a"], 0.03)
        self.assertAlmostEqual(adjusted["b"], 0.04)
        self.assertAlmostEqual(adjusted["c"], 0.2)
        self.assertIsNone(adjusted["d"])

    def test_expression_parser_is_strict_and_propagates_unknown(self) -> None:
        expression = inference.compile_expression("same_stage == 1 and same_region != 0", {"same_stage", "same_region"})
        self.assertTrue(inference.evaluate_expression(expression, {"same_stage": 1, "same_region": 1}))
        self.assertIsNone(inference.evaluate_expression(expression, {"same_stage": None, "same_region": 1}))
        with self.assertRaises(inference.ExpressionConfigError):
            inference.compile_expression("__import__('os')", {"same_stage"})
        with self.assertRaises(inference.ExpressionConfigError):
            inference.compile_expression("not_declared == 1", {"same_stage"})


class NetworkInferenceDataTests(unittest.TestCase):
    @staticmethod
    def covote(
        a: str,
        b: str,
        value: str,
        *,
        round_value: str = "10",
        complete: bool = True,
    ) -> dict[str, str]:
        return {
            "region": "cn",
            "round": round_value,
            "pair_category": "character",
            "canonical_a": a,
            "canonical_b": b,
            "name_a": a,
            "name_b": b,
            "complete_pair_matrix": str(complete),
            "data_completeness": "complete_matrix" if complete else "official_published_leading_list",
            "censoring_status": "not_censored" if complete else "right_censored_by_official_list",
            "intersection_count": value,
            "conditional_rate": value,
            "share": "0.0" if value == "0" else "0.2",
            "jaccard": "0.0" if value == "0" else "0.3",
        }

    @staticmethod
    def feature(
        a: str,
        b: str,
        same_stage: str,
        stage_a: str,
        stage_b: str,
        *,
        round_value: str = "10",
    ) -> dict[str, str]:
        return {
            "region": "cn",
            "round": round_value,
            "pair_category": "character",
            "canonical_a": a,
            "canonical_b": b,
            "canonical_pair_key": inference.pair_key_from_values(a, b),
            "same_stage": same_stage,
            "a_stage": stage_a,
            "b_stage": stage_b,
        }

    @staticmethod
    def config(*, metric: str = "intersection_count", minimum_scope: str = "any_observed") -> dict:
        return {
            "analysis_name": "test_network_inference",
            "parameters": {
                "random_seed": 17,
                "permutations": 31,
                "bootstrap_repetitions": 31,
                "confidence_level": 0.95,
                "tail": "two-sided",
                "adjustment_family": "region_round_metric",
            },
            "metrics": [{"name": metric, "column": metric, "minimum_scope": minimum_scope}],
            "hypotheses": [{
                "name": "same_stage",
                "observation": "same_stage == 1",
                "control": "same_stage == 0",
                "scope": "all_pairs",
                "inference_status": "exploratory",
            }],
        }

    def test_run_keeps_a_real_complete_zero_and_marks_partial_rows(self) -> None:
        covote = [
            self.covote("a", "b", "0"),
            self.covote("a", "c", "2"),
            self.covote("a", "d", "5", round_value="11", complete=False),
        ]
        features = [
            self.feature("a", "b", "true", "1", "1"),
            self.feature("a", "c", "false", "1", "2"),
            self.feature("a", "d", "true", "1", "1", round_value="11"),
        ]
        rows, integrity = inference.run_analysis(
            self.config(), covote_rows=covote, feature_rows=features
        )
        round_10 = next(row for row in rows if row["round"] == "10")
        round_11 = next(row for row in rows if row["round"] == "11")
        self.assertEqual((round_10["observation_n"], round_10["control_n"]), (1, 1))
        self.assertEqual(round_10["observation_median"], 0.0)
        self.assertEqual(round_10["control_median"], 2.0)
        self.assertEqual(round_10["data_status"], "complete_matrix")
        self.assertEqual(round_11["data_status"], "empty_control_group")
        self.assertEqual(round_11["metric_scope"], "partial_matrix_observed_only")
        self.assertEqual(integrity["rows"], 3)
        self.assertEqual(integrity["missing_feature_rows"], 0)

    def test_node_permutation_p_is_reproducible_and_is_not_asymptotic(self) -> None:
        covote = [
            self.covote("a", "b", "1"),
            self.covote("a", "c", "2"),
            self.covote("b", "c", "3"),
        ]
        features = [
            self.feature("a", "b", "true", "1", "1"),
            self.feature("a", "c", "false", "1", "2"),
            self.feature("b", "c", "false", "1", "2"),
        ]
        config = self.config()
        first, _ = inference.run_analysis(config, covote_rows=covote, feature_rows=features)
        second, _ = inference.run_analysis(config, covote_rows=covote, feature_rows=features)
        self.assertEqual(first, second)
        result = first[0]
        self.assertIsNotNone(result["raw_p"])
        self.assertGreaterEqual(result["raw_p"], 0.0)
        self.assertLessEqual(result["raw_p"], 1.0)
        self.assertGreater(result["valid_permutations"], 0)
        # The implementation reports the requested Monte Carlo count and does
        # not expose an independent-sample normal/chi-square p value.
        self.assertEqual(result["permutations"], 31)

    def test_node_permutation_p_supports_all_tail_modes(self) -> None:
        covote = [
            self.covote("a", "b", "1"),
            self.covote("a", "c", "2"),
            self.covote("b", "c", "3"),
        ]
        features = [
            self.feature("a", "b", "true", "1", "1"),
            self.feature("a", "c", "false", "1", "2"),
            self.feature("b", "c", "false", "1", "2"),
        ]
        p_values = {}
        for tail in ("two-sided", "greater", "less"):
            config = self.config()
            config["parameters"]["tail"] = tail
            rows, _ = inference.run_analysis(config, covote_rows=covote, feature_rows=features)
            p_values[tail] = rows[0]["raw_p"]
        self.assertTrue(all(0.0 <= value <= 1.0 for value in p_values.values()))
        self.assertNotEqual(p_values["greater"], p_values["less"])
        self.assertNotEqual(p_values["two-sided"], p_values["greater"])

        covote = [self.covote("a", "b", "1", complete=False)]
        features = [self.feature("a", "b", "true", "1", "1")]
        rows, _ = inference.run_analysis(
            self.config(metric="share", minimum_scope="complete_matrix"),
            covote_rows=covote,
            feature_rows=features,
        )
        self.assertEqual(rows[0]["observation_n"], 0)
        self.assertIsNone(rows[0]["raw_p"])
        self.assertEqual(rows[0]["data_status"], "metric_requires_complete_matrix")
        self.assertEqual(rows[0]["metric_scope"], "complete_matrix")


if __name__ == "__main__":
    unittest.main()
