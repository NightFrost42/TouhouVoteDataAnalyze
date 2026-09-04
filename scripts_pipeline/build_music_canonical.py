"""Build traceable same-track merge groups from the user's repaired workbooks.

Same tracks reprinted in different works are intentionally merged.  Additive
fields are summed within site and poll round, while every contributing source
row is retained in a separate long table.  Cross-round values are never added.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd


WORKSPACE = Path(__file__).resolve().parents[1]
OUT_ROOT = WORKSPACE / "data_processed" / "music_canonical"
REPORT_PATH = WORKSPACE / "metadata" / "music_canonical_validation.json"
JP22_THEME_OVERLAY_PATH = WORKSPACE / "metadata" / "jp22_character_theme_tags.csv"

MANUAL_ALIASES = {
    "今宵是飘逸的利己主义者": "今宵是飘逸的自我主义者",
    "今宵是飘逸的自我主义者": "今宵是飘逸的自我主义者",
    "恋色Magic": "恋色Master spark",
    "恋色Magic（恋色Master spark）": "恋色Master spark",
    "恋色Master spark（恋色Magic）": "恋色Master spark",
    "仲夏的妖精梦": "盛夏的妖精梦",
    "盛夏的妖精梦": "盛夏的妖精梦",
}


def clean_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    return re.sub(r"\s+", " ", text)


def strip_song_suffix(value: Any) -> str:
    """Remove a display-only subtitle introduced by a wave-dash separator.

    Official Japanese result pages frequently append an English subtitle such
    as ``〜 Stone Goddess``.  It is useful provenance, so callers keep the raw
    title separately, but the canonical/display title should identify the
    song before that separator.  Treat all common wave-dash variants alike.
    """

    text = clean_text(value)
    return re.sub(r"[〜～~].*", "", text).strip()


def normalize_for_match(value: Any) -> str:
    """Follow the user's intended TouhouVoteMusic.py normalization."""
    text = strip_song_suffix(value)
    text = re.sub(r"[（(].*?[)）]", "", text)
    text = text.strip()
    return MANUAL_ALIASES.get(text, text)


def normalize_exact_title(value: Any) -> str:
    """Normalize a canonical title while retaining raw subtitle evidence elsewhere."""
    text = strip_song_suffix(value)
    return MANUAL_ALIASES.get(text, text)


def jp_title_key(value: Any) -> str:
    text = strip_song_suffix(value)
    text = re.sub(r"[（(].*?[)）]", "", text)
    return re.sub(r"\s+", "", text).casefold()


def group_id(title: str) -> str:
    digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]
    return f"music:{digest}"


def numeric(value: Any) -> float | int | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        converted = float(str(value).replace(",", ""))
        return int(converted) if converted.is_integer() else converted
    except ValueError:
        return None


def first_present(row: pd.Series, names: list[str]) -> Any:
    for name in names:
        if name in row.index and pd.notna(row[name]):
            return row[name]
    return None


def load_jp22_theme_overlay(path: Path = JP22_THEME_OVERLAY_PATH) -> tuple[
    dict[str, dict[str, str]], dict[str, dict[str, str]]
]:
    """Load traceable JP22 character-theme tags without editing the workbook.

    The repaired workbook remains authoritative.  This small, text-based
    overlay only fills titles that were not present there yet, and is keyed by
    both the official music id and the exact Japanese title so it works for
    normalized official rows as well as any future workbook export.
    """

    by_title: dict[str, dict[str, str]] = {}
    by_music_id: dict[str, dict[str, str]] = {}
    if not path.exists():
        return by_title, by_music_id
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "round",
            "character_id",
            "character_name_jp",
            "character_name_cn",
            "music_id",
            "music_name_jp",
            "music_name_cn",
            "thbwiki_url",
            "source_note",
            "confidence",
        }
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(
                f"JP22 character-theme overlay missing columns: {sorted(missing)!r}"
            )
        for raw in reader:
            record = {key: clean_text(value) for key, value in raw.items()}
            if record.get("round") != "22":
                raise ValueError(
                    f"JP22 character-theme overlay contains non-JP22 row: {record!r}"
                )
            if not record.get("music_id") or not record.get("music_name_jp"):
                raise ValueError(
                    f"JP22 character-theme overlay row lacks music identity: {record!r}"
                )
            title_key = normalize_exact_title(record["music_name_jp"])
            music_id = record["music_id"]
            if title_key in by_title or music_id in by_music_id:
                raise ValueError(
                    f"duplicate JP22 character-theme overlay key: {record!r}"
                )
            by_title[title_key] = record
            by_music_id[music_id] = record
    return by_title, by_music_id


def overlay_mapping(
    overlay: dict[str, str],
) -> dict[str, str]:
    """Adapt an overlay row to the same mapping shape as workbook records."""

    canonical_full = normalize_exact_title(overlay["music_name_cn"])
    if not canonical_full:
        canonical_full = normalize_exact_title(overlay["music_name_jp"])
    return {
        "jp": normalize_exact_title(overlay["music_name_jp"]),
        "canonical_full": canonical_full,
        "canonical_theme": normalize_for_match(canonical_full),
        "owner": overlay["character_name_cn"],
    }


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    mapping = pd.read_excel(WORKSPACE / "TouhouMusicInfo.xlsx")
    overlay_by_title, overlay_by_music_id = load_jp22_theme_overlay()
    mapping_rows: list[dict[str, str]] = []
    by_jp_exact: dict[str, dict[str, str]] = {}
    by_jp_theme_key: dict[str, dict[str, str]] = {}
    by_cn_exact: dict[str, dict[str, str]] = {}
    by_cn_theme_key: dict[str, dict[str, str]] = {}
    for _, row in mapping.iterrows():
        jp = clean_text(row.get("曲目"))
        cn_full = normalize_exact_title(row.get("译名"))
        cn_theme = normalize_for_match(row.get("译名"))
        owner = clean_text(row.get("所属角色"))
        if not cn_full:
            continue
        record = {
            "jp": jp,
            "canonical_full": cn_full,
            "canonical_theme": cn_theme,
            "owner": owner,
        }
        mapping_rows.append(record)
        if jp:
            by_jp_exact.setdefault(jp, record)
            # The user's repaired character-theme table is the authority for
            # merging titled variants.  Unowned generic prefixes (for example
            # two different tracks beginning "东方封魔录") are not merged.
            if owner:
                by_jp_theme_key.setdefault(jp_title_key(jp), record)
        by_cn_exact.setdefault(clean_text(cn_full).casefold(), record)
        if owner:
            by_cn_theme_key.setdefault(normalize_for_match(cn_full).casefold(), record)

    source_rows: list[dict[str, Any]] = []
    workbook_specs = [
        ("jp", WORKSPACE / "TouhouVote_music_jp.xlsx"),
        ("cn", WORKSPACE / "TouhouVote_music_cn.xlsx"),
    ]
    for site, workbook in workbook_specs:
        sheets = pd.read_excel(workbook, sheet_name=None)
        for sheet_name, frame in sheets.items():
            round_number = int(re.search(r"\d+", str(sheet_name)).group())
            for zero_index, row in frame.iterrows():
                raw_jp = clean_text(row.get("曲目")) if site == "jp" else ""
                raw_cn = clean_text(row.get("译名"))
                mapped: dict[str, str] | None = None
                merge_basis = "exact_title"
                if raw_jp:
                    mapped = by_jp_exact.get(raw_jp)
                    if mapped is not None:
                        merge_basis = "user_repaired_exact" if mapped["owner"] else "repaired_exact"
                    else:
                        mapped = by_jp_theme_key.get(jp_title_key(raw_jp))
                        if mapped is not None:
                            merge_basis = "user_repaired_theme"
                if mapped is None and raw_cn:
                    mapped = by_cn_exact.get(clean_text(raw_cn).casefold())
                    if mapped is not None:
                        merge_basis = "user_repaired_exact" if mapped["owner"] else "repaired_exact"
                    else:
                        mapped = by_cn_theme_key.get(normalize_for_match(raw_cn).casefold())
                        if mapped is not None:
                            merge_basis = "user_repaired_theme"
                if mapped is None and raw_jp:
                    overlay = overlay_by_title.get(normalize_exact_title(raw_jp))
                    if overlay is not None:
                        mapped = overlay_mapping(overlay)
                        merge_basis = "jp22_thbwiki_overlay"
                if mapped is not None:
                    canonical = (
                        mapped["canonical_theme"]
                        if mapped["owner"]
                        else mapped["canonical_full"]
                    )
                else:
                    canonical = normalize_exact_title(raw_cn or raw_jp)
                if not canonical:
                    canonical = raw_cn or raw_jp
                owner = mapped["owner"] if mapped else ""

                score = numeric(first_present(row, ["得票数", "票数"]))
                primary = numeric(first_present(row, ["本名票数", "本命数"]))
                comments = numeric(first_present(row, ["评论数"]))
                male = numeric(first_present(row, ["男性数", "男性"]))
                female = numeric(first_present(row, ["女性数", "女性"]))
                source_rows.append(
                    {
                        "site": site,
                        "round": round_number,
                        "source_kind": "user_repaired_workbook",
                        "source_file": workbook.name,
                        "source_record_id": "",
                        "source_sheet": str(sheet_name),
                        "source_excel_row": int(zero_index) + 2,
                        "source_rank": numeric(first_present(row, ["排名", "名次"])),
                        "raw_title_jp": raw_jp,
                        "raw_title_cn": raw_cn,
                        "canonical_track": canonical,
                        "merge_group_id": group_id(canonical),
                        "merge_basis": merge_basis,
                        "mapped_character": owner,
                        "score": score,
                        "primary_count": primary,
                        "comment_count": comments,
                        "male_count": male,
                        "female_count": female,
                    }
                )

    # The repaired workbooks remain authoritative wherever they contain a
    # round.  Supplement only wholly missing JP rounds from the normalized
    # official ranking table; this supplements rounds absent from the repaired
    # workbooks (currently JP21 and JP22) without changing any existing rows.
    existing_jp_rounds = {
        int(row["round"]) for row in source_rows if row["site"] == "jp"
    }
    official_jp_path = WORKSPACE / "data_processed" / "jp_official" / "rankings.csv"
    if official_jp_path.exists():
        official_jp = pd.read_csv(official_jp_path)
        official_jp = official_jp[official_jp["category"] == "music"]
        for _, row in official_jp.iterrows():
            round_number = int(row["round"])
            if round_number in existing_jp_rounds:
                continue
            raw_jp = clean_text(row.get("name"))
            mapped = by_jp_exact.get(raw_jp)
            merge_basis = "official_jp_exact_title"
            if mapped is not None:
                merge_basis = (
                    "official_jp_user_repaired_exact"
                    if mapped["owner"]
                    else "official_jp_repaired_exact"
                )
            else:
                mapped = by_jp_theme_key.get(jp_title_key(raw_jp))
                if mapped is not None:
                    merge_basis = "official_jp_user_repaired_theme"
            if mapped is None:
                overlay = overlay_by_music_id.get(clean_text(row.get("code")))
                if overlay is None:
                    overlay = overlay_by_title.get(normalize_exact_title(raw_jp))
                if overlay is not None:
                    mapped = overlay_mapping(overlay)
                    merge_basis = "official_jp_thbwiki_overlay"
            if mapped is not None:
                canonical = (
                    mapped["canonical_theme"]
                    if mapped["owner"]
                    else mapped["canonical_full"]
                )
                raw_cn = mapped["canonical_full"]
                owner = mapped["owner"]
            else:
                canonical = raw_jp
                raw_cn = ""
                owner = ""
            source_rows.append(
                {
                    "site": "jp",
                    "round": round_number,
                    "source_kind": "normalized_jp_official",
                    "source_file": official_jp_path.relative_to(WORKSPACE).as_posix(),
                    "source_record_id": clean_text(row.get("code")),
                    "source_sheet": f"official_ranking_round_{round_number}",
                    "source_excel_row": None,
                    "source_rank": numeric(row.get("rank")),
                    "raw_title_jp": raw_jp,
                    "raw_title_cn": raw_cn,
                    "canonical_track": canonical,
                    "merge_group_id": group_id(canonical),
                    "merge_basis": merge_basis,
                    "mapped_character": owner,
                    "score": numeric(row.get("point")),
                    "primary_count": numeric(row.get("primary_num")),
                    "comment_count": numeric(row.get("comment_num")),
                    "male_count": None,
                    "female_count": None,
                }
            )

    source = pd.DataFrame(source_rows)
    source.to_csv(OUT_ROOT / "local_music_source_rows.csv", index=False, encoding="utf-8-sig")
    supplemental_mapping_audit = source[
        source["source_kind"] == "normalized_jp_official"
    ][
        [
            "round",
            "source_rank",
            "source_record_id",
            "raw_title_jp",
            "raw_title_cn",
            "canonical_track",
            "merge_basis",
            "mapped_character",
        ]
    ].copy()
    supplemental_mapping_audit["matched_existing_repaired_mapping"] = ~(
        supplemental_mapping_audit["merge_basis"].isin(
            {"official_jp_exact_title", "official_jp_thbwiki_overlay"}
        )
    )
    supplemental_mapping_audit["mapped_by_character_theme_overlay"] = (
        supplemental_mapping_audit["merge_basis"] == "official_jp_thbwiki_overlay"
    )
    supplemental_mapping_audit.to_csv(
        OUT_ROOT / "jp_official_supplement_mapping_audit.csv",
        index=False,
        encoding="utf-8-sig",
    )

    additive = ["score", "primary_count", "comment_count", "male_count", "female_count"]
    merged_rows: list[dict[str, Any]] = []
    for (site, round_number, merge_id, canonical), group in source.groupby(
        ["site", "round", "merge_group_id", "canonical_track"], sort=False, dropna=False
    ):
        row: dict[str, Any] = {
            "site": site,
            "round": int(round_number),
            "merge_group_id": merge_id,
            "canonical_track": canonical,
            "source_row_count": len(group),
            "source_titles_jp_json": json.dumps(
                sorted({value for value in group["raw_title_jp"] if value}), ensure_ascii=False
            ),
            "source_titles_cn_json": json.dumps(
                sorted({value for value in group["raw_title_cn"] if value}), ensure_ascii=False
            ),
            "source_ranks_json": json.dumps(
                [int(value) if float(value).is_integer() else float(value) for value in group["source_rank"].dropna()],
                ensure_ascii=False,
            ),
            "mapped_characters_json": json.dumps(
                sorted({value for value in group["mapped_character"] if value}), ensure_ascii=False
            ),
            "merge_bases_json": json.dumps(
                sorted(set(group["merge_basis"])), ensure_ascii=False
            ),
        }
        for field in additive:
            values = pd.to_numeric(group[field], errors="coerce")
            row[field] = values.sum(min_count=1)
        if pd.notna(row["score"]) and row["score"]:
            row["primary_rate_recomputed"] = (
                row["primary_count"] / row["score"] if pd.notna(row["primary_count"]) else None
            )
        else:
            row["primary_rate_recomputed"] = None
        merged_rows.append(row)

    merged = pd.DataFrame(merged_rows)
    merged["merged_rank"] = (
        merged.groupby(["site", "round"])["score"]
        .rank(method="min", ascending=False, na_option="bottom")
        .astype("Int64")
    )
    merged.sort_values(["site", "round", "merged_rank", "canonical_track"], inplace=True)
    merged.to_csv(OUT_ROOT / "local_music_merged.csv", index=False, encoding="utf-8-sig")

    groups = (
        source.groupby(["merge_group_id", "canonical_track"], as_index=False)
        .agg(
            source_row_count=("merge_group_id", "size"),
            sites=("site", lambda values: json.dumps(sorted(set(values)), ensure_ascii=False)),
            mapped_characters=(
                "mapped_character",
                lambda values: json.dumps(sorted({value for value in values if value}), ensure_ascii=False),
            ),
        )
        .sort_values("canonical_track")
    )
    groups.to_csv(OUT_ROOT / "merge_groups.csv", index=False, encoding="utf-8-sig")

    conservation: list[dict[str, Any]] = []
    for (site, round_number), original in source.groupby(["site", "round"]):
        aggregate = merged[(merged["site"] == site) & (merged["round"] == round_number)]
        original_total = pd.to_numeric(original["score"], errors="coerce").sum()
        merged_total = pd.to_numeric(aggregate["score"], errors="coerce").sum()
        conservation.append(
            {
                "site": site,
                "round": int(round_number),
                "source_total_score": float(original_total),
                "merged_total_score": float(merged_total),
                "conserved": bool(math.isclose(original_total, merged_total, rel_tol=0, abs_tol=1e-9)),
            }
        )

    yaoya = merged[
        (merged["site"] == "cn")
        & (merged["round"] == 11)
        & (merged["canonical_track"] == "妖妖跋扈")
    ]
    round_coverage = {
        site: sorted({int(value) for value in source.loc[source["site"] == site, "round"]})
        for site in ("jp", "cn")
    }
    required_rounds = {"jp": list(range(3, 23)), "cn": list(range(1, 12))}
    coverage_complete = all(
        round_coverage[site] == required_rounds[site] for site in required_rounds
    )
    report = {
        "schema_version": 2,
        "source_rows": len(source),
        "merged_rows": len(merged),
        "round_coverage": round_coverage,
        "required_rounds": required_rounds,
        "round_coverage_complete": coverage_complete,
        "source_kind_counts": {
            str(key): int(value)
            for key, value in source["source_kind"].value_counts().items()
        },
        "jp_official_supplement_mapping": {
            "rows": int(len(supplemental_mapping_audit)),
            "matched_existing_repaired_mapping": int(
                supplemental_mapping_audit["matched_existing_repaired_mapping"].sum()
            ),
            "unmatched_kept_as_official_japanese": int(
                (supplemental_mapping_audit["merge_basis"] == "official_jp_exact_title").sum()
            ),
            "audit_path": "data_processed/music_canonical/jp_official_supplement_mapping_audit.csv",
            "policy": "never guess or overwrite missing translations; keep the official Japanese title and expose it for manual review",
        },
        "jp22_character_theme_overlay": {
            "path": JP22_THEME_OVERLAY_PATH.relative_to(WORKSPACE).as_posix(),
            "rows": len(overlay_by_title),
            "mapped_source_rows": int(
                (source["merge_basis"] == "official_jp_thbwiki_overlay").sum()
                + (source["merge_basis"] == "jp22_thbwiki_overlay").sum()
            ),
            "workbook_authoritative_rows": int(
                (
                    (source["site"] == "jp")
                    & (source["round"] == 22)
                    & source["source_record_id"].isin(set(overlay_by_music_id))
                    & (source["merge_basis"] == "official_jp_user_repaired_exact")
                ).sum()
            ),
            "policy": "add only missing JP22 character-theme mappings; never overwrite repaired workbook ownership",
        },
        "groups_with_multiple_rows_same_round": int((merged["source_row_count"] > 1).sum()),
        "conservation": conservation,
        "all_score_totals_conserved": all(item["conserved"] for item in conservation),
        "cn11_yaoya_bahu_check": (
            None
            if yaoya.empty
            else {
                "source_row_count": int(yaoya.iloc[0]["source_row_count"]),
                "score": float(yaoya.iloc[0]["score"]),
                "primary_count": float(yaoya.iloc[0]["primary_count"]),
            }
        ),
        "rule": "sum additive fields within site+round+merge_group_id; never across rounds",
    }
    if not report["all_score_totals_conserved"]:
        raise AssertionError("music score totals were not conserved")
    if not report["round_coverage_complete"]:
        raise AssertionError(
            f"music round coverage incomplete: {round_coverage!r}"
        )
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
