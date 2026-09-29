from __future__ import annotations

import unittest

from scripts_pipeline import network_sensitivity_scan as scan


class SensitivityScanTests(unittest.TestCase):
    def test_all_observed_scope_does_not_filter_round_labels(self) -> None:
        self.assertEqual(scan._round_filter_from_scope({"round": "all_observed"}), set())
        self.assertEqual(scan._round_filter_from_scope({"round": ["10", "11"]}), {"10", "11"})

    def test_bh_is_monotone_and_keeps_missing_values(self) -> None:
        result = scan.bh_adjust({"a": 0.01, "b": 0.02, "c": 0.2, "d": None})
        self.assertAlmostEqual(result["a"], 0.03)
        self.assertAlmostEqual(result["b"], 0.03)
        self.assertAlmostEqual(result["c"], 0.2)
        self.assertIsNone(result["d"])

    def test_cp_uses_only_published_two_person_combinations(self) -> None:
        rows = [
            {"region": "cn", "round": "11", "data_source": "official_cp",
             "name_a": "a", "name_b": "b", "name_c": "", "cp_vote_count": "5"},
            {"region": "cn", "round": "11", "data_source": "official_cp",
             "name_a": "a", "name_b": "c", "name_c": "d", "cp_vote_count": "9"},
            {"region": "cn", "round": "11", "data_source": "covote_fallback",
             "name_a": "b", "name_b": "c", "name_c": "", "cp_vote_count": "10"},
        ]
        counts = scan._cp_counts(rows)
        self.assertEqual(len(counts), 1)
        self.assertEqual(counts[("cn", "11", "a|b")], 5.0)

    def test_explicit_node_set_requires_both_endpoints(self) -> None:
        record = scan.inference.PairRecord("cn", "11", "a|b",
                                           {"canonical_a": "a", "canonical_b": "b"}, None)
        self.assertTrue(scan._node_eligible(record, {"name": "explicit", "ids": ["a", "b"]}))
        self.assertFalse(scan._node_eligible(record, {"name": "explicit", "ids": ["a"]}))

    def test_thresholds_and_conditions_report_counts_coverage_and_warnings(self) -> None:
        covote = []
        features = []
        pairs = [
            ("a", "b", 0, 1.1, 0.2, 0.1, 1, "true"),
            ("a", "c", 2, 1.5, 0.3, 0.2, 1, "false"),
            ("b", "c", 4, 2.0, 0.4, 0.3, 2, "false"),
            ("a", "d", 6, 2.5, 0.5, 0.4, 4, "true"),
        ]
        for a, b, count, lift, cosine, phi, rank, same in pairs:
            covote.append({
                "region": "cn", "round": "11", "pair_category": "character",
                "canonical_a": a, "canonical_b": b, "intersection_count": str(count),
                "lift": str(lift), "cosine": str(cosine), "phi": str(phi),
                "complete_pair_matrix": "true", "rank_a": str(rank), "rank_b": str(rank),
            })
            features.append({
                "region": "cn", "round": "11", "pair_category": "character",
                "canonical_a": a, "canonical_b": b, "same_first_appearance_work": same,
                "a_reference_first_appearance_work": "1" if a in {"a", "b"} else "2",
                "b_reference_first_appearance_work": "1" if b in {"a", "b"} else "2",
            })
        config = {
            "analysis_name": "test_sensitivity",
            "parameters": {"random_seed": 4, "permutations": 9, "min_group_n": 2},
            "metrics": [
                {"name": metric, "column": metric, "minimum_scope": "complete_matrix"}
                for metric in ("lift", "cosine", "phi")
            ],
            "hypotheses": [{
                "name": "same_work", "observation": "same_first_appearance_work == 1",
                "control": "same_first_appearance_work == 0",
            }],
            "scans": [
                {"threshold_type": "intersection_count", "thresholds": [0, 2]},
                {"threshold_type": "lift", "thresholds": [1.5]},
                {"threshold_type": "cp_vote_count", "thresholds": [0]},
            ],
            "node_sets": [{"name": "all_observed"}, {"name": "top_ranked", "rank_max": 2}],
            "data_completeness": ["complete_matrix", "observed_only"],
            "adjustments": ["holm", "bh"],
        }
        cp = [{"region": "cn", "round": "11", "data_source": "official_cp",
               "name_a": "a", "name_b": "b", "cp_vote_count": "5", "name_c": ""}]
        rows, summary = scan.scan_analysis(config, covote_rows=covote,
                                           feature_rows=features, cp_rows=cp)
        base = next(row for row in rows if row["threshold_type"] == "intersection_count"
                    and row["threshold"] == 0 and row["node_set"] == "all_observed"
                    and row["metric"] == "lift" and row["adjustment_method"] == "holm"
                    and row["data_completeness"] == "complete_matrix")
        self.assertEqual((base["observation_n"], base["control_n"]), (2, 2))
        self.assertEqual((base["eligible_pair_n"], base["effective_pair_n"]), (4, 4))
        self.assertEqual(base["pair_coverage"], 1.0)
        self.assertTrue(base["adjustment_family"].startswith("sensitivity:"))
        same_data = next(row for row in rows if row["threshold_type"] == "intersection_count"
                         and row["threshold"] == 0 and row["node_set"] == "all_observed"
                         and row["metric"] == "lift" and row["adjustment_method"] == "holm"
                         and row["data_completeness"] == "observed_only")
        self.assertEqual(base["raw_p"], same_data["raw_p"])
        filtered = next(row for row in rows if row["threshold_type"] == "intersection_count"
                        and row["threshold"] == 2 and row["node_set"] == "all_observed"
                        and row["metric"] == "lift" and row["adjustment_method"] == "holm"
                        and row["data_completeness"] == "complete_matrix")
        self.assertEqual(filtered["effective_pair_n"], 3)
        self.assertEqual(filtered["pair_coverage"], 0.75)
        self.assertIn("low_power_heuristic", filtered["warning"])
        cp_row = next(row for row in rows if row["threshold_type"] == "cp_vote_count"
                      and row["node_set"] == "all_observed" and row["metric"] == "lift"
                      and row["adjustment_method"] == "holm"
                      and row["data_completeness"] == "complete_matrix")
        self.assertEqual(cp_row["effective_pair_n"], 1)
        self.assertIn("unlisted_unknown", cp_row["warning"])
        self.assertTrue(summary)
        self.assertTrue(all(row["interpretation"] == "sensitivity_only_not_independent_validation"
                            for row in summary))

    def test_stability_separates_direction_from_significance(self) -> None:
        common = {"region": "cn", "round": "11", "metric": "lift",
                  "threshold_type": "intersection_count", "hypothesis": "same_work",
                  "node_set": "all_observed", "data_completeness": "complete_matrix",
                  "adjustment_method": "holm"}
        rows = [{**common, "effect_size": 0.2, "adjusted_p": 0.01},
                {**common, "effect_size": 0.3, "adjusted_p": 0.2}]
        result = scan.summarize(rows)
        self.assertEqual(result[0]["direction_stability"], "stable_positive")
        self.assertEqual(result[0]["significance_stability"], "mixed")

    def test_partial_pairs_keep_count_but_suppress_complete_matrix_lift(self) -> None:
        covote = [{
            "region": "jp", "round": "22", "pair_category": "character",
            "canonical_a": "a", "canonical_b": "b", "intersection_count": "3",
            "lift": "1.8", "complete_pair_matrix": "false",
        }]
        features = [{
            "region": "jp", "round": "22", "pair_category": "character",
            "canonical_a": "a", "canonical_b": "b", "same_first_appearance_work": "true",
        }]
        config = {
            "metrics": [{"name": name, "column": name} for name in ("intersection_count", "lift")],
            "hypotheses": [{"name": "same_work", "observation": "same_first_appearance_work == 1",
                            "control": "same_first_appearance_work == 0"}],
            "scans": [{"threshold_type": "intersection_count", "thresholds": [0]}],
            "data_completeness": ["partial_observed_pairs"],
            "parameters": {"permutations": 0},
        }
        rows, _ = scan.scan_analysis(config, covote_rows=covote, feature_rows=features)
        by_metric = {row["metric"]: row for row in rows}
        self.assertEqual(by_metric["intersection_count"]["observation_n"], 1)
        self.assertEqual(by_metric["lift"]["effective_pair_n"], 0)
        self.assertEqual(by_metric["lift"]["status"], "metric_requires_complete_matrix")


if __name__ == "__main__":
    unittest.main()
