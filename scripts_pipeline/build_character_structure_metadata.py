#!/usr/bin/env python3
"""Build auditable character-structure metadata from approved local sources.

The current character crosswalk defines the roster and composite key.  Saved
THBWiki rows are reference-index context only, not official certification.
Human-coded structural values must come from the dedicated override ledger and
must carry basis/source/version.  Missing values remain empty.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
METADATA = ROOT / "metadata"
CROSSWALK_PATH = METADATA / "character_name_crosswalk.csv"
REFERENCE_PATH = METADATA / "thbwiki_official_character_list.csv"
OVERRIDES_PATH = METADATA / "character_structure_manual_overrides.csv"
OUTPUT_PATH = METADATA / "character_structure_metadata.csv"
AUDIT_PATH = METADATA / "character_structure_field_audit.csv"
MANIFEST_PATH = METADATA / "character_structure_metadata_manifest.json"

SCHEMA_VERSION = 1
CODING_VERSION = "character-structure-v1"
REFERENCE_SOURCE_LABEL = "THBWiki saved character reference index; not official certification"
ALLOWED_OVERRIDE_ATTRIBUTES = {"stage", "boss_identity", "region", "community"}
FORBIDDEN_SOURCE_FRAGMENTS = (
    "analysis_results/community_poll_alignment",
    "analysis_character_factions.csv",
    "bilibili",
    "tieba",
    "pixiv",
    "character_community_tag_coverage",
    "community_detection",
    "network_cluster",
)
AUDITED_ATTRIBUTES = (
    "crosswalk_first_appearance_work_id",
    "reference_first_appearance_work",
    "reference_identity_or_title",
    "reference_character_type",
    "reference_source_group",
    "stage",
    "boss_identity",
    "region",
    "region_type",
    "community",
    "community_type",
)
MAIN_FIELDS = (
    "canonical_name",
    "canonical_name_cn",
    "crosswalk_key",
    "character_jp",
    "character_jp_normalized",
    "crosswalk_first_appearance_work_id",
    "reference_first_appearance_work",
    "reference_identity_or_title",
    "reference_character_type",
    "reference_source_group",
    "stage",
    "boss_identity",
    "region",
    "region_type",
    "community",
    "community_type",
    "reference_match_status",
    "crosswalk_table_path",
    "crosswalk_source_path",
    "crosswalk_source_sheet",
    "reference_source_path",
    "reference_source_url",
    "reference_snapshot_date",
    "reference_list_standard",
    "metadata_status",
)
AUDIT_FIELDS = (
    "canonical_name",
    "canonical_name_cn",
    "crosswalk_key",
    "attribute",
    "value",
    "value_status",
    "basis",
    "source",
    "version",
    "source_sha256",
    "match_status",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict[str, str]], fields: Iterable[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_name(value: str) -> str:
    """Match the existing analysis canonical-name normalization exactly."""
    return re.sub(r"[\s・･·\-—_]+", "", value or "").casefold()


def unique_match(rows: list[dict[str, str]], field: str, value: str) -> tuple[dict[str, str] | None, str]:
    if not value:
        return None, "unmatched"
    candidates = [row for row in rows if row.get(field, "").strip() == value]
    if len(candidates) == 1:
        return candidates[0], "matched"
    if len(candidates) > 1:
        return None, "ambiguous"
    return None, "unmatched"


def match_reference(
    crosswalk_row: dict[str, str], reference_rows: list[dict[str, str]]
) -> tuple[dict[str, str] | None, str]:
    """Use exact keys first and one conservative normalization fallback.

    The function never consults aliases, substrings, rankings, tags, or
    community-analysis output.  An ambiguous candidate set is rejected.
    """
    canonical_cn = crosswalk_row.get("character_cn", "").strip()
    character_jp = crosswalk_row.get("character_jp", "").strip()
    attempts = (
        ("character_key_thb", canonical_cn, "exact_character_key_thb"),
        ("canonical_cn_fun", canonical_cn, "exact_canonical_cn_fun"),
        ("character_jp", character_jp, "exact_character_jp"),
    )
    for field, value, status in attempts:
        candidate, result = unique_match(reference_rows, field, value)
        if result == "matched":
            return candidate, status
        if result == "ambiguous":
            return None, f"ambiguous_{status}"

    normalized_jp = normalize_name(
        crosswalk_row.get("character_jp_normalized", "").strip() or character_jp
    )
    if normalized_jp:
        candidates = [
            row
            for row in reference_rows
            if normalize_name(row.get("character_jp", "").strip()) == normalized_jp
        ]
        if len(candidates) == 1:
            return candidates[0], "normalized_character_jp"
        if len(candidates) > 1:
            return None, "ambiguous_normalized_character_jp"
    return None, "unmatched"


def load_overrides(
    crosswalk_rows: list[dict[str, str]],
) -> tuple[dict[str, dict[str, list[dict[str, str]]]], list[dict[str, str]]]:
    canonical_names = {row.get("character_cn", "").strip() for row in crosswalk_rows}
    grouped: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
    rejected: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for row_number, raw in enumerate(read_csv(OVERRIDES_PATH), 2):
        row = {key: (value or "").strip() for key, value in raw.items()}
        canonical = row.get("canonical_name_cn", "")
        attribute = row.get("attribute", "")
        value = row.get("value", "")
        reason = ""
        if canonical not in canonical_names:
            reason = "canonical_name_not_in_crosswalk"
        elif attribute not in ALLOWED_OVERRIDE_ATTRIBUTES:
            reason = "attribute_not_allowed"
        elif not value:
            reason = "blank_value"
        elif not all(row.get(field) for field in ("basis", "source", "version")):
            reason = "missing_basis_source_or_version"
        elif any(fragment in row.get("source", "").casefold() for fragment in FORBIDDEN_SOURCE_FRAGMENTS):
            reason = "forbidden_analysis_source"
        elif (canonical, attribute, value) in seen:
            reason = "duplicate_override"

        if reason:
            rejected.append({**row, "row_number": str(row_number), "rejection_reason": reason})
            continue
        seen.add((canonical, attribute, value))
        grouped[canonical][attribute].append(row)

    return grouped, rejected


def joined_override_values(rows: list[dict[str, str]], field: str) -> str:
    values: list[str] = []
    for row in rows:
        value = row.get(field, "").strip()
        if value and value not in values:
            values.append(value)
    return ";".join(values)


def source_hash(source: str, fallback: str) -> str:
    for item in source.split(";"):
        candidate = item.strip().split("#", 1)[0]
        path = ROOT / candidate
        if candidate and path.is_file():
            return sha256(path)
    return fallback


def reference_audit(
    row: dict[str, str],
    attribute: str,
    source_sha: str,
) -> dict[str, str]:
    value = row.get(attribute, "")
    if not value:
        return blank_audit(row, attribute, "no_approved_reference_value")
    source = row["reference_source_path"]
    if row.get("reference_source_url"):
        source += f";{row['reference_source_url']}"
    return {
        "canonical_name": row["canonical_name"],
        "canonical_name_cn": row["canonical_name_cn"],
        "crosswalk_key": row["crosswalk_key"],
        "attribute": attribute,
        "value": value,
        "value_status": "reference_index_value",
        "basis": "Direct copy from the matched saved reference-index row; not treated as official certification.",
        "source": source,
        "version": f"thbwiki-index-{row.get('reference_snapshot_date') or 'snapshot-undated'}",
        "source_sha256": source_sha,
        "match_status": row["reference_match_status"],
    }


def blank_audit(row: dict[str, str], attribute: str, match_status: str) -> dict[str, str]:
    return {
        "canonical_name": row["canonical_name"],
        "canonical_name_cn": row["canonical_name_cn"],
        "crosswalk_key": row["crosswalk_key"],
        "attribute": attribute,
        "value": "",
        "value_status": "unverified_blank",
        "basis": "",
        "source": "",
        "version": "",
        "source_sha256": "",
        "match_status": match_status,
    }


def build() -> tuple[list[dict[str, str]], list[dict[str, str]], dict]:
    crosswalk_rows = read_csv(CROSSWALK_PATH)
    reference_rows = read_csv(REFERENCE_PATH)
    overrides, rejected_overrides = load_overrides(crosswalk_rows)

    crosswalk_sha = sha256(CROSSWALK_PATH)
    reference_sha = sha256(REFERENCE_PATH)
    overrides_sha = sha256(OVERRIDES_PATH)
    source_script_sha = sha256(ROOT / "scripts_pipeline" / "build_vote_explorer_analysis_data.py")

    output: list[dict[str, str]] = []
    audit: list[dict[str, str]] = []
    primary_keys: set[tuple[str, str]] = set()

    for crosswalk in crosswalk_rows:
        canonical_cn = crosswalk.get("character_cn", "").strip()
        canonical_name = normalize_name(canonical_cn)
        crosswalk_key = crosswalk.get("character_jp_normalized", "").strip()
        key = (canonical_name, crosswalk_key)
        if not canonical_name or not crosswalk_key:
            raise ValueError(f"Blank primary-key component in crosswalk row: {crosswalk!r}")
        if key in primary_keys:
            raise ValueError(f"Duplicate character-structure primary key: {key!r}")
        primary_keys.add(key)

        reference, match_status = match_reference(crosswalk, reference_rows)
        reference = reference or {}
        manual = overrides.get(canonical_cn, {})
        region_rows = manual.get("region", [])
        community_rows = manual.get("community", [])
        stage_rows = manual.get("stage", [])
        boss_rows = manual.get("boss_identity", [])
        has_manual = any((region_rows, community_rows, stage_rows, boss_rows))
        has_reference = bool(reference)

        if has_reference and has_manual:
            metadata_status = "reference_and_manual"
        elif has_reference:
            metadata_status = "reference_only"
        elif has_manual:
            metadata_status = "manual_only"
        else:
            metadata_status = "crosswalk_only"

        row = {
            "canonical_name": canonical_name,
            "canonical_name_cn": canonical_cn,
            "crosswalk_key": crosswalk_key,
            "character_jp": crosswalk.get("character_jp", "").strip(),
            "character_jp_normalized": crosswalk_key,
            "crosswalk_first_appearance_work_id": crosswalk.get("first_appearance_work_id", "").strip(),
            "reference_first_appearance_work": reference.get("first_appearance", "").strip(),
            "reference_identity_or_title": reference.get("reference_identity_or_title", "").strip(),
            "reference_character_type": reference.get("character_type_thb", "").strip(),
            "reference_source_group": reference.get("source_group_thb", "").strip(),
            "stage": joined_override_values(stage_rows, "value"),
            "boss_identity": joined_override_values(boss_rows, "value"),
            "region": joined_override_values(region_rows, "value"),
            "region_type": joined_override_values(region_rows, "value_type"),
            "community": joined_override_values(community_rows, "value"),
            "community_type": joined_override_values(community_rows, "value_type"),
            "reference_match_status": match_status,
            "crosswalk_table_path": CROSSWALK_PATH.relative_to(ROOT).as_posix(),
            "crosswalk_source_path": crosswalk.get("source_path", "").strip(),
            "crosswalk_source_sheet": crosswalk.get("source_sheet", "").strip(),
            "reference_source_path": REFERENCE_PATH.relative_to(ROOT).as_posix() if reference else "",
            "reference_source_url": reference.get("thbwiki_url", "").strip(),
            "reference_snapshot_date": reference.get("observation_date", "").strip(),
            "reference_list_standard": reference.get("list_standard", "").strip(),
            "metadata_status": metadata_status,
        }
        output.append(row)

        work_id = row["crosswalk_first_appearance_work_id"]
        if work_id:
            audit.append({
                "canonical_name": canonical_name,
                "canonical_name_cn": canonical_cn,
                "crosswalk_key": crosswalk_key,
                "attribute": "crosswalk_first_appearance_work_id",
                "value": work_id,
                "value_status": "crosswalk_source_value",
                "basis": "Direct copy from the current crosswalk; no work title is inferred from the numeric code.",
                "source": f"{CROSSWALK_PATH.relative_to(ROOT).as_posix()};{row['crosswalk_source_path']}#{row['crosswalk_source_sheet']}",
                "version": f"character-crosswalk-sha256-{crosswalk_sha[:12]}",
                "source_sha256": crosswalk_sha,
                "match_status": "crosswalk_row",
            })
        else:
            audit.append(blank_audit(row, "crosswalk_first_appearance_work_id", "crosswalk_value_blank"))

        for attribute in (
            "reference_first_appearance_work",
            "reference_identity_or_title",
            "reference_character_type",
            "reference_source_group",
        ):
            audit.append(reference_audit(row, attribute, reference_sha))

        for attribute, manual_rows, derived_field in (
            ("stage", stage_rows, "value"),
            ("boss_identity", boss_rows, "value"),
            ("region", region_rows, "value"),
            ("region_type", region_rows, "value_type"),
            ("community", community_rows, "value"),
            ("community_type", community_rows, "value_type"),
        ):
            value = row[attribute]
            if not value:
                audit.append(blank_audit(row, attribute, "no_approved_manual_override"))
                continue
            source = joined_override_values(manual_rows, "source")
            audit.append({
                "canonical_name": canonical_name,
                "canonical_name_cn": canonical_cn,
                "crosswalk_key": crosswalk_key,
                "attribute": attribute,
                "value": value,
                "value_status": "manual_coded_value",
                "basis": joined_override_values(manual_rows, "basis"),
                "source": source,
                "version": joined_override_values(manual_rows, "version"),
                "source_sha256": source_hash(source, overrides_sha),
                "match_status": "exact_canonical_name_override",
            })

    write_csv(OUTPUT_PATH, output, MAIN_FIELDS)
    write_csv(AUDIT_PATH, audit, AUDIT_FIELDS)

    coverage = {
        attribute: {
            "populated": sum(bool(row.get(attribute, "")) for row in output),
            "blank": sum(not row.get(attribute, "") for row in output),
        }
        for attribute in AUDITED_ATTRIBUTES
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "coding_version": CODING_VERSION,
        "scope": {
            "roster_source": CROSSWALK_PATH.relative_to(ROOT).as_posix(),
            "primary_key": ["canonical_name", "crosswalk_key"],
            "rows": len(output),
            "primary_key_unique": len(primary_keys) == len(output),
        },
        "policy": {
            "unknown_values": "empty_string",
            "reference_index_note": REFERENCE_SOURCE_LABEL,
            "manual_values": "Accepted only from the exact-name override ledger with non-empty basis/source/version.",
            "prohibited_inference": "No vote, social-platform, tag, graph, network-cluster, or community-detection output may fill structure fields.",
            "forbidden_source_fragments": list(FORBIDDEN_SOURCE_FRAGMENTS),
        },
        "inputs": {
            CROSSWALK_PATH.relative_to(ROOT).as_posix(): {"rows": len(crosswalk_rows), "sha256": crosswalk_sha},
            REFERENCE_PATH.relative_to(ROOT).as_posix(): {"rows": len(reference_rows), "sha256": reference_sha},
            OVERRIDES_PATH.relative_to(ROOT).as_posix(): {
                "rows": sum(len(values) for attrs in overrides.values() for values in attrs.values()),
                "sha256": overrides_sha,
                "rejected_rows": rejected_overrides,
            },
            "scripts_pipeline/build_vote_explorer_analysis_data.py#FACTION_MEMBERS": {
                "sha256": source_script_sha,
                "usage": "Declared source of the pre-existing explicit manual affiliations copied into the override ledger; never parsed as a roster or inference input.",
            },
        },
        "reference_match_status": dict(sorted(Counter(row["reference_match_status"] for row in output).items())),
        "metadata_status": dict(sorted(Counter(row["metadata_status"] for row in output).items())),
        "field_coverage": coverage,
        "outputs": {
            OUTPUT_PATH.relative_to(ROOT).as_posix(): {"rows": len(output), "sha256": sha256(OUTPUT_PATH)},
            AUDIT_PATH.relative_to(ROOT).as_posix(): {"rows": len(audit), "sha256": sha256(AUDIT_PATH)},
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output, audit, manifest


def main() -> None:
    output, audit, manifest = build()
    print(f"character structure rows: {len(output)}")
    print(f"field audit rows: {len(audit)}")
    print(f"reference matches: {manifest['reference_match_status']}")
    print(f"stage populated: {manifest['field_coverage']['stage']['populated']}")
    print(f"boss identity populated: {manifest['field_coverage']['boss_identity']['populated']}")


if __name__ == "__main__":
    main()
