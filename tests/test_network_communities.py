from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts_pipeline import network_communities as nc


class NetworkCommunityAlgorithmTests(unittest.TestCase):
    def test_empty_graph_and_isolates_are_defined(self) -> None:
        empty = nc.WeightedGraph()
        self.assertEqual(nc.louvain_partition(empty), [])
        self.assertEqual(nc.pagerank(empty), {})
        self.assertIsNone(nc.normalized_mutual_information({}, {}))

        graph = nc.WeightedGraph(["isolated", "other"])
        partition = nc.louvain_partition(graph, random_seed=4)
        metrics = nc.compute_run_metrics(graph, partition, resolution=1.0)
        self.assertEqual(len(partition), 2)
        self.assertEqual(metrics["modularity"], 0.0)
        self.assertEqual(metrics["pagerank"]["isolated"], 0.5)
        self.assertEqual(metrics["k_core"]["isolated"], 0)
        self.assertEqual(metrics["bridge_score"]["isolated"], 0.0)

    def test_single_community_path_and_metrics(self) -> None:
        graph = nc.WeightedGraph(["a", "b", "c"])
        graph.add_edge("a", "b", 2)
        graph.add_edge("b", "c", 2)
        partition = [{"a", "b", "c"}]
        metrics = nc.compute_run_metrics(graph, partition, resolution=1.0)
        self.assertEqual(metrics["community_count"] if "community_count" in metrics else len(partition), 1)
        self.assertAlmostEqual(sum(metrics["pagerank"].values()), 1.0)
        self.assertEqual(metrics["k_core"]["b"], 1)
        self.assertGreater(metrics["betweenness"]["b"], metrics["betweenness"]["a"])
        self.assertEqual(metrics["nmi"], 1.0)

    def test_louvain_is_seed_reproducible_and_ids_are_member_based(self) -> None:
        graph = nc.WeightedGraph(["a", "b", "c", "d", "e", "f"])
        for source, target in (("a", "b"), ("b", "c"), ("a", "c"), ("d", "e"), ("e", "f"), ("d", "f")):
            graph.add_edge(source, target, 5)
        first = nc.louvain_partition(graph, random_seed=19)
        second = nc.louvain_partition(graph, random_seed=19)
        self.assertEqual(first, second)
        first_ids = nc._community_ids(first)[0]
        second_ids = nc._community_ids(second)[0]
        self.assertEqual(first_ids, second_ids)
        self.assertEqual(len(first), 2)

    def test_nmi_and_bridge_score_compare_different_partitions(self) -> None:
        graph = nc.WeightedGraph(["a", "b", "c", "d"])
        graph.add_edge("a", "b", 3)
        graph.add_edge("b", "c", 1)
        graph.add_edge("c", "d", 3)
        components = nc.connected_components(graph)
        self.assertEqual(len(components), 1)
        left = {"a": 0, "b": 0, "c": 1, "d": 1}
        right = {"a": 0, "b": 1, "c": 0, "d": 1}
        self.assertGreaterEqual(nc.normalized_mutual_information(left, right), 0.0)
        scores = nc.bridge_scores(graph, [{"a", "b"}, {"c", "d"}])
        self.assertGreater(scores["b"], scores["a"])
        self.assertGreater(scores["c"], scores["d"])

    def test_nmi_ignores_arbitrary_constant_partition_labels(self) -> None:
        self.assertEqual(
            nc.normalized_mutual_information(
                {"a": 0, "b": 0}, {"a": 7, "b": 7},
            ),
            1.0,
        )


class NetworkCommunityInputAndOutputTests(unittest.TestCase):
    def _write_csv(self, path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_empty_thresholded_network_keeps_nodes(self) -> None:
        nodes = [
            {"round_label": "CN11", "category": "character", "canonical_name": "a", "name_cn": "甲", "name_jp": "A"},
            {"round_label": "CN11", "category": "character", "canonical_name": "b", "name_cn": "乙", "name_jp": "B"},
        ]
        pairs = [{
            "round_label": "CN11", "pair_category": "character", "canonical_a": "a", "canonical_b": "b",
            "name_a_cn": "甲", "name_b_cn": "乙", "name_a": "A", "name_b": "B", "intersection_count": "1",
        }]
        network = nc.build_internal_network(nodes, pairs, round_label="CN11", scope="character", threshold=2)
        self.assertEqual(network.graph.nodes(), ["a", "b"])
        self.assertEqual(network.graph.edge_count(), 0)
        self.assertEqual(network.excluded_reasons["threshold"], 1)

    def test_end_to_end_outputs_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "vote_explorer" / "data"
            self._write_csv(
                data / "analysis_character_metrics_all.csv",
                ["round_label", "category", "canonical_name", "name_cn", "name_jp"],
                [
                    {"round_label": "CN11", "category": "character", "canonical_name": "a", "name_cn": "甲", "name_jp": "A"},
                    {"round_label": "CN11", "category": "character", "canonical_name": "b", "name_cn": "乙", "name_jp": "B"},
                    {"round_label": "CN11", "category": "character", "canonical_name": "c", "name_cn": "丙", "name_jp": "C"},
                ],
            )
            self._write_csv(
                data / "analysis_covote_pairs_all.csv",
                [
                    "round_label", "pair_category", "canonical_a", "canonical_b", "name_a_cn", "name_b_cn",
                    "name_a", "name_b", "intersection_count",
                ],
                [
                    {"round_label": "CN11", "pair_category": "character", "canonical_a": "a", "canonical_b": "b", "name_a_cn": "甲", "name_b_cn": "乙", "name_a": "A", "name_b": "B", "intersection_count": "4"},
                    {"round_label": "CN11", "pair_category": "character", "canonical_a": "b", "canonical_b": "c", "name_a_cn": "乙", "name_b_cn": "丙", "name_a": "B", "name_b": "C", "intersection_count": "4"},
                ],
            )
            output = root / "analysis_results" / "network_communities"
            result = nc.run_analysis(
                root=root, data_dir=data, output_dir=output, round_label="CN11",
                scope="character", threshold=3, random_seed=9,
            )
            manifest_path = nc._write_manifest(result, root=root, random_seed=9)
            expected = {
                "community_assignments.csv", "community_summary.csv", "node_centrality.csv",
                "modularity_summary.csv", "community_run_manifest.json",
            }
            self.assertEqual({path.name for path in output.iterdir()}, expected)
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["parameters"]["algorithm"], "louvain")
            self.assertEqual(payload["parameters"]["weight_metric"], "intersection_count")
            self.assertEqual(payload["parameters"]["threshold"], 3)
            self.assertEqual(payload["parameters"]["resolution"], 1.0)
            self.assertEqual(payload["statistical_test"]["random_seed"], 9)
            self.assertTrue(payload["community_contract"]["labels_are_not_official_factions"])
            with (output / "modularity_summary.csv").open(encoding="utf-8-sig", newline="") as stream:
                summary = list(csv.DictReader(stream))
            self.assertEqual(summary[0]["benchmark_status"], "recorded")
            with (output / "community_assignments.csv").open(encoding="utf-8-sig", newline="") as stream:
                assignments = list(csv.DictReader(stream))
            self.assertEqual({row["canonical_name"] for row in assignments}, {"a", "b", "c"})

    def test_run_all_rounds_writes_independent_round_bundles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "vote_explorer" / "data"
            self._write_csv(
                data / "analysis_character_metrics_all.csv",
                ["round_label", "category", "canonical_name", "name_cn", "name_jp"],
                [
                    {"round_label": "CN1", "category": "character", "canonical_name": "a"},
                    {"round_label": "CN2", "category": "character", "canonical_name": "b"},
                ],
            )
            self._write_csv(
                data / "analysis_covote_pairs_all.csv",
                ["round_label", "pair_category", "canonical_a", "canonical_b", "intersection_count"],
                [{"round_label": "CN2", "pair_category": "character", "canonical_a": "b", "canonical_b": "c", "intersection_count": "4"}],
            )
            result = nc.run_all_rounds(
                root=root, data_dir=data,
                output_dir=root / "analysis_results" / "network_communities",
                scope="character", threshold=3,
            )
            self.assertEqual(result["rounds"], ["CN1", "CN2"])
            for label in result["rounds"]:
                bundle = root / "analysis_results" / "network_communities" / "by_round" / label
                self.assertTrue((bundle / "community_run_manifest.json").exists())
                self.assertTrue((bundle / "community_assignments.csv").exists())
            self.assertTrue((root / "analysis_results" / "network_communities" / "all_rounds_manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
