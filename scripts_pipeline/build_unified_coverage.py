"""Build the offline JP3--22 / CN1--11 component coverage matrix.

The script reads only ``metadata/`` and ``data_processed/``.  It deliberately
does not inspect ``data_raw/`` so it can run while crawlers are active.  A row
is marked ``official_not_offered`` or ``fetch_failed`` only when an existing
metadata file says so explicitly.  Partial or not-yet-certified modern data is
``pending`` rather than being mistaken for official absence.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence


SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_WORKSPACE = SCRIPT_PATH.parents[1]

STATUSES = (
    "available_crawled",
    "official_not_offered",
    "fetch_failed",
    "not_applicable",
    "pending",
)

STATUS_LABELS = {
    "available_crawled": "A",
    "official_not_offered": "O",
    "fetch_failed": "F",
    "not_applicable": "N",
    "pending": "P",
}

STATUS_MEANING = {
    "available_crawled": "公开组件已抓取，且现有元数据/规范化表足以确认该组件完成",
    "official_not_offered": "现有官方站覆盖元数据明确记录该组件未提供；不是抓取失败",
    "fetch_failed": "现有覆盖元数据明确记录应抓组件请求失败；不得解释为官网未提供",
    "not_applicable": "统一矩阵中的组件不属于该平台/代际接口的同类功能",
    "pending": "尚未抓取、只抓到部分、尚未规范化，或现有证据不足以判定完整性",
}

COMPONENTS: tuple[tuple[str, str, str], ...] = (
    ("main_rankings", "主榜", "角色、音乐、作品等官网主要排名部门"),
    ("questionnaire_definitions", "问卷定义", "アンケート题目、选项和分组定义"),
    ("questionnaire_results", "问卷结果", "アンケート选项计数、比例和分母"),
    ("questionnaire_trends", "问卷趋势", "官网公开的按时间变化问卷序列"),
    ("entity_questionnaire_details", "实体问卷明细", "逐角色、曲目、作品等实体的问卷拆分"),
    ("associations_covote", "关联/共投", "实体关联、共投或交叉投票数据"),
    ("condition_rankings", "条件榜", "按问卷选项等条件筛选后的排名"),
    ("open_text", "开放文本", "官网公开的问卷自由回答或反馈文本"),
)

COMPONENT_LABEL = {code: label for code, label, _ in COMPONENTS}

# Open-ended text is deliberately outside the numeric crawl queue's scope.
# Every other matrix component is required before that queue may claim full
# completion.  Keep this definition here (rather than inferring it from the
# current rows) so a missing or failed required component cannot disappear
# from the completion gate.
INTENTIONALLY_EXCLUDED_COMPONENTS = {
    "open_text": "excluded from the numeric crawl queue scope",
}
REQUIRED_COMPONENTS = tuple(
    code for code, _, _ in COMPONENTS if code not in INTENTIONALLY_EXCLUDED_COMPONENTS
)


@dataclass(frozen=True)
class CoverageRow:
    platform: str
    round: int
    component: str
    component_label: str
    status: str
    observed_records: int | None
    expected_records: int | None
    record_unit: str
    status_basis: str
    evidence: tuple[str, ...]
    note: str


class SnapshotReader:
    """Read stable snapshots and retain checksums for every input used."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.metadata = self.workspace / "metadata"
        self.processed = self.workspace / "data_processed"
        self.inputs: dict[str, dict[str, Any]] = {}

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.workspace).as_posix()

    @staticmethod
    def _signature(path: Path) -> tuple[int, int]:
        stat = path.stat()
        return stat.st_size, stat.st_mtime_ns

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _record_input(self, path: Path, before: tuple[int, int]) -> None:
        after = self._signature(path)
        if after != before:
            raise RuntimeError(f"input changed while being read; rerun after writer finishes: {path}")
        relative = self.relative(path)
        if relative.startswith("data_raw/"):
            raise AssertionError(f"raw input is forbidden: {relative}")
        self.inputs[relative] = {
            "path": relative,
            "bytes": after[0],
            "modified_time_ns": after[1],
            "sha256": self._sha256(path),
        }
        if self._signature(path) != after:
            raise RuntimeError(f"input changed while hashing; rerun after writer finishes: {path}")

    def json(self, relative: str) -> dict[str, Any]:
        path = self.workspace / relative
        before = self._signature(path)
        data = path.read_bytes()
        if self._signature(path) != before:
            raise RuntimeError(f"input changed while being read; rerun after writer finishes: {path}")
        value = json.loads(data.decode("utf-8-sig"))
        self._record_input(path, before)
        return value

    def table(
        self,
        relative: str,
        *,
        unique_fields: Sequence[str] = (),
        value_field: str | None = None,
    ) -> dict[str, Any]:
        path = self.workspace / relative
        before = self._signature(path)
        row_counts: Counter[int] = Counter()
        unique_values: dict[int, set[tuple[str, ...]]] = defaultdict(set)
        value_sums: Counter[int] = Counter()

        opener = gzip.open if path.name.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or "round" not in reader.fieldnames:
                raise ValueError(f"table lacks round column: {path}")
            missing = [field for field in unique_fields if field not in reader.fieldnames]
            if missing:
                raise ValueError(f"table lacks unique fields {missing}: {path}")
            if value_field and value_field not in reader.fieldnames:
                raise ValueError(f"table lacks value field {value_field}: {path}")
            for row in reader:
                round_no = int(row["round"])
                row_counts[round_no] += 1
                if unique_fields:
                    unique_values[round_no].add(tuple(row[field] for field in unique_fields))
                if value_field:
                    raw_value = row.get(value_field, "").strip()
                    if raw_value:
                        value_sums[round_no] += int(float(raw_value))

        self._record_input(path, before)
        return {
            "rows": dict(row_counts),
            "unique": {round_no: len(values) for round_no, values in unique_values.items()},
            "value_sums": dict(value_sums),
        }


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding=encoding, newline="")
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def as_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    return int(value)


def explicit_status(statuses: Iterable[str]) -> str:
    """Combine explicit subcomponent states without hiding a fetch failure."""

    values = [value for value in statuses if value]
    invalid = sorted(set(values) - set(STATUSES))
    if invalid:
        raise ValueError(f"unknown component status(es): {invalid}")
    if "fetch_failed" in values:
        return "fetch_failed"
    if "pending" in values:
        return "pending"
    if "available_crawled" in values:
        return "available_crawled"
    if values and all(value == "official_not_offered" for value in values):
        return "official_not_offered"
    if values and all(value == "not_applicable" for value in values):
        return "not_applicable"
    return "pending"


def add_row(
    rows: list[CoverageRow],
    platform: str,
    round_no: int,
    component: str,
    status: str,
    *,
    observed: int | None = None,
    expected: int | None = None,
    unit: str = "",
    basis: str,
    evidence: Iterable[str],
    note: str,
) -> None:
    if component not in COMPONENT_LABEL:
        raise ValueError(f"unknown component: {component}")
    if status not in STATUSES:
        raise ValueError(f"unknown status: {status}")
    rows.append(
        CoverageRow(
            platform=platform,
            round=round_no,
            component=component,
            component_label=COMPONENT_LABEL[component],
            status=status,
            observed_records=observed,
            expected_records=expected,
            record_unit=unit,
            status_basis=basis,
            evidence=tuple(dict.fromkeys(evidence)),
            note=note,
        )
    )


def build_jp_legacy(reader: SnapshotReader, rows: list[CoverageRow]) -> None:
    component_path = "metadata/jp_official_legacy_component_status.json"
    crawl_path = "metadata/jp_official_legacy_coverage.json"
    component_meta = reader.json(component_path)
    crawl_meta = reader.json(crawl_path)
    crawl_rounds = crawl_meta["rounds"]

    q_path = "data_processed/jp_official_legacy/questionnaire_long.csv"
    entity_q_path = "data_processed/jp_official_legacy/entity_questionnaire_long.csv"
    association_path = "data_processed/jp_official_legacy/entity_association_long.csv"
    entity_metric_path = "data_processed/jp_official_legacy/source_entity_metrics.csv"
    q_index = reader.table(q_path, unique_fields=("scope", "question_id", "question"))
    entity_q_index = reader.table(entity_q_path)
    association_index = reader.table(association_path)
    entity_metric_index = reader.table(entity_metric_path)

    for round_no in range(3, 17):
        key = str(round_no)
        meta = component_meta["rounds"][key]
        crawl = crawl_rounds[key]
        rankings = list(meta.get("ranking_categories_available_crawled", []))
        failures = meta.get("fetch_failures", [])
        main_status = "available_crawled" if rankings else ("fetch_failed" if failures else "pending")
        metric_rows = entity_metric_index["rows"].get(round_no, 0)
        add_row(
            rows,
            "JP",
            round_no,
            "main_rankings",
            main_status,
            observed=metric_rows or len(rankings),
            expected=len(rankings),
            unit="normalized_rows" if metric_rows else "ranking_categories",
            basis="explicit_metadata+processed_table",
            evidence=(component_path, entity_metric_path),
            note=f"官网已抓排名类别：{', '.join(rankings) or '无'}；抓取失败记录 {len(failures)} 条。",
        )

        questionnaire_status = meta["questionnaire"]
        q_rows = q_index["rows"].get(round_no, 0)
        q_questions = q_index["unique"].get(round_no, 0)
        for component, observed, unit in (
            ("questionnaire_definitions", q_questions, "questions"),
            ("questionnaire_results", q_rows, "normalized_rows"),
        ):
            add_row(
                rows,
                "JP",
                round_no,
                component,
                questionnaire_status,
                observed=observed,
                expected=None,
                unit=unit,
                basis="explicit_metadata+processed_table",
                evidence=(component_path, q_path),
                note=f"legacy normalizer 问卷长表 {q_rows} 行、约 {q_questions} 个题目键。",
            )

        add_row(
            rows,
            "JP",
            round_no,
            "questionnaire_trends",
            "not_applicable",
            observed=0,
            expected=0,
            unit="series",
            basis="interface_scope",
            evidence=(component_path,),
            note="JP legacy 静态アンケート页没有与 CN 现代接口按小时趋势表同构的组件。",
        )

        profile_status = meta["entity_numeric_profiles"]
        entity_rows = entity_q_index["rows"].get(round_no, 0)
        association_rows = association_index["rows"].get(round_no, 0)
        add_row(
            rows,
            "JP",
            round_no,
            "entity_questionnaire_details",
            profile_status,
            observed=entity_rows,
            expected=None,
            unit="normalized_rows",
            basis="explicit_metadata+processed_table",
            evidence=(component_path, entity_q_path),
            note=f"逐实体问卷明细 {entity_rows} 行；官网组件状态由 legacy normalizer 明确给出。",
        )
        add_row(
            rows,
            "JP",
            round_no,
            "associations_covote",
            profile_status,
            observed=association_rows,
            expected=None,
            unit="normalized_rows",
            basis="explicit_metadata+processed_table",
            evidence=(component_path, association_path),
            note=f"逐实体关联明细 {association_rows} 行；与实体 numeric profile 同源。",
        )
        add_row(
            rows,
            "JP",
            round_no,
            "condition_rankings",
            "not_applicable",
            observed=0,
            expected=0,
            unit="condition_files",
            basis="interface_scope",
            evidence=(component_path,),
            note="JP legacy 逐实体关联不等同于 CN 现代站的任意问卷选项条件榜。",
        )

        comment_pages = as_int(
            crawl.get("detail_categories", {})
            .get("questionnaire_comment", {})
            .get("fetched_ok")
        )
        open_status = "available_crawled" if comment_pages else "pending"
        add_row(
            rows,
            "JP",
            round_no,
            "open_text",
            open_status,
            observed=comment_pages,
            expected=(
                as_int(
                    crawl.get("detail_categories", {})
                    .get("questionnaire_comment", {})
                    .get("discovered")
                )
                or None
            ),
            unit="official_comment_pages",
            basis="explicit_metadata" if comment_pages else "incomplete_or_unverified",
            evidence=(crawl_path,),
            note=(
                f"官方 questionnaire_comment 页面已抓 {comment_pages} 页；当前矩阵只确认页面覆盖。"
                if comment_pages
                else "现有覆盖元数据没有明确证明开放文本已提供或已完整抓取，保守记 pending。"
            ),
        )


def build_jp_current(reader: SnapshotReader, rows: list[CoverageRow]) -> None:
    report_path = "metadata/jp_official_normalization_report.json"
    manifest_path = "metadata/jp_official_download_manifest.json"
    report = reader.json(report_path)
    manifest = reader.json(manifest_path)
    available_rounds = {int(value) for value in report.get("available_rounds", [])}
    detail_rounds = {int(value) for value in manifest.get("detail_rounds", [])}

    rankings_path = "data_processed/jp_official/rankings.csv"
    q_path = "data_processed/jp_official/questionnaire_long.csv"
    entity_q_path = "data_processed/jp_official/detail_questionnaire_long.csv"
    association_path = "data_processed/jp_official/detail_associations.csv"
    feedback_path = "data_processed/jp_official/questionnaire_feedback_counts.csv"
    rankings = reader.table(rankings_path)
    questionnaire = reader.table(q_path, unique_fields=("question_key",))
    entity_q = reader.table(entity_q_path)
    associations = reader.table(association_path)
    feedback = reader.table(feedback_path, value_field="response_count")

    for round_no in range(17, 23):
        ranking_rows = rankings["rows"].get(round_no, 0)
        main_status = "available_crawled" if round_no in available_rounds and ranking_rows else "pending"
        add_row(
            rows,
            "JP",
            round_no,
            "main_rankings",
            main_status,
            observed=ranking_rows,
            expected=None,
            unit="normalized_rows",
            basis="processed_table" if main_status == "available_crawled" else "incomplete_or_unverified",
            evidence=(report_path, rankings_path),
            note=f"官网现站规范化主榜 {ranking_rows} 行。",
        )

        q_rows = questionnaire["rows"].get(round_no, 0)
        q_questions = questionnaire["unique"].get(round_no, 0)
        q_status = "available_crawled" if round_no in available_rounds and q_rows else "pending"
        add_row(
            rows,
            "JP",
            round_no,
            "questionnaire_definitions",
            q_status,
            observed=q_questions,
            expected=None,
            unit="question_keys",
            basis="processed_table" if q_status == "available_crawled" else "incomplete_or_unverified",
            evidence=(report_path, q_path),
            note=f"アンケート模块含 {q_questions} 个 question_key。",
        )
        add_row(
            rows,
            "JP",
            round_no,
            "questionnaire_results",
            q_status,
            observed=q_rows,
            expected=None,
            unit="normalized_rows",
            basis="processed_table" if q_status == "available_crawled" else "incomplete_or_unverified",
            evidence=(report_path, q_path),
            note=f"アンケート结果长表 {q_rows} 行。",
        )
        add_row(
            rows,
            "JP",
            round_no,
            "questionnaire_trends",
            "not_applicable",
            observed=0,
            expected=0,
            unit="series",
            basis="interface_scope",
            evidence=(manifest_path,),
            note="JP 现站模块没有与 CN 现代接口按小时趋势表同构的公开组件。",
        )

        detail_rows = entity_q["rows"].get(round_no, 0)
        detail_status = "available_crawled" if detail_rows else "pending"
        add_row(
            rows,
            "JP",
            round_no,
            "entity_questionnaire_details",
            detail_status,
            observed=detail_rows,
            expected=None,
            unit="normalized_rows",
            basis="processed_table" if detail_rows else "incomplete_or_unverified",
            evidence=(manifest_path, report_path, entity_q_path),
            note=(
                f"逐实体问卷明细 {detail_rows} 行。"
                if detail_rows
                else f"本次 manifest 的 detail_rounds={sorted(detail_rounds)}；未抓详情不等于官网未提供。"
            ),
        )

        association_rows = associations["rows"].get(round_no, 0)
        association_status = "available_crawled" if association_rows else "pending"
        add_row(
            rows,
            "JP",
            round_no,
            "associations_covote",
            association_status,
            observed=association_rows,
            expected=None,
            unit="normalized_rows",
            basis="processed_table" if association_rows else "incomplete_or_unverified",
            evidence=(manifest_path, report_path, association_path),
            note=(
                f"逐实体关联明细 {association_rows} 行。"
                if association_rows
                else f"本次 manifest 的 detail_rounds={sorted(detail_rounds)}；保守记 pending。"
            ),
        )
        add_row(
            rows,
            "JP",
            round_no,
            "condition_rankings",
            "not_applicable",
            observed=0,
            expected=0,
            unit="condition_files",
            basis="interface_scope",
            evidence=(manifest_path,),
            note="JP 逐实体关联页不等同于 CN 现代站的任意问卷选项条件榜。",
        )

        feedback_responses = feedback["value_sums"].get(round_no, 0)
        feedback_rows = feedback["rows"].get(round_no, 0)
        open_status = "available_crawled" if feedback_rows else "pending"
        add_row(
            rows,
            "JP",
            round_no,
            "open_text",
            open_status,
            observed=feedback_responses,
            expected=None,
            unit="feedback_responses",
            basis="processed_table" if feedback_rows else "incomplete_or_unverified",
            evidence=(feedback_path, manifest_path),
            note=(
                f"官方 questionnaire feedback 数组记录 {feedback_responses} 个回答；规范化表保存回答数。"
                if feedback_rows
                else "当前 processed/manifest 未证明该回开放反馈完整抓取，保守记 pending。"
            ),
        )


def build_cn_legacy(reader: SnapshotReader, rows: list[CoverageRow]) -> None:
    coverage_path = "metadata/cn_official_legacy_coverage.json"
    validation_path = "metadata/cn_official_legacy_validation.json"
    verification_path = "metadata/cn_component_verification.json"
    coverage = reader.json(coverage_path)
    reader.json(validation_path)
    verification = (
        reader.json(verification_path)
        if (reader.workspace / verification_path).exists()
        else {}
    )
    by_round: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in coverage["rows"]:
        by_round[int(item["round"])].append(item)

    for round_no in range(1, 10):
        round_rows = by_round[round_no]
        if not round_rows:
            raise ValueError(f"CN legacy coverage lacks round {round_no}")

        summary_status = explicit_status(item["summary_status"] for item in round_rows)
        summary_expected = sum(as_int(item.get("summary_pages_expected_or_discovered")) for item in round_rows)
        summary_downloaded = sum(as_int(item.get("summary_pages_downloaded")) for item in round_rows)
        add_row(
            rows,
            "CN",
            round_no,
            "main_rankings",
            summary_status,
            observed=summary_downloaded,
            expected=summary_expected,
            unit="official_summary_pages",
            basis="explicit_metadata",
            evidence=(coverage_path, validation_path),
            note=f"汇总页 {summary_downloaded}/{summary_expected}；任一应抓部门失败都会保留为 fetch_failed。",
        )

        paper = next((item for item in round_rows if item["category"] == "paper"), None)
        if paper is None:
            raise ValueError(f"CN legacy coverage lacks paper row for round {round_no}")
        questionnaire_status = paper["questionnaire_status"]
        groups_expected = as_int(paper.get("questionnaire_groups_expected"))
        groups_downloaded = as_int(paper.get("questionnaire_groups_downloaded"))
        if questionnaire_status == "available_crawled" and groups_downloaded == 0:
            groups_expected = max(groups_expected, 1)
            groups_downloaded = 1
            q_unit = "official_questionnaire_page"
        else:
            q_unit = "official_questionnaire_groups"
        for component in ("questionnaire_definitions", "questionnaire_results"):
            add_row(
                rows,
                "CN",
                round_no,
                component,
                questionnaire_status,
                observed=groups_downloaded,
                expected=groups_expected or None,
                unit=q_unit,
                basis="explicit_metadata",
                evidence=(coverage_path, validation_path),
                note=(
                    f"paper 问卷状态为 {questionnaire_status}；抓取组/页 {groups_downloaded}/{groups_expected or '?'}。"
                ),
            )

        verified = verification.get("rounds", {}).get(str(round_no), {})
        trend_verified = verified.get("questionnaire_trends", {})
        trend_status = trend_verified.get("status", "pending")
        trend_basis = trend_verified.get("status_basis", "incomplete_or_unverified")
        add_row(
            rows,
            "CN",
            round_no,
            "questionnaire_trends",
            trend_status,
            observed=trend_verified.get("observed_records", 0),
            expected=trend_verified.get("expected_records"),
            unit="series",
            basis=trend_basis,
            evidence=(coverage_path, validation_path, verification_path),
            note=trend_verified.get(
                "note",
                "legacy questionnaire trend interface has not been verified; keep pending.",
            ),
        )

        entity_verified = verified.get("entity_questionnaire_details", {})
        entity_status = entity_verified.get(
            "status", explicit_status(item["item_api_status"] for item in round_rows)
        )
        entity_expected = sum(
            as_int(item.get("detail_pages_expected"))
            for item in round_rows
            if item["item_api_status"] != "official_not_offered"
        )
        entity_observed = entity_verified.get(
            "observed_records",
            sum(as_int(item.get("votepaper_json")) for item in round_rows),
        )
        entity_expected_verified = entity_verified.get("expected_records")
        add_row(
            rows,
            "CN",
            round_no,
            "entity_questionnaire_details",
            entity_status,
            observed=entity_observed,
            expected=entity_expected_verified if entity_expected_verified is not None else (entity_expected or None),
            unit="per_entity_votepaper_json",
            basis=entity_verified.get("status_basis", "explicit_metadata"),
            evidence=(coverage_path, validation_path, verification_path),
            note=entity_verified.get(
                "note",
                f"逐实体 votepaper JSON {entity_observed}；接口子项状态合并为 {entity_status}。",
            ),
        )

        cross_status = explicit_status(item["crossvote_status"] for item in round_rows)
        cross_observed = sum(bool(item.get("crossvote_default_available")) for item in round_rows)
        add_row(
            rows,
            "CN",
            round_no,
            "associations_covote",
            cross_status,
            observed=cross_observed,
            expected=None,
            unit="crossvote_categories",
            basis="explicit_metadata",
            evidence=(coverage_path, validation_path),
            note=f"crossvote 类别状态合并为 {cross_status}；默认公开参数成功类别 {cross_observed}。",
        )

        add_row(
            rows,
            "CN",
            round_no,
            "condition_rankings",
            "not_applicable",
            observed=0,
            expected=0,
            unit="condition_files",
            basis="interface_scope",
            evidence=(coverage_path,),
            note="CN1—9 legacy 接口没有与 CN10—11 全问卷选项条件榜同构的组件。",
        )
        add_row(
            rows,
            "CN",
            round_no,
            "open_text",
            "pending",
            observed=0,
            expected=None,
            unit="answers",
            basis="incomplete_or_unverified",
            evidence=(coverage_path,),
            note="现有 legacy coverage 未单列开放回答正文覆盖；没有证据时保守记 pending。",
        )


def build_cn_modern(reader: SnapshotReader, rows: list[CoverageRow]) -> None:
    coverage_path = "metadata/cn_modern_coverage.json"
    report_path = "metadata/cn_official_normalization_report.json"
    verification_path = "metadata/cn_component_verification.json"
    coverage = reader.json(coverage_path)
    report = reader.json(report_path)
    verification = (
        reader.json(verification_path)
        if (reader.workspace / verification_path).exists()
        else {}
    )
    coverage_rounds = {int(item["round"]): item for item in coverage.get("rounds", [])}
    report_rounds = {int(item["round"]): item for item in report.get("rounds", [])}

    rankings_path = "data_processed/cn_official/rankings.csv"
    questions_path = "data_processed/cn_official/questionnaire_questions.csv"
    options_path = "data_processed/cn_official/questionnaire_options.csv"
    q_results_path = "data_processed/cn_official/questionnaire_long.csv"
    trends_path = "data_processed/cn_official/questionnaire_trends.csv.gz"
    conditions_summary_path = "data_processed/cn_official/condition_option_summary.csv"
    conditions_rankings_path = "data_processed/cn_official/condition_rankings.csv.gz"
    covote_path = "data_processed/cn_official/covote_metrics.csv.gz"
    open_text_path = "data_processed/cn_official/open_text_answers.csv.gz"

    rankings = reader.table(rankings_path)
    questions = reader.table(questions_path, unique_fields=("question_id",))
    options = reader.table(options_path)
    q_results = reader.table(q_results_path, unique_fields=("question_id",))
    trends = reader.table(trends_path, unique_fields=("question_id", "series"))
    condition_summary = reader.table(conditions_summary_path, unique_fields=("question_id", "answer_id"))
    condition_rankings = reader.table(conditions_rankings_path)
    covote = reader.table(covote_path)
    open_text = reader.table(open_text_path)

    for round_no in (10, 11):
        info = report_rounds.get(round_no, {})
        coverage_info = coverage_rounds.get(round_no, {})

        ranking_rows = rankings["rows"].get(round_no, 0)
        main_status = "available_crawled" if info.get("available") and ranking_rows else "pending"
        add_row(
            rows,
            "CN",
            round_no,
            "main_rankings",
            main_status,
            observed=ranking_rows,
            expected=None,
            unit="normalized_rows",
            basis="processed_table" if main_status == "available_crawled" else "incomplete_or_unverified",
            evidence=(coverage_path, report_path, rankings_path),
            note=f"规范化主榜 {ranking_rows} 行；未出现的届次保守记 pending。",
        )

        expected_questions = as_int(info.get("questions"))
        expected_options = as_int(info.get("options"))
        observed_questions = questions["unique"].get(round_no, 0)
        observed_options = options["rows"].get(round_no, 0)
        definitions_complete = bool(
            expected_questions
            and observed_questions >= expected_questions
            and observed_options >= expected_options
        )
        definitions_status = "available_crawled" if definitions_complete else "pending"
        add_row(
            rows,
            "CN",
            round_no,
            "questionnaire_definitions",
            definitions_status,
            observed=observed_questions,
            expected=expected_questions or None,
            unit="questions",
            basis="processed_table" if definitions_complete else "incomplete_or_unverified",
            evidence=(coverage_path, report_path, questions_path, options_path),
            note=f"题目 {observed_questions}/{expected_questions or '?'}，选项 {observed_options}/{expected_options or '?'}。",
        )

        expected_categorical = as_int(info.get("categorical_questions"))
        observed_result_questions = q_results["unique"].get(round_no, 0)
        result_rows = q_results["rows"].get(round_no, 0)
        results_complete = bool(expected_categorical and observed_result_questions >= expected_categorical)
        results_status = "available_crawled" if results_complete else "pending"
        add_row(
            rows,
            "CN",
            round_no,
            "questionnaire_results",
            results_status,
            observed=result_rows,
            expected=None,
            unit="normalized_option_rows",
            basis="processed_table" if results_complete else "incomplete_or_unverified",
            evidence=(coverage_path, report_path, q_results_path),
            note=(
                f"分类题结果覆盖 {observed_result_questions}/{expected_categorical or '?'} 题，共 {result_rows} 个选项行。"
            ),
        )

        trend_rows = trends["rows"].get(round_no, 0)
        trend_status = "available_crawled" if trend_rows else "pending"
        add_row(
            rows,
            "CN",
            round_no,
            "questionnaire_trends",
            trend_status,
            observed=trend_rows,
            expected=None,
            unit="time_series_rows",
            basis="processed_table" if trend_rows else "incomplete_or_unverified",
            evidence=(coverage_path, report_path, trends_path),
            note=f"问卷趋势长表 {trend_rows} 行。",
        )

        entity_verified = (
            verification.get("rounds", {})
            .get(str(round_no), {})
            .get("entity_questionnaire_details", {})
        )
        entity_status = entity_verified.get("status", "pending")
        add_row(
            rows,
            "CN",
            round_no,
            "entity_questionnaire_details",
            entity_status,
            observed=entity_verified.get("observed_records", 0),
            expected=entity_verified.get("expected_records"),
            unit="normalized_rows",
            basis=entity_verified.get("status_basis", "incomplete_or_unverified"),
            evidence=(coverage_path, report_path, verification_path),
            note=entity_verified.get(
                "note",
                "现代 CN 实体问卷明细尚未认证；缺失时保留 pending。",
            ),
        )

        covote_rows = covote["rows"].get(round_no, 0)
        covote_info = info.get("covote", {})
        covote_complete = bool(covote_info) and all(
            bool(covote_info.get(category, {}).get("complete"))
            for category in ("character", "music")
        )
        covote_status = "available_crawled" if covote_complete and covote_rows else "pending"
        expected_pairs = sum(
            as_int(covote_info.get(category, {}).get("expected_pairs"))
            for category in ("character", "music")
        )
        add_row(
            rows,
            "CN",
            round_no,
            "associations_covote",
            covote_status,
            observed=covote_rows,
            expected=expected_pairs or None,
            unit="pair_rows",
            basis="processed_table" if covote_status == "available_crawled" else "incomplete_or_unverified",
            evidence=(coverage_path, report_path, covote_path),
            note=f"共投对 {covote_rows}/{expected_pairs or '?'}；不完整或 API 未认证时记 pending。",
        )

        condition_files = as_int(info.get("condition_files"))
        condition_expected = as_int(info.get("condition_files_expected"))
        condition_complete = bool(info.get("conditions_complete"))
        condition_keys = condition_summary["unique"].get(round_no, 0)
        condition_rows = condition_rankings["rows"].get(round_no, 0)
        condition_status = "available_crawled" if condition_complete else "pending"
        add_row(
            rows,
            "CN",
            round_no,
            "condition_rankings",
            condition_status,
            observed=condition_keys or condition_files,
            expected=condition_expected or None,
            unit="question_answer_conditions",
            basis="processed_table" if condition_complete else "incomplete_or_unverified",
            evidence=(coverage_path, report_path, conditions_summary_path, conditions_rankings_path),
            note=(
                f"条件文件/键 {condition_files or condition_keys}/{condition_expected or '?'}，排名明细 {condition_rows} 行；部分抓取仍记 pending。"
            ),
        )

        open_rows = open_text["rows"].get(round_no, 0)
        open_status = "available_crawled" if open_rows else "pending"
        add_row(
            rows,
            "CN",
            round_no,
            "open_text",
            open_status,
            observed=open_rows,
            expected=None,
            unit="answer_rows",
            basis="processed_table" if open_rows else "incomplete_or_unverified",
            evidence=(coverage_path, report_path, open_text_path),
            note=f"匿名官网开放回答 {open_rows} 行。",
        )

        # Preserve the reason that an absent modern round is pending rather than
        # inventing official absence from a failed/in-progress coverage check.
        if not info and coverage_info.get("complete") is False:
            pass


def validate(rows: Sequence[CoverageRow]) -> dict[str, Any]:
    expected_keys = {
        ("JP", round_no, component)
        for round_no in range(3, 23)
        for component, _, _ in COMPONENTS
    } | {
        ("CN", round_no, component)
        for round_no in range(1, 12)
        for component, _, _ in COMPONENTS
    }
    actual_keys = {(row.platform, row.round, row.component) for row in rows}
    duplicate_count = len(rows) - len(actual_keys)
    invalid_statuses = sorted({row.status for row in rows} - set(STATUSES))
    official_absence_without_explicit_basis = [
        (row.platform, row.round, row.component)
        for row in rows
        if row.status == "official_not_offered" and not row.status_basis.startswith("explicit_metadata")
    ]
    fetch_failures_without_explicit_basis = [
        (row.platform, row.round, row.component)
        for row in rows
        if row.status == "fetch_failed" and not row.status_basis.startswith("explicit_metadata")
    ]
    required_rows = [row for row in rows if row.component in REQUIRED_COMPONENTS]
    incomplete_required_rows: list[dict[str, Any]] = []
    for row in required_rows:
        if row.status in ("available_crawled", "not_applicable"):
            continue
        if row.status == "official_not_offered" and row.status_basis.startswith(
            "explicit_metadata"
        ):
            continue
        if row.status == "official_not_offered":
            reason = "official_not_offered_without_explicit_metadata"
        else:
            reason = row.status
        incomplete_required_rows.append(
            {
                "platform": row.platform,
                "round": row.round,
                "component": row.component,
                "status": row.status,
                "status_basis": row.status_basis,
                "reason": reason,
            }
        )
    # The active queue includes the CN10-11 modern-site stages again. Keep
    # their rows visible while they are incomplete, and make the priority
    # completion gate cover the complete requested scope (JP3-22 + CN1-11).
    priority_rows = [
        row
        for row in required_rows
        if row.platform == "JP" or (row.platform == "CN" and row.round <= 11)
    ]
    priority_incomplete_rows = [
        row
        for row in priority_rows
        if row.status not in ("available_crawled", "not_applicable")
        and not (
            row.status == "official_not_offered"
            and row.status_basis.startswith("explicit_metadata")
        )
    ]
    result = {
        "expected_rows": len(expected_keys),
        "actual_rows": len(rows),
        "unique_keys": len(actual_keys),
        "duplicate_key_count": duplicate_count,
        "missing_keys": [list(value) for value in sorted(expected_keys - actual_keys)],
        "extra_keys": [list(value) for value in sorted(actual_keys - expected_keys)],
        "invalid_statuses": invalid_statuses,
        "official_not_offered_without_explicit_metadata": official_absence_without_explicit_basis,
        "fetch_failed_without_explicit_metadata": fetch_failures_without_explicit_basis,
        "status_counts": dict(Counter(row.status for row in rows)),
        "required_components": list(REQUIRED_COMPONENTS),
        "intentionally_excluded_components": dict(INTENTIONALLY_EXCLUDED_COMPONENTS),
        "required_rows": len(required_rows),
        "required_status_counts": dict(Counter(row.status for row in required_rows)),
        "incomplete_required_rows": incomplete_required_rows,
        "incomplete_required_status_counts": dict(
            Counter(row["reason"] for row in incomplete_required_rows)
        ),
        "priority_scope": "JP3-22 + CN1-11",
        "priority_scope_required_rows": len(priority_rows),
        "priority_scope_incomplete_rows": [
            {
                "platform": row.platform,
                "round": row.round,
                "component": row.component,
                "status": row.status,
            }
            for row in priority_incomplete_rows
        ],
        "priority_scope_complete": not priority_incomplete_rows,
    }
    result["valid"] = not any(
        (
            result["actual_rows"] != result["expected_rows"],
            duplicate_count,
            result["missing_keys"],
            result["extra_keys"],
            invalid_statuses,
            official_absence_without_explicit_basis,
            fetch_failures_without_explicit_basis,
        )
    )
    # ``valid`` above certifies matrix shape and provenance invariants only.
    # Queue completion is intentionally stricter: every required row must be
    # crawled, not applicable, or explicitly documented by metadata as an
    # official absence.  In particular, pending/fetch_failed always block it.
    result["all_required_components_complete"] = bool(
        result["valid"] and not incomplete_required_rows
    )
    return result


def csv_text(rows: Sequence[CoverageRow]) -> str:
    import io

    buffer = io.StringIO(newline="")
    fieldnames = [
        "platform",
        "round",
        "component",
        "component_label",
        "status",
        "observed_records",
        "expected_records",
        "record_unit",
        "status_basis",
        "evidence",
        "note",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        item = asdict(row)
        item["evidence"] = ";".join(row.evidence)
        item["observed_records"] = "" if row.observed_records is None else row.observed_records
        item["expected_records"] = "" if row.expected_records is None else row.expected_records
        writer.writerow(item)
    return buffer.getvalue()


def markdown_text(
    rows: Sequence[CoverageRow],
    validation: dict[str, Any],
    generated_at: str,
    csv_hash: str,
    json_hash: str,
) -> str:
    lookup = {(row.platform, row.round, row.component): row for row in rows}
    lines = [
        "# JP3—22 / CN1—11 逐届逐组件覆盖矩阵",
        "",
        f"生成时间：`{generated_at}`。本表由 `scripts_pipeline/build_unified_coverage.py` 离线生成，只读取 `metadata/` 与 `data_processed/`。",
        "",
        "状态：`A` = available_crawled，`O` = official_not_offered，`F` = fetch_failed，`N` = not_applicable，`P` = pending。部分抓取一律记 `P`；抓取失败不会降格成 `O`。",
        "",
    ]

    headers = ["平台/届"] + [label for _, label, _ in COMPONENTS]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for platform, rounds in (("JP", range(3, 23)), ("CN", range(1, 12))):
        for round_no in rounds:
            values = [f"{platform}{round_no}"]
            for component, _, _ in COMPONENTS:
                values.append(STATUS_LABELS[lookup[(platform, round_no, component)].status])
            lines.append("| " + " | ".join(values) + " |")

    lines.extend(
        [
            "",
            "## 状态统计",
            "",
            "| 状态 | 行数 |",
            "|---|---:|",
        ]
    )
    for status in STATUSES:
        lines.append(f"| `{status}` | {validation['status_counts'].get(status, 0)} |")

    failures = [row for row in rows if row.status == "fetch_failed"]
    pending = [row for row in rows if row.status == "pending"]
    jp_current_detail_pending = [
        row.round
        for row in rows
        if row.platform == "JP"
        and 17 <= row.round <= 22
        and row.component == "entity_questionnaire_details"
        and row.status == "pending"
    ]
    if jp_current_detail_pending:
        jp_detail_note = (
            "- JP 现站尚未由 processed 详情长表认证的回次为 "
            + ", ".join(str(value) for value in jp_current_detail_pending)
            + "；它们记 `pending`，不解释成官网未提供。"
        )
    else:
        jp_detail_note = "- JP17—21 的逐实体详情均已在 processed 长表中出现；即使旧 manifest 的 detail_rounds 滞后，也以本次稳定表快照记录实际覆盖。"
    lines.extend(
        [
            "",
            "## 校验与注意事项",
            "",
            f"- 矩阵应有 30 届 × 8 组件 = 240 行；实际 {validation['actual_rows']} 行，唯一键 {validation['unique_keys']} 个，校验 `{'PASS' if validation['valid'] else 'FAIL'}`。",
            f"- 当前优先范围（JP3—22 + CN1—11）完成判定 `{'PASS' if validation['priority_scope_complete'] else 'FAIL'}`；CN10—11 若快照尚未齐全仍保留为 `pending`，不会伪装成已完成。",
            f"- 明确抓取失败共 {len(failures)} 行；它们均保留为 `fetch_failed`。",
            f"- 尚待抓取、规范化或完整性认证共 {len(pending)} 行；它们均保留为 `pending`。",
            "- `official_not_offered` 只来自现有 metadata 的明确状态；`not_applicable` 仅表示统一组件在该平台/接口代际没有同构含义。",
            jp_detail_note,
            "- CN10 的条件榜与共投若未达到 expected 数量，即使已有部分本地行也记 `pending`。",
            "- CN10—11 的实体问卷明细由现代站 `queryQuestionnaire(query=...)` 专用断点阶段补抓；快照未齐时保持 `pending`，不会把接口存在误报成 `not_applicable`。",
            "",
            "## 产物校验和",
            "",
            f"- `metadata/unified_component_coverage.csv`: `{csv_hash}`",
            f"- `metadata/unified_component_coverage.json`: `{json_hash}`",
            "",
            "逐行证据、观察行数、预期数量和备注见 CSV/JSON。",
            "",
        ]
    )
    return "\n".join(lines)


def build(workspace: Path) -> tuple[Path, Path, Path, dict[str, Any]]:
    workspace = workspace.resolve()
    reader = SnapshotReader(workspace)
    rows: list[CoverageRow] = []
    build_jp_legacy(reader, rows)
    build_jp_current(reader, rows)
    build_cn_legacy(reader, rows)
    build_cn_modern(reader, rows)

    platform_order = {"JP": 0, "CN": 1}
    component_order = {code: index for index, (code, _, _) in enumerate(COMPONENTS)}
    rows.sort(key=lambda row: (platform_order[row.platform], row.round, component_order[row.component]))
    validation = validate(rows)
    if not validation["valid"]:
        raise RuntimeError(f"coverage validation failed: {json.dumps(validation, ensure_ascii=False)}")

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    csv_path = workspace / "metadata" / "unified_component_coverage.csv"
    json_path = workspace / "metadata" / "unified_component_coverage.json"
    markdown_path = workspace / "reports" / "unified_component_coverage.md"

    atomic_write_text(csv_path, csv_text(rows), encoding="utf-8-sig")
    payload = {
        "schema_version": 1,
        "generated_at": generated_at,
        "scope": {"JP": [3, 22], "CN": [1, 11]},
        "offline_only": True,
        "input_roots": ["metadata", "data_processed"],
        "status_definitions": STATUS_MEANING,
        "components": [
            {"component": code, "label": label, "description": description}
            for code, label, description in COMPONENTS
        ],
        "rows": [
            {
                **asdict(row),
                "evidence": list(row.evidence),
            }
            for row in rows
        ],
        "validation": validation,
        "input_snapshots": [reader.inputs[key] for key in sorted(reader.inputs)],
    }
    atomic_write_text(
        json_path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    csv_hash = sha256(csv_path)
    json_hash = sha256(json_path)
    atomic_write_text(
        markdown_path,
        markdown_text(rows, validation, generated_at, csv_hash, json_hash),
        encoding="utf-8",
    )
    return csv_path, json_path, markdown_path, validation


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=DEFAULT_WORKSPACE,
        help=f"workspace root (default: {DEFAULT_WORKSPACE})",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    csv_path, json_path, markdown_path, validation = build(args.workspace)
    workspace = args.workspace.resolve()
    result = {
        "rows": validation["actual_rows"],
        "valid": validation["valid"],
        "all_required_components_complete": validation[
            "all_required_components_complete"
        ],
        "status_counts": validation["status_counts"],
        "outputs": [
            {
                "path": path.resolve().relative_to(workspace).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in (csv_path, json_path, markdown_path)
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
