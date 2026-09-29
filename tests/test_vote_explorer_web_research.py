from __future__ import annotations

import csv
from collections import Counter, defaultdict
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from vote_explorer_web.research_bundle import build_research_bundle, normalize


class ResearchBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inference = self.root / "analysis_results/network_inference"
        self.inference.mkdir(parents=True)
        self.output = self.root / "web_data/research"

    def source(self, filename, rows, manifest_name=None, **extra):
        path = self.inference / filename
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        if manifest_name:
            manifest = {"outputs": [{"path": path.relative_to(self.root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}], **extra}
            (path.parent / manifest_name).write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def decoded(self, entry):
        payload = json.loads((self.output / entry["path"]).read_text(encoding="utf-8"))
        return payload, [dict(payload["defaults"], **dict(zip(payload["columns"], values))) for values in payload["values"]]

    def test_preserve_blank_zero_long_seed_and_latest_results(self):
        rows = [dict(region="cn", round="11", dependent_metric="cosine", coefficient="", qap_p="", ordinary_p="0.01",
                     complete_case_n="0", n_pairs="10", permutation_seed="8509473029546610632", status="no_complete_cases"),
                dict(region="cn", round="11", dependent_metric="cosine", coefficient="0", qap_p="1", ordinary_p="1",
                     complete_case_n="10", n_pairs="10", permutation_seed="8509473029546610632", status="ok")]
        self.source("mrqap_coefficients.csv", rows, "model_run_manifest.json", statistical_test={"permutations": 200, "random_seed": 42})
        stale = self.inference / "unified"
        stale.mkdir()
        (stale / "mrqap_coefficients.csv").write_text("stale invalid data")
        index = build_research_bundle(self.root, self.output)
        payload, actual = self.decoded(index["entries"][0])
        self.assertEqual(index["total_rows"], 2)
        self.assertEqual(actual[0]["coefficient"], "")
        self.assertEqual(actual[1]["coefficient"], "0")
        self.assertEqual(actual[0]["permutation_seed"], "8509473029546610632")
        self.assertEqual(actual[0]["web_n_pairs"], "0")
        self.assertEqual(actual[0]["n_pairs"], "10")
        self.assertFalse(actual[0]["web_complete_matrix"])
        self.assertEqual(actual[0]["web_permutations"], 200)
        self.assertEqual(payload["sources"][0]["provenance_status"], "output_hash_verified")

    def test_tampered_result_fails_without_replacing_published_index(self):
        path = self.source("hypothesis_tests.csv", [{"region": "cn", "round": "11", "metric": "phi", "cliffs_delta": "0"}], "hypothesis_tests_manifest.json")
        build_research_bundle(self.root, self.output)
        before = (self.output / "index.json").read_bytes()
        path.write_text(path.read_text(encoding="utf-8-sig") + "cn,11,phi,1", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            build_research_bundle(self.root, self.output)
        self.assertEqual(before, (self.output / "index.json").read_bytes())

    def test_absent_manifest_retains_unknown_parameters_and_marks_exploration(self):
        self.source("sensitivity_scan.csv", [{"region": "jp", "round": "22", "metric": "lift", "effect_size": "",
                    "threshold_type": "cp_vote_count", "threshold": "0", "valid_permutations": "199", "data_completeness": "partial_observed_pairs"}])
        index = build_research_bundle(self.root, self.output)
        payload, rows = self.decoded(index["entries"][0])
        self.assertTrue(rows[0]["web_exploratory"])
        self.assertFalse(rows[0]["web_complete_matrix"])
        self.assertEqual(rows[0]["web_permutations"], "")
        self.assertEqual(rows[0]["web_random_seed"], "")
        self.assertEqual(rows[0]["web_threshold"], "cp_vote_count ≥ 0")
        self.assertEqual(payload["sources"][0]["provenance_status"], "no_run_manifest")

    def test_completeness_uses_effective_matrix_not_endpoint_flags(self):
        raw = dict(round="CN11", metric_a="lift", metric_b="cosine", source_complete_a="True", source_complete_b="True", complete_pair_matrix="False")
        self.assertFalse(normalize("matrix_correlations", raw, {})["web_complete_matrix"])
        raw["complete_pair_matrix"] = "True"
        self.assertTrue(normalize("matrix_correlations", raw, {})["web_complete_matrix"])

    def test_batch_manifest_is_authoritative_and_missing_members_fail(self):
        parent = self.root / "analysis_results/network_communities"
        parent.mkdir()
        batch = parent / "all_rounds_manifest.json"
        batch.write_text(json.dumps({"run_manifests": ["analysis_results/network_communities/by_round/CN11/community_run_manifest.json"]}))
        # A stale root manifest must never silently substitute for a listed run.
        (parent / "community_run_manifest.json").write_text('{}')
        with self.assertRaises(FileNotFoundError):
            build_research_bundle(self.root, self.output)

    def test_empty_repository_builds_explicit_unavailable_index(self):
        index = build_research_bundle(self.root, self.output)
        self.assertEqual(index["entries"], [])
        self.assertGreater(len(index["notices"]), 0)
        self.assertFalse(index["client_statistics"])

    def test_manifest_cannot_escape_repository(self):
        parent = self.root / "analysis_results/network_communities"
        parent.mkdir()
        (parent / "all_rounds_manifest.json").write_text(json.dumps({"run_manifests": ["../outside.json"]}))
        with self.assertRaisesRegex(ValueError, "escapes repository"):
            build_research_bundle(self.root, self.output)

    def test_deployed_bundle_preserves_all_source_cells_and_hashes(self):
        root = Path(__file__).resolve().parents[1]
        output = root / "vote_explorer_web/web_data/research"
        index = json.loads((output / "index.json").read_text(encoding="utf-8"))
        actual = defaultdict(Counter)
        sources = {}
        def signature(row):
            return json.dumps(row, ensure_ascii=False, sort_keys=True)
        for entry in index["entries"]:
            data = (output / entry["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"])
            payload = json.loads(data)
            self.assertEqual(len(payload["values"]), entry["rows"])
            sources.update({s["source_path"]: s for s in payload["sources"]})
            for values in payload["values"]:
                row = dict(payload["defaults"], **dict(zip(payload["columns"], values)))
                original = {k: v for k, v in row.items() if not k.startswith("web_")}
                actual[row["web_source_path"]][signature(original)] += 1
        for name, source in sources.items():
            path = root / name
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), source["sha256"])
            with path.open(encoding="utf-8-sig", newline="") as handle:
                expected = Counter(signature(row) for row in csv.DictReader(handle))
            self.assertEqual(actual[name], expected, name)
        self.assertEqual(sum(sum(rows.values()) for rows in actual.values()), index["total_rows"])


if __name__ == "__main__":
    unittest.main()
