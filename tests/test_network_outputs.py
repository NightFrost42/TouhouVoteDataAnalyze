from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts_pipeline import network_inference_output as output
from vote_explorer.analysis_engine import TEMPLATES


class NetworkOutputContractTests(unittest.TestCase):
    def _config(self) -> dict[str, object]:
        return {
            "analysis_id": "network_output_fixture",
            "analysis_version": "1.0.0",
            "missing_policy": "exclude_unknown_no_zero_fill",
            "statistical_test": {"method": "fixture", "random_seed": 23, "permutations": 9, "tail": "two-sided"},
        }

    def _tables(self) -> dict[str, list[dict[str, object]]]:
        return {
            "hypothesis_tests": [{
                "region": "cn", "round": "11", "metric": "intersection_count", "hypothesis": "same_stage",
                "observation_n": "1", "control_n": "1", "cliffs_delta": "0", "raw_p": "0", "adjusted_p": "0",
                "adjustment_method": "holm", "adjustment_family": "cn11:intersection_count", "permutations": "9",
                "valid_permutations": "9", "random_seed": "23", "inference_status": "exploratory",
                "data_status": "complete_matrix", "metric_scope": "complete_matrix",
            }],
            "matrix_correlations": [], "mrqap_coefficients": [], "sensitivity_scan": [],
        }

    def test_csvs_have_complete_common_fields_and_preserve_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "metadata").mkdir()
            (root / "metadata" / "network_inference_output.schema.json").write_text("{}", encoding="utf-8")
            source = root / "source.csv"
            source.write_text("value\n0\n", encoding="utf-8")
            destination = root / "analysis_results" / "network_inference"
            manifest = output.write_network_inference_outputs(
                self._tables(), root=root, output_dir=destination,
                analysis_config=self._config(), input_files=[source],
            )
            for table in output.TABLES:
                with (destination / f"{table}.csv").open(encoding="utf-8-sig", newline="") as handle:
                    fields = next(csv.reader(handle))
                self.assertTrue(set(output.COMMON_COLUMNS).issubset(fields), table)
            with (destination / "hypothesis_tests.csv").open(encoding="utf-8-sig", newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["effect_size"], "0.0")
            self.assertEqual(row["p_value"], "0.0")
            self.assertEqual(manifest["parameters"]["table_counts"], {name: (1 if name == "hypothesis_tests" else 0) for name in output.TABLES})
            payload = json.loads((destination / "model_run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["data_integrity"]["status"], "passed_with_warnings")
            self.assertTrue((destination / "README.md").is_file())
            self.assertTrue((destination / "analysis_summary.md").is_file())

    def test_existing_output_is_preserved_and_zero_fill_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "metadata").mkdir()
            (root / "metadata" / "network_inference_output.schema.json").write_text("{}", encoding="utf-8")
            source = root / "source.csv"
            source.write_text("value\n0\n", encoding="utf-8")
            destination = root / "out"
            destination.mkdir()
            (destination / "keep.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(output.OutputContractError):
                output.write_network_inference_outputs(self._tables(), root=root, output_dir=destination, analysis_config=self._config(), input_files=[source])
            rows = self._tables()
            rows["hypothesis_tests"][0]["missing_policy"] = "missing_as_zero"
            with self.assertRaises(output.OutputContractError):
                output.write_network_inference_outputs(rows, root=root, output_dir=root / "fresh", analysis_config=self._config(), input_files=[source])

    def test_templates_keep_legacy_and_network_entries_discoverable(self) -> None:
        payload = json.loads((Path(__file__).resolve().parents[1] / "vote_explorer_web" / "web_data" / "templates.json").read_text(encoding="utf-8"))
        keys = {spec["key"] for spec in payload["template_specs"]}
        desktop_keys = {spec.key for spec in TEMPLATES}
        self.assertIn("c00_rank_trend", keys)
        self.assertIn("a17_concentration_clusters", keys)
        self.assertIn("a18_music_concentration_clusters", keys)
        self.assertTrue({"c00_rank_trend", "a17_concentration_clusters", "a18_music_concentration_clusters"}.issubset(desktop_keys))
        self.assertTrue(set(payload["round_labels"]).issuperset({"CN1", "CN11", "JP3", "JP22"}))


if __name__ == "__main__":
    unittest.main()
