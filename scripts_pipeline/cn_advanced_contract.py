"""Shared coverage contract for Chinese advanced-search archives.

The legacy (CN5--9) PHP site and the modern (CN10--11) GraphQL site expose
the same *atomic* filters, but they do not expose the same questionnaire
cross-tab endpoint.  CN10--11 therefore rebuild the finite legacy pair surface
from explicit Boolean answer-cell queries.  Keeping the contract in one small
module prevents the two crawlers from silently drifting back to different
condition names or combination rules.

This module is metadata-only.  It does not make network requests and it does
not claim that the modern endpoint itself is the legacy bulk endpoint.
"""

from __future__ import annotations

from typing import Any


CONTRACT_VERSION = 2


def advanced_coverage_contract(
    *,
    questionnaire_pair_status: str,
    questionnaire_pair_reason: str,
) -> dict[str, Any]:
    """Return the canonical advanced-search families and combinations.

    ``questionnaire_pair_status`` is deliberately supplied by each crawler:
    CN5--9 can report ``available_crawled`` from one bulk response per pair;
    CN10--11 progresses from ``pending`` through ``partial`` to
    ``available_crawled`` while issuing every exact Boolean answer cell.
    """

    if questionnaire_pair_status not in {
        "available_crawled",
        "official_not_offered",
        "fetch_failed",
        "pending",
        "partial",
    }:
        raise ValueError(f"unknown questionnaire pair status: {questionnaire_pair_status}")
    return {
        "schemaVersion": CONTRACT_VERSION,
        "conditionFamilies": [
            {
                "id": "questionnaire_answer",
                "unit": "one questionnaire answer option",
                "queryForm": "q<questionId>=<answerId>",
                "questionTypes": ["Single", "Multiple"],
                "excludedQuestionTypes": ["Input", "open_text"],
                "comparableRankingTargets": ["character", "music"],
                "legacyResultScopes": ["character", "music"],
                "modernResultScopes": ["global_stats", "character", "music", "cp"],
                "modernAdditionalResultScopes": ["global_stats", "cp"],
                "combination": "singleton; multiple clauses are an explicit Boolean query",
                "legacyComponent": "questionnaire_atomic_rankings",
                "modernComponent": "questionnaireAnswerConditions",
            },
            {
                "id": "questionnaire_pair",
                "unit": "unordered pair of distinct eligible questions",
                "queryForm": "all answer cross-cells for question A × question B",
                "questionTypes": ["Single", "Multiple"],
                "excludedQuestionTypes": ["Input", "open_text"],
                "comparableTargets": ["global"],
                "resultScopes": ["pair_cells", "conditional_percentages"],
                "combination": "one unordered pair per eligible question pair",
                "legacyComponent": "questionnaire_unordered_pairs",
                "modernComponent": "questionnaireUnorderedPairs",
                "status": questionnaire_pair_status,
                "statusReason": questionnaire_pair_reason,
            },
            {
                "id": "entity_vote",
                "unit": "one named character or music entity",
                "queryForms": [
                    "chars: [<name>]",
                    "chars_first=<name>",
                    "musics: [<name>]",
                    "musics_first=<name>",
                ],
                "sourceCategories": ["character", "music"],
                "conditionKinds": ["any", "first"],
                "comparableRankingTargets": ["character", "music"],
                "legacyResultScopes": ["character", "music"],
                "modernResultScopes": ["global_stats", "character", "music", "cp"],
                "modernAdditionalResultScopes": ["global_stats", "cp"],
                "combination": "singleton; zero-sized first cohorts are excluded",
                "legacyComponent": "entity_atomic_rankings",
                "modernComponent": "entityAtomicConditions",
            },
        ],
        "booleanQueryLanguage": {
            "operators": ["AND", "OR"],
            "grouping": ["(", ")"],
            "capturedAsRawQueries": True,
            "cartesianEnumeration": False,
            "reason": "the official query language permits unbounded Boolean products",
        },
        "parityInterpretation": {
            "atomicFamiliesMustMatch": True,
            "comparableAtomicTargets": ["character", "music"],
            "modernAdditionalScopesAreExtensions": ["global_stats", "cp"],
            "questionnairePairMatrixMustBeReportedSeparately": True,
            "modernPairEndpointEquivalentToLegacy": False,
            "modernEnumeratedCellsEquivalentToLegacyDataset": True,
            "note": (
                "The modern endpoint has no bulk cross-table operation. "
                "Enumerating every qA=answerA AND qB=answerB cell restores "
                "the same finite count/percentage dataset with different "
                "transport provenance."
            ),
        },
    }
