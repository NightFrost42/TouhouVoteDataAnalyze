"""Deterministic standard community detection for vote co-vote networks.

This module is deliberately separate from :mod:`vote_explorer.analysis_engine`'s
thresholded single-link concentration clusters.  It builds an observed weighted
network, runs a dependency-free Louvain implementation, and writes auditable
community/centrality tables plus a model-run manifest.

The module never reads the original-setting faction crosswalk.  Community
labels are structural analysis outputs and must not be interpreted as official
factions, CP labels, or replacement metadata.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import json
import math
import random
import re
import sys
import time
import tracemalloc
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

try:
    from vote_explorer.data_chunks import iter_csv_rows, part_paths
except ImportError:  # pragma: no cover - direct execution from another cwd
    _ROOT_FOR_IMPORT = Path(__file__).resolve().parents[1]
    if str(_ROOT_FOR_IMPORT) not in sys.path:
        sys.path.insert(0, str(_ROOT_FOR_IMPORT))
    from vote_explorer.data_chunks import iter_csv_rows, part_paths

try:
    from .model_run_manifest import write_model_run_manifest
except ImportError:  # pragma: no cover - direct CLI execution
    from model_run_manifest import write_model_run_manifest


SOFTWARE_VERSION = "1.0.0"
DEFAULT_RANDOM_SEED = 20260801
DEFAULT_ROUND = "CN11"
DEFAULT_WEIGHT_METRIC = "intersection_count"
DEFAULT_THRESHOLD = 100.0
DEFAULT_RESOLUTION = 1.0
SUPPORTED_WEIGHT_METRICS = frozenset({
    "intersection_count", "raw_count", "conditional_rate", "conditional_rate_a_to_b",
    "conditional_rate_b_to_a", "direction_a_to_b", "direction_b_to_a", "share", "lift",
    "lift_a_to_b", "lift_b_to_a", "excess_count", "cosine", "cosine_ochiai", "ochiai",
    "jaccard", "pmi", "pmi_nats", "npmi", "phi",
})

ASSIGNMENT_FIELDS = [
    "round_label", "scope", "node_type", "canonical_name", "name_cn", "name_jp",
    "community_id", "community_rank", "community_size",
    "connected_component_id", "connected_component_size",
    "weighted_degree", "unweighted_degree", "pagerank", "betweenness", "k_core",
    "bridge_score", "algorithm", "weight_metric", "threshold",
    "min_intersection_count", "resolution", "random_seed", "software_version",
    "official_faction_source", "official_faction_note",
]
SUMMARY_FIELDS = [
    "round_label", "scope", "community_id", "community_rank", "node_count",
    "edge_count", "internal_weight", "total_weighted_degree",
    "modularity_contribution", "algorithm", "weight_metric", "threshold",
    "min_intersection_count", "resolution", "random_seed", "software_version",
    "official_faction_source", "official_faction_note",
]
CENTRALITY_FIELDS = [
    "round_label", "scope", "node_type", "canonical_name", "name_cn", "name_jp",
    "weighted_degree", "unweighted_degree", "pagerank", "betweenness", "k_core",
    "bridge_score", "community_id", "connected_component_id", "algorithm",
    "weight_metric", "threshold", "min_intersection_count", "resolution",
    "random_seed", "software_version", "official_faction_source",
    "official_faction_note",
]
MODULARITY_FIELDS = [
    "round_label", "scope", "algorithm", "weight_metric", "threshold",
    "min_intersection_count", "resolution", "random_seed", "node_count",
    "edge_count", "connected_component_count", "community_count", "modularity",
    "degree_assortativity", "nmi_vs_connected_components", "runtime_seconds",
    "load_seconds", "algorithm_seconds", "peak_memory_bytes", "benchmark_status",
    "software_version", "official_faction_source", "official_faction_note",
]

OFFICIAL_FACTION_SOURCE = "not_used"
OFFICIAL_FACTION_NOTE = (
    "community labels are structural network results; they are not official "
    "factions and do not replace original-setting faction metadata"
)


class CommunityAnalysisError(ValueError):
    """Raised for invalid graph data or unsupported analysis settings."""


def normalize_round_label(value: object, default: str = DEFAULT_ROUND) -> str:
    text = str(value or "").strip().upper()
    if re.fullmatch(r"(?:CN|JP)\d+", text):
        return text
    if re.fullmatch(r"\d+", text):
        return f"JP{text}"
    return default


def normalize_name(value: object) -> str:
    return re.sub(r"[\s・･·\-—_]+", "", str(value or "")).casefold()


def _text(value: object) -> str:
    return str(value or "").strip()


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    elif not str(value).strip():
        return None
    else:
        try:
            result = float(str(value).strip())
        except (TypeError, ValueError):
            return None
    return result if math.isfinite(result) else None


def _positive_number(value: object) -> float | None:
    result = _number(value)
    return result if result is not None and result > 0 else None


def _json_number(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return float(value)


def _stable_digest(values: Iterable[str], prefix: str, namespace: str = "") -> str:
    payload = json.dumps(
        [namespace, sorted(set(values))], ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()[:16]}"


def _stable_node_sort(value: str) -> tuple[str, str]:
    return (str(value), str(value).casefold())


class WeightedGraph:
    """A small undirected positive-weight graph with explicit self-loops.

    Original vote networks have no self-loops.  Aggregated Louvain graphs do,
    so they are retained separately and contribute twice to node degree, as an
    undirected weighted graph convention requires.
    """

    def __init__(self, nodes: Iterable[str] = ()) -> None:
        self.adj: dict[str, dict[str, float]] = {}
        self.loops: dict[str, float] = {}
        for node in nodes:
            self.add_node(node)

    def add_node(self, node: str) -> None:
        self.adj.setdefault(str(node), {})

    def add_edge(self, source: str, target: str, weight: float) -> None:
        source, target = str(source), str(target)
        weight = _positive_number(weight)
        if weight is None:
            raise CommunityAnalysisError(f"edge weight must be finite and positive: {weight!r}")
        self.add_node(source)
        self.add_node(target)
        if source == target:
            self.loops[source] = self.loops.get(source, 0.0) + weight
            return
        self.adj[source][target] = self.adj[source].get(target, 0.0) + weight
        self.adj[target][source] = self.adj[target].get(source, 0.0) + weight

    def nodes(self) -> list[str]:
        return sorted(self.adj, key=_stable_node_sort)

    def neighbors(self, node: str) -> Mapping[str, float]:
        return self.adj.get(node, {})

    def degree(self, node: str) -> float:
        return sum(self.adj.get(node, {}).values()) + 2.0 * self.loops.get(node, 0.0)

    def weighted_degree(self, node: str) -> float:
        return self.degree(node)

    def unweighted_degree(self, node: str) -> int:
        return len(self.adj.get(node, {}))

    def edge_items(self, include_loops: bool = True) -> Iterator[tuple[str, str, float]]:
        seen: set[tuple[str, str]] = set()
        for source in self.nodes():
            for target, weight in sorted(self.adj[source].items(), key=lambda item: _stable_node_sort(item[0])):
                key = tuple(sorted((source, target), key=_stable_node_sort))
                if key in seen:
                    continue
                seen.add(key)
                yield key[0], key[1], weight
        if include_loops:
            for node in sorted(self.loops, key=_stable_node_sort):
                yield node, node, self.loops[node]

    def edge_count(self) -> int:
        return sum(1 for _ in self.edge_items(include_loops=True))

    def total_edge_weight(self) -> float:
        return sum(weight for _, _, weight in self.edge_items(include_loops=True))

    def copy(self) -> "WeightedGraph":
        result = WeightedGraph(self.nodes())
        for source, target, weight in self.edge_items(include_loops=True):
            result.add_edge(source, target, weight)
        return result


@dataclass
class NodeMetadata:
    node_id: str
    node_type: str
    canonical_name: str
    name_cn: str = ""
    name_jp: str = ""


@dataclass
class PreparedNetwork:
    graph: WeightedGraph
    metadata: dict[str, NodeMetadata]
    source_paths: list[Path] = field(default_factory=list)
    input_rows: int = 0
    included_pairs: int = 0
    excluded_pairs: int = 0
    duplicate_pairs: int = 0
    invalid_pairs: int = 0
    excluded_reasons: Counter[str] = field(default_factory=Counter)
    notes: list[str] = field(default_factory=list)


def _remember_metadata(
    metadata: dict[str, NodeMetadata],
    node_id: str,
    node_type: str,
    canonical_name: str,
    name_cn: object = "",
    name_jp: object = "",
) -> None:
    if not node_id:
        return
    candidate = NodeMetadata(
        node_id=node_id,
        node_type=node_type,
        canonical_name=canonical_name or node_id,
        name_cn=_text(name_cn),
        name_jp=_text(name_jp),
    )
    previous = metadata.get(node_id)
    if previous is None:
        metadata[node_id] = candidate
        return
    # Prefer non-empty translated names without replacing a stable canonical ID.
    if not previous.name_cn and candidate.name_cn:
        previous.name_cn = candidate.name_cn
    if not previous.name_jp and candidate.name_jp:
        previous.name_jp = candidate.name_jp


def _row_round(row: Mapping[str, object]) -> str:
    return normalize_round_label(row.get("round_label") or row.get("round"), default="")


def _passes_data_policy(row: Mapping[str, object], policy: str) -> bool:
    completeness = _text(row.get("data_completeness"))
    category = _text(row.get("pair_category"))
    if policy == "observed":
        return True
    if policy == "complete_matrix":
        return completeness == "complete_matrix" or row.get("complete_pair_matrix") in {True, "True", "true", 1, "1"}
    if policy == "published_leading_list":
        return completeness == "official_published_leading_list"
    if policy == "cross_department_conditional_only":
        # Cross-department source rows do not carry pair_category in older
        # bundles; the absence of an internal category is intentional here.
        return not category or category == "cross_department"
    raise CommunityAnalysisError(f"unsupported data policy: {policy}")


def _edge_weight(row: Mapping[str, object], metric: str) -> float | None:
    value = _positive_number(row.get(metric))
    if value is not None:
        return value
    # A missing explicit field is never silently replaced by another metric.
    return None


def _meets_min_count(row: Mapping[str, object], minimum: float) -> bool:
    if minimum <= 0:
        return True
    count = _number(row.get("intersection_count"))
    return count is not None and count >= minimum


def _canonical_internal(row: Mapping[str, object], side: str) -> str:
    value = _text(row.get(f"canonical_{side}"))
    if value:
        return value
    return normalize_name(row.get(f"name_{side}") or row.get(f"name_{side}_cn") or row.get(f"name_{side}_jp"))


def _canonical_cross(row: Mapping[str, object], side: str) -> str:
    value = _text(row.get(f"{side}_canonical"))
    if value:
        return value
    return normalize_name(row.get(f"{side}_name_cn") or row.get(f"{side}_name_jp"))


def _add_filtered_edge(
    network: PreparedNetwork,
    seen: set[tuple[str, str]],
    source: str,
    target: str,
    row: Mapping[str, object],
    *,
    weight_metric: str,
    threshold: float,
    min_intersection_count: float,
    data_policy: str,
) -> None:
    network.input_rows += 1
    if source == target or not source or not target:
        network.excluded_pairs += 1
        network.excluded_reasons["self_or_missing_node"] += 1
        return
    if not _passes_data_policy(row, data_policy):
        network.excluded_pairs += 1
        network.excluded_reasons["data_policy"] += 1
        return
    if not _meets_min_count(row, min_intersection_count):
        network.excluded_pairs += 1
        network.excluded_reasons["minimum_intersection_count"] += 1
        return
    weight = _edge_weight(row, weight_metric)
    if weight is None:
        network.excluded_pairs += 1
        network.invalid_pairs += 1
        network.excluded_reasons["missing_or_invalid_weight"] += 1
        return
    if weight < threshold:
        network.excluded_pairs += 1
        network.excluded_reasons["threshold"] += 1
        return
    key = tuple(sorted((source, target), key=_stable_node_sort))
    if key in seen:
        network.duplicate_pairs += 1
        network.excluded_pairs += 1
        network.excluded_reasons["duplicate_unordered_pair"] += 1
        return
    seen.add(key)
    network.graph.add_edge(source, target, weight)
    network.included_pairs += 1


def build_internal_network(
    node_rows: Iterable[Mapping[str, object]],
    pair_rows: Iterable[Mapping[str, object]],
    *,
    round_label: str,
    scope: str,
    weight_metric: str = DEFAULT_WEIGHT_METRIC,
    threshold: float = DEFAULT_THRESHOLD,
    min_intersection_count: float = 0.0,
    data_policy: str = "observed",
) -> PreparedNetwork:
    """Build a character-only or music-only network from already-read rows."""
    if scope not in {"character", "music"}:
        raise CommunityAnalysisError(f"internal scope must be character or music: {scope}")
    if data_policy not in {"observed", "complete_matrix", "published_leading_list"}:
        raise CommunityAnalysisError(f"unsupported internal data policy: {data_policy}")
    graph = WeightedGraph()
    metadata: dict[str, NodeMetadata] = {}
    result = PreparedNetwork(graph=graph, metadata=metadata)
    target_round = normalize_round_label(round_label, default="")
    for row in node_rows:
        if _row_round(row) != target_round or _text(row.get("category")) != scope:
            continue
        canonical = _text(row.get("canonical_name")) or normalize_name(row.get("name_cn") or row.get("name_jp"))
        if not canonical:
            continue
        graph.add_node(canonical)
        _remember_metadata(metadata, canonical, scope, canonical, row.get("name_cn"), row.get("name_jp"))
    seen: set[tuple[str, str]] = set()
    for row in pair_rows:
        if _row_round(row) != target_round or _text(row.get("pair_category")) != scope:
            continue
        source = _canonical_internal(row, "a")
        target = _canonical_internal(row, "b")
        if not source or not target:
            result.input_rows += 1
            result.excluded_pairs += 1
            result.excluded_reasons["self_or_missing_node"] += 1
            continue
        _remember_metadata(metadata, source, scope, source, row.get("name_a_cn"), row.get("name_a"))
        _remember_metadata(metadata, target, scope, target, row.get("name_b_cn"), row.get("name_b"))
        graph.add_node(source)
        graph.add_node(target)
        _add_filtered_edge(
            result, seen, source, target, row, weight_metric=weight_metric,
            threshold=threshold, min_intersection_count=min_intersection_count,
            data_policy=data_policy,
        )
    return result


def build_cross_department_network(
    character_rows: Iterable[Mapping[str, object]],
    music_rows: Iterable[Mapping[str, object]],
    cross_rows: Iterable[Mapping[str, object]],
    *,
    round_label: str,
    weight_metric: str = DEFAULT_WEIGHT_METRIC,
    threshold: float = DEFAULT_THRESHOLD,
    min_intersection_count: float = 0.0,
    data_policy: str = "observed",
) -> PreparedNetwork:
    """Build a bipartite character×music network from official cross rows."""
    if data_policy not in {"observed", "cross_department_conditional_only"}:
        raise CommunityAnalysisError(f"unsupported cross-department data policy: {data_policy}")
    graph = WeightedGraph()
    metadata: dict[str, NodeMetadata] = {}
    result = PreparedNetwork(graph=graph, metadata=metadata)
    target_round = normalize_round_label(round_label, default="")
    for row in character_rows:
        if _row_round(row) != target_round or _text(row.get("category")) != "character":
            continue
        canonical = _text(row.get("canonical_name")) or normalize_name(row.get("name_cn") or row.get("name_jp"))
        node_id = f"character:{canonical}" if canonical else ""
        if not node_id:
            continue
        graph.add_node(node_id)
        _remember_metadata(metadata, node_id, "character", canonical, row.get("name_cn"), row.get("name_jp"))
    for row in music_rows:
        if _row_round(row) != target_round or _text(row.get("category")) != "music":
            continue
        canonical = _text(row.get("canonical_name")) or normalize_name(row.get("name_cn") or row.get("name_jp"))
        node_id = f"music:{canonical}" if canonical else ""
        if not node_id:
            continue
        graph.add_node(node_id)
        _remember_metadata(metadata, node_id, "music", canonical, row.get("name_cn"), row.get("name_jp"))
    seen: set[tuple[str, str]] = set()
    for row in cross_rows:
        if _row_round(row) != target_round:
            continue
        character = _canonical_cross(row, "character")
        music = _canonical_cross(row, "music")
        if not character or not music:
            result.input_rows += 1
            result.excluded_pairs += 1
            result.excluded_reasons["self_or_missing_node"] += 1
            continue
        source, target = f"character:{character}", f"music:{music}"
        _remember_metadata(metadata, source, "character", character, row.get("character_name_cn"), row.get("character_name_jp"))
        _remember_metadata(metadata, target, "music", music, row.get("music_name_cn"), row.get("music_name_jp"))
        graph.add_node(source)
        graph.add_node(target)
        _add_filtered_edge(
            result, seen, source, target, row, weight_metric=weight_metric,
            threshold=threshold, min_intersection_count=min_intersection_count,
            data_policy=data_policy,
        )
    return result


def connected_components(graph: WeightedGraph) -> list[set[str]]:
    """Return undirected connected components, including isolated nodes."""
    unseen = set(graph.nodes())
    components: list[set[str]] = []
    while unseen:
        start = min(unseen, key=_stable_node_sort)
        unseen.remove(start)
        component = {start}
        stack = [start]
        while stack:
            current = stack.pop()
            for neighbor in graph.neighbors(current):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    component.add(neighbor)
                    stack.append(neighbor)
        components.append(component)
    return sorted(components, key=lambda group: (-len(group), tuple(sorted(group, key=_stable_node_sort))))


def _community_modularity_gain(
    node_degree: float,
    candidate_weight: float,
    candidate_total_degree: float,
    *,
    resolution: float,
    two_m: float,
) -> float:
    return candidate_weight - resolution * candidate_total_degree * node_degree / two_m


def _louvain_local_move(
    graph: WeightedGraph,
    *,
    resolution: float,
    random_seed: int,
    max_passes: int,
) -> tuple[dict[str, int], bool]:
    nodes = graph.nodes()
    community = {node: index for index, node in enumerate(nodes)}
    totals = {community[node]: graph.degree(node) for node in nodes}
    total_weight = graph.total_edge_weight()
    two_m = 2.0 * total_weight
    if not nodes or two_m <= 0:
        return community, False
    rng = random.Random(random_seed)
    moved_any = False
    for _ in range(max(1, max_passes)):
        order = list(nodes)
        rng.shuffle(order)
        moved_this_pass = False
        for node in order:
            old = community[node]
            degree = graph.degree(node)
            totals[old] -= degree
            neighbor_weights: dict[int, float] = defaultdict(float)
            for neighbor, weight in graph.neighbors(node).items():
                neighbor_weights[community[neighbor]] += weight
            # Self-loops are internal in every candidate and therefore cancel
            # from the local-move comparison.  Original vote graphs have none;
            # they only appear after Louvain aggregation.
            old_gain = _community_modularity_gain(
                degree, neighbor_weights.get(old, 0.0), totals[old],
                resolution=resolution, two_m=two_m,
            )
            best, best_gain = old, old_gain
            candidates = sorted((candidate for candidate in neighbor_weights if candidate != old))
            rng.shuffle(candidates)
            for candidate in candidates:
                gain = _community_modularity_gain(
                    degree, neighbor_weights[candidate], totals.get(candidate, 0.0),
                    resolution=resolution, two_m=two_m,
                )
                if gain > best_gain + 1e-12:
                    best, best_gain = candidate, gain
            community[node] = best
            totals[best] = totals.get(best, 0.0) + degree
            if best != old:
                moved_this_pass = True
                moved_any = True
        if not moved_this_pass:
            break
    return community, moved_any


def _aggregate_graph(
    graph: WeightedGraph,
    partition: Mapping[str, int],
    active_members: Mapping[str, tuple[str, ...]],
) -> tuple[WeightedGraph, dict[str, tuple[str, ...]]]:
    groups: dict[int, list[str]] = defaultdict(list)
    for node in graph.nodes():
        groups[partition[node]].append(node)
    ordered_groups = sorted(
        groups.values(),
        key=lambda members: tuple(sorted(members, key=_stable_node_sort)),
    )
    node_to_new: dict[str, str] = {}
    new_members: dict[str, tuple[str, ...]] = {}
    for index, members in enumerate(ordered_groups):
        new_node = f"__community_{index}"
        node_to_new.update({node: new_node for node in members})
        original_members: list[str] = []
        for node in members:
            original_members.extend(active_members[node])
        new_members[new_node] = tuple(sorted(original_members, key=_stable_node_sort))
    aggregated = WeightedGraph(new_members)
    for source, target, weight in graph.edge_items(include_loops=True):
        aggregated.add_edge(node_to_new[source], node_to_new[target], weight)
    return aggregated, new_members


def louvain_partition(
    graph: WeightedGraph,
    *,
    resolution: float = DEFAULT_RESOLUTION,
    random_seed: int = DEFAULT_RANDOM_SEED,
    max_levels: int = 100,
    max_passes: int = 100,
) -> list[set[str]]:
    """Run deterministic weighted Louvain and return original-node communities.

    The implementation uses the standard modularity local-move gain and graph
    aggregation phases.  Node traversal and candidate tie order are seeded;
    stable member-based IDs are generated later, so output labels do not depend
    on Python dictionary insertion order.
    """
    if resolution <= 0 or not math.isfinite(resolution):
        raise CommunityAnalysisError("resolution must be finite and positive")
    if max_levels <= 0 or max_passes <= 0:
        raise CommunityAnalysisError("max_levels and max_passes must be positive")
    current = graph.copy()
    active_members = {node: (node,) for node in current.nodes()}
    for level in range(max_levels):
        partition, moved = _louvain_local_move(
            current, resolution=resolution, random_seed=random_seed + level,
            max_passes=max_passes,
        )
        groups: dict[int, set[str]] = defaultdict(set)
        for node, label in partition.items():
            groups[label].update(active_members[node])
        if not moved or len(groups) == len(current.nodes()):
            return sorted(groups.values(), key=lambda group: (-len(group), tuple(sorted(group, key=_stable_node_sort))))
        current, active_members = _aggregate_graph(current, partition, active_members)
    # A max-level limit is a safety valve for pathological inputs.  The latest
    # partition is still a valid Louvain phase and is returned explicitly.
    partition, _ = _louvain_local_move(
        current, resolution=resolution, random_seed=random_seed + max_levels,
        max_passes=max_passes,
    )
    groups = defaultdict(set)
    for node, label in partition.items():
        groups[label].update(active_members[node])
    return sorted(groups.values(), key=lambda group: (-len(group), tuple(sorted(group, key=_stable_node_sort))))


def partition_map(partition: Sequence[set[str]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for index, group in enumerate(partition):
        for node in group:
            result[node] = index
    return result


def weighted_modularity(
    graph: WeightedGraph,
    partition: Sequence[set[str]],
    *,
    resolution: float = DEFAULT_RESOLUTION,
) -> tuple[float | None, dict[int, float]]:
    """Return weighted modularity and each community's additive contribution."""
    total_weight = graph.total_edge_weight()
    if total_weight <= 0:
        return 0.0, {index: 0.0 for index in range(len(partition))}
    node_to_group = partition_map(partition)
    internal: dict[int, float] = defaultdict(float)
    total_degree: dict[int, float] = defaultdict(float)
    for node in graph.nodes():
        total_degree[node_to_group[node]] += graph.degree(node)
    for source, target, weight in graph.edge_items(include_loops=True):
        if node_to_group[source] == node_to_group[target]:
            internal[node_to_group[source]] += weight
    contributions: dict[int, float] = {}
    for index in range(len(partition)):
        contributions[index] = (
            internal.get(index, 0.0) / total_weight
            - resolution * (total_degree.get(index, 0.0) / (2.0 * total_weight)) ** 2
        )
    return sum(contributions.values()), contributions


def degree_assortativity(graph: WeightedGraph) -> float | None:
    """Weighted Pearson correlation of endpoint degrees.

    Each undirected edge contributes two oriented endpoint observations, with
    the edge weight as its observation weight.  Self-loops are excluded because
    they are only introduced internally by graph aggregation and are not
    observed vote relationships.
    """
    observations: list[tuple[float, float, float]] = []
    for source, target, weight in graph.edge_items(include_loops=False):
        observations.append((graph.degree(source), graph.degree(target), weight))
        observations.append((graph.degree(target), graph.degree(source), weight))
    total = sum(weight for _, _, weight in observations)
    if total <= 0 or len(observations) < 2:
        return None
    mean_x = sum(x * weight for x, _, weight in observations) / total
    mean_y = sum(y * weight for _, y, weight in observations) / total
    covariance = sum(weight * (x - mean_x) * (y - mean_y) for x, y, weight in observations) / total
    variance_x = sum(weight * (x - mean_x) ** 2 for x, _, weight in observations) / total
    variance_y = sum(weight * (y - mean_y) ** 2 for _, y, weight in observations) / total
    if variance_x <= 0 or variance_y <= 0:
        return None
    return covariance / math.sqrt(variance_x * variance_y)


def pagerank(graph: WeightedGraph, *, alpha: float = 0.85, max_iter: int = 200, tolerance: float = 1e-12) -> dict[str, float]:
    """Compute weighted undirected PageRank, including isolates."""
    nodes = graph.nodes()
    if not nodes:
        return {}
    n = len(nodes)
    score = {node: 1.0 / n for node in nodes}
    out_weight = {
        node: sum(graph.neighbors(node).values()) + graph.loops.get(node, 0.0)
        for node in nodes
    }
    for _ in range(max_iter):
        dangling = sum(score[node] for node in nodes if out_weight[node] <= 0)
        next_score = {node: (1.0 - alpha) / n + alpha * dangling / n for node in nodes}
        for source in nodes:
            if out_weight[source] <= 0:
                continue
            share = alpha * score[source] / out_weight[source]
            for target, weight in graph.neighbors(source).items():
                next_score[target] += share * weight
            if source in graph.loops:
                next_score[source] += share * graph.loops[source]
        delta = sum(abs(next_score[node] - score[node]) for node in nodes)
        score = next_score
        if delta <= tolerance:
            break
    normalizer = sum(score.values())
    return {node: value / normalizer for node, value in score.items()} if normalizer else score


def weighted_betweenness(graph: WeightedGraph) -> dict[str, float]:
    """Brandes weighted betweenness with edge distance equal to 1 / weight."""
    nodes = graph.nodes()
    result = {node: 0.0 for node in nodes}
    for source in nodes:
        stack: list[str] = []
        predecessors: dict[str, list[str]] = {node: [] for node in nodes}
        sigma = {node: 0.0 for node in nodes}
        distance = {node: math.inf for node in nodes}
        sigma[source] = 1.0
        distance[source] = 0.0
        queue: list[tuple[float, int, str]] = [(0.0, 0, source)]
        queue_serial = 1
        while queue:
            current_distance, _, current = heapq.heappop(queue)
            if current_distance > distance[current] + 1e-12:
                continue
            stack.append(current)
            for neighbor, weight in graph.neighbors(current).items():
                candidate = current_distance + 1.0 / weight
                if candidate < distance[neighbor] - 1e-12:
                    distance[neighbor] = candidate
                    sigma[neighbor] = sigma[current]
                    predecessors[neighbor] = [current]
                    heapq.heappush(queue, (candidate, queue_serial, neighbor))
                    queue_serial += 1
                elif abs(candidate - distance[neighbor]) <= 1e-12:
                    sigma[neighbor] += sigma[current]
                    predecessors[neighbor].append(current)
        dependency = {node: 0.0 for node in nodes}
        while stack:
            node = stack.pop()
            for predecessor in predecessors[node]:
                if sigma[node] > 0:
                    dependency[predecessor] += (sigma[predecessor] / sigma[node]) * (1.0 + dependency[node])
            if node != source:
                result[node] += dependency[node]
    # Undirected graphs count each path in both source directions.
    result = {node: value / 2.0 for node, value in result.items()}
    n = len(nodes)
    if n > 2:
        factor = 2.0 / ((n - 1) * (n - 2))
        result = {node: value * factor for node, value in result.items()}
    return result


def k_core_numbers(graph: WeightedGraph) -> dict[str, int]:
    """Return the unweighted core number of every node."""
    degree = {node: graph.unweighted_degree(node) for node in graph.nodes()}
    remaining = set(degree)
    core = {node: 0 for node in degree}
    current_k = 0
    while remaining:
        eligible = [node for node in remaining if degree[node] <= current_k]
        if not eligible:
            current_k += 1
            continue
        for start in sorted(eligible, key=_stable_node_sort):
            if start not in remaining:
                continue
            stack = [start]
            remaining.remove(start)
            while stack:
                node = stack.pop()
                core[node] = current_k
                for neighbor in graph.neighbors(node):
                    if neighbor in remaining:
                        degree[neighbor] -= 1
                        if degree[neighbor] <= current_k:
                            remaining.remove(neighbor)
                            stack.append(neighbor)
    return core


def bridge_scores(graph: WeightedGraph, partition: Sequence[set[str]]) -> dict[str, float]:
    """Return each node's cross-community incident-weight fraction."""
    groups = partition_map(partition)
    output: dict[str, float] = {}
    for node in graph.nodes():
        total = graph.degree(node)
        boundary = sum(weight for neighbor, weight in graph.neighbors(node).items() if groups.get(neighbor) != groups.get(node))
        output[node] = boundary / total if total > 0 else 0.0
    return output


def normalized_mutual_information(
    left: Mapping[str, int], right: Mapping[str, int]
) -> float | None:
    """Arithmetic NMI, ``2 I(X;Y)/(H(X)+H(Y))`` over a common node set."""
    nodes = sorted(set(left) & set(right), key=_stable_node_sort)
    if not nodes:
        return None
    left_counts = Counter(left[node] for node in nodes)
    right_counts = Counter(right[node] for node in nodes)
    joint = Counter((left[node], right[node]) for node in nodes)
    n = float(len(nodes))
    h_left = -sum((count / n) * math.log(count / n) for count in left_counts.values() if count)
    h_right = -sum((count / n) * math.log(count / n) for count in right_counts.values() if count)
    mutual = 0.0
    for (left_label, right_label), count in joint.items():
        pxy = count / n
        px = left_counts[left_label] / n
        py = right_counts[right_label] / n
        mutual += pxy * math.log(pxy / (px * py))
    denominator = h_left + h_right
    if denominator <= 0:
        # Both partitions are constant.  Community labels are arbitrary IDs,
        # so equal information content means a perfect match even when the
        # integer labels themselves differ.
        return 1.0
    return 2.0 * mutual / denominator


def _component_mapping(components: Sequence[set[str]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for index, component in enumerate(components):
        for node in component:
            result[node] = index
    return result


def _community_ids(
    partition: Sequence[set[str]], namespace: str = ""
) -> tuple[dict[int, str], dict[str, int], dict[int, int]]:
    ordered_indices = sorted(
        range(len(partition)),
        key=lambda index: (-len(partition[index]), tuple(sorted(partition[index], key=_stable_node_sort))),
    )
    ids: dict[int, str] = {}
    ranks: dict[str, int] = {}
    sizes: dict[int, int] = {}
    for rank, index in enumerate(ordered_indices, 1):
        group = partition[index]
        ids[index] = _stable_digest(group, "C", namespace)
        sizes[index] = len(group)
        for node in group:
            ranks[node] = rank
    return ids, ranks, sizes


def _community_edge_stats(
    graph: WeightedGraph,
    partition: Sequence[set[str]],
) -> tuple[dict[int, int], dict[int, float]]:
    group_map = partition_map(partition)
    edge_count: dict[int, int] = Counter()
    internal_weight: dict[int, float] = defaultdict(float)
    for source, target, weight in graph.edge_items(include_loops=False):
        source_group, target_group = group_map[source], group_map[target]
        if source_group == target_group:
            edge_count[source_group] += 1
            internal_weight[source_group] += weight
    for index, group in enumerate(partition):
        # Isolated communities are valid and must be present in summaries.
        edge_count.setdefault(index, 0)
        internal_weight.setdefault(index, 0.0)
    return edge_count, internal_weight


def compute_metrics(
    graph: WeightedGraph,
    partition: Sequence[set[str]],
) -> dict[str, object]:
    components = connected_components(graph)
    component_map = _component_mapping(components)
    community_map = partition_map(partition)
    community_ids, community_ranks, community_sizes = _community_ids(partition)
    modularity, contributions = weighted_modularity(graph, partition)
    # Recompute with the caller's resolution in run_analysis; this helper's
    # default is useful for unit tests and direct callers.
    pagerank_values = pagerank(graph)
    betweenness_values = weighted_betweenness(graph)
    core_values = k_core_numbers(graph)
    bridge_values = bridge_scores(graph, partition)
    return {
        "components": components,
        "component_map": component_map,
        "community_map": community_map,
        "community_ids": community_ids,
        "community_ranks": community_ranks,
        "community_sizes": community_sizes,
        "community_count": len(community_ids),
        "modularity": modularity,
        "modularity_contributions": contributions,
        "pagerank": pagerank_values,
        "betweenness": betweenness_values,
        "k_core": core_values,
        "bridge_score": bridge_values,
    }


def compute_run_metrics(
    graph: WeightedGraph,
    partition: Sequence[set[str]],
    *,
    resolution: float,
    namespace: str = "",
) -> dict[str, object]:
    """Compute all final metrics using the exact requested resolution."""
    components = connected_components(graph)
    component_map = _component_mapping(components)
    community_map = partition_map(partition)
    community_ids, community_ranks, community_sizes = _community_ids(partition, namespace)
    modularity, contributions = weighted_modularity(graph, partition, resolution=resolution)
    return {
        "components": components,
        "component_map": component_map,
        "community_map": community_map,
        "community_ids": community_ids,
        "community_ranks": community_ranks,
        "community_sizes": community_sizes,
        "community_count": len(community_ids),
        "modularity": modularity,
        "modularity_contributions": contributions,
        "degree_assortativity": degree_assortativity(graph),
        "nmi": normalized_mutual_information(community_map, component_map),
        "pagerank": pagerank(graph),
        "betweenness": weighted_betweenness(graph),
        "k_core": k_core_numbers(graph),
        "bridge_score": bridge_scores(graph, partition),
    }


def _write_csv(path: Path, rows: Iterable[Mapping[str, object]], fields: Sequence[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
            count += 1
    return count


def _relative_paths(root: Path, paths: Iterable[Path]) -> list[str]:
    result: list[str] = []
    for path in paths:
        resolved = path.resolve()
        try:
            result.append(resolved.relative_to(root.resolve()).as_posix())
        except ValueError as exc:
            raise CommunityAnalysisError(f"input/output path outside workspace: {path}") from exc
    return sorted(dict.fromkeys(result))


def _source_files(logical_path: Path) -> list[Path]:
    paths = part_paths(logical_path)
    if not paths:
        raise FileNotFoundError(logical_path)
    return paths


def _load_rows(path: Path) -> Iterator[dict[str, str]]:
    yield from iter_csv_rows(path, compressed=path.suffix == ".gz")


def _network_from_files(
    *,
    root: Path,
    data_dir: Path,
    round_label: str,
    scope: str,
    weight_metric: str,
    threshold: float,
    min_intersection_count: float,
    data_policy: str,
    pair_rounds: set[str] | None = None,
) -> PreparedNetwork:
    character_path = data_dir / "analysis_character_metrics_all.csv"
    music_path = data_dir / "analysis_music_metrics_all.csv"
    pair_path = data_dir / "analysis_covote_pairs_all.csv"
    cross_path = data_dir / "analysis_character_music_covote_all.csv"
    if scope == "cross_department":
        character_files = _source_files(character_path)
        music_files = _source_files(music_path)
        cross_files = _source_files(cross_path) if pair_rounds is None or round_label in pair_rounds else []
        result = build_cross_department_network(
            (row for path in character_files for row in _load_rows(path)),
            (row for path in music_files for row in _load_rows(path)),
            (row for path in cross_files for row in _load_rows(path)),
            round_label=round_label, weight_metric=weight_metric,
            threshold=threshold, min_intersection_count=min_intersection_count,
            data_policy=data_policy,
        )
        result.source_paths = character_files + music_files + cross_files
        return result
    node_files = _source_files(character_path if scope == "character" else music_path)
    pair_files = _source_files(pair_path) if pair_rounds is None or round_label in pair_rounds else []
    result = build_internal_network(
        (row for path in node_files for row in _load_rows(path)),
        (row for path in pair_files for row in _load_rows(path)),
        round_label=round_label, scope=scope, weight_metric=weight_metric,
        threshold=threshold, min_intersection_count=min_intersection_count,
        data_policy=data_policy,
    )
    result.source_paths = node_files + pair_files
    return result


def _write_outputs(
    output_dir: Path,
    network: PreparedNetwork,
    metrics: Mapping[str, object],
    *,
    round_label: str,
    scope: str,
    algorithm: str,
    weight_metric: str,
    threshold: float,
    min_intersection_count: float,
    resolution: float,
    random_seed: int,
    benchmark: Mapping[str, object],
) -> dict[str, Path]:
    graph = network.graph
    partition = [set(group) for group in _partition_from_map(metrics["community_map"], metrics["community_ids"])]
    community_map = metrics["community_map"]
    community_ids = metrics["community_ids"]
    community_ranks = metrics["community_ranks"]
    community_sizes = metrics["community_sizes"]
    component_map = metrics["component_map"]
    component_ids = {
        index: _stable_digest(component, "CC", f"{round_label}:{scope}")
        for index, component in enumerate(metrics["components"])
    }
    component_sizes = {index: len(component) for index, component in enumerate(metrics["components"])}
    common = {
        "round_label": round_label, "scope": scope, "algorithm": algorithm,
        "weight_metric": weight_metric, "threshold": threshold,
        "min_intersection_count": min_intersection_count, "resolution": resolution,
        "random_seed": random_seed, "software_version": SOFTWARE_VERSION,
        "official_faction_source": OFFICIAL_FACTION_SOURCE,
        "official_faction_note": OFFICIAL_FACTION_NOTE,
    }
    assignments: list[dict[str, object]] = []
    centrality: list[dict[str, object]] = []
    for node in graph.nodes():
        metadata = network.metadata.get(node, NodeMetadata(node, "unknown", node))
        group = community_map[node]
        community_id = community_ids[group]
        row = {
            **common, "node_type": metadata.node_type, "canonical_name": metadata.canonical_name,
            "name_cn": metadata.name_cn, "name_jp": metadata.name_jp,
            "community_id": community_id, "community_rank": community_ranks[node],
            "community_size": community_sizes[group],
            "connected_component_id": component_ids[component_map[node]],
            "connected_component_size": component_sizes[component_map[node]],
            "weighted_degree": _json_number(graph.weighted_degree(node)),
            "unweighted_degree": graph.unweighted_degree(node),
            "pagerank": _json_number(metrics["pagerank"][node]),
            "betweenness": _json_number(metrics["betweenness"][node]),
            "k_core": metrics["k_core"][node],
            "bridge_score": _json_number(metrics["bridge_score"][node]),
        }
        assignments.append(row)
        centrality.append({key: row[key] for key in CENTRALITY_FIELDS})
    assignments.sort(key=lambda row: (int(row["community_rank"]), _stable_node_sort(str(row["canonical_name"]))))
    centrality.sort(key=lambda row: _stable_node_sort(str(row["canonical_name"])))

    edge_counts, internal_weights = _community_edge_stats(graph, partition)
    summaries: list[dict[str, object]] = []
    for group_index, community_id in sorted(community_ids.items(), key=lambda item: community_ranks[next(iter(partition[item[0]]))]):
        summaries.append({
            **common, "community_id": community_id, "community_rank": community_ranks[next(iter(partition[group_index]))],
            "node_count": community_sizes[group_index], "edge_count": edge_counts[group_index],
            "internal_weight": _json_number(internal_weights[group_index]),
            "total_weighted_degree": _json_number(sum(graph.degree(node) for node in partition[group_index])),
            "modularity_contribution": _json_number(metrics["modularity_contributions"].get(group_index, 0.0)),
        })
    summaries.sort(key=lambda row: int(row["community_rank"]))

    modularity_row = {
        **common, "node_count": len(graph.nodes()), "edge_count": graph.edge_count(),
        "connected_component_count": len(metrics["components"]),
        "community_count": len(community_ids), "modularity": _json_number(metrics["modularity"]),
        "degree_assortativity": _json_number(metrics["degree_assortativity"]),
        "nmi_vs_connected_components": _json_number(metrics["nmi"]),
        **benchmark, "benchmark_status": "recorded",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "community_assignments": output_dir / "community_assignments.csv",
        "community_summary": output_dir / "community_summary.csv",
        "node_centrality": output_dir / "node_centrality.csv",
        "modularity_summary": output_dir / "modularity_summary.csv",
    }
    _write_csv(paths["community_assignments"], assignments, ASSIGNMENT_FIELDS)
    _write_csv(paths["community_summary"], summaries, SUMMARY_FIELDS)
    _write_csv(paths["node_centrality"], centrality, CENTRALITY_FIELDS)
    _write_csv(paths["modularity_summary"], [modularity_row], MODULARITY_FIELDS)
    return paths


def _partition_from_map(community_map: Mapping[str, int], community_ids: Mapping[int, str]) -> list[set[str]]:
    groups: dict[int, set[str]] = defaultdict(set)
    for node, group in community_map.items():
        groups[group].add(node)
    return [groups[index] for index in sorted(community_ids)]


def run_analysis(
    *,
    root: Path,
    data_dir: Path,
    output_dir: Path,
    round_label: str = DEFAULT_ROUND,
    scope: str = "character",
    algorithm: str = "louvain",
    weight_metric: str = DEFAULT_WEIGHT_METRIC,
    threshold: float = DEFAULT_THRESHOLD,
    min_intersection_count: float = 0.0,
    resolution: float = DEFAULT_RESOLUTION,
    random_seed: int = DEFAULT_RANDOM_SEED,
    data_policy: str = "observed",
    max_levels: int = 100,
    max_passes: int = 100,
    pair_rounds: set[str] | None = None,
) -> dict[str, object]:
    """Run one configured network and write the requested output bundle."""
    algorithm = str(algorithm).casefold()
    if algorithm != "louvain":
        raise CommunityAnalysisError("only algorithm=louvain is currently implemented")
    if scope not in {"character", "music", "cross_department"}:
        raise CommunityAnalysisError(f"unsupported scope: {scope}")
    if weight_metric not in SUPPORTED_WEIGHT_METRICS:
        raise CommunityAnalysisError(f"unsupported weight metric: {weight_metric}")
    if not re.fullmatch(r"(?:CN|JP)\d+", str(round_label or "").strip().upper()):
        raise CommunityAnalysisError(f"round_label must be CN/JP plus a round number: {round_label!r}")
    if resolution <= 0 or not math.isfinite(resolution):
        raise CommunityAnalysisError("resolution must be finite and positive")
    if max_levels <= 0 or max_passes <= 0:
        raise CommunityAnalysisError("max_levels and max_passes must be positive")
    if threshold < 0 or not math.isfinite(threshold):
        raise CommunityAnalysisError("threshold must be finite and non-negative")
    if min_intersection_count < 0 or not math.isfinite(min_intersection_count):
        raise CommunityAnalysisError("min_intersection_count must be finite and non-negative")
    round_label = normalize_round_label(round_label)
    root, data_dir, output_dir = root.resolve(), data_dir.resolve(), output_dir.resolve()
    tracemalloc.start()
    try:
        load_started = time.perf_counter()
        network = _network_from_files(
            root=root, data_dir=data_dir, round_label=round_label, scope=scope,
            weight_metric=weight_metric, threshold=threshold,
            min_intersection_count=min_intersection_count, data_policy=data_policy,
            pair_rounds=pair_rounds,
        )
        load_seconds = time.perf_counter() - load_started
        algorithm_started = time.perf_counter()
        partition = louvain_partition(
            network.graph, resolution=resolution, random_seed=random_seed,
            max_levels=max_levels, max_passes=max_passes,
        )
        metrics = compute_run_metrics(
            network.graph, partition, resolution=resolution, namespace=f"{round_label}:{scope}",
        )
        algorithm_seconds = time.perf_counter() - algorithm_started
        _, peak_memory = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    benchmark = {
        "runtime_seconds": _json_number(load_seconds + algorithm_seconds),
        "load_seconds": _json_number(load_seconds),
        "algorithm_seconds": _json_number(algorithm_seconds),
        "peak_memory_bytes": int(peak_memory),
    }
    paths = _write_outputs(
        output_dir, network, metrics, round_label=round_label, scope=scope,
        algorithm=algorithm, weight_metric=weight_metric, threshold=threshold,
        min_intersection_count=min_intersection_count, resolution=resolution,
        random_seed=random_seed, benchmark=benchmark,
    )
    manifest_path = output_dir / "community_run_manifest.json"
    input_paths = _relative_paths(root, network.source_paths)
    output_paths = _relative_paths(root, paths.values())
    parameters = {
        "round_label": round_label, "scope": scope, "algorithm": algorithm,
        "algorithm_version": SOFTWARE_VERSION, "weight_metric": weight_metric,
        "threshold": threshold, "min_intersection_count": min_intersection_count,
        "resolution": resolution, "random_seed": random_seed,
        "data_policy": data_policy, "max_levels": max_levels, "max_passes": max_passes,
        "include_isolated_nodes": True,
        "community_id_scheme": "sha256([round_label + ':' + scope, sorted_member_node_ids])[0:16]",
        "bridge_score_definition": "cross-community incident weight / weighted degree",
        "nmi_definition": "arithmetic 2I/(H_community+H_connected_component)",
        "software_version": SOFTWARE_VERSION,
        "benchmark": benchmark,
        "official_faction_source": OFFICIAL_FACTION_SOURCE,
        "official_faction_note": OFFICIAL_FACTION_NOTE,
    }
    integrity = {
        "status": "passed" if network.invalid_pairs == 0 else "warning",
        "checks": [
            {"name": "positive_finite_included_weights", "ok": network.invalid_pairs == 0},
            {"name": "isolated_nodes_retained", "ok": True},
            {"name": "official_faction_metadata_not_used", "ok": True},
        ],
        "coverage": {"round_label": round_label, "scope": scope, "data_policy": data_policy},
        "missing": {"excluded_pair_reasons": dict(network.excluded_reasons)},
        "duplicate_count": network.duplicate_pairs,
        "invalid_count": network.invalid_pairs,
        "warnings": network.notes,
    }
    return {
        "network": network,
        "metrics": metrics,
        "paths": paths,
        "manifest_path": manifest_path,
        "input_paths": input_paths,
        "output_paths": output_paths,
        "parameters": parameters,
        "integrity": integrity,
        "benchmark": benchmark,
    }


def _rounds_in_files(paths: Iterable[Path]) -> set[str]:
    rounds: set[str] = set()
    for path in paths:
        for row in _load_rows(path):
            label = _row_round(row)
            if label:
                rounds.add(label)
    return rounds


def discover_round_labels(*, data_dir: Path, scope: str) -> list[str]:
    """Discover the node-universe rounds used by ``--round all``."""
    if scope == "character":
        paths = _source_files(data_dir / "analysis_character_metrics_all.csv")
    elif scope == "music":
        paths = _source_files(data_dir / "analysis_music_metrics_all.csv")
    elif scope == "cross_department":
        character_rounds = _rounds_in_files(_source_files(data_dir / "analysis_character_metrics_all.csv"))
        music_rounds = _rounds_in_files(_source_files(data_dir / "analysis_music_metrics_all.csv"))
        return sorted(character_rounds | music_rounds, key=lambda value: (value[:2], int(value[2:])))
    else:
        raise CommunityAnalysisError(f"unsupported scope: {scope}")
    return sorted(_rounds_in_files(paths), key=lambda value: (value[:2], int(value[2:])))


def run_all_rounds(
    *,
    root: Path,
    data_dir: Path,
    output_dir: Path,
    scope: str = "character",
    algorithm: str = "louvain",
    weight_metric: str = DEFAULT_WEIGHT_METRIC,
    threshold: float = DEFAULT_THRESHOLD,
    min_intersection_count: float = 0.0,
    resolution: float = DEFAULT_RESOLUTION,
    random_seed: int = DEFAULT_RANDOM_SEED,
    data_policy: str = "observed",
    max_levels: int = 100,
    max_passes: int = 100,
) -> dict[str, object]:
    """Run the selected network scope independently for every available round."""
    root, data_dir, output_dir = root.resolve(), data_dir.resolve(), output_dir.resolve()
    rounds = discover_round_labels(data_dir=data_dir, scope=scope)
    if not rounds:
        raise CommunityAnalysisError(f"no rounds found for scope: {scope}")
    pair_path = data_dir / (
        "analysis_character_music_covote_all.csv"
        if scope == "cross_department" else "analysis_covote_pairs_all.csv"
    )
    pair_rounds = _rounds_in_files(_source_files(pair_path))
    results: list[dict[str, object]] = []
    for round_label in rounds:
        result_dir = output_dir / "by_round" / round_label
        result = run_analysis(
            root=root, data_dir=data_dir, output_dir=result_dir,
            round_label=round_label, scope=scope, algorithm=algorithm,
            weight_metric=weight_metric, threshold=threshold,
            min_intersection_count=min_intersection_count, resolution=resolution,
            random_seed=random_seed, data_policy=data_policy,
            max_levels=max_levels, max_passes=max_passes, pair_rounds=pair_rounds,
        )
        _write_manifest(result, root=root, random_seed=random_seed)
        results.append(result)
    batch_manifest = {
        "manifest_type": "network_community_batch",
        "software_version": SOFTWARE_VERSION,
        "scope": scope,
        "algorithm": str(algorithm).casefold(),
        "weight_metric": weight_metric,
        "threshold": threshold,
        "min_intersection_count": min_intersection_count,
        "resolution": resolution,
        "random_seed": random_seed,
        "data_policy": data_policy,
        "rounds": rounds,
        "run_count": len(results),
        "run_manifests": [
            result["manifest_path"].resolve().relative_to(root).as_posix()
            for result in results
        ],
        "contract": {
            "one_independent_output_bundle_per_round": True,
            "labels_are_not_official_factions": True,
            "rounds_without_published_pairs_retain_isolated_nodes": True,
        },
    }
    batch_path = output_dir / "all_rounds_manifest.json"
    batch_path.parent.mkdir(parents=True, exist_ok=True)
    batch_path.write_text(json.dumps(batch_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"rounds": rounds, "results": results, "manifest_path": batch_path}


def _build_manifest(result: Mapping[str, object], *, root: Path, random_seed: int) -> dict[str, object]:
    # Imported lazily so pure algorithm users do not need to initialize the
    # manifest helper until they write a real run.
    try:
        from .model_run_manifest import create_model_run_manifest
    except ImportError:  # pragma: no cover - direct CLI execution
        from model_run_manifest import create_model_run_manifest
    network: PreparedNetwork = result["network"]  # type: ignore[assignment]
    parameters = result["parameters"]
    integrity = result["integrity"]
    paths = result["paths"]
    manifest = create_model_run_manifest(
        root,
        analysis="standard_community_detection",
        analysis_version=SOFTWARE_VERSION,
        inputs=[{"path": path, "role": "network_input"} for path in result["input_paths"]],
        outputs=[{"path": path, "role": "community_output"} for path in result["output_paths"]],
        parameters=parameters,
        test_method="louvain_seeded_local_move",
        random_seed=random_seed,
        permutations=0,
        tail="two-sided",
        node_set={
            "entity_type": parameters["scope"],
            "source": ";".join(result["input_paths"]),
            "selection_rule": "round_label and scope node universe; isolates retained",
            "ids": sorted(network.graph.nodes(), key=_stable_node_sort),
        },
        pair_inclusion={
            "rule": f"{parameters['weight_metric']} >= {parameters['threshold']}",
            "directed": False,
            "self_pairs": False,
            "deduplication": "canonical_unordered_first_observation",
            "missing_pair_policy": "exclude_unpublished_or_invalid_rows_and_report",
            "included_pairs": network.included_pairs,
            "excluded_pairs": network.excluded_pairs,
            "threshold": parameters["threshold"],
            "minimum_intersection_count": parameters["min_intersection_count"],
        },
        data_integrity=integrity,
        code_version=SOFTWARE_VERSION,
        script="scripts_pipeline/network_communities.py",
    )
    manifest["community_contract"] = {
        "labels_are_not_official_factions": True,
        "existing_single_link_components_are_unchanged": True,
        "connected_component_reference": "thresholded observed graph",
        "output_files": {
            key: _relative_paths(root, [value])[0]
            for key, value in paths.items()
        },
        "benchmark": result["benchmark"],
    }
    return manifest


def _write_manifest(result: Mapping[str, object], *, root: Path, random_seed: int) -> Path:
    manifest_path: Path = result["manifest_path"]  # type: ignore[assignment]
    manifest = _build_manifest(result, root=root, random_seed=random_seed)
    write_model_run_manifest(manifest_path, manifest, root=root)
    return manifest_path


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run reproducible standard community detection on a vote network.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--round", dest="round_label", default=DEFAULT_ROUND,
        help="CN/JP round label, or 'all' for every available round",
    )
    parser.add_argument("--scope", choices=("character", "music", "cross_department"), default="character")
    parser.add_argument("--algorithm", choices=("louvain",), default="louvain")
    parser.add_argument("--weight-metric", default=DEFAULT_WEIGHT_METRIC)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--min-intersection-count", type=float, default=0.0)
    parser.add_argument("--resolution", type=float, default=DEFAULT_RESOLUTION)
    parser.add_argument("--random-seed", type=int, default=DEFAULT_RANDOM_SEED)
    parser.add_argument("--data-policy", choices=("observed", "complete_matrix", "published_leading_list", "cross_department_conditional_only"), default="observed")
    parser.add_argument("--max-levels", type=int, default=100)
    parser.add_argument("--max-passes", type=int, default=100)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    root = args.root.resolve()
    data_dir = (args.data_dir or root / "vote_explorer" / "data").resolve()
    output_dir = (args.output_dir or root / "analysis_results" / "network_communities").resolve()
    try:
        if str(args.round_label).casefold() == "all":
            batch = run_all_rounds(
                root=root, data_dir=data_dir, output_dir=output_dir,
                scope=args.scope, algorithm=args.algorithm,
                weight_metric=args.weight_metric, threshold=args.threshold,
                min_intersection_count=args.min_intersection_count,
                resolution=args.resolution, random_seed=args.random_seed,
                data_policy=args.data_policy, max_levels=args.max_levels,
                max_passes=args.max_passes,
            )
            manifest_path = batch["manifest_path"]
        else:
            result = run_analysis(
                root=root, data_dir=data_dir, output_dir=output_dir,
                round_label=args.round_label, scope=args.scope, algorithm=args.algorithm,
                weight_metric=args.weight_metric, threshold=args.threshold,
                min_intersection_count=args.min_intersection_count, resolution=args.resolution,
                random_seed=args.random_seed, data_policy=args.data_policy,
                max_levels=args.max_levels, max_passes=args.max_passes,
            )
            manifest_path = _write_manifest(result, root=root, random_seed=args.random_seed)
    except (CommunityAnalysisError, FileNotFoundError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"wrote {output_dir}; manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
