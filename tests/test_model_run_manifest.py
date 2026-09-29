from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts_pipeline.model_run_manifest import (
    MANIFEST_TYPE,
    ManifestValidationError,
    SCHEMA_VERSION,
    create_model_run_manifest,
    node_ids_sha256,
    read_model_run_manifest,
    validate_model_run_manifest,
    verify_model_run_manifest,
    write_model_run_manifest,
)


class ModelRunManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "data").mkdir()
        (self.root / "results").mkdir()
        self.input_path = self.root / "data" / "pairs.csv"
        self.output_path = self.root / "results" / "edges.csv"
        self.input_path.write_bytes("a,b,count\nreimu,marisa,12\n".encode("utf-8"))
        self.output_path.write_bytes("a,b,p\nreimu,marisa,0.01\n".encode("utf-8"))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _manifest(self) -> dict:
        return create_model_run_manifest(
            self.root,
            analysis="character_covote_network",
            analysis_version="1.0.0",
            inputs=[
                {
                    "path": "data/pairs.csv",
                    "role": "pair_source",
                    "row_count": 1,
                    "columns": ["a", "b", "count"],
                    "sha256": "stale-value",
                    "size_bytes": 1,
                }
            ],
            outputs=[{"path": "results/edges.csv", "role": "edge_table"}],
            parameters={"round": "CN11", "min_count": 10},
            random_seed=20260801,
            permutations=20_000,
            tail="two-sided",
            node_set={
                "entity_type": "character",
                "source": "analysis_character_metrics_all.csv",
                "selection_rule": "rank <= 100",
                "ids": ["marisa", "reimu"],
            },
            pair_inclusion={
                "rule": "intersection_count >= 10",
                "directed": False,
                "self_pairs": False,
                "missing_pair_policy": "exclude_and_report",
            },
            data_integrity={
                "status": "passed",
                "checks": [{"name": "round_coverage", "ok": True}],
                "coverage": {"rounds": ["CN11"]},
                "missing": {"pairs": 0},
                "duplicate_count": 0,
                "invalid_count": 0,
                "warnings": [],
            },
            code={"version": "git-tree-version"},
        )

    def test_create_read_and_verify_round_trip(self) -> None:
        manifest = self._manifest()
        self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)
        self.assertEqual(manifest["manifest_type"], MANIFEST_TYPE)
        self.assertEqual(manifest["analysis"]["name"], "character_covote_network")
        self.assertEqual(manifest["analysis"]["version"], "1.0.0")
        self.assertEqual(manifest["statistical_test"]["random_seed"], 20260801)
        self.assertEqual(manifest["statistical_test"]["permutations"], 20_000)
        self.assertEqual(manifest["statistical_test"]["tail"], "two-sided")
        self.assertEqual(manifest["node_set"]["ids"], ["marisa", "reimu"])
        self.assertEqual(manifest["node_set"]["count"], 2)
        self.assertEqual(manifest["node_set"]["ids_sha256"], node_ids_sha256(["marisa", "reimu"]))
        self.assertEqual(
            manifest["inputs"][0]["sha256"],
            hashlib.sha256(self.input_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(manifest["inputs"][0]["size_bytes"], self.input_path.stat().st_size)
        self.assertEqual(manifest["inputs"][0]["row_count"], 1)
        self.assertIn("git_commit", manifest["code"])
        self.assertIn("git_dirty", manifest["code"])

        manifest_path = self.root / "results" / "model_run_manifest.json"
        written = write_model_run_manifest(manifest_path, manifest)
        loaded = read_model_run_manifest(manifest_path)
        self.assertEqual(loaded, written)
        verification = verify_model_run_manifest(loaded, root=self.root)
        self.assertTrue(verification["ok"], verification)
        self.assertEqual(len(verification["inputs"]), 1)
        self.assertEqual(len(verification["outputs"]), 1)
        self.assertTrue(verification["inputs"][0]["sha256_ok"])
        self.assertTrue(verification["outputs"][0]["size_ok"])
        self.assertTrue(manifest_path.read_bytes().endswith(b"\n"))

    def test_writer_recomputes_stale_hashes_and_normalizes_paths(self) -> None:
        manifest = self._manifest()
        manifest["inputs"][0]["sha256"] = "0" * 64
        manifest["inputs"][0]["size_bytes"] = 0
        manifest_path = self.root / "results" / "model_run_manifest.json"
        written = write_model_run_manifest(manifest_path, manifest, root=self.root)
        self.assertNotEqual(written["inputs"][0]["sha256"], "0" * 64)
        self.assertEqual(written["inputs"][0]["path"], "data/pairs.csv")
        self.assertEqual(read_model_run_manifest(manifest_path), written)

    def test_verification_identifies_tampered_input(self) -> None:
        manifest_path = self.root / "results" / "model_run_manifest.json"
        write_model_run_manifest(manifest_path, self._manifest())
        self.input_path.write_text("tampered\n", encoding="utf-8")
        verification = verify_model_run_manifest(manifest_path, root=self.root)
        self.assertFalse(verification["ok"])
        self.assertIn("data/pairs.csv", verification["hash_mismatches"])
        self.assertNotIn("results/edges.csv", verification["hash_mismatches"])
        self.assertFalse(next(item for item in verification["inputs"])["ok"])
        self.assertTrue(next(item for item in verification["outputs"])["ok"])

    def test_verification_identifies_tampered_output(self) -> None:
        manifest_path = self.root / "results" / "model_run_manifest.json"
        write_model_run_manifest(manifest_path, self._manifest())
        self.output_path.write_text("changed\n", encoding="utf-8")
        verification = verify_model_run_manifest(manifest_path, root=self.root)
        self.assertFalse(verification["ok"])
        self.assertIn("results/edges.csv", verification["hash_mismatches"])
        self.assertTrue(next(item for item in verification["inputs"])["ok"])
        self.assertFalse(next(item for item in verification["outputs"])["ok"])

    def test_node_order_is_canonical_and_conflicts_fail(self) -> None:
        manifest = self._manifest()
        self.assertEqual(
            manifest["node_set"]["ids_sha256"],
            node_ids_sha256(["reimu", "marisa"]),
        )
        bad_nodes = dict(manifest["node_set"])
        bad_nodes["count"] = 99
        with self.assertRaises(ManifestValidationError):
            create_model_run_manifest(
                self.root,
                analysis="network",
                inputs=[],
                outputs=[],
                node_set=bad_nodes,
                pair_inclusion={"rule": "all pairs"},
            )

    def test_invalid_statistical_settings_and_paths_fail(self) -> None:
        common = {
            "root": self.root,
            "analysis": "network",
            "inputs": ["data/pairs.csv"],
            "outputs": ["results/edges.csv"],
            "node_set": {
                "entity_type": "character",
                "source": "roster",
                "selection_rule": "all",
                "ids": ["a"],
            },
            "pair_inclusion": {"rule": "all pairs"},
        }
        with self.assertRaises(ManifestValidationError):
            create_model_run_manifest(**common, tail="one-sided")
        with self.assertRaises(ManifestValidationError):
            create_model_run_manifest(**common, permutations=-1)
        with self.assertRaises(ManifestValidationError):
            invalid_nodes = {**common["node_set"], "ids": ["a", "a"]}
            invalid_common = {**common, "node_set": invalid_nodes}
            create_model_run_manifest(**invalid_common)
        with self.assertRaises(FileNotFoundError):
            missing_input_common = {**common, "inputs": ["missing.csv"]}
            create_model_run_manifest(**missing_input_common)
        with self.assertRaises(ManifestValidationError):
            outside_input_common = {**common, "inputs": ["../outside.csv"]}
            create_model_run_manifest(**outside_input_common)
        with self.assertRaises(ManifestValidationError):
            create_model_run_manifest(
                self.root,
                analysis="network",
                inputs=[],
                outputs=[],
                node_set=common["node_set"],
                pair_inclusion=None,
            )

    def test_manifest_schema_has_matching_version_and_contract(self) -> None:
        repository_schema = Path(__file__).resolve().parents[1] / "metadata" / "model_run_manifest.schema.json"
        schema = json.loads(repository_schema.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema["$defs"]["statisticalTest"]["properties"]["tail"]["enum"], ["two-sided", "greater", "less"])
        self.assertEqual(schema["$defs"]["fileRecord"]["required"], ["path", "sha256", "size_bytes"])
        manifest = self._manifest()
        self.assertEqual(validate_model_run_manifest(manifest), manifest)


if __name__ == "__main__":
    unittest.main()
