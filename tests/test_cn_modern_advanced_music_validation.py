from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping
import unittest
from unittest import mock


SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "scripts_pipeline"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import crawl_cn_modern as core  # noqa: E402
import crawl_cn_modern_advanced as advanced  # noqa: E402


GRAPHQL_KEY = "queryMusicsCovote"
RECONSTRUCTION_OPERATION = "MusicCovoteReciprocalMatrixReconstruction"
CELL_KEYS = ("m00", "m01", "m10", "m11")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strict_nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def resolve_evidence_path(workspace: Path, relative_path: object) -> Path | None:
    if not isinstance(relative_path, str) or not relative_path:
        return None
    supplied = Path(relative_path)
    if supplied.is_absolute():
        return None
    workspace = workspace.resolve()
    candidate = (workspace / supplied).resolve()
    try:
        candidate.relative_to(workspace)
    except ValueError:
        return None
    return candidate


def reference_reconstructed_music_matrix_valid(
    path: Path,
    *,
    base: Mapping[str, Any],
    workspace: Path,
    require_bridge: bool = True,
) -> bool:
    """Executable contract for the stronger production checkpoint validator.

    This intentionally remains independent of the production implementation.
    It lets the corruption fixtures run before that implementation exists and
    acts as a readable specification for the production contract below.
    """

    try:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
        provenance = wrapper["provenance"]
        context = wrapper["context"]
        stats = base["data"]["queryGlobalStats"]
        entries = base["data"]["queryMusicRanking"]["entries"]

        vote_year = stats["voteYear"]
        universe = stats["numMusic"]
        if not strict_nonnegative_int(vote_year) or not strict_nonnegative_int(
            universe
        ):
            return False

        names: list[str] = []
        marginals: dict[str, int] = {}
        for entry in entries:
            name = entry["name"]
            count = entry["voteCount"]
            if (
                not isinstance(name, str)
                or not name
                or name in marginals
                or not strict_nonnegative_int(count)
                or count > universe
            ):
                return False
            names.append(name)
            marginals[name] = count

        expected_pair_count = len(names) * (len(names) - 1) // 2
        expected_pairs = {
            frozenset((left, right))
            for left, right in itertools.combinations(names, 2)
        }
        if (
            provenance.get("source") != core.ENDPOINT
            or provenance.get("operation") != RECONSTRUCTION_OPERATION
            or provenance.get("method")
            != "official POST responses combined locally"
            or context.get("topK") != len(names)
            or context.get("expectedPairCount") != expected_pair_count
        ):
            return False

        items = wrapper["data"][GRAPHQL_KEY]["items"]
        if not isinstance(items, list) or len(items) != expected_pair_count:
            return False
        observed_pairs: set[frozenset[str]] = set()
        for item in items:
            if not isinstance(item, Mapping):
                return False
            a = item.get("a")
            b = item.get("b")
            if (
                not isinstance(a, str)
                or not isinstance(b, str)
                or a == b
                or a not in marginals
                or b not in marginals
            ):
                return False
            pair = frozenset((a, b))
            if pair in observed_pairs:
                return False
            observed_pairs.add(pair)
            cells = {key: item.get(key) for key in CELL_KEYS}
            if not all(strict_nonnegative_int(value) for value in cells.values()):
                return False
            if (
                sum(cells.values()) != universe
                or cells["m00"] + cells["m10"] != marginals[a]
                or cells["m00"] + cells["m01"] != marginals[b]
            ):
                return False
        if observed_pairs != expected_pairs:
            return False

        proof_path_text = provenance.get("questionnairePartitionProofPath")
        proof_sha = provenance.get("questionnairePartitionProofSha256")
        attempts_path_text = provenance.get("questionnairePartitionAttemptsPath")
        attempts_sha = provenance.get("questionnairePartitionAttemptsSha256")
        validation_path_text = context.get("validationPath")
        validation_sha = context.get("validationSha256")
        evidence = (
            (proof_path_text, proof_sha),
            (attempts_path_text, attempts_sha),
            (validation_path_text, validation_sha),
        )
        resolved: list[Path] = []
        for relative_path, expected_sha in evidence:
            evidence_path = resolve_evidence_path(workspace, relative_path)
            if (
                evidence_path is None
                or not evidence_path.is_file()
                or not isinstance(expected_sha, str)
                or len(expected_sha) != 64
                or sha256_file(evidence_path) != expected_sha
            ):
                return False
            resolved.append(evidence_path)
        proof_path, attempts_path, validation_path = resolved
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        attempts = json.loads(attempts_path.read_text(encoding="utf-8"))
        validation = json.loads(validation_path.read_text(encoding="utf-8"))

        if require_bridge and (
            proof.get("complete") is not True
            or proof.get("round") != vote_year
            or proof.get("officialEndpoint") != core.ENDPOINT
            or attempts.get("complete") is not True
            or attempts.get("round") != vote_year
            or attempts.get("proofPath") != proof_path_text
            or attempts.get("proofSha256") != proof_sha
        ):
            return False

        bridge = validation.get("questionnairePartitionBridge")
        if require_bridge and not isinstance(bridge, Mapping):
            return False
        if require_bridge and (
            bridge.get("proofPath") != proof_path_text
            or bridge.get("proofSha256") != proof_sha
            or bridge.get("attemptsPath") != attempts_path_text
            or bridge.get("attemptsSha256") != attempts_sha
        ):
            return False
        if (
            validation.get("round") != vote_year
            or validation.get("category") != "music"
            or validation.get("sourceItems") != len(names)
            or validation.get("expectedPairs") != expected_pair_count
            or validation.get("observedPairs") != expected_pair_count
            or validation.get("universe") != universe
            or validation.get("allMarginalAndUniverseIdentitiesPassed") is not True
            or validation.get("allAvailableConditionalSymmetryChecksPassed")
            is not True
        ):
            return False
        return True
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


class SyntheticMusicFixture:
    """Small exact analogue of the 612-item/186966-pair CN11 matrix."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.matrix_path = workspace / "covote" / "music.json"
        self.proof_path = workspace / "evidence" / "bridge_proof.json"
        self.attempts_path = workspace / "evidence" / "bridge_attempts.json"
        self.validation_path = workspace / "evidence" / "validation.json"
        self.names = ["Alpha", "Beta\t", "Gamma", "Zero"]
        self.counts = {"Alpha": 10, "Beta\t": 8, "Gamma": 5, "Zero": 0}
        self.universe = 20
        self.base = {
            "provenance": {
                "variables": {
                    "voteStart": core.ROUNDS[11].vote_start,
                    "voteYear": 11,
                }
            },
            "data": {
                "queryGlobalStats": {"voteYear": 11, "numMusic": self.universe},
                "queryMusicRanking": {
                    "entries": [
                        {"name": name, "voteCount": self.counts[name]}
                        for name in self.names
                    ]
                },
            }
        }
        self.proof: dict[str, Any]
        self.attempts: dict[str, Any]
        self.validation: dict[str, Any]
        self.wrapper: dict[str, Any]
        self.witness_proof_path = workspace / "evidence" / "witness_proof.json"
        self.witness_response_path = workspace / "evidence" / "witness_stats.json"
        self.witness_proof: dict[str, Any] | None = None
        self.witness_response: dict[str, Any] | None = None
        self.reset()

    def relative(self, path: Path) -> str:
        return path.relative_to(self.workspace).as_posix()

    def matrix_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for a, b in itertools.combinations(self.names, 2):
            intersection = min(self.counts[a], self.counts[b]) // 2
            items.append(
                {
                    "a": a,
                    "b": b,
                    "m00": intersection,
                    "m01": self.counts[b] - intersection,
                    "m10": self.counts[a] - intersection,
                    "m11": (
                        self.universe
                        - self.counts[a]
                        - self.counts[b]
                        + intersection
                    ),
                }
            )
        return items

    def reset(self) -> None:
        proof_path_text = self.relative(self.proof_path)
        attempts_path_text = self.relative(self.attempts_path)
        validation_path_text = self.relative(self.validation_path)
        self.proof = {
            "schemaVersion": 1,
            "round": 11,
            "officialEndpoint": core.ENDPOINT,
            "complete": True,
            "targetPair": {"a": "Alpha", "b": "Beta\t"},
            "aggregatedTargetPair": {
                "a": "Alpha",
                "b": "Beta\t",
                "m00": 4,
                "m01": 4,
                "m10": 6,
                "m11": 6,
            },
        }
        write_json(self.proof_path, self.proof)
        proof_sha = sha256_file(self.proof_path)
        self.attempts = {
            "schemaVersion": 1,
            "round": 11,
            "complete": True,
            "proofPath": proof_path_text,
            "proofSha256": proof_sha,
            "statsRequests": [],
            "covoteAttempts": [],
        }
        write_json(self.attempts_path, self.attempts)
        attempts_sha = sha256_file(self.attempts_path)
        self.validation = {
            "round": 11,
            "category": "music",
            "sourceItems": len(self.names),
            "expectedPairs": 6,
            "observedPairs": 6,
            "universe": self.universe,
            "allMarginalAndUniverseIdentitiesPassed": True,
            "allAvailableConditionalSymmetryChecksPassed": True,
            "questionnairePartitionBridge": {
                "proofPath": proof_path_text,
                "proofSha256": proof_sha,
                "attemptsPath": attempts_path_text,
                "attemptsSha256": attempts_sha,
                "pairsUsed": 1,
            },
        }
        write_json(self.validation_path, self.validation)
        validation_sha = sha256_file(self.validation_path)
        self.wrapper = {
            "provenance": {
                "source": core.ENDPOINT,
                "method": "official POST responses combined locally",
                "operation": RECONSTRUCTION_OPERATION,
                "sourceCheckpointCount": 2,
                "questionnairePartitionProofPath": proof_path_text,
                "questionnairePartitionProofSha256": proof_sha,
                "questionnairePartitionAttemptsPath": attempts_path_text,
                "questionnairePartitionAttemptsSha256": attempts_sha,
            },
            "context": {
                "topK": len(self.names),
                "expectedPairCount": 6,
                "validationPath": validation_path_text,
                "validationSha256": validation_sha,
            },
            "data": {GRAPHQL_KEY: {"items": self.matrix_items()}},
        }
        self.write_matrix()

    def write_matrix(self) -> None:
        write_json(self.matrix_path, self.wrapper)

    def rewrite_validation_and_repoint_matrix(self) -> None:
        write_json(self.validation_path, self.validation)
        self.wrapper["context"]["validationSha256"] = sha256_file(
            self.validation_path
        )
        self.write_matrix()

    def rewrite_attempts_and_repoint_dependents(self) -> None:
        write_json(self.attempts_path, self.attempts)
        attempts_sha = sha256_file(self.attempts_path)
        self.wrapper["provenance"][
            "questionnairePartitionAttemptsSha256"
        ] = attempts_sha
        self.validation["questionnairePartitionBridge"][
            "attemptsSha256"
        ] = attempts_sha
        self.rewrite_validation_and_repoint_matrix()

    @staticmethod
    def frechet(partition: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
        universe = partition["numMusic"]
        count_a = partition["targetA"]["voteCount"]
        count_b = partition["targetB"]["voteCount"]
        lower = max(0, count_a + count_b - universe)
        upper = min(count_a, count_b)
        cells = {
            "m00": lower,
            "m01": count_b - lower,
            "m10": count_a - lower,
            "m11": universe - count_a - count_b + lower,
        }
        return (
            {
                "method": "binary-event Frechet bounds from exact local marginals",
                "universeNumMusic": universe,
                "targetAVoteCount": count_a,
                "targetBVoteCount": count_b,
                "intersectionLowerBound": lower,
                "intersectionUpperBound": upper,
                "boundsAreEqual": lower == upper,
                "uniqueIntersection": lower,
                "allCellIdentitiesPassed": True,
            },
            cells,
        )

    def rewrite_witness_proof_and_chain(self) -> None:
        assert self.witness_proof is not None
        write_json(self.witness_proof_path, self.witness_proof)
        identity = {
            "path": self.relative(self.witness_proof_path),
            "sha256": sha256_file(self.witness_proof_path),
            "role": "unit witness exact split proof",
        }
        witness_node = self.proof["resolutionTree"]["children"][0]
        witness_node["splitProof"]["proofEvidence"] = identity
        self.attempts["witnessFallbacks"][0]["proofEvidence"] = identity
        self.rewrite_top_proof_and_chain()

    def rewrite_top_proof_and_chain(self) -> None:
        write_json(self.proof_path, self.proof)
        proof_sha = sha256_file(self.proof_path)
        proof_path_text = self.relative(self.proof_path)
        self.attempts["proofPath"] = proof_path_text
        self.attempts["proofSha256"] = proof_sha
        write_json(self.attempts_path, self.attempts)
        attempts_sha = sha256_file(self.attempts_path)
        bridge = self.validation["questionnairePartitionBridge"]
        bridge["proofPath"] = proof_path_text
        bridge["proofSha256"] = proof_sha
        bridge["attemptsPath"] = self.relative(self.attempts_path)
        bridge["attemptsSha256"] = attempts_sha
        self.wrapper["provenance"]["questionnairePartitionProofPath"] = proof_path_text
        self.wrapper["provenance"]["questionnairePartitionProofSha256"] = proof_sha
        self.wrapper["provenance"]["questionnairePartitionAttemptsPath"] = (
            self.relative(self.attempts_path)
        )
        self.wrapper["provenance"]["questionnairePartitionAttemptsSha256"] = (
            attempts_sha
        )
        self.rewrite_validation_and_repoint_matrix()

    def rewrite_witness_response_and_chain(self) -> None:
        assert self.witness_response is not None
        assert self.witness_proof is not None
        write_json(self.witness_response_path, self.witness_response)
        identity = {
            "path": self.relative(self.witness_response_path),
            "sha256": sha256_file(self.witness_response_path),
            "operation": "MusicCovotePartitionStats",
            "role": "unit witness subset",
        }
        self.witness_proof["officialChildResponseEvidence"] = identity
        self.witness_proof["officialChild"]["statsEvidence"] = identity
        witness_node = self.proof["resolutionTree"]["children"][0]
        witness_node["splitProof"]["officialChildResponseEvidence"] = identity
        witness_node["children"][0]["partition"]["statsEvidence"] = identity
        self.attempts["witnessFallbacks"][0][
            "officialChildResponseEvidence"
        ] = identity
        self.rewrite_witness_proof_and_chain()

    def enable_witness(self, witness_name: str = "Gamma") -> None:
        parent_query = "q1=1"
        query = parent_query + ' AND musics: ["Gamma"]'
        selection = {
            "name": witness_name,
            "rank": 1,
            "parentVoteCount": 1,
            "selectionRule": "lowest exact filtered rank",
            "eligibleCandidateCount": 1,
        }
        parent_names = [witness_name, "Alpha", "Beta\t"]
        parent_counts = [1, 1, 1]
        parent = {
            "filters": [{"questionId": 1, "answerId": 1}],
            "query": parent_query,
            "numVote": 2,
            "numMusic": 2,
            "rankingEntryCount": 3,
            "rankingNamesByRank": parent_names,
            "rankingNamesByRankSha256": advanced.canonical_json_sha256(
                parent_names
            ),
            "rankingVoteCountsByRank": parent_counts,
            "rankingVoteCountsByRankSha256": advanced.canonical_json_sha256(
                parent_counts
            ),
            "targetA": {"name": "Alpha", "voteCount": 1, "rank": 2},
            "targetB": {"name": "Beta\t", "voteCount": 1, "rank": 3},
            "statsEvidence": {
                "path": "evidence/parent_stats.json",
                "sha256": "1" * 64,
            },
        }
        child_names = [witness_name, "Alpha"]
        child_counts = [1, 1]
        official_child = {
            "filters": [{"questionId": 1, "answerId": 1}],
            "query": query,
            "numVote": 1,
            "numMusic": 1,
            "rankingEntryCount": 2,
            "rankingNamesByRank": child_names,
            "rankingNamesByRankSha256": advanced.canonical_json_sha256(child_names),
            "rankingVoteCountsByRank": child_counts,
            "rankingVoteCountsByRankSha256": advanced.canonical_json_sha256(
                child_counts
            ),
            "targetA": {"name": "Alpha", "voteCount": 1, "rank": 2},
            "targetB": {"name": "Beta\t", "voteCount": 0, "rank": None},
            "witnessFilter": {"type": "music_any", "name": witness_name},
        }
        complement = {
            "filters": [{"questionId": 1, "answerId": 1}],
            "query": None,
            "numVote": 1,
            "numMusic": 1,
            "targetA": {"name": "Alpha", "voteCount": 0, "rank": None},
            "targetB": {"name": "Beta\t", "voteCount": 1, "rank": None},
            "residualDefinition": {
                "operation": "exact parent minus official unit witness child",
                "witnessName": witness_name,
                "hasDirectOfficialQuery": False,
            },
        }
        parent_values = {
            "numVote": 2,
            "numMusic": 2,
            "targetAVoteCount": 1,
            "targetBVoteCount": 1,
        }
        conservation = {
            "observedSums": parent_values,
            "expectedParentValues": parent_values,
            "passed": True,
        }
        child_frechet, child_cells = self.frechet(official_child)
        complement_frechet, complement_cells = self.frechet(complement)
        aggregated = {
            key: child_cells[key] + complement_cells[key] for key in CELL_KEYS
        }
        self.witness_response = {
            "provenance": {
                "source": core.ENDPOINT,
                "method": "POST",
                "operation": "MusicCovotePartitionStats",
                "documentSha256": core.sha256_bytes(
                    advanced.MUSIC_COVOTE_PARTITION_STATS_QUERY.encode("utf-8")
                ),
                "variables": core.base_variables(
                    core.ROUNDS[11], query=query
                ),
                "status": 200,
                "contentType": "application/json",
            },
            "data": {
                "queryGlobalStats": {
                    "voteYear": 11,
                    "numVote": 1,
                    "numMusic": 1,
                },
                "queryMusicRanking": {
                    "global": {"totalUniqueItems": 2, "totalVotes": 1},
                    "entries": [
                        {
                            "rank": 1,
                            "displayRank": 1,
                            "name": witness_name,
                            "voteCount": 1,
                        },
                        {
                            "rank": 2,
                            "displayRank": 2,
                            "name": "Alpha",
                            "voteCount": 1,
                        },
                    ],
                },
            },
        }
        write_json(self.witness_response_path, self.witness_response)
        response_evidence = {
            "path": self.relative(self.witness_response_path),
            "sha256": sha256_file(self.witness_response_path),
            "operation": "MusicCovotePartitionStats",
            "role": "unit witness subset",
        }
        official_child["statsEvidence"] = response_evidence
        self.witness_proof = {
            "schemaVersion": 1,
            "round": 11,
            "complete": True,
            "targetPair": {"a": "Alpha", "b": "Beta\t"},
            "parent": parent,
            "selection": selection,
            "officialChildQuery": query,
            "officialChildResponseEvidence": response_evidence,
            "officialChild": official_child,
            "complement": complement,
            "conservationProof": conservation,
            "childFrechetProof": child_frechet,
            "complementFrechetProof": complement_frechet,
            "aggregatedCells": aggregated,
        }
        write_json(self.witness_proof_path, self.witness_proof)
        proof_evidence = {
            "path": self.relative(self.witness_proof_path),
            "sha256": sha256_file(self.witness_proof_path),
            "role": "unit witness exact split proof",
        }
        witness_node = {
            "nodeType": "witness_partition_split",
            "partition": parent,
            "splitProof": {
                "method": "unit music witness plus exact complement",
                "selection": selection,
                "proofEvidence": proof_evidence,
                "officialChildResponseEvidence": response_evidence,
                "conservationProof": conservation,
            },
            "children": [
                {
                    "nodeType": "locally_proven_frechet_leaf",
                    "partition": official_child,
                    "localIntersectionProof": child_frechet,
                    "cells": child_cells,
                },
                {
                    "nodeType": "locally_proven_frechet_leaf",
                    "partition": complement,
                    "localIntersectionProof": complement_frechet,
                    "cells": complement_cells,
                },
            ],
            "cells": aggregated,
        }
        self.proof["resolutionTree"] = {
            "nodeType": "refinement_split",
            "children": [witness_node],
            "cells": self.proof["aggregatedTargetPair"],
        }
        self.attempts["witnessFallbacks"] = [
            {
                "parentQuery": parent_query,
                "query": query,
                "status": "validated",
                "selection": selection,
                "officialChildResponseEvidence": response_evidence,
                "proofEvidence": proof_evidence,
                "conservationPassed": True,
                "bothFrechetIntersectionsUnique": True,
            }
        ]
        self.rewrite_top_proof_and_chain()


class ReconstructedMusicValidationReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(
            prefix="cn11_music_validation_"
        )
        self.workspace = Path(self._temporary.name)
        self.fixture = SyntheticMusicFixture(self.workspace)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def strong_valid(self) -> bool:
        return reference_reconstructed_music_matrix_valid(
            self.fixture.matrix_path,
            base=self.fixture.base,
            workspace=self.workspace,
            require_bridge=True,
        )

    def legacy_valid(self) -> bool:
        return core.covote_matrix_checkpoint_valid(
            self.fixture.matrix_path,
            graphql_key=GRAPHQL_KEY,
            expected_pairs=6,
        )

    def assert_legacy_leak_is_rejected(self) -> None:
        self.fixture.write_matrix()
        self.assertTrue(self.legacy_valid(), "fixture must expose the legacy leak")
        self.assertFalse(self.strong_valid())

    def test_cn11_catalogue_pair_count_is_186966(self) -> None:
        self.assertEqual(612 * 611 // 2, 186_966)

    def test_valid_exact_matrix_and_evidence_chain_pass(self) -> None:
        self.assertTrue(self.legacy_valid())
        self.assertTrue(self.strong_valid())

    def test_unknown_or_normalized_name_is_rejected_but_legacy_accepts(self) -> None:
        # The trailing TAB is part of the official catalogue identity.
        self.fixture.wrapper["data"][GRAPHQL_KEY]["items"][0]["b"] = "Beta"
        self.assert_legacy_leak_is_rejected()

    def test_diagonal_pair_is_rejected_but_legacy_accepts(self) -> None:
        item = self.fixture.wrapper["data"][GRAPHQL_KEY]["items"][0]
        item["b"] = item["a"]
        self.assert_legacy_leak_is_rejected()

    def test_reverse_duplicate_is_rejected_but_legacy_accepts(self) -> None:
        items = self.fixture.wrapper["data"][GRAPHQL_KEY]["items"]
        items[1]["a"], items[1]["b"] = items[0]["b"], items[0]["a"]
        self.assert_legacy_leak_is_rejected()

    def test_wrong_marginal_is_rejected_but_legacy_accepts(self) -> None:
        item = self.fixture.wrapper["data"][GRAPHQL_KEY]["items"][0]
        item["m00"] += 1
        item["m11"] -= 1
        self.assert_legacy_leak_is_rejected()

    def test_wrong_universe_is_rejected_but_legacy_accepts(self) -> None:
        self.fixture.wrapper["data"][GRAPHQL_KEY]["items"][0]["m11"] += 1
        self.assert_legacy_leak_is_rejected()

    def test_wrong_operation_or_source_is_rejected_but_legacy_accepts(self) -> None:
        for key, replacement in (
            ("operation", "MusicCovoteCounts"),
            ("source", "https://example.invalid/graphql"),
        ):
            with self.subTest(key=key):
                self.fixture.reset()
                self.fixture.wrapper["provenance"][key] = replacement
                self.assert_legacy_leak_is_rejected()

    def test_missing_or_wrong_proof_hash_is_rejected_but_legacy_accepts(self) -> None:
        self.fixture.wrapper["provenance"][
            "questionnairePartitionProofSha256"
        ] = "0" * 64
        self.assert_legacy_leak_is_rejected()

    def test_wrong_attempts_hash_is_rejected_but_legacy_accepts(self) -> None:
        self.fixture.wrapper["provenance"][
            "questionnairePartitionAttemptsSha256"
        ] = "0" * 64
        self.assert_legacy_leak_is_rejected()

    def test_wrong_validation_hash_is_rejected_but_legacy_accepts(self) -> None:
        self.fixture.wrapper["context"]["validationSha256"] = "0" * 64
        self.assert_legacy_leak_is_rejected()

    def test_validation_cross_reference_must_match_even_with_fresh_file_hash(self) -> None:
        self.fixture.validation["questionnairePartitionBridge"][
            "proofSha256"
        ] = "0" * 64
        self.fixture.rewrite_validation_and_repoint_matrix()
        self.assertTrue(self.legacy_valid())
        self.assertFalse(self.strong_valid())

    def test_attempts_cross_reference_must_match_even_with_fresh_file_hash(self) -> None:
        self.fixture.attempts["proofSha256"] = "0" * 64
        self.fixture.rewrite_attempts_and_repoint_dependents()
        self.assertTrue(self.legacy_valid())
        self.assertFalse(self.strong_valid())

    def test_evidence_path_cannot_escape_workspace(self) -> None:
        self.fixture.wrapper["provenance"][
            "questionnairePartitionProofPath"
        ] = "../bridge_proof.json"
        self.assert_legacy_leak_is_rejected()


class AdvancedMusicValidationDispatchTests(unittest.TestCase):
    """Prevent reconstruction provenance corruption from reaching the weak gate."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(
            prefix="cn11_music_dispatch_"
        )
        self.workspace = Path(self._temporary.name)
        self.fixture = SyntheticMusicFixture(self.workspace)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def dispatch_valid(self) -> bool:
        with mock.patch.object(advanced, "WORKSPACE", self.workspace):
            return advanced.advanced_covote_matrix_checkpoint_valid(
                self.fixture.matrix_path,
                category="music",
                graphql_key=GRAPHQL_KEY,
                expected_pairs=6,
                base=self.fixture.base,
            )

    def test_corrupt_reconstruction_cannot_masquerade_as_direct_operation(self) -> None:
        self.assertTrue(self.dispatch_valid())
        self.fixture.wrapper["provenance"]["operation"] = "MusicCovoteCounts"
        self.fixture.wrapper["data"][GRAPHQL_KEY]["items"][0]["m00"] += 1
        self.fixture.write_matrix()
        self.assertFalse(self.dispatch_valid())

    def test_unknown_official_operation_is_not_sent_to_the_legacy_gate(self) -> None:
        self.fixture.wrapper["provenance"] = {
            "source": core.ENDPOINT,
            "method": "POST",
            "operation": "UnknownMusicOperation",
        }
        self.fixture.wrapper["context"] = {}
        self.fixture.write_matrix()
        self.assertFalse(self.dispatch_valid())

    def test_known_official_direct_response_still_uses_direct_gate(self) -> None:
        self.fixture.wrapper["provenance"] = {
            "source": core.ENDPOINT,
            "method": "POST",
            "operation": "MusicCovoteCounts",
        }
        self.fixture.wrapper["context"] = {
            "topK": len(self.fixture.names),
            "expectedPairCount": 6,
        }
        self.fixture.write_matrix()
        self.assertTrue(self.dispatch_valid())


PRODUCTION_VALIDATOR = getattr(
    advanced, "reconstructed_music_matrix_checkpoint_valid", None
)


@unittest.skipUnless(
    PRODUCTION_VALIDATOR is not None,
    "production strong reconstructed-music validator is not implemented yet",
)
class ReconstructedMusicProductionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(
            prefix="cn11_music_production_contract_"
        )
        self.workspace = Path(self._temporary.name)
        self.fixture = SyntheticMusicFixture(self.workspace)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def production_valid(self) -> bool:
        assert PRODUCTION_VALIDATOR is not None
        return bool(
            PRODUCTION_VALIDATOR(
                self.fixture.matrix_path,
                base=self.fixture.base,
                workspace=self.workspace,
                require_bridge=True,
            )
        )

    def test_valid_fixture_passes(self) -> None:
        self.assertTrue(self.production_valid())

    def test_bad_name_diagonal_and_reverse_duplicate_are_rejected(self) -> None:
        cases = ("normalized_name", "diagonal", "reversed_pair")
        for case in cases:
            with self.subTest(case=case):
                self.fixture.reset()
                items = self.fixture.wrapper["data"][GRAPHQL_KEY]["items"]
                if case == "normalized_name":
                    items[0]["b"] = "Beta"
                elif case == "diagonal":
                    items[0]["b"] = items[0]["a"]
                else:
                    items = self.fixture.wrapper["data"][GRAPHQL_KEY]["items"]
                    items[1]["a"], items[1]["b"] = items[0]["b"], items[0]["a"]
                self.fixture.write_matrix()
                self.assertFalse(self.production_valid())

    def test_wrong_marginal_and_universe_are_rejected(self) -> None:
        for case in ("marginal", "universe"):
            with self.subTest(case=case):
                self.fixture.reset()
                item = self.fixture.wrapper["data"][GRAPHQL_KEY]["items"][0]
                if case == "marginal":
                    item["m00"] += 1
                    item["m11"] -= 1
                else:
                    item["m11"] += 1
                self.fixture.write_matrix()
                self.assertFalse(self.production_valid())

    def test_wrong_wrapper_operation_and_source_are_rejected(self) -> None:
        for key, replacement in (
            ("operation", "MusicCovoteCounts"),
            ("source", "https://example.invalid/graphql"),
        ):
            with self.subTest(key=key):
                self.fixture.reset()
                self.fixture.wrapper["provenance"][key] = replacement
                self.fixture.write_matrix()
                self.assertFalse(self.production_valid())

    def test_wrong_proof_attempts_and_validation_hashes_are_rejected(self) -> None:
        locations = (
            ("provenance", "questionnairePartitionProofSha256"),
            ("provenance", "questionnairePartitionAttemptsSha256"),
            ("context", "validationSha256"),
        )
        for section, key in locations:
            with self.subTest(section=section, key=key):
                self.fixture.reset()
                self.fixture.wrapper[section][key] = "0" * 64
                self.fixture.write_matrix()
                self.assertFalse(self.production_valid())

    def test_internal_evidence_cross_references_are_rejected(self) -> None:
        self.fixture.validation["questionnairePartitionBridge"][
            "proofSha256"
        ] = "0" * 64
        self.fixture.rewrite_validation_and_repoint_matrix()
        self.assertFalse(self.production_valid())

        self.fixture.reset()
        self.fixture.attempts["proofSha256"] = "0" * 64
        self.fixture.rewrite_attempts_and_repoint_dependents()
        self.assertFalse(self.production_valid())

    def test_evidence_path_traversal_is_rejected(self) -> None:
        self.fixture.wrapper["provenance"][
            "questionnairePartitionProofPath"
        ] = "../bridge_proof.json"
        self.fixture.write_matrix()
        self.assertFalse(self.production_valid())

    def test_valid_nested_witness_evidence_passes(self) -> None:
        self.fixture.enable_witness()

        self.assertTrue(self.production_valid())

    def test_missing_nested_witness_files_are_rejected(self) -> None:
        for missing in ("response", "proof"):
            with self.subTest(missing=missing):
                self.fixture.reset()
                self.fixture.enable_witness()
                path = (
                    self.fixture.witness_response_path
                    if missing == "response"
                    else self.fixture.witness_proof_path
                )
                path.unlink()
                self.assertFalse(self.production_valid())

    def test_witness_raw_provenance_is_recomputed_not_trusted(self) -> None:
        mutations = {
            "source": lambda provenance: provenance.__setitem__(
                "source", "https://example.invalid/graphql"
            ),
            "method": lambda provenance: provenance.__setitem__("method", "GET"),
            "operation": lambda provenance: provenance.__setitem__(
                "operation", "OtherOperation"
            ),
            "status": lambda provenance: provenance.__setitem__("status", 201),
            "content_type": lambda provenance: provenance.__setitem__(
                "contentType", "text/plain"
            ),
            "document_hash": lambda provenance: provenance.__setitem__(
                "documentSha256", "0" * 64
            ),
            "variables": lambda provenance: provenance["variables"].__setitem__(
                "query", "q1=2"
            ),
        }
        for case, mutate in mutations.items():
            with self.subTest(case=case):
                self.fixture.reset()
                self.fixture.enable_witness()
                assert self.fixture.witness_response is not None
                mutate(self.fixture.witness_response["provenance"])
                self.fixture.rewrite_witness_response_and_chain()
                self.assertFalse(self.production_valid())

    def test_witness_selection_target_control_and_parent_count_are_rejected(
        self,
    ) -> None:
        self.fixture.enable_witness()
        assert self.fixture.witness_proof is not None
        self.fixture.witness_proof["selection"]["name"] = "Alpha"
        self.fixture.rewrite_witness_proof_and_chain()
        self.assertFalse(self.production_valid())

        self.fixture.reset()
        self.fixture.enable_witness("Gamma\v")
        self.assertFalse(self.production_valid())

        self.fixture.reset()
        self.fixture.enable_witness()
        assert self.fixture.witness_proof is not None
        parent = self.fixture.witness_proof["parent"]
        parent["rankingVoteCountsByRank"][0] = 2
        parent["rankingVoteCountsByRankSha256"] = advanced.canonical_json_sha256(
            parent["rankingVoteCountsByRank"]
        )
        self.fixture.rewrite_witness_proof_and_chain()
        self.assertFalse(self.production_valid())

    def test_witness_conservation_frechet_and_tree_cells_are_recomputed(self) -> None:
        cases = ("conservation", "frechet", "tree_cells")
        for case in cases:
            with self.subTest(case=case):
                self.fixture.reset()
                self.fixture.enable_witness()
                assert self.fixture.witness_proof is not None
                node = self.fixture.proof["resolutionTree"]["children"][0]
                if case == "conservation":
                    self.fixture.witness_proof["complement"]["targetA"][
                        "voteCount"
                    ] = 1
                elif case == "frechet":
                    self.fixture.witness_proof["childFrechetProof"][
                        "intersectionUpperBound"
                    ] = 1
                else:
                    node["children"][0]["cells"] = {
                        "m00": 0,
                        "m01": 0,
                        "m10": 0,
                        "m11": 1,
                    }
                self.fixture.rewrite_witness_proof_and_chain()
                self.assertFalse(self.production_valid())

    def test_witness_tree_and_attempts_must_match_one_to_one(self) -> None:
        for case in ("query", "selection", "duplicate", "missing"):
            with self.subTest(case=case):
                self.fixture.reset()
                self.fixture.enable_witness()
                records = self.fixture.attempts["witnessFallbacks"]
                if case == "query":
                    records[0]["query"] = "q1=2"
                elif case == "selection":
                    records[0]["selection"] = {**records[0]["selection"], "rank": 2}
                elif case == "duplicate":
                    records.append(dict(records[0]))
                else:
                    records.clear()
                self.fixture.rewrite_top_proof_and_chain()
                self.assertFalse(self.production_valid())

    def test_witness_evidence_path_and_hash_are_rejected_inside_fresh_top_chain(
        self,
    ) -> None:
        for case in ("path", "hash"):
            with self.subTest(case=case):
                self.fixture.reset()
                self.fixture.enable_witness()
                evidence = self.fixture.proof["resolutionTree"]["children"][0][
                    "splitProof"
                ]["proofEvidence"]
                if case == "path":
                    evidence["path"] = "../witness_proof.json"
                else:
                    evidence["sha256"] = "0" * 64
                self.fixture.rewrite_top_proof_and_chain()
                self.assertFalse(self.production_valid())

    def test_real_cn11_matrix_when_available(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        base_path = (
            repository
            / "data_raw"
            / "cn_official"
            / "round_11"
            / "graphql"
            / "base.json"
        )
        matrix_path = (
            repository
            / "data_raw"
            / "cn_official"
            / "round_11"
            / "covote"
            / "music.json"
        )
        if not base_path.is_file() or not matrix_path.is_file():
            self.skipTest("CN11 reconstructed music.json is not available yet")
        base = json.loads(base_path.read_text(encoding="utf-8"))
        self.assertEqual(
            len(base["data"]["queryMusicRanking"]["entries"]), 612
        )
        assert PRODUCTION_VALIDATOR is not None
        self.assertTrue(
            PRODUCTION_VALIDATOR(
                matrix_path,
                base=base,
                workspace=repository,
                require_bridge=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
