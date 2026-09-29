#!/usr/bin/env python3
"""Build per-round structural features for the observed character co-vote pairs.

Only pairs already present in the co-vote table are materialised.  Structural
attributes are compared independently: a missing or ambiguous value on either
endpoint yields ``unknown`` for that feature rather than ``false``.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METADATA_PATH = ROOT / "metadata" / "character_structure_metadata.csv"
DEFAULT_COVOTE_PATH = ROOT / "vote_explorer" / "data" / "analysis_covote_pairs_all.csv"
DEFAULT_OUTPUT_PATH = ROOT / "vote_explorer" / "data" / "analysis_character_pair_structure_features_all.csv"

# These are the audited, roster-level attributes in character_structure_metadata.
# Identity/provenance fields are deliberately not compared as structural
# features, but the endpoint values are retained for auditability.
STRUCTURE_ATTRIBUTES = (
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
SET_ATTRIBUTES = frozenset({"region", "community"})
METADATA_IDENTITY_FIELDS = (
    "canonical_name",
    "canonical_name_cn",
    "crosswalk_key",
    "character_jp",
    "character_jp_normalized",
)
UNKNOWN_TOKENS = frozenset(
    {
        "",
        "unknown",
        "unk",
        "na",
        "n/a",
        "null",
        "none",
        "未确认",
        "未知",
        "不详",
        "未提供",
        "unverified",
        "unverified_blank",
    }
)

# The first fields keep the link back to the exact observed co-vote row.  The
# alias pair_key is retained for lightweight consumers; canonical_pair_key is
# the contract shared with analysis_covote_pairs_all.csv.
BASE_FIELDS = (
    "region",
    "round",
    "round_label",
    "pair_category",
    "canonical_pair_key",
    "pair_key",
    "name_a",
    "name_b",
    "name_a_cn",
    "name_b_cn",
    "canonical_a",
    "canonical_b",
    "metadata_a_status",
    "metadata_b_status",
    "pair_metadata_status",
    "intersection_count",
    "data_completeness",
    "censoring_status",
    "source_type",
    "source_path",
)
ENDPOINT_FIELDS = tuple(
    field
    for attribute in STRUCTURE_ATTRIBUTES
    for field in (f"a_{attribute}", f"b_{attribute}")
)
FEATURE_FIELDS = tuple(f"same_{attribute}" for attribute in STRUCTURE_ATTRIBUTES) + tuple(
    field
    for attribute in SET_ATTRIBUTES
    for field in (f"shared_{attribute}", f"common_{attribute}")
)
# Short aliases make the table convenient for callers that do not need to know
# that these values originate in the reference-index-prefixed columns.
FEATURE_ALIASES = (
    "same_first_appearance_work",
    "same_character_type",
    "same_source_group",
)
OUTPUT_FIELDS = BASE_FIELDS + ENDPOINT_FIELDS + FEATURE_FIELDS + FEATURE_ALIASES


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[Mapping[str, object]], fields: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalize_name(value: object) -> str:
    """Use the analysis identity normalization without empty-key matches."""
    return re.sub(r"[\s・･·\-—_]+", "", str(value or ""))


def character_key(value: object) -> str:
    """Normalize width/case/punctuation for deterministic character identity."""
    return normalize_name(unicodedata.normalize("NFKC", str(value or "")).casefold())


def canonical_pair_key(canonical_a: object, canonical_b: object) -> str:
    """Return an unordered, stable key for two canonical endpoint IDs."""
    values = [character_key(canonical_a), character_key(canonical_b)]
    if not all(values) or values[0] == values[1]:
        return ""
    return "|".join(sorted(values))


def _clean(value: object) -> str:
    return str(value or "").strip()


def _is_unknown(value: object) -> bool:
    return _clean(value).casefold() in UNKNOWN_TOKENS


def _comparison_key(value: object) -> str:
    # Structural values are categorical.  Ignore presentation punctuation and
    # width differences, but never turn a missing value into a real category.
    return character_key(value)


def _split_values(value: object) -> set[str] | None:
    """Return a known set value, or None when the set itself is unknown."""
    raw = _clean(value)
    if _is_unknown(raw):
        return None
    parts = {_comparison_key(part) for part in re.split(r"\s*;\s*", raw) if _clean(part)}
    return parts or None


def _display_set(value: object) -> list[str] | None:
    raw = _clean(value)
    if _is_unknown(raw):
        return None
    parts: list[str] = []
    for part in re.split(r"\s*;\s*", raw):
        part = _clean(part)
        if part and part not in parts:
            parts.append(part)
    return parts or None


def _same_value(value_a: object, value_b: object, *, set_mode: bool = False) -> str:
    if set_mode:
        set_a, set_b = _split_values(value_a), _split_values(value_b)
        if set_a is None or set_b is None:
            return "unknown"
        return "true" if set_a == set_b else "false"
    if _is_unknown(value_a) or _is_unknown(value_b):
        return "unknown"
    return "true" if _comparison_key(value_a) == _comparison_key(value_b) else "false"


def _shared_value(value_a: object, value_b: object) -> tuple[str, str]:
    set_a, set_b = _split_values(value_a), _split_values(value_b)
    if set_a is None or set_b is None:
        return "unknown", ""
    common_keys = set_a & set_b
    if not common_keys:
        return "false", ""
    display_a = _display_set(value_a) or []
    display_b = _display_set(value_b) or []
    display_by_key = {_comparison_key(value): value for value in display_a + display_b}
    common = ";".join(display_by_key[key] for key in sorted(common_keys))
    return "true", common


def _metadata_index(rows: list[dict[str, str]]) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    direct: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        for field in METADATA_IDENTITY_FIELDS:
            key = character_key(row.get(field, ""))
            if key and index not in direct[key]:
                direct[key].append(index)

    aliases: dict[str, list[int]] = defaultdict(list)
    alias_path = ROOT / "metadata" / "character_translation_aliases_cn.csv"
    if alias_path.exists():
        for alias_row in read_csv(alias_path):
            alias = character_key(alias_row.get("alias_cn", ""))
            target = character_key(alias_row.get("canonical_cn", ""))
            if not alias or not target:
                continue
            for index in direct.get(target, []):
                if index not in aliases[alias]:
                    aliases[alias].append(index)
    return direct, aliases


def _resolve_metadata(
    pair_row: Mapping[str, object],
    side: str,
    metadata: list[dict[str, str]],
    direct: Mapping[str, list[int]],
    aliases: Mapping[str, list[int]],
) -> tuple[dict[str, str] | None, str]:
    candidates = (
        pair_row.get(f"canonical_{side}", ""),
        pair_row.get(f"name_{side}_cn", ""),
        pair_row.get(f"name_{side}", ""),
    )
    hits: set[int] = set()
    for candidate in candidates:
        key = character_key(candidate)
        if not key:
            continue
        hits.update(direct.get(key, []))
        hits.update(aliases.get(key, []))
    if len(hits) == 1:
        return metadata[next(iter(hits))], "confirmed"
    if len(hits) > 1:
        return None, "ambiguous"
    return None, "missing"


def _is_music_covote_row(row: Mapping[str, object]) -> bool:
    category = _clean(row.get("pair_category", ""))
    if category:
        return category == "music"
    return _clean(row.get("source_type", "")) == "cn10_11_official_music_covote_matrix"


def _source_key(row: Mapping[str, object]) -> str:
    existing = _clean(row.get("canonical_pair_key", ""))
    if existing:
        return existing
    return canonical_pair_key(
        row.get("canonical_a") or row.get("name_a_cn") or row.get("name_a"),
        row.get("canonical_b") or row.get("name_b_cn") or row.get("name_b"),
    )


def _endpoint_order(row: Mapping[str, object]) -> tuple[int, int]:
    a = character_key(row.get("canonical_a") or row.get("name_a_cn") or row.get("name_a"))
    b = character_key(row.get("canonical_b") or row.get("name_b_cn") or row.get("name_b"))
    if a <= b:
        return 0, 1
    return 1, 0


def _get_endpoint(row: Mapping[str, object], side: str, index: int) -> object:
    return row.get(f"{side}_{index}", "")


def _row_order(row: Mapping[str, object]) -> tuple:
    completeness = _clean(row.get("data_completeness", ""))
    completeness_rank = {"complete_matrix": 0, "official_published_leading_list": 1}.get(completeness, 2)
    try:
        intersection = -float(row.get("intersection_count") or 0)
    except (TypeError, ValueError):
        intersection = 0.0
    return (
        _clean(row.get("region", "")),
        _clean(row.get("round", "")),
        _source_key(row),
        completeness_rank,
        intersection,
        _clean(row.get("source_type", "")),
        _clean(row.get("source_path", "")),
    )


def build_character_pair_structure_features(
    covote_rows: list[dict[str, str]],
    metadata_rows: list[dict[str, str]] | None = None,
    *,
    metadata_path: Path = DEFAULT_METADATA_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> list[dict[str, str]]:
    """Build one structural-feature row for each observed character pair.

    The function never creates unobserved combinations.  It keeps a pair when
    one endpoint or one attribute is unresolved, but emits ``unknown`` for the
    affected feature so downstream code can distinguish unknown from a proven
    difference.
    """
    metadata = metadata_rows if metadata_rows is not None else (read_csv(metadata_path) if metadata_path.exists() else [])
    direct, aliases = _metadata_index(metadata)

    # Existing datasets generated before canonical_pair_key may contain both
    # directions.  Sort first, then retain one deterministic source row.
    observed: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in sorted(covote_rows, key=_row_order):
        if _is_music_covote_row(row):
            continue
        category = _clean(row.get("pair_category", "")) or "character"
        if category != "character":
            continue
        pair_key = _source_key(row)
        if not pair_key:
            continue
        region, round_value = _clean(row.get("region", "")), _clean(row.get("round", ""))
        if not region or not round_value:
            continue
        observed.setdefault((region, round_value, pair_key), row)

    output: list[dict[str, str]] = []
    for (_, _, pair_key), source_row in sorted(observed.items()):
        metadata_a, status_a = _resolve_metadata(source_row, "a", metadata, direct, aliases)
        metadata_b, status_b = _resolve_metadata(source_row, "b", metadata, direct, aliases)
        source_order = _endpoint_order(source_row)
        source_sides = ("a", "b")
        ordered_sides = (source_sides[source_order[0]], source_sides[source_order[1]])
        endpoints = (metadata_a, metadata_b)
        ordered_metadata = (endpoints[source_order[0]], endpoints[source_order[1]])
        statuses = (status_a, status_b)
        ordered_statuses = (statuses[source_order[0]], statuses[source_order[1]])

        if all(status == "confirmed" for status in ordered_statuses):
            pair_status = "confirmed"
        elif any(status == "ambiguous" for status in ordered_statuses):
            pair_status = "ambiguous"
        elif any(status == "confirmed" for status in ordered_statuses):
            pair_status = "partial"
        else:
            pair_status = "missing"

        row: dict[str, str] = {
            "region": _clean(source_row.get("region", "")),
            "round": _clean(source_row.get("round", "")),
            "round_label": _clean(source_row.get("round_label", "")),
            "pair_category": "character",
            "canonical_pair_key": pair_key,
            "pair_key": pair_key,
            "name_a": _clean(source_row.get(f"name_{ordered_sides[0]}", "")),
            "name_b": _clean(source_row.get(f"name_{ordered_sides[1]}", "")),
            "name_a_cn": _clean(source_row.get(f"name_{ordered_sides[0]}_cn", "")),
            "name_b_cn": _clean(source_row.get(f"name_{ordered_sides[1]}_cn", "")),
            "canonical_a": _clean(source_row.get(f"canonical_{ordered_sides[0]}", "")),
            "canonical_b": _clean(source_row.get(f"canonical_{ordered_sides[1]}", "")),
            "metadata_a_status": ordered_statuses[0],
            "metadata_b_status": ordered_statuses[1],
            "pair_metadata_status": pair_status,
            "intersection_count": _clean(source_row.get("intersection_count", "")),
            "data_completeness": _clean(source_row.get("data_completeness", "")),
            "censoring_status": _clean(source_row.get("censoring_status", "")),
            "source_type": _clean(source_row.get("source_type", "")),
            "source_path": _clean(source_row.get("source_path", "")),
        }

        for endpoint_prefix, metadata_row in (("a", ordered_metadata[0]), ("b", ordered_metadata[1])):
            for attribute in STRUCTURE_ATTRIBUTES:
                row[f"{endpoint_prefix}_{attribute}"] = _clean(
                    metadata_row.get(attribute, "") if metadata_row else ""
                )

        for attribute in STRUCTURE_ATTRIBUTES:
            value_a, value_b = row[f"a_{attribute}"], row[f"b_{attribute}"]
            row[f"same_{attribute}"] = _same_value(
                value_a, value_b, set_mode=attribute in SET_ATTRIBUTES
            )
            if attribute in SET_ATTRIBUTES:
                shared, common = _shared_value(value_a, value_b)
                row[f"shared_{attribute}"] = shared
                row[f"common_{attribute}"] = common

        row["same_first_appearance_work"] = row["same_reference_first_appearance_work"]
        row["same_character_type"] = row["same_reference_character_type"]
        row["same_source_group"] = row["same_reference_source_group"]
        output.append(row)

    output.sort(key=lambda row: (
        row["region"],
        int(float(row["round"])) if row["round"].replace(".", "", 1).isdigit() else row["round"],
        row["canonical_pair_key"],
    ))
    write_csv(output_path, output, OUTPUT_FIELDS)
    return output


def build_from_files(
    *,
    covote_path: Path = DEFAULT_COVOTE_PATH,
    metadata_path: Path = DEFAULT_METADATA_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> list[dict[str, str]]:
    """Read the checked-in tables and write the structural feature output."""
    covote_rows = read_csv(covote_path) if covote_path.exists() else []
    return build_character_pair_structure_features(
        covote_rows,
        metadata_path=metadata_path,
        output_path=output_path,
    )


def main() -> None:
    rows = build_from_files()
    print(f"character pair structure feature rows: {len(rows)}")


if __name__ == "__main__":
    main()
