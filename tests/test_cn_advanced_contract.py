from __future__ import annotations

import unittest
from unittest import mock

from scripts_pipeline import crawl_cn_modern as modern_core
from scripts_pipeline import crawl_cn_modern_advanced as modern_advanced
from scripts_pipeline.cn_advanced_contract import advanced_coverage_contract
from scripts_pipeline.crawl_cn_modern_advanced import (
    questionnaire_pair_cell_response_valid,
    questionnaire_pair_cells,
    questionnaire_pair_inventory,
    questionnaire_pair_query,
)
from scripts_pipeline.build_vote_explorer_analysis_data import _cn_question_key


class ChineseAdvancedContractTests(unittest.TestCase):
    def test_family_names_and_pair_status_are_shared(self) -> None:
        contract = advanced_coverage_contract(
            questionnaire_pair_status="official_not_offered",
            questionnaire_pair_reason="modern schema has no cross endpoint",
        )
        self.assertEqual(
            [item["id"] for item in contract["conditionFamilies"]],
            ["questionnaire_answer", "questionnaire_pair", "entity_vote"],
        )
        pair = next(item for item in contract["conditionFamilies"] if item["id"] == "questionnaire_pair")
        self.assertEqual(pair["status"], "official_not_offered")
        self.assertFalse(contract["parityInterpretation"]["modernPairEndpointEquivalentToLegacy"])
        questionnaire = contract["conditionFamilies"][0]
        self.assertEqual(questionnaire["comparableRankingTargets"], ["character", "music"])
        self.assertEqual(questionnaire["modernAdditionalResultScopes"], ["global_stats", "cp"])

        partial = advanced_coverage_contract(
            questionnaire_pair_status="partial",
            questionnaire_pair_reason="explicit cell crawl is incomplete",
        )
        self.assertEqual(partial["conditionFamilies"][1]["status"], "partial")
        self.assertTrue(
            partial["parityInterpretation"][
                "modernEnumeratedCellsEquivalentToLegacyDataset"
            ]
        )

    def test_modern_pair_filter_is_explicit_and_requires_distinct_questions(self) -> None:
        self.assertEqual(
            questionnaire_pair_query("q11011", 1101101, 11021, "1102101"),
            "q11011=1101101 AND q11021=1102101",
        )
        with self.assertRaises(ValueError):
            questionnaire_pair_query(11011, 1101101, "q11011", 1101102)

    def test_modern_pair_cells_follow_legacy_matrix_row_order(self) -> None:
        pair = {
            "question1": {
                "questionId": 100,
                "options": [
                    {"optionIndex": 0, "answerId": 101, "content": "a"},
                    {"optionIndex": 1, "answerId": 102, "content": "b"},
                ],
            },
            "question2": {
                "questionId": 200,
                "options": [
                    {"optionIndex": 0, "answerId": 201, "content": "x"},
                    {"optionIndex": 1, "answerId": 202, "content": "y"},
                ],
            },
        }
        self.assertEqual(
            [
                (cell["question1AnswerId"], cell["question2AnswerId"])
                for cell in questionnaire_pair_cells(pair)
            ],
            [(101, 201), (102, 201), (101, 202), (102, 202)],
        )

    def test_modern_pair_cell_response_requires_matching_official_provenance(self) -> None:
        config = modern_core.ROUNDS[10]
        query = "q10011=1001101 AND q10021=1002101"
        response = {
            "provenance": {
                "operation": "QuestionnairePairCell",
                "variables": modern_core.base_variables(config, query=query),
                "status": 200,
            },
            "data": {"queryGlobalStats": {"voteYear": 10, "numVote": 12}},
        }
        self.assertEqual(
            questionnaire_pair_cell_response_valid(
                response,
                config=config,
                query=query,
            ),
            (True, None),
        )
        response["data"]["queryGlobalStats"]["numVote"] = -1
        self.assertFalse(
            questionnaire_pair_cell_response_valid(
                response,
                config=config,
                query=query,
            )[0]
        )

    def test_pair_stage_stops_after_first_outage_failure(self) -> None:
        pair = {
            "question1": {
                "questionId": 100,
                "question": "q1",
                "questionType": "Single",
                "options": [
                    {"optionIndex": 0, "answerId": 101, "content": "a"},
                    {"optionIndex": 1, "answerId": 102, "content": "b"},
                ],
            },
            "question2": {
                "questionId": 200,
                "question": "q2",
                "questionType": "Single",
                "options": [
                    {"optionIndex": 0, "answerId": 201, "content": "x"},
                    {"optionIndex": 1, "answerId": 202, "content": "y"},
                ],
            },
            "answerCellCount": 4,
        }
        client = mock.Mock()
        client.graphql.side_effect = OSError("site unavailable")
        coverage = {
            "expectedPairs": 1,
            "availablePairs": 0,
            "expectedAnswerCells": 4,
            "availableAnswerCells": 0,
            "invalidDetails": [],
            "complete": False,
        }
        with (
            mock.patch.object(modern_advanced, "questionnaire_pair_specs", return_value=[pair]),
            mock.patch.object(modern_advanced, "questionnaire_pair_coverage", return_value=coverage),
            mock.patch.object(modern_advanced, "load_questionnaire_pair_checkpoint", return_value=({}, [])),
            mock.patch.object(modern_advanced, "write_questionnaire_pair_checkpoint"),
            mock.patch.object(modern_advanced, "write_queue_status"),
        ):
            failures, requests = modern_advanced.crawl_questionnaire_pairs(
                modern_core.ROUNDS[10],
                client,
                max_requests=None,
            )
        self.assertEqual(requests, 1)
        self.assertEqual(client.graphql.call_count, 1)
        self.assertEqual(len(failures), 1)

    def test_modern_pair_inventory_keeps_real_cn10_cn11_gap_counts(self) -> None:
        expected = {
            10: (74, 387, 2701, 73168),
            11: (73, 403, 2628, 79239),
        }
        for round_number, counts in expected.items():
            with self.subTest(round=round_number):
                inventory = questionnaire_pair_inventory(
                    modern_core.ROUNDS[round_number]
                )
                self.assertEqual(
                    (
                        inventory["eligibleQuestionCount"],
                        inventory["eligibleAnswerOptionCount"],
                        inventory["unorderedQuestionPairCount"],
                        inventory["answerCellCount"],
                    ),
                    counts,
                )

    def test_modern_question_wording_reuses_legacy_analysis_keys(self) -> None:
        self.assertEqual(
            _cn_question_key(
                "您的性别是？（填写的信息仅用于数据分析，不会披露个人信息）"
            ),
            "sex",
        )
        self.assertEqual(_cn_question_key("您的年龄阶段是？"), "age")


if __name__ == "__main__":
    unittest.main()
