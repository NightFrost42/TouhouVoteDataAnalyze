from __future__ import annotations

import csv
import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "scripts_pipeline"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import build_character_structure_metadata as structure  # noqa: E402


class CharacterStructureMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.crosswalk = structure.read_csv(structure.CROSSWALK_PATH)
        cls.reference = structure.read_csv(structure.REFERENCE_PATH)
        cls.overrides = structure.read_csv(structure.OVERRIDES_PATH)
        cls.metadata = structure.read_csv(structure.OUTPUT_PATH)
        cls.audit = structure.read_csv(structure.AUDIT_PATH)
        cls.manifest = json.loads(structure.MANIFEST_PATH.read_text(encoding="utf-8"))

    @staticmethod
    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def test_crosswalk_is_the_complete_primary_roster(self) -> None:
        expected = {
            (
                structure.normalize_name(row["character_cn"]),
                row["character_jp_normalized"].strip(),
            )
            for row in self.crosswalk
        }
        actual = {(row["canonical_name"], row["crosswalk_key"]) for row in self.metadata}
        self.assertEqual(len(self.metadata), len(self.crosswalk))
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), len(self.metadata))
        self.assertTrue(self.manifest["scope"]["primary_key_unique"])

    def test_no_analysis_entity_expansion(self) -> None:
        crosswalk_names = {structure.normalize_name(row["character_cn"]) for row in self.crosswalk}
        metadata_names = {row["canonical_name"] for row in self.metadata}
        self.assertEqual(metadata_names, crosswalk_names)
        self.assertFalse(
            any(row["crosswalk_table_path"] != "metadata/character_name_crosswalk.csv" for row in self.metadata)
        )

    def test_reference_matches_are_deterministic_and_source_limited(self) -> None:
        for row in self.metadata:
            expected, status = structure.match_reference(
                next(item for item in self.crosswalk if item["character_cn"] == row["canonical_name_cn"]),
                self.reference,
            )
            self.assertEqual(row["reference_match_status"], status, row["canonical_name_cn"])
            if expected is None:
                self.assertEqual(row["reference_source_path"], "")
                self.assertEqual(row["reference_source_url"], "")
            else:
                self.assertEqual(row["reference_source_path"], "metadata/thbwiki_official_character_list.csv")
                self.assertEqual(row["reference_source_url"], expected["thbwiki_url"])
                self.assertEqual(row["reference_list_standard"], expected["list_standard"])

    def test_manual_ledger_is_explicit_and_provenanced(self) -> None:
        crosswalk_names = {row["character_cn"] for row in self.crosswalk}
        seen: set[tuple[str, str, str]] = set()
        for row in self.overrides:
            self.assertIn(row["canonical_name_cn"], crosswalk_names)
            self.assertIn(row["attribute"], structure.ALLOWED_OVERRIDE_ATTRIBUTES)
            self.assertTrue(row["value"])
            for field in ("basis", "source", "version"):
                self.assertTrue(row[field], (row, field))
            lower_source = row["source"].casefold()
            self.assertFalse(
                any(fragment in lower_source for fragment in structure.FORBIDDEN_SOURCE_FRAGMENTS),
                row["source"],
            )
            key = (row["canonical_name_cn"], row["attribute"], row["value"])
            self.assertNotIn(key, seen)
            seen.add(key)

    def test_every_audited_field_has_one_row_and_matches_wide_table(self) -> None:
        expected_audit_keys = {
            (row["canonical_name"], row["crosswalk_key"], attribute)
            for row in self.metadata
            for attribute in structure.AUDITED_ATTRIBUTES
        }
        actual_audit_keys = {
            (row["canonical_name"], row["crosswalk_key"], row["attribute"])
            for row in self.audit
        }
        self.assertEqual(actual_audit_keys, expected_audit_keys)
        self.assertEqual(len(self.audit), len(expected_audit_keys))

        by_key = {
            (row["canonical_name"], row["crosswalk_key"], row["attribute"]): row
            for row in self.audit
        }
        for metadata_row in self.metadata:
            for attribute in structure.AUDITED_ATTRIBUTES:
                audit_row = by_key[(metadata_row["canonical_name"], metadata_row["crosswalk_key"], attribute)]
                self.assertEqual(audit_row["value"], metadata_row[attribute], attribute)
                if audit_row["value"]:
                    self.assertTrue(audit_row["basis"], audit_row)
                    self.assertTrue(audit_row["source"], audit_row)
                    self.assertTrue(audit_row["version"], audit_row)
                    self.assertTrue(audit_row["source_sha256"], audit_row)
                else:
                    self.assertEqual(audit_row["value_status"], "unverified_blank")
                    self.assertEqual(audit_row["basis"], "")
                    self.assertEqual(audit_row["source"], "")
                    self.assertEqual(audit_row["version"], "")
                    self.assertEqual(audit_row["source_sha256"], "")

    def test_stage_and_boss_identity_are_not_guessed(self) -> None:
        self.assertTrue(all(not row["stage"] for row in self.metadata))
        self.assertTrue(all(not row["boss_identity"] for row in self.metadata))
        for row in self.audit:
            if row["attribute"] in {"stage", "boss_identity"}:
                self.assertEqual(row["value"], "")
                self.assertEqual(row["value_status"], "unverified_blank")

    def test_forbidden_community_sources_do_not_enter_outputs(self) -> None:
        for row in self.audit:
            source = row["source"].casefold()
            self.assertFalse(
                any(fragment in source for fragment in structure.FORBIDDEN_SOURCE_FRAGMENTS),
                row,
            )
        for row in self.metadata:
            self.assertNotIn("analysis_results/community_poll_alignment", row["reference_source_path"])
            self.assertNotIn("analysis_character_factions.csv", row["reference_source_path"])

    def test_manifest_hashes_counts_and_coverage(self) -> None:
        inputs = self.manifest["inputs"]
        for path in (
            structure.CROSSWALK_PATH,
            structure.REFERENCE_PATH,
            structure.OVERRIDES_PATH,
        ):
            relative = path.relative_to(ROOT).as_posix()
            self.assertEqual(inputs[relative]["sha256"], self.sha256(path))
        outputs = self.manifest["outputs"]
        self.assertEqual(outputs[structure.OUTPUT_PATH.relative_to(ROOT).as_posix()]["rows"], len(self.metadata))
        self.assertEqual(outputs[structure.AUDIT_PATH.relative_to(ROOT).as_posix()]["rows"], len(self.audit))
        self.assertEqual(
            outputs[structure.OUTPUT_PATH.relative_to(ROOT).as_posix()]["sha256"],
            self.sha256(structure.OUTPUT_PATH),
        )
        self.assertEqual(
            outputs[structure.AUDIT_PATH.relative_to(ROOT).as_posix()]["sha256"],
            self.sha256(structure.AUDIT_PATH),
        )
        for attribute in structure.AUDITED_ATTRIBUTES:
            expected_populated = sum(bool(row[attribute]) for row in self.metadata)
            self.assertEqual(self.manifest["field_coverage"][attribute]["populated"], expected_populated)
            self.assertEqual(
                self.manifest["field_coverage"][attribute]["blank"],
                len(self.metadata) - expected_populated,
            )


if __name__ == "__main__":
    unittest.main()
