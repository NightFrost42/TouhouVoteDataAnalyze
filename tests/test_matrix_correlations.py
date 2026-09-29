from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from scripts_pipeline.analyze_matrix_correlations import (
    INTERPRETATION_NOTE,
    MISSING_PAIR_RULE,
    MatrixData,
    build_matrix_from_rows,
    build_comparisons,
    correlate_matrices,
    extract_upper_triangle,
    load_cp_matrices,
    pearson_correlation,
    spearman_correlation,
    write_results,
)


class MatrixCorrelationTests(unittest.TestCase):
    def _matrix(
        self,
        name: str,
        metric: str,
        values: dict[tuple[str, str], float],
        *,
        nodes: set[str] | None = None,
        complete: bool = True,
    ) -> MatrixData:
        node_set = nodes or {node for pair in values for node in pair}
        return MatrixData(
            matrix_name=name,
            metric=metric,
            region="test",
            round="T1",
            node_type="character",
            values=values,
            nodes=frozenset(node_set),
            complete_pair_matrix=complete,
        )

    def test_upper_triangle_ignores_diagonal_and_preserves_zero(self) -> None:
        matrix = {
            "C": {"C": 999, "A": 2, "B": 0},
            "A": {"A": 999, "B": 1, "C": 2},
            "B": {"A": 1, "B": 999, "C": 0},
        }
        self.assertEqual(
            extract_upper_triangle(matrix),
            {("a", "b"): 1, ("a", "c"): 2, ("b", "c"): 0},
        )

    def test_label_alignment_is_invariant_to_node_order(self) -> None:
        first = self._matrix(
            "a", "x", {("a", "b"): 1, ("a", "c"): 2, ("b", "c"): 4}
        )
        second = self._matrix(
            "b", "y", {("b", "c"): 40, ("a", "c"): 20, ("a", "b"): 10}
        )
        shuffled = self._matrix(
            "b", "y", {("c", "a"): 20, ("b", "a"): 10, ("c", "b"): 40}
        )
        result_a = correlate_matrices(first, second, permutations=40, random_seed=17)
        result_b = correlate_matrices(first, shuffled, permutations=40, random_seed=17)
        self.assertEqual(result_a["pair_count"], 3)
        self.assertEqual(result_a["node_count"], 3)
        self.assertEqual(result_a["observed_correlation"], 1.0)
        self.assertEqual(result_a["permutation_p"], result_b["permutation_p"])

    def test_identical_matrix_has_correlation_one_and_reproducible_permutation(self) -> None:
        values = {("a", "b"): 3, ("a", "c"): 9, ("b", "c"): 1, ("a", "d"): 0, ("b", "d"): 4, ("c", "d"): 7}
        first = self._matrix("a", "x", values)
        second = self._matrix("b", "y", values)
        result_a = correlate_matrices(first, second, method="spearman", permutations=80, random_seed=123)
        result_b = correlate_matrices(first, second, method="spearman", permutations=80, random_seed=123)
        self.assertEqual(result_a["observed_correlation"], 1.0)
        self.assertEqual(result_a["permutation_p"], result_b["permutation_p"])
        self.assertEqual(result_a["valid_permutations"], 80)

    def test_missing_pairs_are_excluded_not_zero_filled(self) -> None:
        first = self._matrix(
            "a", "x", {("a", "b"): 0, ("a", "c"): 2, ("b", "c"): 4}, complete=False
        )
        second = self._matrix(
            "b", "y", {("a", "b"): 0, ("a", "c"): 3}, nodes={"a", "b", "c"}, complete=False
        )
        result = correlate_matrices(first, second, permutations=20, random_seed=1)
        self.assertEqual(result["pair_count"], 2)
        self.assertFalse(result["complete_pair_matrix"])
        self.assertEqual(result["missing_pair_rule"], MISSING_PAIR_RULE)
        self.assertNotEqual(result["warning"], "")

    def test_spearman_ties_and_constant_input(self) -> None:
        self.assertAlmostEqual(spearman_correlation([1, 1, 3, 4], [2, 4, 6, 8]), 0.9486832980505138)
        self.assertAlmostEqual(pearson_correlation([1, 2, 3], [2, 4, 6]), 1.0)
        self.assertIsNone(pearson_correlation([1, 1, 1], [1, 2, 3]))
        self.assertIsNone(spearman_correlation([1, 2], [2, 3]))

    def test_long_table_skips_self_pairs_and_preserves_zero(self) -> None:
        matrix = build_matrix_from_rows(
            [
                {"a": "A", "b": "A", "value": "99", "complete": "True"},
                {"a": "A", "b": "B", "value": "0", "complete": "True"},
                {"a": "B", "b": "A", "value": "0", "complete": "True"},
            ],
            matrix_name="m",
            metric="value",
            region="test",
            round_label="T1",
            node_type="character",
            endpoint_a="a",
            endpoint_b="b",
            value_fields="value",
            completeness_field="complete",
        )
        self.assertEqual(matrix.values, {("a", "b"): 0.0})
        self.assertEqual(matrix.duplicate_count, 1)
        self.assertEqual(matrix.nodes, frozenset({"a", "b"}))

    def test_result_marks_noncausal_interpretation(self) -> None:
        first = self._matrix("a", "x", {("a", "b"): 1, ("a", "c"): 2, ("b", "c"): 3})
        second = self._matrix("b", "y", {("a", "b"): 3, ("a", "c"): 2, ("b", "c"): 1})
        result = correlate_matrices(first, second, permutations=0)
        self.assertEqual(result["interpretation_note"], INTERPRETATION_NOTE)
        self.assertEqual(result["correlation_method"], "spearman")
        self.assertIsNone(result["permutation_p"])

    def test_complete_flag_requires_all_common_pairs(self) -> None:
        first = self._matrix(
            "a", "x", {("a", "b"): 1, ("a", "c"): 2, ("b", "c"): 3}, complete=True
        )
        second = self._matrix(
            "b", "y", {("a", "b"): 1, ("a", "c"): 2}, nodes={"a", "b", "c"}, complete=True
        )
        result = correlate_matrices(first, second, permutations=4, random_seed=9)
        self.assertEqual(result["pair_count"], 2)
        self.assertFalse(result["complete_pair_matrix"])
        self.assertEqual(result["source_complete_a"], True)
        self.assertEqual(result["source_complete_b"], True)

    def test_conflicting_duplicate_pair_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            build_matrix_from_rows(
                [
                    {"a": "A", "b": "B", "value": "1", "complete": "True"},
                    {"a": "B", "b": "A", "value": "2", "complete": "True"},
                ],
                matrix_name="m",
                metric="value",
                region="test",
                round_label="T1",
                node_type="character",
                endpoint_a="a",
                endpoint_b="b",
                value_fields="value",
                completeness_field="complete",
            )

    def test_cp_loader_excludes_fallback_and_three_member_combinations(self) -> None:
        fields = [
            "region", "round", "round_label", "name_a", "name_b", "name_c",
            "data_source", "comparison_count", "cp_vote_count",
        ]
        rows = [
            {"region": "cn", "round": "10", "round_label": "CN10", "name_a": "A", "name_b": "B", "name_c": "", "data_source": "official_cp", "comparison_count": "9"},
            {"region": "cn", "round": "10", "round_label": "CN10", "name_a": "B", "name_b": "C", "name_c": "", "data_source": "co-vote_fallback", "comparison_count": "8"},
            {"region": "cn", "round": "10", "round_label": "CN10", "name_a": "A", "name_b": "C", "name_c": "D", "data_source": "official_cp", "comparison_count": "7"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cp.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            matrices = load_cp_matrices(path)
        self.assertEqual(len(matrices), 1)
        self.assertEqual(matrices[0].values, {("a", "b"): 9.0})
        self.assertFalse(matrices[0].complete_pair_matrix)

    def test_rejects_incompatible_node_types(self) -> None:
        character = self._matrix("character", "raw_count", {("a", "b"): 1})
        music = MatrixData("music", "raw_count", "test", "T1", "music", {("a", "b"): 2}, frozenset({"a", "b"}))
        with self.assertRaisesRegex(ValueError, "same region and node type"):
            correlate_matrices(character, music)

    def test_written_schema_includes_pair_count_and_interpretation(self) -> None:
        first = self._matrix("a", "x", {("a", "b"): 1, ("a", "c"): 2, ("b", "c"): 3})
        second = self._matrix("b", "y", {("a", "b"): 3, ("a", "c"): 2, ("b", "c"): 1})
        row = correlate_matrices(first, second, permutations=0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "correlations.csv"
            write_results(path, [row])
            with path.open(encoding="utf-8-sig", newline="") as stream:
                actual = list(csv.DictReader(stream))
        self.assertEqual(len(actual), 1)
        self.assertEqual(actual[0]["pair_count"], "3")
        self.assertEqual(actual[0]["correlation_method"], "spearman")
        self.assertEqual(actual[0]["interpretation_note"], INTERPRETATION_NOTE)

    def test_cross_round_comparison_uses_common_node_pairs(self) -> None:
        current = MatrixData(
            "covote_character", "raw_count", "jp", "JP1", "character",
            {("a", "b"): 1, ("a", "c"): 2, ("b", "c"): 3}, frozenset({"a", "b", "c"}), True,
        )
        previous = MatrixData(
            "covote_character", "raw_count", "jp", "JP0", "character",
            {("b", "a"): 4, ("c", "a"): 5, ("c", "b"): 6},
            frozenset({"a", "b", "c"}), True,
        )
        rows = build_comparisons(
            [current, previous], permutations=0, round_pairs=[("JP1", "JP0")]
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["correlation_method"] for row in rows}, {"pearson", "spearman"})
        self.assertTrue(all(row["round"] == "JP1_vs_JP0" and row["pair_count"] == 3 for row in rows))


if __name__ == "__main__":
    unittest.main()
