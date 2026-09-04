"""Quantify the intentional same-round music reprint aggregation rule."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKSPACE = Path(__file__).resolve().parents[1]
CANONICAL_ROOT = WORKSPACE / "data_processed" / "music_canonical"
JP_ROOT = WORKSPACE / "data_processed" / "jp_official"
OUT_ROOT = WORKSPACE / "analysis_results" / "music_merge"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    source_path = CANONICAL_ROOT / "local_music_source_rows.csv"
    merged_path = CANONICAL_ROOT / "local_music_merged.csv"
    validation_path = WORKSPACE / "metadata" / "music_canonical_validation.json"
    source = read_csv(source_path)
    merged = read_csv(merged_path)
    validation = json.loads(validation_path.read_text(encoding="utf-8-sig"))

    affected = []
    for row in merged:
        source_count = int(float(row["source_row_count"]))
        if source_count <= 1:
            continue
        source_ranks = [float(value) for value in json.loads(row["source_ranks_json"])]
        contributors = [
            source_row
            for source_row in source
            if source_row["site"] == row["site"]
            and int(source_row["round"]) == int(row["round"])
            and source_row["merge_group_id"] == row["merge_group_id"]
        ]
        contributor_scores = [
            float(value)
            for value in (item.get("score") for item in contributors)
            if value not in (None, "")
        ]
        merged_rank = float(row["merged_rank"])
        best_source_rank = min(source_ranks) if source_ranks else None
        best_source_score = max(contributor_scores) if contributor_scores else None
        merged_score = as_float(row.get("score"))
        affected.append(
            {
                "site": row["site"],
                "round": int(row["round"]),
                "merge_group_id": row["merge_group_id"],
                "canonical_track": row["canonical_track"],
                "source_row_count": source_count,
                "source_titles_jp_json": row["source_titles_jp_json"],
                "source_titles_cn_json": row["source_titles_cn_json"],
                "source_ranks_json": row["source_ranks_json"],
                "best_source_rank": best_source_rank,
                "merged_rank": merged_rank,
                "rank_improvement_vs_best_source": (
                    best_source_rank - merged_rank if best_source_rank is not None else None
                ),
                "best_source_score": best_source_score,
                "merged_score": merged_score,
                "score_added_by_other_reprints": (
                    merged_score - best_source_score
                    if merged_score is not None and best_source_score is not None
                    else None
                ),
                "primary_count": as_float(row.get("primary_count")),
            }
        )

    effect_path = OUT_ROOT / "same_round_merge_effects.csv"
    fieldnames = list(affected[0]) if affected else []
    with effect_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(affected)

    by_round = Counter((row["site"], row["round"]) for row in affected)
    changes = [row["rank_improvement_vs_best_source"] for row in affected]
    improved = [float(value) for value in changes if value is not None and value > 0]
    unchanged = [value for value in changes if value == 0]
    worsened = [float(value) for value in changes if value is not None and value < 0]

    cn11_yaoya = next(
        (
            row
            for row in affected
            if row["site"] == "cn"
            and row["round"] == 11
            and row["canonical_track"] == "妖妖跋扈"
        ),
        None,
    )
    jp21_yaoya = next(
        (
            row
            for row in affected
            if row["site"] == "jp"
            and row["round"] == 21
            and row["canonical_track"] == "妖妖跋扈"
        ),
        None,
    )
    jp_summary = read_csv(JP_ROOT / "rankings.csv")
    jp_details = read_csv(JP_ROOT / "detail_items.csv")
    un_summary = next(
        row
        for row in jp_summary
        if row["round"] == "20"
        and row["category"] == "music"
        and row["name"] == "U.N.オーエンは彼女なのか？"
    )
    un_detail = next(
        row
        for row in jp_details
        if row["round"] == "20"
        and row["source_category"] == "music"
        and row["source_name"] == "U.N.オーエンは彼女なのか？"
    )
    un_discrepancy = {
        "round": 20,
        "track": "U.N.オーエンは彼女なのか？",
        "official_aggregate_point": int(float(un_summary["point"])),
        "official_detail_source_sum_point": int(float(un_detail["point"])),
        "difference_detail_minus_aggregate": int(float(un_detail["point"]))
        - int(float(un_summary["point"])),
        "policy": "retain both official values with their source scope; do not silently reconcile",
    }

    report = {
        "schema_version": 2,
        "generated_at": utc_now(),
        "rule": validation["rule"],
        "source_rows": len(source),
        "merged_rows": len(merged),
        "rows_collapsed": len(source) - len(merged),
        "same_round_multi_source_groups": len(affected),
        "groups_by_site_round": [
            {"site": site, "round": round_number, "groups": count}
            for (site, round_number), count in sorted(by_round.items())
        ],
        "rank_effect": {
            "improved_vs_best_source": len(improved),
            "unchanged_vs_best_source": len(unchanged),
            "worsened_vs_best_source": len(worsened),
            "largest_improvement": max(improved) if improved else 0,
        },
        "all_score_totals_conserved": validation["all_score_totals_conserved"],
        "round_coverage": validation["round_coverage"],
        "round_coverage_complete": validation["round_coverage_complete"],
        "cn11_yaoya_bahu": cn11_yaoya,
        "jp21_yaoya_bakkou": jp21_yaoya,
        "jp20_un_owen_official_scope_discrepancy": un_discrepancy,
        "inputs": [
            {
                "path": path.relative_to(WORKSPACE).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in (source_path, merged_path, validation_path, JP_ROOT / "rankings.csv", JP_ROOT / "detail_items.csv")
        ],
        "output": {
            "path": effect_path.relative_to(WORKSPACE).as_posix(),
            "bytes": effect_path.stat().st_size,
            "sha256": sha256_file(effect_path),
        },
    }
    report_path = OUT_ROOT / "report.json"
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    summary_path = OUT_ROOT / "summary.md"
    summary_path.write_text(
        "\n".join(
            [
                "# 同曲再收录叠加影响",
                "",
                f"- 原始音乐行：{len(source):,}；同站同届合并后：{len(merged):,}；折叠{len(source)-len(merged):,}行。",
                f"- 同届多来源合并组：{len(affected)}；各站各届总得点/票数全部守恒：{validation['all_score_totals_conserved']}。",
                f"- 相对合并前最佳单条排名：{len(improved)}组上升，{len(unchanged)}组不变，{len(worsened)}组下降。",
                f"- CN11《妖妖跋扈》：3条来源合计{int(cn11_yaoya['merged_score']) if cn11_yaoya else 'NA'}票、{int(cn11_yaoya['primary_count']) if cn11_yaoya else 'NA'}本命。",
                f"- JP21《妖々跋扈》两条再收录来源合计{int(jp21_yaoya['merged_score']) if jp21_yaoya else 'NA'}点、{int(jp21_yaoya['primary_count']) if jp21_yaoya else 'NA'}一推；按叠加后得点从最佳单条第{int(jp21_yaoya['best_source_rank']) if jp21_yaoya else 'NA'}升至第{int(jp21_yaoya['merged_rank']) if jp21_yaoya else 'NA'}。",
                f"- JP20《U.N.オーエンは彼女なのか？》官方汇总为{un_discrepancy['official_aggregate_point']:,}点，详情来源相加为{un_discrepancy['official_detail_source_sum_point']:,}点；二者相差1点，按不同官方口径并列保留。",
                "- 规则仅在同一站点、同一届次内叠加；跨届从不相加。原始条目、别名、来源行和合并组ID均保留。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
