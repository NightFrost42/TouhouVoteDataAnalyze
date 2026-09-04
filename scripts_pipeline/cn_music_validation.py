"""Strict validation for reconstructed CN music co-vote matrices.

The historical generic checkpoint validator only verifies row count and basic
cell types.  This module validates the stronger reconstruction contract without
depending on the crawler's control flow, so it can be reused by resume gates,
coverage reports, and offline audits.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
import unicodedata

try:  # Package import in tests and top-level import in crawler entry points.
    from . import crawl_cn_modern as core
except ImportError:  # pragma: no cover - exercised by script-style imports.
    import crawl_cn_modern as core  # type: ignore[no-redef]


GRAPHQL_KEY = "queryMusicsCovote"
RECONSTRUCTION_OPERATION = "MusicCovoteReciprocalMatrixReconstruction"
RECONSTRUCTION_METHOD = "official POST responses combined locally"
CELL_KEYS = ("m00", "m01", "m10", "m11")
WITNESS_STATS_OPERATION = "MusicCovotePartitionStats"
WITNESS_STATS_DOCUMENT = """
query MusicCovotePartitionStats(
  $query: String!
  $voteStart: DateTimeUtc!
  $voteYear: Int!
) {
  queryGlobalStats(query: $query, voteStart: $voteStart, voteYear: $voteYear) {
    voteYear
    numVote
    numMusic
  }
  queryMusicRanking(query: $query, voteStart: $voteStart, voteYear: $voteYear) {
    global { totalUniqueItems totalVotes }
    entries { rank displayRank name voteCount }
  }
}
"""


def _strict_nonnegative_int(value: Any) -> bool:
    """Accept JSON integers while rejecting bool, float, and numeric strings."""

    return type(value) is int and value >= 0


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_object(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"{path} does not contain a JSON object")
    return value


def _resolve_evidence_path(workspace: Path, relative_path: Any) -> Path:
    """Resolve one evidence path and forbid absolute paths or workspace escape."""

    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("evidence path must be a non-empty relative string")
    supplied = Path(relative_path)
    if supplied.is_absolute():
        raise ValueError("absolute evidence paths are not allowed")
    workspace_resolved = workspace.resolve()
    candidate = (workspace_resolved / supplied).resolve()
    try:
        candidate.relative_to(workspace_resolved)
    except ValueError as exc:
        raise ValueError("evidence path escapes the workspace") from exc
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _validated_evidence_file(
    workspace: Path, relative_path: Any, expected_sha256: Any
) -> tuple[Path, Mapping[str, Any]]:
    path = _resolve_evidence_path(workspace, relative_path)
    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(char not in "0123456789abcdef" for char in expected_sha256)
        or _sha256_file(path) != expected_sha256
    ):
        raise ValueError(f"evidence SHA-256 mismatch: {path}")
    return path, _load_json_object(path)


def _catalogue(
    base: Mapping[str, Any],
) -> tuple[int, int, list[str], dict[str, int]]:
    stats = base["data"]["queryGlobalStats"]
    entries = base["data"]["queryMusicRanking"]["entries"]
    if not isinstance(stats, Mapping) or not isinstance(entries, list):
        raise TypeError("base global stats/ranking structure is malformed")
    vote_year = stats.get("voteYear")
    universe = stats.get("numMusic")
    if not _strict_nonnegative_int(vote_year) or not _strict_nonnegative_int(
        universe
    ):
        raise ValueError("base voteYear/numMusic is not a strict non-negative integer")

    names: list[str] = []
    marginals: dict[str, int] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise TypeError("base music ranking contains a non-object row")
        name = entry.get("name")
        count = entry.get("voteCount")
        if (
            not isinstance(name, str)
            or not name
            or name in marginals
            or not _strict_nonnegative_int(count)
            or count > universe
        ):
            raise ValueError("base music catalogue has an invalid name or marginal")
        names.append(name)
        marginals[name] = count
    return vote_year, universe, names, marginals


def _same_reference(
    value: Mapping[str, Any],
    *,
    path_key: str,
    sha_key: str,
    expected_path: str,
    expected_sha: str,
) -> bool:
    return value.get(path_key) == expected_path and value.get(sha_key) == expected_sha


def _canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _evidence_identity(record: Any) -> tuple[str, str]:
    if not isinstance(record, Mapping):
        raise TypeError("witness evidence record is not an object")
    path = record.get("path")
    sha256 = record.get("sha256")
    if (
        not isinstance(path, str)
        or not path
        or not isinstance(sha256, str)
        or len(sha256) != 64
        or any(char not in "0123456789abcdef" for char in sha256)
    ):
        raise ValueError("witness evidence path/hash is malformed")
    return path, sha256


def _partition_values(partition: Any, label: str) -> dict[str, int]:
    if not isinstance(partition, Mapping):
        raise TypeError(f"{label} partition is not an object")
    target_a = partition.get("targetA")
    target_b = partition.get("targetB")
    if not isinstance(target_a, Mapping) or not isinstance(target_b, Mapping):
        raise TypeError(f"{label} target records are malformed")
    values = {
        "numVote": partition.get("numVote"),
        "numMusic": partition.get("numMusic"),
        "targetAVoteCount": target_a.get("voteCount"),
        "targetBVoteCount": target_b.get("voteCount"),
    }
    if not all(_strict_nonnegative_int(value) for value in values.values()):
        raise ValueError(f"{label} four-field values are malformed")
    if (
        values["numMusic"] > values["numVote"]
        or values["targetAVoteCount"] > values["numMusic"]
        or values["targetBVoteCount"] > values["numMusic"]
    ):
        raise ValueError(f"{label} four-field values violate cohort bounds")
    return values


def _derived_cells(partition: Mapping[str, Any], intersection: int) -> dict[str, int]:
    values = _partition_values(partition, "Frechet")
    cells = {
        "m00": intersection,
        "m01": values["targetBVoteCount"] - intersection,
        "m10": values["targetAVoteCount"] - intersection,
        "m11": (
            values["numMusic"]
            - values["targetAVoteCount"]
            - values["targetBVoteCount"]
            + intersection
        ),
    }
    if not _strict_nonnegative_int(intersection) or not all(
        _strict_nonnegative_int(value) for value in cells.values()
    ):
        raise ValueError("witness Frechet cells are not non-negative integers")
    return cells


def _validate_frechet_resolution(
    partition: Mapping[str, Any], proof: Any, cells: Any, label: str
) -> dict[str, int]:
    if not isinstance(proof, Mapping) or not isinstance(cells, Mapping):
        raise TypeError(f"{label} Frechet evidence is malformed")
    values = _partition_values(partition, label)
    lower = max(
        0,
        values["targetAVoteCount"]
        + values["targetBVoteCount"]
        - values["numMusic"],
    )
    upper = min(values["targetAVoteCount"], values["targetBVoteCount"])
    if lower != upper:
        raise ValueError(f"{label} Frechet bounds are not unique")
    expected_cells = _derived_cells(partition, lower)
    if dict(cells) != expected_cells:
        raise ValueError(f"{label} cells disagree with exact Frechet bounds")
    expected_proof_fields = {
        "universeNumMusic": values["numMusic"],
        "targetAVoteCount": values["targetAVoteCount"],
        "targetBVoteCount": values["targetBVoteCount"],
        "intersectionLowerBound": lower,
        "intersectionUpperBound": upper,
        "boundsAreEqual": True,
        "uniqueIntersection": lower,
        "allCellIdentitiesPassed": True,
    }
    if any(proof.get(key) != value for key, value in expected_proof_fields.items()):
        raise ValueError(f"{label} Frechet proof fields disagree with the partition")
    return expected_cells


def _target_ranking_record(
    entries: Sequence[Mapping[str, Any]], target_name: str
) -> dict[str, Any]:
    matches = [entry for entry in entries if entry.get("name") == target_name]
    if len(matches) > 1:
        raise ValueError("witness raw ranking duplicates a target")
    if not matches:
        return {"name": target_name, "voteCount": 0, "rank": None}
    entry = matches[0]
    return {
        "name": target_name,
        "voteCount": entry["voteCount"],
        "rank": entry["rank"],
    }


def _validate_raw_witness_child(
    raw: Mapping[str, Any],
    official_child: Mapping[str, Any],
    *,
    vote_year: int,
    vote_start: str,
    official_query: str,
    witness_name: str,
    target_a: str,
    target_b: str,
    response_identity: tuple[str, str],
) -> None:
    provenance = raw.get("provenance")
    if not isinstance(provenance, Mapping):
        raise TypeError("witness raw provenance is malformed")
    expected_variables = {
        "voteStart": vote_start,
        "voteYear": vote_year,
        "query": official_query,
    }
    if (
        provenance.get("source") != core.ENDPOINT
        or provenance.get("method") != "POST"
        or provenance.get("operation") != WITNESS_STATS_OPERATION
        or provenance.get("status") != 200
        or "json" not in str(provenance.get("contentType", "")).lower()
        or provenance.get("documentSha256")
        != hashlib.sha256(WITNESS_STATS_DOCUMENT.encode("utf-8")).hexdigest()
        or provenance.get("variables") != expected_variables
    ):
        raise ValueError("witness raw provenance/document/variables mismatch")

    data = raw.get("data")
    if not isinstance(data, Mapping):
        raise TypeError("witness raw data is malformed")
    stats = data.get("queryGlobalStats")
    ranking = data.get("queryMusicRanking")
    if not isinstance(stats, Mapping) or not isinstance(ranking, Mapping):
        raise TypeError("witness raw stats/ranking is malformed")
    num_vote = stats.get("numVote")
    num_music = stats.get("numMusic")
    if stats.get("voteYear") != vote_year or num_vote != 1 or num_music != 1:
        raise ValueError("witness raw response is not an exact unit cohort")
    entries = ranking.get("entries")
    ranking_global = ranking.get("global")
    if not isinstance(entries, list) or not isinstance(ranking_global, Mapping):
        raise TypeError("witness raw ranking structure is malformed")
    ordered: list[Mapping[str, Any]] = []
    names_seen: set[str] = set()
    ranks_seen: set[int] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise TypeError("witness raw ranking contains a non-object row")
        name = entry.get("name")
        rank = entry.get("rank")
        count = entry.get("voteCount")
        if (
            not isinstance(name, str)
            or not name
            or name in names_seen
            or not _strict_nonnegative_int(rank)
            or rank <= 0
            or rank in ranks_seen
            or not _strict_nonnegative_int(count)
            or count <= 0
        ):
            raise ValueError("witness raw ranking row is malformed")
        names_seen.add(name)
        ranks_seen.add(rank)
        ordered.append(entry)
    if ranks_seen != set(range(1, len(entries) + 1)):
        raise ValueError("witness raw ranking ranks are not contiguous")
    ordered.sort(key=lambda entry: entry["rank"])
    names = [entry["name"] for entry in ordered]
    counts = [entry["voteCount"] for entry in ordered]
    if (
        ranking_global.get("totalUniqueItems") != len(entries)
        or ranking_global.get("totalVotes") != 1
    ):
        raise ValueError("witness raw ranking global totals mismatch")
    if witness_name not in names or counts[names.index(witness_name)] != 1:
        raise ValueError("witness raw ranking does not contain the witness once")

    expected_child_fields = {
        "query": official_query,
        "numVote": 1,
        "numMusic": 1,
        "rankingEntryCount": len(entries),
        "rankingNamesByRank": names,
        "rankingNamesByRankSha256": _canonical_json_sha256(names),
        "rankingVoteCountsByRank": counts,
        "rankingVoteCountsByRankSha256": _canonical_json_sha256(counts),
        "targetA": _target_ranking_record(ordered, target_a),
        "targetB": _target_ranking_record(ordered, target_b),
    }
    if any(
        official_child.get(key) != value
        for key, value in expected_child_fields.items()
    ):
        raise ValueError("witness proof child disagrees with the raw official response")
    if _evidence_identity(official_child.get("statsEvidence")) != response_identity:
        raise ValueError("witness child statsEvidence disagrees with the raw response")


def _witness_query(parent_query: str, witness_name: str) -> str:
    if not parent_query or not witness_name:
        raise ValueError("witness query inputs are empty")
    return parent_query + " AND musics: " + json.dumps(
        [witness_name], ensure_ascii=False
    )


def _walk_witness_nodes(node: Any) -> list[Mapping[str, Any]]:
    if not isinstance(node, Mapping):
        raise TypeError("resolutionTree contains a non-object node")
    result = [node] if node.get("nodeType") == "witness_partition_split" else []
    children = node.get("children", [])
    if not isinstance(children, list):
        raise TypeError("resolutionTree children is not a list")
    for child in children:
        result.extend(_walk_witness_nodes(child))
    return result


def _validate_witness_node(
    node: Mapping[str, Any],
    *,
    workspace: Path,
    vote_year: int,
    vote_start: str,
    proof_target_pair: Mapping[str, Any],
) -> dict[str, Any]:
    split_proof = node.get("splitProof")
    if not isinstance(split_proof, Mapping):
        raise TypeError("witness tree splitProof is malformed")
    proof_identity = _evidence_identity(split_proof.get("proofEvidence"))
    response_identity = _evidence_identity(
        split_proof.get("officialChildResponseEvidence")
    )
    _, witness_proof = _validated_evidence_file(
        workspace, proof_identity[0], proof_identity[1]
    )
    _, raw_response = _validated_evidence_file(
        workspace, response_identity[0], response_identity[1]
    )
    witness_target_pair = witness_proof.get("targetPair")
    target_a = proof_target_pair.get("a")
    target_b = proof_target_pair.get("b")
    if (
        witness_proof.get("round") != vote_year
        or witness_proof.get("complete") is not True
        or not isinstance(witness_target_pair, Mapping)
        or witness_target_pair.get("a") != target_a
        or witness_target_pair.get("b") != target_b
    ):
        raise ValueError("witness proof round/completeness/target pair mismatch")

    parent = witness_proof.get("parent")
    official_child = witness_proof.get("officialChild")
    complement = witness_proof.get("complement")
    selection = witness_proof.get("selection")
    if not all(
        isinstance(value, Mapping)
        for value in (parent, official_child, complement, selection)
    ):
        raise TypeError("witness proof partitions/selection are malformed")
    if node.get("partition") != parent or split_proof.get("selection") != selection:
        raise ValueError("witness tree parent/selection disagrees with witness proof")
    witness_name = selection.get("name")
    parent_query = parent.get("query")
    if (
        not isinstance(target_a, str)
        or not isinstance(target_b, str)
        or not isinstance(witness_name, str)
        or not witness_name
        or witness_name in {target_a, target_b}
        or unicodedata.category(witness_name[-1]) == "Cc"
        or not isinstance(parent_query, str)
        or not parent_query
    ):
        raise ValueError(
            "witness selection is a target or has a trailing Unicode control"
        )
    expected_query = _witness_query(parent_query, witness_name)
    if (
        witness_proof.get("officialChildQuery") != expected_query
        or official_child.get("query") != expected_query
        or official_child.get("witnessFilter")
        != {"type": "music_any", "name": witness_name}
    ):
        raise ValueError("witness official child query/filter mismatch")

    parent_names = parent.get("rankingNamesByRank")
    parent_counts = parent.get("rankingVoteCountsByRank")
    if (
        not isinstance(parent_names, list)
        or not isinstance(parent_counts, list)
        or len(parent_names) != len(parent_counts)
        or parent.get("rankingEntryCount") != len(parent_names)
        or parent.get("rankingNamesByRankSha256")
        != _canonical_json_sha256(parent_names)
        or parent.get("rankingVoteCountsByRankSha256")
        != _canonical_json_sha256(parent_counts)
        or any(not isinstance(name, str) or not name for name in parent_names)
        or any(not _strict_nonnegative_int(count) for count in parent_counts)
        or len(parent_names) != len(set(parent_names))
    ):
        raise ValueError("witness parent ranking evidence is malformed")
    rank = selection.get("rank")
    if (
        not _strict_nonnegative_int(rank)
        or rank <= 0
        or rank > len(parent_names)
        or parent_names[rank - 1] != witness_name
        or parent_counts[rank - 1] != 1
        or selection.get("parentVoteCount") != 1
    ):
        raise ValueError("witness selection is not an exact parent voteCount=1 row")

    if (
        _evidence_identity(witness_proof.get("officialChildResponseEvidence"))
        != response_identity
    ):
        raise ValueError("witness response evidence references disagree")
    _validate_raw_witness_child(
        raw_response,
        official_child,
        vote_year=vote_year,
        vote_start=vote_start,
        official_query=expected_query,
        witness_name=witness_name,
        target_a=target_a,
        target_b=target_b,
        response_identity=response_identity,
    )
    child_names = official_child.get("rankingNamesByRank")
    child_counts = official_child.get("rankingVoteCountsByRank")
    if not isinstance(child_names, list) or not isinstance(child_counts, list):
        raise TypeError("witness child ranking evidence is malformed")
    parent_count_map = dict(zip(parent_names, parent_counts))
    if any(
        name not in parent_count_map or count > parent_count_map[name]
        for name, count in zip(child_names, child_counts)
    ):
        raise ValueError("witness child ranking is not a subset of its parent")

    if official_child.get("filters") != parent.get("filters") or complement.get(
        "filters"
    ) != parent.get("filters"):
        raise ValueError("witness child/complement filters differ from the parent")
    for partition, label in (
        (parent, "witness parent"),
        (official_child, "witness child"),
        (complement, "witness complement"),
    ):
        if partition["targetA"].get("name") != target_a or partition["targetB"].get(
            "name"
        ) != target_b:
            raise ValueError(f"{label} target names mismatch")
    parent_values = _partition_values(parent, "witness parent")
    child_values = _partition_values(official_child, "witness child")
    complement_values = _partition_values(complement, "witness complement")
    if parent_values["numMusic"] != 2 or (
        child_values["numMusic"], complement_values["numMusic"]
    ) != (1, 1):
        raise ValueError("witness split is not two exact unit music cohorts")
    observed_sums = {
        key: child_values[key] + complement_values[key] for key in parent_values
    }
    if observed_sums != parent_values:
        raise ValueError("witness child+complement four-field conservation failed")
    expected_conservation = {
        "observedSums": observed_sums,
        "expectedParentValues": parent_values,
        "passed": True,
    }
    if (
        witness_proof.get("conservationProof") != expected_conservation
        or split_proof.get("conservationProof") != expected_conservation
    ):
        raise ValueError("witness recorded conservation proof is inconsistent")

    children = node.get("children")
    if not isinstance(children, list) or len(children) != 2:
        raise ValueError("witness tree must have exactly two unit children")
    child_node, complement_node = children
    if not isinstance(child_node, Mapping) or not isinstance(complement_node, Mapping):
        raise TypeError("witness tree unit children are malformed")
    if (
        child_node.get("nodeType") != "locally_proven_frechet_leaf"
        or complement_node.get("nodeType") != "locally_proven_frechet_leaf"
        or child_node.get("partition") != official_child
        or complement_node.get("partition") != complement
    ):
        raise ValueError("witness tree child partitions disagree with witness proof")
    child_cells = _validate_frechet_resolution(
        official_child,
        witness_proof.get("childFrechetProof"),
        child_node.get("cells"),
        "witness child",
    )
    complement_cells = _validate_frechet_resolution(
        complement,
        witness_proof.get("complementFrechetProof"),
        complement_node.get("cells"),
        "witness complement",
    )
    if (
        child_node.get("localIntersectionProof")
        != witness_proof.get("childFrechetProof")
        or complement_node.get("localIntersectionProof")
        != witness_proof.get("complementFrechetProof")
    ):
        raise ValueError("witness tree Frechet proofs disagree with witness proof")
    aggregated_cells = {
        key: child_cells[key] + complement_cells[key] for key in CELL_KEYS
    }
    if (
        witness_proof.get("aggregatedCells") != aggregated_cells
        or node.get("cells") != aggregated_cells
        or _derived_cells(parent, aggregated_cells["m00"]) != aggregated_cells
    ):
        raise ValueError("witness aggregated cells disagree with parent identities")
    return {
        "parentQuery": parent_query,
        "query": expected_query,
        "selection": dict(selection),
        "responseIdentity": response_identity,
        "proofIdentity": proof_identity,
    }


def _validate_witness_evidence(
    proof: Mapping[str, Any],
    attempts: Mapping[str, Any],
    *,
    base: Mapping[str, Any],
    workspace: Path,
    vote_year: int,
) -> None:
    resolution_tree = proof.get("resolutionTree")
    witness_nodes = (
        [] if resolution_tree is None else _walk_witness_nodes(resolution_tree)
    )
    attempt_records = attempts.get("witnessFallbacks", [])
    if not isinstance(attempt_records, list):
        raise TypeError("attempts.witnessFallbacks is not a list")
    validated_attempts = [
        record
        for record in attempt_records
        if isinstance(record, Mapping) and record.get("status") == "validated"
    ]
    if not witness_nodes:
        if validated_attempts:
            raise ValueError(
                "validated witness attempts exist without witness tree nodes"
            )
        return

    target_pair = proof.get("targetPair")
    base_provenance = base.get("provenance")
    if not isinstance(target_pair, Mapping) or not isinstance(
        base_provenance, Mapping
    ):
        raise TypeError("witness validation lacks target pair/base provenance")
    base_variables = base_provenance.get("variables")
    if not isinstance(base_variables, Mapping) or not isinstance(
        base_variables.get("voteStart"), str
    ):
        raise ValueError("witness validation lacks an exact base voteStart")
    vote_start = base_variables["voteStart"]
    validated_nodes = [
        _validate_witness_node(
            node,
            workspace=workspace,
            vote_year=vote_year,
            vote_start=vote_start,
            proof_target_pair=target_pair,
        )
        for node in witness_nodes
    ]
    if len(validated_attempts) != len(validated_nodes):
        raise ValueError("witness tree/attempt validated entry counts differ")

    unmatched = list(validated_attempts)
    for node_record in validated_nodes:
        matches: list[Mapping[str, Any]] = []
        for attempt in unmatched:
            try:
                matches_node = (
                    attempt.get("parentQuery") == node_record["parentQuery"]
                    and attempt.get("selection") == node_record["selection"]
                    and _evidence_identity(
                        attempt.get("officialChildResponseEvidence")
                    )
                    == node_record["responseIdentity"]
                    and _evidence_identity(attempt.get("proofEvidence"))
                    == node_record["proofIdentity"]
                    and attempt.get("conservationPassed") is True
                    and attempt.get("bothFrechetIntersectionsUnique") is True
                    and (
                        "query" not in attempt
                        or attempt.get("query") == node_record["query"]
                    )
                )
            except (TypeError, ValueError):
                matches_node = False
            if matches_node:
                matches.append(attempt)
        if len(matches) != 1:
            raise ValueError("witness tree node has no unique matching attempts entry")
        unmatched.remove(matches[0])
    if unmatched:
        raise ValueError("validated witness attempts contain unmatched entries")


def _validate_evidence_chain(
    wrapper: Mapping[str, Any],
    *,
    base: Mapping[str, Any],
    workspace: Path,
    vote_year: int,
    universe: int,
    source_items: int,
    expected_pairs: int,
    require_bridge: bool,
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any]]:
    provenance = wrapper["provenance"]
    context = wrapper["context"]
    if not isinstance(provenance, Mapping) or not isinstance(context, Mapping):
        raise TypeError("matrix provenance/context is malformed")

    validation_path_text = context.get("validationPath")
    validation_sha = context.get("validationSha256")
    _, validation = _validated_evidence_file(
        workspace, validation_path_text, validation_sha
    )
    if (
        validation.get("round") != vote_year
        or validation.get("category") != "music"
        or validation.get("sourceItems") != source_items
        or validation.get("expectedPairs") != expected_pairs
        or validation.get("observedPairs") != expected_pairs
        or validation.get("universe") != universe
        or validation.get("allMarginalAndUniverseIdentitiesPassed") is not True
        or validation.get("allAvailableConditionalSymmetryChecksPassed") is not True
    ):
        raise ValueError("matrix validation summary disagrees with base/matrix scope")

    evidence_counts = validation.get("pairEvidenceCounts")
    if evidence_counts is not None:
        if not isinstance(evidence_counts, Mapping) or not all(
            _strict_nonnegative_int(value) for value in evidence_counts.values()
        ):
            raise ValueError("pairEvidenceCounts is malformed")
        if sum(evidence_counts.values()) != expected_pairs:
            raise ValueError("pairEvidenceCounts does not cover every matrix pair")

    proof_fields = (
        provenance.get("questionnairePartitionProofPath"),
        provenance.get("questionnairePartitionProofSha256"),
    )
    attempts_fields = (
        provenance.get("questionnairePartitionAttemptsPath"),
        provenance.get("questionnairePartitionAttemptsSha256"),
    )
    bridge = validation.get("questionnairePartitionBridge")
    if not require_bridge and all(
        value is None for value in (*proof_fields, *attempts_fields)
    ):
        if bridge is not None:
            raise ValueError("validation declares a bridge absent from provenance")
        return None, validation

    proof_path_text, proof_sha = proof_fields
    attempts_path_text, attempts_sha = attempts_fields
    _, proof = _validated_evidence_file(workspace, proof_path_text, proof_sha)
    _, attempts = _validated_evidence_file(
        workspace, attempts_path_text, attempts_sha
    )
    if (
        proof.get("complete") is not True
        or proof.get("round") != vote_year
        or proof.get("officialEndpoint") != core.ENDPOINT
        or attempts.get("complete") is not True
        or attempts.get("round") != vote_year
        or not _same_reference(
            attempts,
            path_key="proofPath",
            sha_key="proofSha256",
            expected_path=proof_path_text,
            expected_sha=proof_sha,
        )
    ):
        raise ValueError("proof/attempts evidence chain is incomplete or inconsistent")
    if not isinstance(bridge, Mapping) or not _same_reference(
        bridge,
        path_key="proofPath",
        sha_key="proofSha256",
        expected_path=proof_path_text,
        expected_sha=proof_sha,
    ) or not _same_reference(
        bridge,
        path_key="attemptsPath",
        sha_key="attemptsSha256",
        expected_path=attempts_path_text,
        expected_sha=attempts_sha,
    ):
        raise ValueError("validation bridge references disagree with provenance")
    pairs_used = bridge.get("pairsUsed")
    if pairs_used is not None and (
        not _strict_nonnegative_int(pairs_used) or pairs_used <= 0
    ):
        raise ValueError("bridge pairsUsed must be a positive strict integer")
    _validate_witness_evidence(
        proof,
        attempts,
        base=base,
        workspace=workspace,
        vote_year=vote_year,
    )
    return proof, validation


def _proof_target_pair(
    proof: Mapping[str, Any] | None,
    *,
    marginals: Mapping[str, int],
    universe: int,
) -> tuple[str, str, dict[str, int]] | None:
    if proof is None:
        return None
    pair = proof.get("targetPair")
    aggregate = proof.get("aggregatedTargetPair")
    if not isinstance(pair, Mapping) or not isinstance(aggregate, Mapping):
        raise ValueError("bridge proof has no target/aggregate pair")
    target_a = pair.get("a")
    target_b = pair.get("b")
    if (
        not isinstance(target_a, str)
        or not isinstance(target_b, str)
        or target_a == target_b
        or target_a not in marginals
        or target_b not in marginals
        or aggregate.get("a") != target_a
        or aggregate.get("b") != target_b
    ):
        raise ValueError("bridge proof target pair is not in the exact catalogue")
    cells = {key: aggregate.get(key) for key in CELL_KEYS}
    if not all(_strict_nonnegative_int(value) for value in cells.values()) or (
        sum(cells.values()) != universe
        or cells["m00"] + cells["m10"] != marginals[target_a]
        or cells["m00"] + cells["m01"] != marginals[target_b]
    ):
        raise ValueError("bridge proof target cells violate base identities")
    for key, expected in (
        ("aBaseVoteCount", marginals[target_a]),
        ("bBaseVoteCount", marginals[target_b]),
    ):
        if key in pair and pair[key] != expected:
            raise ValueError("bridge proof target marginal disagrees with base")
    return target_a, target_b, cells


def _triangular_pair_index(item_count: int, left: int, right: int) -> int:
    """Return a dense index for one pair where ``0 <= left < right < n``."""

    return left * (2 * item_count - left - 1) // 2 + (right - left - 1)


def _validate_items(
    items: Sequence[Any],
    *,
    names: Sequence[str],
    marginals: Mapping[str, int],
    universe: int,
    proof_target: tuple[str, str, dict[str, int]] | None,
) -> None:
    source_items = len(names)
    expected_pairs = source_items * (source_items - 1) // 2
    if len(items) != expected_pairs:
        raise ValueError("matrix row count does not equal the full pair universe")
    name_indexes = {name: index for index, name in enumerate(names)}
    observed = bytearray(expected_pairs)
    observed_count = 0
    observed_proof_cells: dict[str, int] | None = None

    for item in items:
        if not isinstance(item, Mapping):
            raise TypeError("matrix contains a non-object row")
        a = item.get("a")
        b = item.get("b")
        if (
            not isinstance(a, str)
            or not isinstance(b, str)
            or a == b
            or a not in name_indexes
            or b not in name_indexes
        ):
            raise ValueError("matrix row has an unknown or diagonal endpoint")
        index_a = name_indexes[a]
        index_b = name_indexes[b]
        left, right = sorted((index_a, index_b))
        pair_index = _triangular_pair_index(source_items, left, right)
        if observed[pair_index]:
            raise ValueError("matrix contains a duplicate or reverse-duplicate pair")
        observed[pair_index] = 1
        observed_count += 1

        cells = {key: item.get(key) for key in CELL_KEYS}
        if not all(_strict_nonnegative_int(value) for value in cells.values()) or (
            sum(cells.values()) != universe
            or cells["m00"] + cells["m10"] != marginals[a]
            or cells["m00"] + cells["m01"] != marginals[b]
        ):
            raise ValueError("matrix row violates a marginal or universe identity")

        if proof_target is not None and {a, b} == {
            proof_target[0],
            proof_target[1],
        }:
            observed_proof_cells = dict(cells)
            if a != proof_target[0]:
                observed_proof_cells["m01"], observed_proof_cells["m10"] = (
                    observed_proof_cells["m10"],
                    observed_proof_cells["m01"],
                )

    # With endpoints restricted to an N-item catalogue, N choose 2 unique rows
    # are necessarily the exact complete unordered-pair universe.
    if observed_count != expected_pairs or (
        expected_pairs and 0 in observed
    ):
        raise ValueError("matrix does not cover the exact unordered-pair universe")
    if proof_target is not None and observed_proof_cells != proof_target[2]:
        raise ValueError("matrix bridge pair disagrees with the hashed proof")


def reconstructed_music_matrix_checkpoint_valid(
    path: Path,
    *,
    base: Mapping[str, Any],
    workspace: Path,
    require_bridge: bool = True,
) -> bool:
    """Return whether a reconstructed music matrix satisfies the strict contract.

    Required base fields are only ``queryGlobalStats.voteYear/numMusic`` and
    ``queryMusicRanking.entries[].name/voteCount``.  Names are compared exactly;
    trailing controls in official catalogue values are never normalized.
    """

    try:
        path = Path(path)
        workspace = Path(workspace)
        wrapper = _load_json_object(path)
        vote_year, universe, names, marginals = _catalogue(base)
        source_items = len(names)
        expected_pairs = source_items * (source_items - 1) // 2
        provenance = wrapper["provenance"]
        context = wrapper["context"]
        if not isinstance(provenance, Mapping) or not isinstance(context, Mapping):
            return False
        if (
            provenance.get("source") != core.ENDPOINT
            or provenance.get("method") != RECONSTRUCTION_METHOD
            or provenance.get("operation") != RECONSTRUCTION_OPERATION
            or not _strict_nonnegative_int(
                provenance.get("sourceCheckpointCount")
            )
            or context.get("topK") != source_items
            or context.get("expectedPairCount") != expected_pairs
        ):
            return False
        proof, _ = _validate_evidence_chain(
            wrapper,
            base=base,
            workspace=workspace,
            vote_year=vote_year,
            universe=universe,
            source_items=source_items,
            expected_pairs=expected_pairs,
            require_bridge=require_bridge,
        )
        proof_target = _proof_target_pair(
            proof, marginals=marginals, universe=universe
        )
        items = wrapper["data"][GRAPHQL_KEY]["items"]
        if not isinstance(items, list):
            return False
        _validate_items(
            items,
            names=names,
            marginals=marginals,
            universe=universe,
            proof_target=proof_target,
        )
        return True
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return False


__all__ = ["reconstructed_music_matrix_checkpoint_valid"]
