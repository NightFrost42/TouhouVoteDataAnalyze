from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts_pipeline.mrqap import (
    MatrixValidationError,
    build_character_dyads,
    fit_ols,
    permute_y_by_nodes,
    run_mrqap,
    validate_matrix_groups,
    write_run_artifacts,
)
from scripts_pipeline.model_run_manifest import verify_model_run_manifest


class MrqapTests(unittest.TestCase):
    @staticmethod
    def rows(*, complete: str = "True", missing_edge: bool = False) -> list[dict[str, str]]:
        # Six unordered pairs over four nodes.  The two predictors are
        # deliberately non-collinear so the hand-checkable coefficients are
        # identified by OLS with an intercept.
        edges = [
            ("a", "b", 0, 0, 0, 1.0, 0),
            ("a", "c", 1, 0, 1, 2.5, 1),
            ("a", "d", 1, 1, 1, 4.0, 1),
            ("b", "c", 0, 1, 1, 0.5, 0),
            ("b", "d", 1, 0, 1, 3.5, 1),
            ("c", "d", 0, 1, 0, -0.5, 0),
        ]
        result: list[dict[str, str]] = []
        for left, right, work, stage, count, lift, formed in edges:
            result.append(
                {
                    "region": "cn",
                    "round": "10",
                    "pair_category": "character",
                    "node_a": left,
                    "node_b": right,
                    "canonical_pair_key": f"{left}|{right}",
                    "complete_pair_matrix": complete,
                    "data_completeness": "complete_matrix" if complete == "True" else "official_published_leading_list",
                    "lift": str(lift),
                    "cosine": str(lift / 10),
                    "phi": str(lift / 20),
                    "formed": str(formed),
                    "same_work": str(work),
                    "same_stage": str(stage),
                    "same_work_adjacent_stage": str(stage),
                    "same_community": str(work),
                    "same_region": "1",
                    "log_count_a": str(1 + count),
                    "log_count_b": str(2 + count),
                }
            )
        if missing_edge:
            result[0]["same_work"] = "unknown"
        return result

    def test_fit_ols_reproduces_known_coefficients_and_ordinary_p(self) -> None:
        x = np.asarray([[0, 0], [1, 0], [1, 1], [0, 1], [1, 0], [0, 1]], dtype=float)
        y = np.asarray([1, 4, 3.5, 0.5, 4, 0.5], dtype=float)
        fit = fit_ols(y, x, ("x1", "x2"))
        self.assertTrue(fit.success, fit.diagnostic)
        assert fit.beta is not None and fit.p_value is not None
        self.assertAlmostEqual(float(fit.beta[0]), 1.0)
        self.assertAlmostEqual(float(fit.beta[1]), 3.0)
        self.assertAlmostEqual(float(fit.beta[2]), -0.5)
        self.assertTrue(0 <= float(fit.p_value[1]) <= 1)

    def test_run_separates_continuous_metrics_and_marks_lpm(self) -> None:
        run = run_mrqap(
            self.rows(),
            continuous_metrics=("lift", "cosine"),
            binary_metrics=("formed",),
            continuous_predictors=("same_work", "log_count_a"),
            binary_predictors=("same_work", "log_count_a"),
            permutations=12,
            random_seed=7,
            permutation_schemes=("node", "freedman_lane"),
        )
        self.assertEqual(len(run.rows), 12)
        self.assertEqual({row["dependent_metric"] for row in run.rows}, {"lift", "cosine", "formed"})
        self.assertEqual({row["model_type"] for row in run.rows if row["dependent_metric"] == "formed"}, {"linear_probability"})
        self.assertEqual({row["model_type"] for row in run.rows if row["dependent_metric"] == "lift"}, {"ols"})
        self.assertEqual({row["permutation_scheme"] for row in run.rows}, {"node", "freedman_lane"})
        for row in run.rows:
            self.assertEqual(row["permutations"], 12)
            self.assertEqual(row["permutations_used"], 12)
            self.assertIsNotNone(row["ordinary_p"])
            self.assertTrue(0 <= row["qap_p"] <= 1)

    def test_node_permutation_preserves_undirected_node_structure(self) -> None:
        values = np.asarray([1, 0, 1, 0, 1, 0], dtype=float)
        edges = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
        permutation = [2, 0, 3, 1]
        permuted = permute_y_by_nodes(values, 4, edges, permutation)
        original_matrix = np.zeros((4, 4))
        permuted_matrix = np.zeros((4, 4))
        for value, (left, right) in zip(values, edges):
            original_matrix[left, right] = original_matrix[right, left] = value
        for value, (left, right) in zip(permuted, edges):
            permuted_matrix[left, right] = permuted_matrix[right, left] = value
        self.assertEqual(sorted(original_matrix.sum(axis=0)), sorted(permuted_matrix.sum(axis=0)))
        np.testing.assert_array_equal(permuted_matrix, original_matrix[np.ix_(permutation, permutation)])

    def test_unknown_structure_is_missing_and_keeps_an_induced_matrix(self) -> None:
        run = run_mrqap(
            self.rows(missing_edge=True),
            continuous_metrics=("lift",),
            binary_metrics=(),
            continuous_predictors=("same_work",),
            binary_predictors=(),
            permutations=4,
            random_seed=3,
            permutation_schemes=("node",),
        )
        self.assertEqual(len(run.rows), 1)
        # The unknown a-b dyad requires dropping one endpoint; the remaining
        # three nodes retain their complete induced submatrix.
        self.assertEqual(run.rows[0]["complete_case_n"], 3)
        self.assertEqual(run.rows[0]["n_nodes"], 3)

    def test_partial_and_mixed_matrices_are_never_silently_zero_filled(self) -> None:
        partial = validate_matrix_groups(self.rows(complete="False"))
        self.assertEqual(len(partial.groups), 0)
        self.assertEqual(partial.excluded[0]["reason"], "partial_or_right_censored_matrix")
        with self.assertRaises(MatrixValidationError):
            validate_matrix_groups(self.rows(complete="False"), strict_partial=True)
        mixed = self.rows()
        mixed[0]["complete_pair_matrix"] = "False"
        mixed[0]["data_completeness"] = "official_published_leading_list"
        with self.assertRaises(MatrixValidationError):
            validate_matrix_groups(mixed)

    def test_collinearity_is_diagnostic_and_not_a_pseudoinverse_result(self) -> None:
        rows = self.rows()
        for row in rows:
            row["same_stage"] = row["same_work"]
        run = run_mrqap(
            rows,
            continuous_metrics=("lift",),
            binary_metrics=(),
            continuous_predictors=("same_work", "same_stage"),
            binary_predictors=(),
            permutations=2,
            random_seed=1,
            permutation_schemes=("node",),
        )
        self.assertEqual(len(run.rows), 2)
        self.assertTrue(all(row["status"] == "rank_deficient" for row in run.rows))
        self.assertTrue(all('"status":"rank_deficient"' in row["collinearity_diagnostic"] for row in run.rows))
        self.assertTrue(all(row["coefficient"] is None for row in run.rows))

    def test_binary_metric_requires_explicit_zero_or_one_for_every_pair(self) -> None:
        rows = self.rows()
        rows[0]["formed"] = "unknown"
        run = run_mrqap(
            rows,
            continuous_metrics=(),
            binary_metrics=("formed",),
            continuous_predictors=(),
            binary_predictors=("same_work",),
            permutations=3,
            random_seed=4,
            permutation_schemes=("node",),
        )
        self.assertEqual(len(run.rows), 1)
        self.assertEqual(run.rows[0]["model_type"], "linear_probability")
        self.assertEqual(run.rows[0]["status"], "binary_matrix_incomplete")
        self.assertIsNone(run.rows[0]["coefficient"])

        covote = [{
            "region": "cn", "round": "10", "pair_category": "character",
            "canonical_a": "A", "canonical_b": "B", "canonical_pair_key": "a|b",
            "complete_pair_matrix": "True", "data_completeness": "complete_matrix",
            "lift": "1.5", "cosine": "0.5", "phi": "0.2", "count_a": "10", "count_b": "20",
        }]
        rows = build_character_dyads(covote, [{
            "region": "cn", "round": "10", "pair_category": "character", "canonical_pair_key": "a|b",
            "same_reference_first_appearance_work": "unknown", "same_stage": "unknown",
        }], [])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["same_work"])
        self.assertNotIn("formed", rows[0])

    def test_manifest_is_directly_verifiable(self) -> None:
        run = run_mrqap(
            self.rows(),
            continuous_metrics=("lift",),
            binary_metrics=(),
            continuous_predictors=("same_work", "log_count_a"),
            binary_predictors=(),
            permutations=2,
            random_seed=11,
            permutation_schemes=("node",),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "dyads.csv"
            with input_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(self.rows()[0]))
                writer.writeheader()
                writer.writerows(self.rows())
            output = root / "analysis_results" / "network_inference" / "mrqap_coefficients.csv"
            manifest_path = root / "analysis_results" / "network_inference" / "model_run_manifest.json"
            manifest = write_run_artifacts(
                run,
                root=root,
                output_path=output,
                manifest_path=manifest_path,
                input_paths=(input_path,),
                parameters={"test": True},
                random_seed=11,
                permutations=2,
            )
            self.assertEqual(manifest["statistical_test"]["permutations"], 2)
            self.assertTrue(manifest["mrqap"]["nodes_sha256"])
            verification = verify_model_run_manifest(manifest_path, root=root)
            self.assertTrue(verification["ok"], verification)


if __name__ == "__main__":
    unittest.main()
