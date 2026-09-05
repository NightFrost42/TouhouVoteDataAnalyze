"""Build a mobile-friendly static snapshot of every desktop analysis template.

The desktop program remains the source of truth.  This script imports its
read-only analysis repository and writes compact chart/table JSON into this
separate web directory.  GitHub Pages can then serve the result without a
Python runtime or a server API.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vote_explorer"))

from analysis_engine import AnalysisRepository, TEMPLATES, normalize_name  # noqa: E402


COMPARISON_TEMPLATE_KEYS = {
    "c00_round_compare", "c01_rank_change", "c03_primary_rate_change",
    "c06_primary_change", "c07_selection_change", "c07_selection_yoy",
    "c08_points_change", "c09_selection_rate_change", "c12_gender_change",
    "m02_round_compare", "a04_count_dumbbell", "a04_count_change",
    "a05_largest_change", "a09_phi_change", "a13_quadrant",
    "p02_combination_compare", "q01_age", "q02_cognition", "q03_usertype",
    "q04_new", "q_custom",
}

# Simple one-round metric/scatter views benefit from a broad browser-side
# range.  Matrices, networks and questionnaire comparisons are deliberately
# kept compact because their O(n²)/many-option payloads would otherwise make a
# GitHub Pages bundle enormous; their source CSVs remain available for export.
BROAD_SINGLE_KEYS = {
    "c00_round_compare", "c00_rank_trend", "c00_all_trend", "c01_rank_change", "c02_selection_top",
    "c02_equal_rank", "c11_structure", "c11_metric_heatmap", "c12_gender_structure", "m02_round_compare",
    "c03_primary_rate", "c03_primary_rate_change", "c04_secondary_rate", "c05_top2_rate",
    "c06_primary_change", "c07_selection_change", "c07_selection_yoy", "c08_points_change",
    "c09_selection_rate_change", "c10_growth_lag", "c12_gender_lean", "c12_gender_change",
    "r01_character_question_scatter", "r02_character_question_diff", "r03_character_question_corr",
    "m01_metric", "m03_rank_trend", "m03_all_trend", "m04_primary_rate", "m05_character_music_cross",
    "m06_music_character_cross", "m07_character_music_covote", "m08_character_carryover",
    "m09_music_arrangement_cross", "m10_character_arrangement_cross", "r04_music_question_scatter",
    "r05_music_question_diff", "r06_music_question_corr", "r07_character_cognition",
    "a03_count_top", "a04_count_change", "a05_largest_change", "a06_lift", "a07_excess",
    "a08_phi", "a09_phi_change", "a10_direction", "a11_asymmetry", "a12_cumulative",
    "a14_count_top10", "a15_lift_top10", "a16_anomalies", "p01_cp_metric", "x_character", "x_covote",
}


def previous_round(repo: AnalysisRepository, current: str) -> str:
    prefix = current[:2]
    rounds = [label for label in repo.round_labels if label.startswith(prefix)]
    try:
        index = rounds.index(current)
    except ValueError:
        return current
    return rounds[index - 1] if index > 0 else current


def default_config(repo: AnalysisRepository, current: str) -> dict:
    relation_answers = repo.entity_question_answers(current, "character", "age")
    relation_answer = relation_answers[0] if relation_answers else ""
    return {
        "current_round": current,
        "compare_round": previous_round(repo, current),
        "top_n": 20,
        "rank_start": 1,
        "rank_end": 20,
        "min_count": 100,
        "min_entity_votes": 0,
        "search": "",
        "faction": "",
        "sort": "desc",
        "language": "cn",
        "change_direction": "all",
        "question_key": "age",
        "relation_question": "age",
        # CN uses raw answers such as “女” while JP uses “女性”; select an
        # actually published option per round so CN10/CN11 entity snapshots
        # are not empty merely because a JP label was used as a default.
        "relation_answer": relation_answer,
        "relation_value_mode": "rate",
        "relation_sort": "count",
        "x_metric": "selection_count",
        "y_metric": "selection_count",
        "pair_range_mode": "both",
        "lift_threshold": 1.20,
    }


def clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value


def annotate_factions(repo: AnalysisRepository, snapshot: dict, round_label: str) -> dict:
    """Attach original-setting group labels to network nodes for web filtering.

    The desktop network builder intentionally keeps its output compact and
    does not serialize the crosswalk on every node.  The static web bundle can
    carry this read-only metadata without changing the desktop application.
    """
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("nodes"), list):
        return snapshot
    by_key = {}
    for row in repo.character_by_round.get(round_label, []):
        for raw in (row.get("name_jp", ""), row.get("name_cn", ""), row.get("canonical_name", "")):
            key = normalize_name(str(raw or ""))
            if key:
                by_key[key] = row
    for node in snapshot["nodes"]:
        raw_id = str(node.get("id", ""))
        row = by_key.get(normalize_name(raw_id))
        if row is None:
            row = by_key.get(normalize_name(str(node.get("label", ""))))
        node["factions"] = sorted(repo.faction_labels_for_row(row or {"canonical_name": raw_id}))
    return snapshot


def annotate_language_labels(repo: AnalysisRepository, snapshot: dict, *round_labels: str) -> dict:
    """Store CN/JP alternatives so the browser's name-language selector works."""
    if not isinstance(snapshot, dict):
        return snapshot
    mapping: dict[str, dict[str, str]] = {}
    used: set[str] = set()
    for label in round_labels:
        for row in repo.character_by_round.get(label, []) + repo.music_by_round.get(label, []):
            cn, jp = str(row.get("name_cn", "") or ""), str(row.get("name_jp", "") or "")
            if cn or jp:
                values = {"cn": cn or jp, "jp": jp or cn}
                for raw in {cn, jp} - {""}:
                    mapping[raw] = values
    def remember(raw: str) -> None:
        text = str(raw or "")
        if text in mapping:
            used.add(text)
            return
        parts = [part.strip() for part in text.split(" × ")]
        if len(parts) > 1 and all(part in mapping for part in parts):
            mapping[text] = {
                "cn": " × ".join(mapping[part]["cn"] for part in parts),
                "jp": " × ".join(mapping[part]["jp"] for part in parts),
            }
            used.add(text)
    for key in ("categories", "row_labels", "col_labels"):
        for value in snapshot.get(key, []) or []:
            remember(value)
    for point in snapshot.get("points", []) or []:
        remember(point.get("label", ""))
    for node in snapshot.get("nodes", []) or []:
        remember(node.get("label", ""))
    snapshot["label_maps"] = {key: mapping[key] for key in used if mapping.get(key, {}).get("cn") or mapping.get(key, {}).get("jp")}
    return snapshot


def main() -> int:
    data_dir = ROOT / "vote_explorer" / "data"
    output_path = Path(__file__).resolve().parent / "web_data" / "templates.json"
    repo = AnalysisRepository(data_dir)
    snapshots: dict[str, dict[str, dict]] = {}
    pair_snapshots: dict[str, dict[str, dict[str, dict]]] = {}
    errors: list[dict[str, str]] = []
    for spec in TEMPLATES:
        by_round: dict[str, dict] = {}
        for round_label in repo.round_labels:
            config = default_config(repo, round_label)
            if spec.key in BROAD_SINGLE_KEYS:
                config.update({"top_n": 100, "rank_end": 2000, "min_count": 0})
            if spec.key in {"a17_concentration_clusters", "a18_music_concentration_clusters"}:
                # A zero threshold would serialize an unreadable near-complete
                # graph.  Keep the audited default edge floor for the cluster
                # seed; the web control can raise it further client-side.
                config.update({"min_count": 100, "top_n": 20})
            try:
                snapshot = repo.build(spec.key, config)
                if spec.key == "a02_network":
                    snapshot = annotate_factions(repo, snapshot, round_label)
                snapshot = annotate_language_labels(repo, snapshot, round_label)
                by_round[round_label] = clean(snapshot)
            except Exception as exc:  # keep one defective source from blocking the bundle
                errors.append({"template": spec.key, "round": round_label, "error": repr(exc)})
                by_round[round_label] = {
                    "title": spec.title,
                    "chart_type": spec.chart_type,
                    "table_headers": ["状态"],
                    "table_rows": [["当前快照无法生成：" + str(exc)]],
                    "note": "该模板的原始数据或当前地区/届次没有可用公开记录。",
                }
        snapshots[spec.key] = by_round

        if spec.key in COMPARISON_TEMPLATE_KEYS:
            by_current: dict[str, dict[str, dict]] = {}
            for current in repo.round_labels:
                same_region = [label for label in repo.round_labels if label[:2] == current[:2] and label != current]
                comparisons: dict[str, dict] = {}
                for compare in same_region:
                    config = default_config(repo, current)
                    config["compare_round"] = compare
                    if spec.key in {"a17_concentration_clusters", "a18_music_concentration_clusters"}:
                        config.update({"min_count": 100, "top_n": 20})
                    try:
                        snapshot = repo.build(spec.key, config)
                        snapshot = annotate_language_labels(repo, snapshot, current, compare)
                        comparisons[compare] = clean(snapshot)
                    except Exception as exc:
                        errors.append({"template": spec.key, "round": f"{current} vs {compare}", "error": repr(exc)})
                        comparisons[compare] = {
                            "title": spec.title,
                            "chart_type": spec.chart_type,
                            "table_headers": ["状态"],
                            "table_rows": [["当前比较快照无法生成：" + str(exc)]],
                            "note": "该模板的原始数据或当前地区/届次没有可用公开记录。",
                        }
                by_current[current] = comparisons
            pair_snapshots[spec.key] = by_current

    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "desktop_source": "vote_explorer/analysis_engine.py",
        "round_labels": repo.round_labels,
        "template_specs": [
            {
                "key": spec.key,
                "group": spec.group,
                "title": spec.title,
                "builder": spec.builder,
                "chart_type": spec.chart_type,
                "description": spec.description,
            }
            for spec in TEMPLATES
        ],
        "snapshots": snapshots,
        "pair_snapshots": pair_snapshots,
        "faction_options": list(repo.faction_options),
        "entity_question_options": {
            round_label: {
                category: {
                    question: repo.entity_question_answers(round_label, category, question)
                    for question in repo.entity_question_questions(round_label, category)
                }
                for category in ("character", "music", "work")
            }
            for round_label in repo.round_labels
        },
        "error_count": len(errors),
        "errors": errors,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {output_path} ({output_path.stat().st_size:,} bytes); templates={len(TEMPLATES)}; errors={len(errors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
