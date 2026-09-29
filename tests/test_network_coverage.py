from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from scripts_pipeline import network_coverage


class NetworkCoverageTests(unittest.TestCase):
    def _write_csv(self, path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_fixed_scope_has_every_analysis_round_and_explicit_missing_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            covote = root / "vote_explorer" / "data" / "analysis_covote_pairs_all.csv"
            self._write_csv(covote, ["region", "round", "round_label", "pair_category", "complete_pair_matrix"], [
                {"region": "cn", "round": "10", "round_label": "CN10", "pair_category": "character", "complete_pair_matrix": "True"},
                {"region": "jp", "round": "11", "round_label": "JP11", "pair_category": "character", "complete_pair_matrix": "False"},
            ])
            (root / "metadata").mkdir(parents=True)
            (root / "metadata" / "jp_official_legacy_component_status.json").write_text(
                '{"rounds":{"10":{"entity_numeric_profiles":"official_not_offered","fetch_failures":[]}}}',
                encoding="utf-8",
            )
            (root / "metadata" / "jp_official_legacy_coverage.json").write_text(
                '{"rounds":{"10":{"pages_ok":36,"pages_recorded":36,"pages_error":0}}}',
                encoding="utf-8",
            )
            network = root / "analysis_results" / "network_inference"
            for filename, fields, rows in (
                ("hypothesis_tests.csv", ["region", "round"], [{"region": "cn", "round": "10"}, {"region": "jp", "round": "11"}]),
                ("mrqap_coefficients.csv", ["region", "round", "status"], [{"region": "cn", "round": "10", "status": "no_complete_cases"}]),
                ("sensitivity_scan.csv", ["region", "round", "effective_pair_n"], [{"region": "cn", "round": "10", "effective_pair_n": "1"}]),
                ("matrix_correlations.csv", ["region", "round"], [
                    {"region": "cn", "round": "CN10"},
                    {"region": "cn", "round": "CN11_vs_CN10"},
                    {"region": "jp", "round": "JP11"},
                ]),
            ):
                self._write_csv(network / filename, fields, rows)
            community = root / "analysis_results" / "network_communities" / "by_round" / "CN1"
            community.mkdir(parents=True)
            (community / "community_run_manifest.json").write_text("{}", encoding="utf-8")
            self._write_csv(community / "community_assignments.csv", ["canonical_name"], [{"canonical_name": "node"}])

            rows = network_coverage.build_coverage(root=root, covote_path=covote)

        self.assertEqual(len(rows), 31 * len(network_coverage.ANALYSES))
        by_key = {(row["analysis"], row["round"]): row for row in rows}
        self.assertEqual(by_key[("hypothesis_tests", "CN10")]["status"], "computed_observed_pairs")
        self.assertEqual(by_key[("hypothesis_tests", "CN1")]["status"], "unavailable_no_official_pair_data")
        self.assertEqual(by_key[("mrqap", "CN10")]["status"], "unavailable_no_complete_cases")
        self.assertEqual(by_key[("mrqap", "JP11")]["status"], "unavailable_incomplete_official_matrix")
        self.assertIn("36/36 pages ok", by_key[("mrqap", "JP10")]["reason"])
        self.assertEqual(by_key[("communities", "CN1")]["status"], "computed_isolates_only")
        self.assertEqual(by_key[("matrix_adjacent_round", "CN11")]["result_rows"], 1)
        self.assertEqual(by_key[("matrix_adjacent_round", "JP3")]["status"], "not_applicable_first_in_scope_round")
        self.assertEqual(by_key[("matrix_adjacent_round", "JP11")]["status"], "unavailable_adjacent_matrix_pair")


if __name__ == "__main__":
    unittest.main()
