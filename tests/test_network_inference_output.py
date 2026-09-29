from __future__ import annotations

import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts_pipeline import network_inference_output as output
from scripts_pipeline.model_run_manifest import verify_model_run_manifest


class NetworkInferenceOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "metadata").mkdir()
        shutil.copy2(output.SCHEMA_PATH, self.root / "metadata" / output.SCHEMA_PATH.name)
        (self.root / "data").mkdir()
        self.input_path = self.root / "data" / "source.csv"
        self.input_path.write_text("pair,value\na|b,0\n", encoding="utf-8")
        self.destination = self.root / "analysis_results" / "network_inference"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def tables() -> dict[str, list[dict[str, object]]]:
        return {
            "hypothesis_tests": [{
                "analysis_name": "fixture_hypothesis",
                "region": "cn",
                "round": "10",
                "metric": "intersection_count",
                "hypothesis": "same_work",
                "observation_n": "2",
                "control_n": "2",
                "cliffs_delta": "0.25",
                "raw_p": "0.4",
                "adjusted_p": "0.8",
                "adjustment_method": "holm",
                "adjustment_family": "cn10:intersection_count",
                "permutations": "99",
                "valid_permutations": "99",
                "random_seed": "17",
                "inference_status": "exploratory",
                "data_status": "complete_matrix",
                "metric_scope": "complete_matrix",
                "missing_policy": "exclude_unknown_no_zero_fill",
            }],
            "matrix_correlations": [{
                "matrix_a": "covote_character",
                "matrix_b": "covote_character",
                "region": "cn",
                "round": "10",
                "node_count": "3",
                "pair_count": "3",
                "metric_a": "raw_count",
                "metric_b": "cosine",
                "correlation_method": "spearman",
                "observed_correlation": "0",
                "permutation_p": "0.5",
                "permutations": "99",
                "random_seed": "17",
                "node_alignment_rule": "canonical_node_id_intersection",
                "missing_pair_rule": "common_observed_pairs_only_no_zero_fill",
                "complete_pair_matrix": "False",
                "valid_permutations": "99",
                "source_complete_a": "True",
                "source_complete_b": "True",
                "interpretation_note": "矩阵结构相关，不代表因果",
            }],
            "mrqap_coefficients": [{
                "region": "cn",
                "round": "10",
                "dependent_metric": "cosine",
                "model_type": "ols",
                "predictor": "same_stage",
                "coefficient": "",
                "ordinary_p": "",
                "qap_p": "",
                "permutations": "99",
                "permutations_used": "0",
                "random_seed": "17",
                "permutation_seed": "23",
                "permutation_scheme": "node",
                "n_pairs": "3",
                "complete_case_n": "0",
                "n_nodes": "0",
                "status": "no_complete_cases",
                "collinearity_diagnostic": "{}",
            }],
            "sensitivity_scan": [{
                "scenario": "threshold_100",
                "region": "cn",
                "round": "10",
                "metric": "intersection_count",
                "threshold": "100",
                "network_scope": "complete_matrix",
                "missing_policy": "exclude_unknown_no_zero_fill",
                "effect": "0",
                "p": "0.5",
                "q": "0.8",
                "adjustment_method": "holm",
                "n_pairs": "3",
                "status": "estimated",
                "parameter_delta": "{\"threshold\":100}",
            }],
        }

    def config(self) -> dict[str, object]:
        return {
            "analysis_id": "fixture_network_output",
            "analysis_version": "1.0.0",
            "missing_policy": "exclude_unknown_no_zero_fill",
            "statistical_test": {
                "method": "upstream_fixture",
                "random_seed": 17,
                "permutations": 99,
                "tail": "two-sided",
            },
        }

    def test_writes_four_tables_summary_and_manifest(self) -> None:
        manifest = output.write_network_inference_outputs(
            self.tables(),
            root=self.root,
            output_dir=self.destination,
            analysis_config=self.config(),
            input_files=[self.input_path],
        )
        self.assertEqual(manifest["parameters"]["table_counts"], {
            "hypothesis_tests": 1,
            "matrix_correlations": 1,
            "mrqap_coefficients": 1,
            "sensitivity_scan": 1,
        })
        for table in output.TABLES:
            self.assertTrue((self.destination / f"{table}.csv").is_file())
        summary = (self.destination / "analysis_summary.md").read_text(encoding="utf-8")
        for caveat in output.CAVEATS:
            self.assertIn(caveat, summary)
        with (self.destination / "matrix_correlations.csv").open(encoding="utf-8-sig", newline="") as handle:
            row = next(csv.DictReader(handle))
        self.assertEqual(row["effect_size"], "0.0")
        self.assertEqual(row["feature_label_zh"], "raw_count 与 cosine 的矩阵相关")
        self.assertEqual(row["missing_policy"], "common_observed_pairs_only_no_zero_fill")
        verification = verify_model_run_manifest(
            self.destination / "model_run_manifest.json", root=self.root
        )
        self.assertTrue(verification["ok"], verification)

        # Figures are optional and do not participate in the explanation.
        shutil.rmtree(self.destination / "figures")
        verification_after_removal = verify_model_run_manifest(
            self.destination / "model_run_manifest.json", root=self.root
        )
        self.assertTrue(verification_after_removal["ok"], verification_after_removal)
        self.assertTrue(any("analysis_summary.md" in item["path"] for item in verification_after_removal["outputs"]))

    def test_explicit_zero_is_kept_and_duplicate_ids_fail(self) -> None:
        rows = self.tables()
        rows["matrix_correlations"][0]["observed_correlation"] = "0"
        first = rows["hypothesis_tests"][0]
        second = dict(first)
        first["result_id"] = "same"
        second["result_id"] = "same"
        rows["hypothesis_tests"].append(second)
        with self.assertRaises(output.OutputContractError):
            output.write_network_inference_outputs(
                rows,
                root=self.root,
                output_dir=self.destination,
                analysis_config=self.config(),
                input_files=[self.input_path],
            )

    def test_nonfinite_unknown_and_zero_fill_are_rejected(self) -> None:
        rows = self.tables()
        rows["matrix_correlations"][0]["observed_correlation"] = "nan"
        with self.assertRaises(output.OutputContractError):
            output.write_network_inference_outputs(
                rows,
                root=self.root,
                output_dir=self.destination,
                analysis_config=self.config(),
                input_files=[self.input_path],
            )

        rows = self.tables()
        rows["sensitivity_scan"][0]["missing_policy"] = "missing_as_zero"
        with self.assertRaises(output.OutputContractError):
            output.write_network_inference_outputs(
                rows,
                root=self.root,
                output_dir=self.destination,
                analysis_config=self.config(),
                input_files=[self.input_path],
            )

        rows = self.tables()
        rows["hypothesis_tests"][0]["unmapped_column"] = "reject"
        with self.assertRaises(output.OutputContractError):
            output.write_network_inference_outputs(
                rows,
                root=self.root,
                output_dir=self.destination,
                analysis_config=self.config(),
                input_files=[self.input_path],
            )

    def test_not_estimable_rows_can_have_blank_effect_and_p_values(self) -> None:
        rows = self.tables()
        result = output.write_network_inference_outputs(
            rows,
            root=self.root,
            output_dir=self.destination,
            analysis_config=self.config(),
            input_files=[self.input_path],
        )
        self.assertEqual(result["parameters"]["table_counts"]["mrqap_coefficients"], 1)
        with (self.destination / "mrqap_coefficients.csv").open(encoding="utf-8-sig", newline="") as handle:
            row = next(csv.DictReader(handle))
        self.assertEqual(row["status"], "not_estimable")
        self.assertEqual(row["effect_size"], "")
        self.assertEqual(row["p_value"], "")


if __name__ == "__main__":
    unittest.main()
