from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "scripts_pipeline"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import crawl_cn_modern as core  # noqa: E402
import crawl_cn_modern_advanced as advanced  # noqa: E402


class AdvancedManifestCoverageTests(unittest.TestCase):
    def test_bridge_definition_sources_are_manifest_candidates(self) -> None:
        config = core.ROUNDS[11]
        expected = {
            config.root / relative_path
            for relative_path in advanced.ADVANCED_MANIFEST_DEFINITION_RELATIVE_PATHS
        }

        self.assertTrue(all(path.is_file() for path in expected))
        self.assertEqual(
            set(advanced.existing_advanced_definition_sources(config.root)),
            expected,
        )
        self.assertLessEqual(
            expected, set(advanced.advanced_manifest_candidate_paths(config))
        )

    def test_missing_definition_sources_are_not_returned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "graphql" / "base.json"
            existing.parent.mkdir(parents=True)
            existing.write_text("{}", encoding="utf-8")

            self.assertEqual(
                advanced.existing_advanced_definition_sources(root), [existing]
            )


class PartitionBridgeResidualTests(unittest.TestCase):
    question_id = 11091
    answer_ids = [11109101, *range(1109102, 1109112)]

    def setUp(self) -> None:
        self.parent = {
            "filters": [],
            "query": None,
            "numVote": 14,
            "numMusic": 4,
            "targetA": {"name": "A", "voteCount": 2, "rank": 1},
            "targetB": {"name": "B", "voteCount": 1, "rank": 2},
        }
        voter_counts = [3, *([1] * 10)]
        music_counts = [2, 1, 1, *([0] * 8)]
        target_a_counts = [1, 1, *([0] * 9)]
        target_b_counts = [0, 0, 1, *([0] * 8)]
        self.children = [
            self.child(
                answer_id,
                num_vote=voter_counts[index],
                num_music=music_counts[index],
                count_a=target_a_counts[index],
                count_b=target_b_counts[index],
            )
            for index, answer_id in enumerate(self.answer_ids)
        ]

    def child(
        self,
        answer_id: int,
        *,
        num_vote: int,
        num_music: int,
        count_a: int,
        count_b: int,
    ) -> dict[str, object]:
        filters = [(self.question_id, answer_id)]
        return {
            "filters": [
                {"questionId": question_id, "answerId": selected_answer_id}
                for question_id, selected_answer_id in filters
            ],
            "query": advanced.music_partition_query(filters),
            "numVote": num_vote,
            "numMusic": num_music,
            "targetA": {"name": "A", "voteCount": count_a, "rank": None},
            "targetB": {"name": "B", "voteCount": count_b, "rank": None},
        }

    def derive(
        self,
        *,
        parent: dict[str, object] | None = None,
        children: list[dict[str, object]] | None = None,
        maximum: int = 1,
    ) -> tuple[dict[str, object], dict[str, object]]:
        return advanced.derive_unanswered_residual_partition(
            parent or self.parent,
            children or self.children,
            question_id=self.question_id,
            explicit_answer_ids=self.answer_ids,
            max_global_unanswered_voters=maximum,
        )

    def test_global_q11091_residual_is_one_voter_and_zero_music_marginals(self) -> None:
        residual, proof = self.derive()

        self.assertEqual(
            (
                residual["numVote"],
                residual["numMusic"],
                residual["targetA"]["voteCount"],
                residual["targetB"]["voteCount"],
            ),
            (1, 0, 0, 0),
        )
        self.assertTrue(proof["nonnegativeResidualPassed"])
        self.assertTrue(
            proof["combinedExactConservationProof"]["passed"]
        )
        resolution = advanced.uniquely_resolve_residual_intersection(residual)
        self.assertEqual(resolution["cells"], {"m00": 0, "m01": 0, "m10": 0, "m11": 0})

    def test_negative_parent_minus_children_residual_is_rejected(self) -> None:
        children = copy.deepcopy(self.children)
        children[0]["numVote"] += 2

        with self.assertRaisesRegex(ValueError, "children exceed their parent"):
            self.derive(children=children)

    def test_conditional_residual_above_global_one_voter_limit_is_rejected(self) -> None:
        parent = copy.deepcopy(self.parent)
        parent["numVote"] = 15

        with self.assertRaisesRegex(ValueError, "global maximum"):
            self.derive(parent=parent)

    def test_nonunique_frechet_intersection_fails_closed(self) -> None:
        ambiguous = {
            "numMusic": 2,
            "targetA": {"voteCount": 1},
            "targetB": {"voteCount": 1},
        }

        with self.assertRaisesRegex(RuntimeError, "do not uniquely determine"):
            advanced.uniquely_resolve_residual_intersection(ambiguous)


class FrechetAndConditionalAxisTests(unittest.TestCase):
    @staticmethod
    def partition(num_music: int, count_a: int, count_b: int) -> dict[str, object]:
        return {
            "numMusic": num_music,
            "targetA": {"voteCount": count_a},
            "targetB": {"voteCount": count_b},
        }

    def test_unit_universe_equal_marginals_resolve_without_covote(self) -> None:
        result = advanced.try_uniquely_resolve_partition_intersection(
            self.partition(1, 1, 1)
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(
            result["cells"], {"m00": 1, "m01": 0, "m10": 0, "m11": 0}
        )
        self.assertEqual(result["proof"]["uniqueIntersection"], 1)

    def test_two_voter_equal_marginals_remain_ambiguous(self) -> None:
        partition = self.partition(2, 1, 1)

        self.assertIsNone(
            advanced.try_uniquely_resolve_partition_intersection(partition)
        )
        self.assertEqual(
            advanced.partition_frechet_bounds(partition)[
                "intersectionUpperBound"
            ],
            1,
        )

    def test_conditional_axes_and_global_residual_constants_are_exact(self) -> None:
        residuals = {
            question_id: (name, maximum)
            for name, question_id, maximum in advanced.MUSIC_COVOTE_RESIDUAL_AXES
        }

        self.assertEqual(
            residuals[11071],
            ("employment_status_conditioned_on_not_student", 12419),
        )
        self.assertEqual(
            residuals[11031],
            ("domestic_region_conditioned_on_domestic", 322),
        )
        self.assertEqual(
            advanced.MUSIC_COVOTE_CONDITIONAL_AXIS_REQUIREMENTS,
            {11071: (11061, 1106102), 11031: (11021, 1102101)},
        )
        self.assertEqual(
            advanced.MUSIC_COVOTE_GLOBAL_INTERSECTION_OPTIONAL,
            frozenset({11071, 11031}),
        )

    def test_conditional_axes_apply_only_inside_their_parent_answers(self) -> None:
        not_student = {
            "filters": [{"questionId": 11061, "answerId": 1106102}]
        }
        student = {"filters": [{"questionId": 11061, "answerId": 1106101}]}
        domestic = {"filters": [{"questionId": 11021, "answerId": 1102101}]}
        outside_china = {
            "filters": [{"questionId": 11021, "answerId": 1102102}]
        }

        self.assertTrue(
            advanced.conditional_residual_axis_applicable(not_student, 11071)
        )
        self.assertFalse(
            advanced.conditional_residual_axis_applicable(student, 11071)
        )
        self.assertTrue(
            advanced.conditional_residual_axis_applicable(domestic, 11031)
        )
        self.assertFalse(
            advanced.conditional_residual_axis_applicable(outside_china, 11031)
        )
        self.assertTrue(
            advanced.conditional_residual_axis_applicable({"filters": []}, 11091)
        )

    def test_optional_global_branch_residual_can_be_nonunique(self) -> None:
        ambiguous = self.partition(2, 1, 1)

        for question_id in (11071, 11031):
            with self.subTest(question_id=question_id):
                evidence = advanced.evaluate_global_residual_intersection(
                    ambiguous, question_id=question_id
                )
                self.assertFalse(evidence["globalIntersectionRequired"])
                self.assertEqual(
                    evidence["globalIntersectionStatus"], "not_required"
                )
                self.assertFalse(
                    evidence["observedFrechetBounds"]["boundsAreEqual"]
                )

        with self.assertRaisesRegex(RuntimeError, "do not uniquely determine"):
            advanced.evaluate_global_residual_intersection(
                ambiguous, question_id=11091
            )


class MusicWitnessFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        names = ["Tiny Shangri-La", "A", "B", "Another"]
        counts = [1, 1, 1, 1]
        self.parent: dict[str, object] = {
            "filters": [{"questionId": 1, "answerId": 1}],
            "query": "q1=1",
            "numVote": 2,
            "numMusic": 2,
            "rankingEntryCount": len(names),
            "rankingNamesByRank": names,
            "rankingNamesByRankSha256": advanced.canonical_json_sha256(names),
            "rankingVoteCountsByRank": counts,
            "rankingVoteCountsByRankSha256": advanced.canonical_json_sha256(
                counts
            ),
            "targetA": {"name": "A", "voteCount": 1, "rank": 2},
            "targetB": {"name": "B", "voteCount": 1, "rank": 3},
        }
        self.selection = advanced.select_unit_music_witness(
            self.parent, target_a="A", target_b="B"
        )
        child_names = ["Tiny Shangri-La", "A"]
        child_counts = [1, 1]
        self.child: dict[str, object] = {
            "filters": copy.deepcopy(self.parent["filters"]),
            "query": advanced.music_witness_query(
                str(self.parent["query"]), str(self.selection["name"])
            ),
            "numVote": 1,
            "numMusic": 1,
            "rankingEntryCount": len(child_names),
            "rankingNamesByRank": child_names,
            "rankingNamesByRankSha256": advanced.canonical_json_sha256(
                child_names
            ),
            "rankingVoteCountsByRank": child_counts,
            "rankingVoteCountsByRankSha256": advanced.canonical_json_sha256(
                child_counts
            ),
            "targetA": {"name": "A", "voteCount": 1, "rank": 2},
            "targetB": {"name": "B", "voteCount": 0, "rank": None},
            "witnessFilter": {
                "type": "music_any",
                "name": self.selection["name"],
            },
        }

    @staticmethod
    def replace_ranking(
        partition: dict[str, object], names: list[str], counts: list[int]
    ) -> None:
        partition["rankingEntryCount"] = len(names)
        partition["rankingNamesByRank"] = names
        partition["rankingNamesByRankSha256"] = advanced.canonical_json_sha256(
            names
        )
        partition["rankingVoteCountsByRank"] = counts
        partition["rankingVoteCountsByRankSha256"] = (
            advanced.canonical_json_sha256(counts)
        )

    def test_selection_and_exact_unit_split_aggregate_parent(self) -> None:
        self.assertEqual(
            (self.selection["name"], self.selection["rank"]),
            ("Tiny Shangri-La", 1),
        )

        split = advanced.derive_music_witness_split(
            self.parent, self.child, self.selection
        )

        self.assertEqual(
            (split["complement"]["numVote"], split["complement"]["numMusic"]),
            (1, 1),
        )
        self.assertEqual(
            split["cells"], {"m00": 0, "m01": 1, "m10": 1, "m11": 0}
        )
        self.assertTrue(split["conservationProof"]["passed"])
        self.assertTrue(
            split["childResolution"]["proof"]["boundsAreEqual"]
        )
        self.assertTrue(
            split["complementResolution"]["proof"]["boundsAreEqual"]
        )

    def test_selection_rejects_no_candidate_and_trailing_control_only(self) -> None:
        no_candidate = copy.deepcopy(self.parent)
        self.replace_ranking(no_candidate, ["A", "B"], [1, 1])
        with self.assertRaisesRegex(RuntimeError, "no non-target one-vote"):
            advanced.select_unit_music_witness(
                no_candidate, target_a="A", target_b="B"
            )

        for label, suffix in (
            ("tab", "\t"),
            ("vertical_tab", "\x0b"),
            ("nul", "\x00"),
            ("c1_next_line", "\x85"),
        ):
            with self.subTest(control=label):
                trailing_only = copy.deepcopy(self.parent)
                self.replace_ranking(
                    trailing_only, [f"Bad{suffix}", "A", "B"], [1, 1, 1]
                )
                with self.assertRaisesRegex(RuntimeError, "no non-target one-vote"):
                    advanced.select_unit_music_witness(
                        trailing_only, target_a="A", target_b="B"
                    )

    def test_selection_rejects_parent_not_two_music_voters(self) -> None:
        parent = copy.deepcopy(self.parent)
        parent["numMusic"] = 3

        with self.assertRaisesRegex(ValueError, "numMusic exactly 2"):
            advanced.select_unit_music_witness(parent, target_a="A", target_b="B")

    def test_child_rejects_nonunit_cohort(self) -> None:
        child = copy.deepcopy(self.child)
        child["numVote"] = 2

        with self.assertRaisesRegex(ValueError, "not an exact one-voter"):
            advanced.validate_music_witness_child(
                self.parent, child, self.selection
            )

    def test_child_rejects_missing_witness(self) -> None:
        child = copy.deepcopy(self.child)
        self.replace_ranking(child, ["A"], [1])

        with self.assertRaisesRegex(ValueError, "does not contain the witness"):
            advanced.validate_music_witness_child(
                self.parent, child, self.selection
            )

    def test_child_rejects_field_above_parent(self) -> None:
        child = copy.deepcopy(self.child)
        child["targetA"] = {"name": "A", "voteCount": 2, "rank": 2}

        with self.assertRaisesRegex(ValueError, "field exceeds its parent"):
            advanced.validate_music_witness_child(
                self.parent, child, self.selection
            )

    def test_child_rejects_ranking_count_above_parent(self) -> None:
        child = copy.deepcopy(self.child)
        self.replace_ranking(child, ["Tiny Shangri-La", "A"], [1, 2])

        with self.assertRaisesRegex(ValueError, "not a subset of its parent"):
            advanced.validate_music_witness_child(
                self.parent, child, self.selection
            )


class ExplodingClient:
    def __getattribute__(self, name: str) -> object:
        raise AssertionError(f"unsafe topK touched client attribute {name}")


class PartitionBridgeResponseValidationTests(unittest.TestCase):
    config = core.ROUNDS[11]
    query = "q1=1"

    @staticmethod
    def partition() -> dict[str, object]:
        names = ["A", "B", "C"]
        return {
            "filters": [{"questionId": 1, "answerId": 1}],
            "query": PartitionBridgeResponseValidationTests.query,
            "numVote": 5,
            "numMusic": 5,
            "rankingEntryCount": len(names),
            "rankingNamesByRank": names,
            "rankingNamesByRankSha256": advanced.canonical_json_sha256(names),
            "targetA": {"name": "A", "voteCount": 3, "rank": 1},
            "targetB": {"name": "B", "voteCount": 2, "rank": 2},
        }

    def covote_wrapper(self, items: list[dict[str, object]]) -> dict[str, object]:
        return {
            "provenance": {
                "source": core.ENDPOINT,
                "operation": "MusicCovoteQuestionnairePartition",
                "variables": core.base_variables(
                    self.config, query=self.query, topK=3
                ),
                "status": 200,
                "contentType": "application/json",
                "documentSha256": core.sha256_bytes(
                    advanced.MUSIC_COVOTE_QUESTIONNAIRE_PARTITION_QUERY.encode(
                        "utf-8"
                    )
                ),
            },
            "data": {
                "queryGlobalStats": {
                    "voteYear": 11,
                    "numVote": 5,
                    "numMusic": 5,
                },
                "queryMusicsCovote": {"items": items},
            },
        }

    def stats_wrapper(
        self, ranks: list[int], *, query: str | None = None
    ) -> dict[str, object]:
        entries = [
            {"rank": rank, "displayRank": str(rank), "name": name, "voteCount": count}
            for rank, name, count in zip(ranks, ["A", "B"], [3, 2])
        ]
        return {
            "provenance": {
                "source": core.ENDPOINT,
                "method": "POST",
                "operation": "MusicCovotePartitionStats",
                "variables": core.base_variables(
                    self.config, query=self.query if query is None else query
                ),
                "status": 200,
                "contentType": "application/json",
                "documentSha256": core.sha256_bytes(
                    advanced.MUSIC_COVOTE_PARTITION_STATS_QUERY.encode("utf-8")
                ),
            },
            "data": {
                "queryGlobalStats": {
                    "voteYear": 11,
                    "numVote": 5,
                    "numMusic": 5,
                },
                "queryMusicRanking": {
                    "global": {"totalUniqueItems": 2, "totalVotes": 5},
                    "entries": entries,
                },
            },
        }

    def test_topk_above_350_is_rejected_without_touching_client(self) -> None:
        partition = {
            "filters": [{"questionId": 1, "answerId": 1}],
            "query": self.query,
            "targetA": {"name": "A", "voteCount": 1, "rank": 1},
            "targetB": {"name": "B", "voteCount": 1, "rank": 351},
        }

        with self.assertRaisesRegex(ValueError, "exceeds safe limit 350"):
            advanced.fetch_music_partition_covote(
                self.config,
                ExplodingClient(),
                partition,
                target_a="A",
                target_b="B",
            )

    def test_wrong_endpoint_set_is_rejected_even_with_expected_pair_count(self) -> None:
        # Three rows still equal C(3, 2), but D is not in ranking topK A/B/C.
        items = [
            {"a": "A", "b": "B", "m00": 1, "m01": 1, "m10": 2, "m11": 1},
            {"a": "A", "b": "D", "m00": 0, "m01": 0, "m10": 0, "m11": 5},
            {"a": "B", "b": "D", "m00": 0, "m01": 0, "m10": 0, "m11": 5},
        ]

        with self.assertRaisesRegex(ValueError, "endpoint set differs"):
            advanced.validate_music_partition_covote_response(
                self.covote_wrapper(items),
                self.config,
                self.partition(),
                top_k=3,
                target_a="A",
                target_b="B",
            )

    def test_noncontiguous_internal_ranks_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "not exactly 1..N"):
            advanced.validate_music_partition_stats_response(
                self.stats_wrapper([1, 3]),
                self.config,
                [(1, 1)],
                target_a="A",
                target_b="B",
                operation="MusicCovotePartitionStats",
                document=advanced.MUSIC_COVOTE_PARTITION_STATS_QUERY,
            )

    def test_query_override_and_ranking_vote_count_evidence_are_preserved(
        self,
    ) -> None:
        witness_query = advanced.music_witness_query(self.query, "Witness")

        record = advanced.validate_music_partition_stats_response(
            self.stats_wrapper([1, 2], query=witness_query),
            self.config,
            [(1, 1)],
            target_a="A",
            target_b="B",
            operation="MusicCovotePartitionStats",
            document=advanced.MUSIC_COVOTE_PARTITION_STATS_QUERY,
            query_filter_override=witness_query,
        )

        self.assertEqual(record["query"], witness_query)
        self.assertEqual(record["rankingVoteCountsByRank"], [3, 2])
        self.assertEqual(
            record["rankingVoteCountsByRankSha256"],
            advanced.canonical_json_sha256([3, 2]),
        )

    def test_stats_provenance_requires_post(self) -> None:
        for label, method in (("missing", None), ("wrong", "GET")):
            with self.subTest(method=label):
                value = self.stats_wrapper([1, 2])
                if method is None:
                    value["provenance"].pop("method")
                else:
                    value["provenance"]["method"] = method
                with self.assertRaisesRegex(ValueError, "method is not POST"):
                    advanced.validate_music_partition_stats_response(
                        value,
                        self.config,
                        [(1, 1)],
                        target_a="A",
                        target_b="B",
                        operation="MusicCovotePartitionStats",
                        document=advanced.MUSIC_COVOTE_PARTITION_STATS_QUERY,
                    )

    def test_stats_variables_allow_equivalent_time_but_reject_shape_drift(
        self,
    ) -> None:
        equivalent = self.stats_wrapper([1, 2])
        equivalent["provenance"]["variables"]["voteStart"] = (
            self.config.vote_start.replace(".000Z", "Z")
        )
        advanced.validate_music_partition_stats_response(
            equivalent,
            self.config,
            [(1, 1)],
            target_a="A",
            target_b="B",
            operation="MusicCovotePartitionStats",
            document=advanced.MUSIC_COVOTE_PARTITION_STATS_QUERY,
        )

        invalid_values = []
        extra = self.stats_wrapper([1, 2])
        extra["provenance"]["variables"]["topK"] = 2
        invalid_values.append(("extra", extra))
        missing = self.stats_wrapper([1, 2])
        missing["provenance"]["variables"].pop("query")
        invalid_values.append(("missing", missing))
        non_integer_year = self.stats_wrapper([1, 2])
        non_integer_year["provenance"]["variables"]["voteYear"] = "11"
        invalid_values.append(("non_integer_year", non_integer_year))

        for label, value in invalid_values:
            with self.subTest(variables=label):
                with self.assertRaisesRegex(ValueError, "variables mismatch"):
                    advanced.validate_music_partition_stats_response(
                        value,
                        self.config,
                        [(1, 1)],
                        target_a="A",
                        target_b="B",
                        operation="MusicCovotePartitionStats",
                        document=advanced.MUSIC_COVOTE_PARTITION_STATS_QUERY,
                    )

    def test_partition_stats_reuse_gate_accepts_equivalent_time_spelling(
        self,
    ) -> None:
        filters = [(1, 1), (2, 2)]
        query = advanced.music_partition_query(filters)
        value = self.stats_wrapper([1, 2], query=query)
        value["provenance"]["variables"]["voteStart"] = (
            self.config.vote_start.replace(".000Z", "Z")
        )
        with tempfile.TemporaryDirectory(dir=advanced.WORKSPACE) as directory:
            checkpoint = Path(directory) / "partition_stats.json"
            checkpoint.write_text(
                json.dumps(value, ensure_ascii=False), encoding="utf-8"
            )
            with patch.object(
                advanced, "music_partition_stats_path", return_value=checkpoint
            ):
                record = advanced.load_or_fetch_music_partition_stats(
                    self.config,
                    ExplodingClient(),
                    filters,
                    target_a="A",
                    target_b="B",
                )

        self.assertTrue(record["statsEvidence"]["reusedCheckpoint"])

    def test_partition_stats_reuse_gate_rejects_extra_variable(self) -> None:
        filters = [(1, 1), (2, 2)]
        query = advanced.music_partition_query(filters)
        value = self.stats_wrapper([1, 2], query=query)
        value["provenance"]["variables"]["unexpected"] = True
        with tempfile.TemporaryDirectory(dir=advanced.WORKSPACE) as directory:
            checkpoint = Path(directory) / "partition_stats.json"
            checkpoint.write_text(
                json.dumps(value, ensure_ascii=False), encoding="utf-8"
            )
            with patch.object(
                advanced, "music_partition_stats_path", return_value=checkpoint
            ):
                with self.assertRaisesRegex(AssertionError, "attribute graphql"):
                    advanced.load_or_fetch_music_partition_stats(
                        self.config,
                        ExplodingClient(),
                        filters,
                        target_a="A",
                        target_b="B",
                    )


if __name__ == "__main__":
    unittest.main()
