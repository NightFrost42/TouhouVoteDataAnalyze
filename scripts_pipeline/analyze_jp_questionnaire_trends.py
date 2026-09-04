"""Build reproducible cross-round trends from official Japanese questionnaires.

The program reads only the locally normalized official data for rounds 3--21.
It writes a lossless numeric long table plus a deliberately conservative trend
layer.  The trend layer never joins answers from different questions into an
individual-level path: every row remains an aggregate for one round/question/
option and retains the official source URL and source-row references.

All derived percentages, bins, aggregates, deltas, hashes, and Markdown
findings are calculated by this program.  No chart/image OCR or estimated
values are used.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable


ANALYSIS_VERSION = "jp-questionnaire-trends-v1"
WORKSPACE = Path(__file__).resolve().parents[1]
LEGACY_CSV = WORKSPACE / "data_processed" / "jp_official_legacy" / "questionnaire_long.csv"
MODERN_CSV = WORKSPACE / "data_processed" / "jp_official" / "questionnaire_long.csv"
MODERN_MANIFEST = WORKSPACE / "metadata" / "jp_official_download_manifest.json"
OUT_ROOT = WORKSPACE / "analysis_results" / "jp_questionnaire"
ROUND_MIN = 3
ROUND_MAX = 21
ARTICLE_ROUND_MAX = 20


RAW_FIELDS = [
    "region",
    "round",
    "source_system",
    "source_question_id",
    "question_key",
    "question",
    "topic",
    "source_item",
    "source_option",
    "count",
    "denominator",
    "percent",
    "official_percent",
    "percent_basis",
    "denominator_basis",
    "source_url",
    "source_file",
    "source_locator",
    "question_path_json",
]

TREND_FIELDS = [
    "topic",
    "comparison_group",
    "definition_version",
    "round",
    "source_question_id",
    "question",
    "item",
    "option",
    "source_option",
    "count",
    "denominator",
    "percent",
    "previous_observed_round",
    "change_from_previous_pp",
    "series_round_count",
    "comparability",
    "change_flags",
    "calculation",
    "source_url",
    "source_file",
    "source_components_json",
]


MODERN_QUESTION_LABELS = {
    "age": "年齢",
    "sex": "性別",
    "location": "居住地域",
    "cleared_title": "作品別ノーコンティニュー到達難易度",
    "charm": "東方Projectに魅力を感じているところ",
    "cognition": "東方Projectを知った時期",
    "trigger": "東方Projectを知ったきっかけ",
    "voted": "過去の人気投票参加経験",
    "magazine": "公式連載作品の購読・閲覧状況",
    "intention": "同人誌即売会に参加する際の目的",
    "event": "参加する東方Project関連イベント",
    "purchase_method": "原作ゲームの購入方法",
    "friends": "東方Projectについて話す知人の人数",
    "subnumber": "整数作品以外のプレイ状況",
    "usertype": "東方Project関連活動",
    "books": "公式書籍の所持状況",
    "lastVote": "最後に人気投票へ参加した時期",
    "parents": "保護者回答",
    "th21": "東方錦上京体験版のプレイ方法",
    "triggerVote": "人気投票を知ったきっかけ",
}


CHANGE_ROWS = [
    ("age", 5, "question_first_available", "年齢の数値回答が初めて確認できる。", "第5回以降のみを比較。"),
    ("age", 6, "source_granularity_change", "概要年齢帯に加えて単年齢詳細も公表する形式へ変更。第6回の上端は40歳以上にまとめられている。", "重複する概要表を数えず、単年齢詳細を共通年齢帯へ再集計。40～49/50歳以上の細分は第6回を欠測扱い。"),
    ("age", 14, "published_bin_label_anomaly", "概要表先頭が『～10歳』、次項も『10歳～14歳』で重複する。", "重複概要表を使わず単年齢詳細から再集計。"),
    ("age", 11, "official_outliers_retained", "単年齢表には100歳等の極端値が含まれる。", "公式原数値を削除せず50歳以上へ集計し、推測による外れ値除去はしない。"),
    ("sex", 18, "option_added", "『その他』が追加され、従来の二択から三択になった。", "男性・女性は継続表示するが制度変更を明示。"),
    ("location", 12, "question_first_available", "居住地域の21区分が初めて確認できる。", "第12回以降を比較。"),
    ("location", 13, "label_change", "北九州/南九州が九州北部/九州南部表記へ変更。", "同一区分として正規化。"),
    ("cognition", 8, "question_absent", "第8・9回は知った時期の設問がない。", "欠測を0として補完しない。"),
    ("cognition", 11, "binning_redesign", "日付区間中心から作品発売区間中心の表記へ変更。", "作品区間が一致する選択肢だけ連結。"),
    ("cognition", 19, "historical_bins_revised", "天空璋以降にナイトメアダイアリーを含む区間が追加・再配置された。", "完全一致する作品区間だけ比較。"),
    ("trigger", 9, "question_absent", "第9・10回は知ったきっかけの設問がない。", "欠測を0として補完しない。"),
    ("trigger", 11, "wording_redesign", "選択肢が大幅に再設計された。", "意味が対応する大分類のみ連結し変更点を保持。"),
    ("trigger", 14, "video_split", "動画サイトがニコニコ動画とその他動画サイトへ分割。", "video_anyは両項を件数加算。"),
    ("trigger", 18, "youtube_split", "YouTubeがその他動画サイトから独立。", "video_anyはニコニコ・YouTube・その他を件数加算。"),
    ("voted", 11, "question_first_available", "過去の人気投票参加回数を初めて確認できる。", "第11回以降を比較。"),
    ("voted", 19, "bin_split", "『過去4回以上』が4～6、7～9、10回以上へ分割。", "3項を加算して従来の4回以上を再現。"),
    ("charm", 7, "legacy_design", "最大3つ選択、13項目の旧設計。", "第11回以降の7項目設計とは連結しない。"),
    ("charm", 11, "question_redesign", "7項目の複数回答設計へ変更。", "第11～21回だけを同一定義で比較。"),
    ("intention", 12, "question_first_available", "即売会参加目的の複数回答設問を確認できる。", "第12回以降を比較。"),
    ("intention", 14, "source_structure_change", "公式表に無名の親グループ行が出現。", "無名親行を除き、名前付き選択肢のみ使用。"),
    ("intention", 17, "denominator_scope_change", "参加目的の分母が参加者数から全回答者数へ変更された。", "参加目的を第12～16回（参加者内）と第17～21回（全回答者内）の別系列に分割。参加/不参加率だけは全回答者基準で連結。"),
    ("event", 19, "question_first_available", "東方関連イベント種別の設問を確認できる。", "第19回は原始値として保持し、同一分母範囲を確認できる第20・21回を比較。"),
    ("event", 20, "denominator_scope_change", "有効回答数が全体規模から限定回答群の規模へ大きく変わり、同一分母範囲を確認できない。", "第19回を第20・21回と連結せず、第20・21回だけを比較。"),
    ("event", 21, "option_added", "イベント種別に新しい選択肢が追加された。", "既存の同名選択肢を継続比較し、新項目は単年値として原始表に保持。"),
    ("cleared_title", 5, "denominator_scope_change", "作品別クリア難易度の分母が当該作品プレイヤー中心の回答群になった。", "第3・4回の全体基準と第5～10回のプレイヤー基準を別系列にする。"),
    ("cleared_title", 11, "response_and_denominator_change", "未購入/Easy未クリアを分離し、全回答者基準の形式へ変更。", "第5～10回のプレイヤー基準と第11回以降の全回答者基準を別系列にする。"),
    ("magazine", 11, "question_redesign", "所持書籍の複数回答から作品別の購読・閲覧状態へ変更。", "第4～10回と第11回以降を別系列にする。"),
    ("magazine", 20, "service_rename", "Comic Walker表記がカドコミ（旧Comic Walker）へ変更。", "同一サービスの改称として正規化。"),
    ("purchase_method", 19, "question_first_available", "CD-ROM/ダウンロード購入方法の設問を確認できる。", "第19～21回を比較。"),
    ("trigger", 21, "wording_and_options_change", "オフライン紹介から家族の例示が外れ、東方STATION等の新項目が追加された。", "対応する既存大分類は継続し、新項目は単年値として原始表に保持。"),
    ("friends", 20, "question_first_available", "東方について話す知人の人数を確認できる。", "第20・21回の同名選択肢を比較。"),
    ("subnumber", 20, "question_first_available", "整数作品以外の作品別項目を確認できる。", "第20・21回の同名作品だけ比較。"),
    ("usertype", 20, "question_first_available", "東方関連活動の複数回答項目を確認できる。", "第20・21回の同名活動だけ比較。"),
    ("played_title", 5, "question_first_available", "プレイ経験作品の複数回答を確認できる。", "第5～10回の同設問内で比較。"),
    ("work_rating", 9, "table_scope_change", "第9回以降は評価表の作品構成が変化。", "同一作品・同一得点選択肢だけ比較。"),
    ("play_time", 9, "binning_redesign", "総プレイ時間の刻みが10時間から5時間中心へ変更。", "第3・4回の共通形式と第9回を連結しない。"),
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(WORKSPACE.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def norm(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("〜", "～").replace("~", "～")
    return " ".join(text.split()).strip()


def compact(value: Any) -> str:
    return re.sub(r"\s+", "", norm(value))


def as_int(value: Any) -> int | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return int(Decimal(text))
    except (InvalidOperation, ValueError):
        return None


def as_decimal(value: Any) -> Decimal | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def fmt_decimal(value: Decimal | None, places: int = 6) -> str:
    if value is None:
        return ""
    quantum = Decimal(1).scaleb(-places)
    text = format(value.quantize(quantum, rounding=ROUND_HALF_UP), "f")
    return text.rstrip("0").rstrip(".") or "0"


def computed_percent(count: int | None, denominator: int | None) -> Decimal | None:
    if count is None or denominator is None or denominator <= 0:
        return None
    return Decimal(count) * Decimal(100) / Decimal(denominator)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> int:
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(materialized)
    return len(materialized)


def json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_path(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
        return [str(item) for item in parsed] if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def legacy_context(row: dict[str, str]) -> str:
    item = norm(row.get("item"))
    if item and not re.search(r"^(?:有効回答数|回答数)[：:]", item):
        return item
    path = parse_path(row.get("question_path_json", ""))
    question = norm(row.get("question"))
    candidates = [
        norm(part)
        for part in path
        if norm(part)
        and norm(part) != question
        and not re.search(r"(?:有効回答数|回答数)[：:]", norm(part))
    ]
    return candidates[-1] if candidates else item


def classify_legacy(row: dict[str, str]) -> str:
    question = norm(row.get("question"))
    item = norm(row.get("item"))
    if "プレイヤー層調査" in question:
        if "性別" in item:
            return "sex"
        if "年齢" in item:
            return "age"
        return "demographics_other"
    if "知った時期別" in question or ("知った時期" in question and ("年齢別" in question or "きっかけ時期" in question)):
        return "cross_tab"
    if "知ったきっかけ" in question and "時期別" in question:
        return "cross_tab"
    if re.search(r"(?:^|[.．])(?:0?1)[.．]?年齢$", question) or question in {"年齢", "1.年齢", "01.年齢"}:
        return "age"
    if re.search(r"(?:^|[.．])(?:0?2)[.．]?性別$", question) or question in {"性別", "2.性別", "02.性別"}:
        return "sex"
    if "住まいの地域" in question:
        return "location"
    if "知った時期" in question or "本格的に知った時期" in question:
        return "cognition"
    if "知った場所" in question or "知ったきっかけ" in question:
        return "trigger"
    if "人気投票へ投票したこと" in question:
        return "voted"
    if "魅力" in question:
        return "charm"
    if "同人誌即売会に参加する際の目当て" in question:
        return "intention"
    if "ノーコン" in question:
        return "cleared_title"
    if "プレイしたことがある作品" in question:
        return "played_title"
    if re.search(r"メイン.*使用.*キャラ", question):
        return "main_character"
    if "作品の評価" in question or "各作品の評価" in question:
        return "work_rating"
    if "総プレイ時間" in question:
        return "play_time"
    if "使用入力デバイス" in question:
        return "input_device"
    if "購読" in question or "所持している本" in question or "所持している書籍" in question:
        return "magazine"
    if "同人イベント" in question or "例大祭に参加" in question:
        return "event_attendance"
    if "一番好きな作品" in question or "気に入っている作品" in question:
        return "favorite_work"
    return "other"


def modern_sources() -> dict[int, tuple[str, str]]:
    manifest = json.loads(MODERN_MANIFEST.read_text(encoding="utf-8"))
    result: dict[int, tuple[str, str]] = {}
    for record in manifest.get("records", []):
        round_no = as_int(record.get("round"))
        if not round_no or not (ROUND_MIN <= round_no <= ROUND_MAX):
            continue
        if record.get("kind") == "aggregate" and record.get("category") == "questionnaire":
            result[round_no] = (str(record.get("url", "")), str(record.get("output", "")))
    missing = sorted(set(range(17, ROUND_MAX + 1)) - set(result))
    if missing:
        raise RuntimeError(f"missing modern questionnaire source records for rounds {missing}")
    return result


def load_raw_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in read_csv(LEGACY_CSV):
        round_no = as_int(source.get("round"))
        if round_no is None or not (ROUND_MIN <= round_no <= min(16, ROUND_MAX)):
            continue
        count = as_int(source.get("count"))
        denominator = as_int(source.get("denominator"))
        official = as_decimal(source.get("official_percentage") or source.get("percentage"))
        calculated = computed_percent(count, denominator)
        rows.append(
            {
                "region": "jp",
                "round": round_no,
                "source_system": "jp_official_legacy",
                "source_question_id": source.get("question_id", ""),
                "question_key": "",
                "question": norm(source.get("question")),
                "topic": classify_legacy(source),
                "source_item": norm(source.get("item")),
                "source_option": norm(source.get("option")),
                "count": count if count is not None else "",
                "denominator": denominator if denominator is not None else "",
                "percent": fmt_decimal(calculated if calculated is not None else official),
                "official_percent": fmt_decimal(official),
                "percent_basis": (
                    "computed_from_count_and_denominator" if calculated is not None else source.get("percentage_basis", "")
                ),
                "denominator_basis": source.get("denominator_basis", ""),
                "source_url": source.get("source_url", ""),
                "source_file": source.get("source_file", ""),
                "source_locator": f"table:{source.get('source_table_index', '')}/row:{source.get('source_row_index', '')}",
                "question_path_json": source.get("question_path_json", "[]"),
                "_source_table_index": source.get("source_table_index", ""),
                "_context": legacy_context(source),
            }
        )

    sources = modern_sources()
    for source in read_csv(MODERN_CSV):
        round_no = as_int(source.get("round"))
        if round_no is None or not (17 <= round_no <= ROUND_MAX):
            continue
        count = as_int(source.get("count"))
        denominator = (
            as_int(source.get("valid_count"))
            or as_int(source.get("total"))
            or as_int(source.get("conditional_denominator_derived"))
        )
        rate = as_decimal(source.get("rate"))
        official = rate * Decimal(100) if rate is not None else None
        calculated = computed_percent(count, denominator)
        url, source_file = sources[round_no]
        key = str(source.get("question_key", ""))
        rows.append(
            {
                "region": "jp",
                "round": round_no,
                "source_system": "jp_official_modern",
                "source_question_id": f"jp{round_no}:{key}",
                "question_key": key,
                "question": MODERN_QUESTION_LABELS.get(key, key),
                "topic": key,
                "source_item": norm(source.get("name")),
                "source_option": norm(source.get("label") or source.get("value")),
                "count": count if count is not None else "",
                "denominator": denominator if denominator is not None else "",
                "percent": fmt_decimal(calculated if calculated is not None else official),
                "official_percent": fmt_decimal(official),
                "percent_basis": "computed_from_count_and_denominator" if calculated is not None else "official_rate",
                "denominator_basis": (
                    "official_valid_count"
                    if as_int(source.get("valid_count")) is not None
                    else "official_total"
                    if as_int(source.get("total")) is not None
                    else "derived_from_official_count_rate_pair"
                    if denominator is not None
                    else "not_available"
                ),
                "source_url": url,
                "source_file": source_file,
                "source_locator": source.get("node_path", ""),
                "question_path_json": "[]",
                "_source_table_index": "",
                "_context": norm(source.get("name")),
            }
        )
    rows.sort(key=lambda row: (int(row["round"]), row["source_question_id"], row["source_locator"]))
    return rows


def component(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_question_id": row["source_question_id"],
        "question": row["question"],
        "source_item": row["source_item"],
        "source_option": row["source_option"],
        "count": row["count"],
        "denominator": row["denominator"],
        "source_url": row["source_url"],
        "source_file": row["source_file"],
        "source_locator": row["source_locator"],
    }


def version_for(topic: str, round_no: int) -> str:
    if topic == "age":
        return "published_age_bins" if round_no == 5 else "exact_or_topcoded_ages_rebinned"
    if topic == "sex":
        return "binary_options" if round_no <= 17 else "three_options_with_other"
    if topic == "location":
        return "north_south_kyushu_labels" if round_no == 12 else "kyushu_north_south_labels"
    if topic == "cognition":
        return "date_interval_labels" if round_no <= 10 else "release_interval_labels"
    if topic == "trigger":
        if round_no <= 8:
            return "legacy_channels"
        if round_no <= 13:
            return "redesigned_channels"
        if round_no <= 17:
            return "split_niconico_other_video"
        return "split_niconico_youtube_other_video"
    if topic == "voted":
        return "three_bins" if round_no <= 18 else "five_bins_reaggregated"
    if topic == "cleared_title":
        if round_no <= 4:
            return "early_overall_max_clear_level"
        if round_no <= 10:
            return "legacy_player_subcohort_max_clear_level"
        return "all_respondents_purchase_and_max_clear_level"
    if topic == "magazine":
        return "holdings_multiple_response" if round_no <= 10 else "per_series_reading_status"
    return "stable"


def flags_for(topic: str, round_no: int) -> str:
    return ";".join(change_type for change_topic, change_round, change_type, _detail, _treatment in CHANGE_ROWS if change_topic == topic and change_round == round_no)


def make_trend(
    *,
    topic: str,
    comparison_group: str,
    round_no: int,
    item: str,
    option: str,
    components: list[dict[str, Any]],
    calculation: str,
    comparability: str = "comparable_after_documented_normalization",
) -> dict[str, Any] | None:
    usable = [row for row in components if isinstance(row.get("count"), int) and isinstance(row.get("denominator"), int)]
    if not usable:
        return None
    denominators = {int(row["denominator"]) for row in usable}
    if len(denominators) != 1:
        return None
    denominator = denominators.pop()
    # Identical official rows sometimes occur as duplicate visual views.  Do
    # not add those twice; different options intentionally remain additive.
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for row in usable:
        signature = (
            row["source_question_id"],
            row["source_item"],
            row["source_option"],
            row["count"],
            row["denominator"],
        )
        if signature not in seen:
            seen.add(signature)
            deduped.append(row)
    count = sum(int(row["count"]) for row in deduped)
    percent = computed_percent(count, denominator)
    if percent is None:
        return None
    questions = list(dict.fromkeys(str(row["question"]) for row in deduped))
    question_ids = list(dict.fromkeys(str(row["source_question_id"]) for row in deduped))
    source_options = list(dict.fromkeys(str(row["source_option"]) for row in deduped))
    urls = list(dict.fromkeys(str(row["source_url"]) for row in deduped if row.get("source_url")))
    files = list(dict.fromkeys(str(row["source_file"]) for row in deduped if row.get("source_file")))
    return {
        "topic": topic,
        "comparison_group": comparison_group,
        "definition_version": version_for(topic, round_no),
        "round": round_no,
        "source_question_id": ";".join(question_ids),
        "question": "; ".join(questions),
        "item": item,
        "option": option,
        "source_option": " + ".join(source_options),
        "count": count,
        "denominator": denominator,
        "percent": fmt_decimal(percent),
        "previous_observed_round": "",
        "change_from_previous_pp": "",
        "series_round_count": "",
        "comparability": comparability,
        "change_flags": flags_for(topic, round_no),
        "calculation": calculation,
        "source_url": ";".join(urls),
        "source_file": ";".join(files),
        "source_components_json": json.dumps([component(row) for row in deduped], ensure_ascii=False, separators=(",", ":")),
    }


def make_complement_trend(
    *,
    topic: str,
    comparison_group: str,
    round_no: int,
    option: str,
    source_row: dict[str, Any],
) -> dict[str, Any] | None:
    """Create denominator-count while retaining the unmodified official row."""
    if not isinstance(source_row.get("count"), int) or not isinstance(source_row.get("denominator"), int):
        return None
    denominator = int(source_row["denominator"])
    count = denominator - int(source_row["count"])
    if count < 0:
        return None
    record = make_trend(
        topic=topic,
        comparison_group=comparison_group,
        round_no=round_no,
        item="",
        option=option,
        components=[source_row],
        calculation="official question denominator - official not-participating count; then count / denominator * 100",
        comparability="comparable_complement_of_official_not_participating_option",
    )
    if record is None:
        return None
    record["source_option"] = f"NOT({source_row['source_option']})"
    record["count"] = count
    record["percent"] = fmt_decimal(computed_percent(count, denominator))
    return record


def age_bucket(option: str) -> str | None:
    text = compact(option)
    match = re.fullmatch(r"(\d+)歳", text)
    if match:
        age = int(match.group(1))
        if age <= 9:
            return "00-09"
        if age <= 14:
            return "10-14"
        if age <= 19:
            return "15-19"
        if age <= 24:
            return "20-24"
        if age <= 29:
            return "25-29"
        if age <= 34:
            return "30-34"
        if age <= 39:
            return "35-39"
        return "40+"
    if text in {"10歳未満", "～9歳"}:
        return "00-09"
    range_match = re.search(r"(\d+)歳?[～-](\d+)歳", text)
    if range_match:
        low, high = map(int, range_match.groups())
        if (low, high) == (10, 14):
            return "10-14"
        if (low, high) == (15, 19):
            return "15-19"
        if (low, high) == (20, 24):
            return "20-24"
        if (low, high) == (25, 29):
            return "25-29"
        if (low, high) == (30, 34):
            return "30-34"
        if (low, high) == (35, 39):
            return "35-39"
        if low >= 40:
            return "40+"
    if re.search(r"(?:40|50|60)歳(?:以上|～)", text):
        return "40+"
    return None


def age_fine_40plus_bucket(option: str) -> str | None:
    text = compact(option)
    match = re.fullmatch(r"(\d+)歳", text)
    if match:
        age = int(match.group(1))
        if 40 <= age <= 49:
            return "40-49"
        if age >= 50:
            return "50+"
        return None
    range_match = re.search(r"(\d+)歳?[～-](\d+)歳", text)
    if range_match:
        low, high = map(int, range_match.groups())
        if low >= 50:
            return "50+"
        if low >= 40 and high <= 49:
            return "40-49"
    if re.search(r"(?:50|60)歳(?:以上|～)", text):
        return "50+"
    return None


def age_source_eligible(row: dict[str, Any]) -> bool:
    round_no = int(row["round"])
    table = str(row.get("_source_table_index"))
    if round_no == 5:
        return table == "1"
    if 6 <= round_no <= 10:
        return table == "2"
    if 11 <= round_no <= 16:
        return table == "1"
    return round_no >= 17


def canonical_location(option: str) -> str:
    text = norm(option).replace("北九州", "九州北部").replace("南九州", "九州南部")
    if text.startswith(("日本国外：東アジア", "日本国外:東アジア")):
        return "日本国外：東アジア"
    return text


def canonical_cognition(option: str) -> str:
    text = norm(option).replace("(", "（").replace(")", "）")
    if "旧東方シリーズから" in text or text.startswith("旧作～秋霜玉"):
        return "旧作～秋霜玉"
    inner_match = re.search(r"（([^）]+)）", text)
    if re.match(r"\d{4}/\d{2}", text) and inner_match:
        inner = inner_match.group(1)
        inner = re.sub(r"(?:の間|から)$", "", inner)
        return norm(inner)
    prefix = text.split("（", 1)[0]
    return norm(prefix)


def trigger_category(option: str) -> str | None:
    text = compact(option).lower()
    if "学校、部活" in text or "知人の紹介" in text:
        return "offline_referral"
    if "オンラインゲーム" in text or "チャット" in text:
        return "online_social"
    if "個人サイト" in text or "ブログ" in text:
        return "personal_sites"
    if "pixiv" in text or "イラストsns" in text or "イラスト投稿サイト" in text:
        return "illustration_sns"
    if "2ちゃんねる" in text or "匿名掲示板" in text:
        return "anonymous_boards"
    if "ニコニコ" in text or "youtube" in text or "動画サイト" in text:
        return "video_any"
    if "twitter" in text:
        return "twitter"
    if "好きな作家" in text:
        return "creator_fandom"
    if "雑誌" in text or "tv" in text or "公式連載" in text or "企業サイト" in text:
        return "official_or_mass_media"
    if "即売会以外のリアルイベント" in text:
        return "other_offline_event"
    if "同人誌即売会" in text or "コミケ" in text:
        return "doujin_event"
    if "同人ショップ" in text or "一般書店" in text:
        return "shop"
    if "音楽ゲーム" in text or "音ゲ" in text:
        return "rhythm_game"
    if "スマホアプリ" in text:
        return "derivative_smartphone_game"
    if "二次創作ゲーム" in text:
        return "derivative_game"
    if "格闘ゲーム" in text:
        return "game_search_fighting"
    if "stg" in text:
        return "game_search_stg"
    if "面白いゲーム" in text:
        return "game_search_general"
    if "キャラクター" in text:
        return "character_interest"
    if "音楽cd" in text or "曲(アレンジ含む)" in text or "曲（アレンジ含む）" in text:
        return "music_interest"
    if "ネットでたまたま" in text:
        return "incidental_web"
    return None


def canonical_work(value: str) -> str:
    text = norm(value).lstrip("■")
    text = re.split(r"\s+-\s+(?:有効回答数|グラフ)", text, maxsplit=1)[0]
    text = re.sub(r"[（(](?:Febri|コンプエース)連載[）)]$", "", text)
    if text.startswith("東方"):
        text = text[2:]
    return norm(text)


def clear_option(option: str) -> str | None:
    text = compact(option)
    mapping = {
        "EASY": "Easyクリア",
        "NORMAL": "Normalクリア",
        "HARD": "Hardクリア",
        "LUNATIC": "Lunaticクリア",
        "Easyクリア": "Easyクリア",
        "Normalクリア": "Normalクリア",
        "Hardクリア": "Hardクリア",
        "Lunaticクリア": "Lunaticクリア",
        "Easy未クリア": "Easy未クリア",
        "未購入": "未購入",
    }
    return mapping.get(text)


def canonical_magazine_option(option: str) -> str:
    text = norm(option)
    if "Comic Walker" in text or "カドコミ" in text:
        return "Comic Walker/カドコミで読んでいる"
    return text


def direct_candidates(
    raw: list[dict[str, Any]],
    *,
    topic: str,
    comparison_group: str,
    item_fn=lambda row: "",
    option_fn=lambda row: norm(row["source_option"]),
    include_fn=lambda row: True,
    comparability: str = "comparable_exact_option",
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in raw:
        if row["topic"] != topic or not include_fn(row):
            continue
        item = item_fn(row)
        option = option_fn(row)
        if not option or option == "__UNLABELED_PARENT_GROUP__":
            continue
        grouped[(int(row["round"]), item, option)].append(row)
    output: list[dict[str, Any]] = []
    for (round_no, item, option), components in grouped.items():
        record = make_trend(
            topic=topic,
            comparison_group=comparison_group,
            round_no=round_no,
            item=item,
            option=option,
            components=components,
            calculation="official_count / official_or_exactly_derived_question_denominator * 100",
            comparability=comparability,
        )
        if record:
            output.append(record)
    return output


def build_trends(raw: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    candidates: list[dict[str, Any]] = []
    warnings: list[str] = []

    # Age: use exactly one official source view per round.  Round 5 uses the
    # overview; rounds 6--10 use the exact-age table; rounds 11--21 use the
    # exact-age source.  This avoids double counting where both views exist and
    # also avoids the round-14 overview typo.
    age_grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in raw:
        if row["topic"] != "age":
            continue
        round_no = int(row["round"])
        bucket = age_bucket(row["source_option"]) if age_source_eligible(row) else None
        if bucket:
            age_grouped[(round_no, bucket)].append(row)
    age_rows: dict[tuple[int, str], dict[str, Any]] = {}
    for (round_no, bucket), components in age_grouped.items():
        record = make_trend(
            topic="age",
            comparison_group="age_fixed_bins",
            round_no=round_no,
            item="",
            option=bucket,
            components=components,
            calculation="sum(official age counts in fixed bin) / common age-question denominator * 100",
        )
        if record:
            candidates.append(record)
            age_rows[(round_no, bucket)] = record
    broad_definitions = {
        "under20": ["00-09", "10-14", "15-19"],
        "twenties": ["20-24", "25-29"],
        "30plus": ["30-34", "35-39", "40+"],
    }
    for round_no in sorted({key[0] for key in age_rows}):
        # Reuse original components referenced by fixed-bin rows, not the
        # derived rows themselves, so every output still points to official rows.
        for broad, buckets in broad_definitions.items():
            components: list[dict[str, Any]] = []
            for bucket in buckets:
                record = age_rows.get((round_no, bucket))
                if record:
                    for source_component in json.loads(record["source_components_json"]):
                        # Recover the matching raw row by stable locator.
                        matches = [
                            row
                            for row in raw
                            if int(row["round"]) == round_no
                            and row["source_question_id"] == source_component["source_question_id"]
                            and row["source_locator"] == source_component["source_locator"]
                        ]
                        components.extend(matches)
            record = make_trend(
                topic="age",
                comparison_group="age_broad_groups",
                round_no=round_no,
                item="",
                option=broad,
                components=components,
                calculation="sum(official counts across fixed age bins) / common age-question denominator * 100",
            )
            if record:
                candidates.append(record)

    # Preserve the useful 40+ split when the official source supports it.
    # Round 6 publishes only a single "40歳以上" value, so it is deliberately
    # missing here instead of being imputed or converted to zero.
    age_40plus_detail: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in raw:
        if row["topic"] != "age" or not age_source_eligible(row):
            continue
        bucket = age_fine_40plus_bucket(row["source_option"])
        if bucket:
            age_40plus_detail[(int(row["round"]), bucket)].append(row)
    for (round_no, bucket), components in age_40plus_detail.items():
        record = make_trend(
            topic="age",
            comparison_group="age_40plus_detail",
            round_no=round_no,
            item="",
            option=bucket,
            components=components,
            calculation="sum(official age counts in 40+ detail bin) / common age-question denominator * 100",
        )
        if record:
            candidates.append(record)

    candidates += direct_candidates(
        raw,
        topic="sex",
        comparison_group="sex_options",
        option_fn=lambda row: {"男性": "male", "女性": "female", "その他": "other"}.get(compact(row["source_option"]), ""),
    )

    location_detail = direct_candidates(
        raw,
        topic="location",
        comparison_group="location_regions",
        option_fn=lambda row: canonical_location(row["source_option"]),
    )
    candidates += location_detail
    by_location_round: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in raw:
        if row["topic"] == "location":
            by_location_round[int(row["round"])].append(row)
    for round_no, rows in by_location_round.items():
        for option, components in {
            "domestic": [row for row in rows if not norm(row["source_option"]).startswith("日本国外")],
            "overseas": [row for row in rows if norm(row["source_option"]).startswith("日本国外")],
        }.items():
            record = make_trend(
                topic="location",
                comparison_group="domestic_overseas",
                round_no=round_no,
                item="",
                option=option,
                components=components,
                calculation="sum(official regional counts) / common location-question denominator * 100",
            )
            if record:
                candidates.append(record)

    candidates += direct_candidates(
        raw,
        topic="cognition",
        comparison_group="cognition_release_cohorts",
        option_fn=lambda row: canonical_cognition(row["source_option"]),
    )

    trigger_grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in raw:
        if row["topic"] == "trigger":
            category = trigger_category(row["source_option"])
            if category:
                trigger_grouped[(int(row["round"]), category)].append(row)
    for (round_no, category), components in trigger_grouped.items():
        record = make_trend(
            topic="trigger",
            comparison_group="trigger_channels",
            round_no=round_no,
            item="",
            option=category,
            components=components,
            calculation=(
                "sum(mutually-exclusive official video suboptions) / question denominator * 100"
                if category == "video_any"
                else "official option count / question denominator * 100"
            ),
            comparability=(
                "comparable_after_video_suboption_reaggregation"
                if category == "video_any"
                else "comparable_after_documented_wording_normalization"
            ),
        )
        if record:
            candidates.append(record)

    voted_grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in raw:
        if row["topic"] != "voted":
            continue
        text = compact(row["source_option"])
        if "今回がはじめて" in text:
            option = "first_time"
        elif "過去1～3回" in text:
            option = "past_1_3"
        elif "過去4回以上" in text or "過去4～6回" in text or "過去7～9回" in text or "過去10回以上" in text:
            option = "past_4_plus"
        else:
            continue
        voted_grouped[(int(row["round"]), option)].append(row)
    for (round_no, option), components in voted_grouped.items():
        record = make_trend(
            topic="voted",
            comparison_group="voting_experience_common_bins",
            round_no=round_no,
            item="",
            option=option,
            components=components,
            calculation="sum(official experience-bin counts in common bin) / question denominator * 100",
        )
        if record:
            candidates.append(record)

    candidates += direct_candidates(
        raw,
        topic="charm",
        comparison_group="charm_7_options",
        include_fn=lambda row: int(row["round"]) >= 11,
        option_fn=lambda row: norm(row["source_option"]),
        comparability="comparable_multiple_response_option",
    )
    # The intention denominator changes at round 17.  Preserve three distinct
    # quantities: overall participation (comparable across 12--21), purposes
    # among participants (12--16), and purposes among all respondents (17--21).
    intention_not_participating: dict[int, dict[str, Any]] = {}
    for row in raw:
        if row["topic"] == "intention" and compact(row["source_option"]) == "参加していない":
            intention_not_participating[int(row["round"])] = row
    for round_no, source_row in sorted(intention_not_participating.items()):
        not_record = make_trend(
            topic="intention",
            comparison_group="event_participation_overall",
            round_no=round_no,
            item="",
            option="not_participating",
            components=[source_row],
            calculation="official not-participating count / all-response denominator * 100",
            comparability="comparable_overall_participation_status",
        )
        if not_record:
            candidates.append(not_record)
        participating_record = make_complement_trend(
            topic="intention",
            comparison_group="event_participation_overall",
            round_no=round_no,
            option="participating",
            source_row=source_row,
        )
        if participating_record:
            candidates.append(participating_record)
    candidates += direct_candidates(
        raw,
        topic="intention",
        comparison_group="event_intention_among_participants",
        include_fn=lambda row: int(row["round"]) <= 16 and compact(row["source_option"]) not in {"参加していない", "__UNLABELED_PARENT_GROUP__"},
        option_fn=lambda row: norm(row["source_option"]),
        comparability="comparable_multiple_response_option_among_event_participants",
    )
    candidates += direct_candidates(
        raw,
        topic="intention",
        comparison_group="event_intention_all_respondents",
        include_fn=lambda row: int(row["round"]) >= 17 and compact(row["source_option"]) != "参加していない",
        option_fn=lambda row: norm(row["source_option"]),
        comparability="comparable_multiple_response_option_among_all_respondents",
    )
    # The official event valid_count changes scope between rounds 19 and 20.
    # Round 19 stays in the raw table; only the confirmed same-scope 20--21
    # sequence enters a trend.
    candidates += direct_candidates(
        raw,
        topic="event",
        comparison_group="event_type_limited_response_group",
        include_fn=lambda row: int(row["round"]) >= 20,
        option_fn=lambda row: norm(row["source_option"]),
        comparability="comparable_multiple_response_option_same_denominator_scope_rounds_20_21",
    )
    candidates += direct_candidates(
        raw,
        topic="purchase_method",
        comparison_group="purchase_method_options",
        option_fn=lambda row: norm(row["source_option"]),
    )
    candidates += direct_candidates(
        raw,
        topic="friends",
        comparison_group="friends_count_options",
        option_fn=lambda row: norm(row["source_option"]),
    )
    candidates += direct_candidates(
        raw,
        topic="subnumber",
        comparison_group="subnumber_title_options",
        option_fn=lambda row: canonical_work(row["source_option"]),
        comparability="comparable_same_subnumber_title_option",
    )
    candidates += direct_candidates(
        raw,
        topic="usertype",
        comparison_group="user_activity_options",
        option_fn=lambda row: norm(row["source_option"]),
        comparability="comparable_multiple_response_option",
    )

    clear_periods = [
        ("title_clear_level_early_overall", lambda round_no: round_no <= 4, "comparable_same_title_and_clear_status_early_overall_scope"),
        ("title_clear_level_legacy_player_subcohort", lambda round_no: 5 <= round_no <= 10, "comparable_same_title_and_clear_status_within_player_subcohort_scope"),
        ("title_clear_level_all_respondents", lambda round_no: round_no >= 11, "comparable_same_title_and_clear_status_all_respondents_scope"),
    ]
    for comparison_group, round_filter, comparability in clear_periods:
        candidates += direct_candidates(
            raw,
            topic="cleared_title",
            comparison_group=comparison_group,
            item_fn=lambda row: canonical_work(row.get("_context") or row["source_item"]),
            option_fn=lambda row: clear_option(row["source_option"]) or "",
            include_fn=lambda row, round_filter=round_filter: (
                round_filter(int(row["round"]))
                and bool(clear_option(row["source_option"]))
                and bool(canonical_work(row.get("_context") or row["source_item"]))
            ),
            comparability=comparability,
        )

    candidates += direct_candidates(
        raw,
        topic="magazine",
        comparison_group="magazine_holdings",
        include_fn=lambda row: int(row["round"]) <= 10,
        option_fn=lambda row: norm(row["source_option"]),
        comparability="comparable_exact_holding_option_within_legacy_design",
    )
    candidates += direct_candidates(
        raw,
        topic="magazine",
        comparison_group="magazine_series_status",
        include_fn=lambda row: int(row["round"]) >= 11,
        item_fn=lambda row: canonical_work(row.get("_context") or row["source_item"]),
        option_fn=lambda row: canonical_magazine_option(row["source_option"]),
        comparability="comparable_same_series_and_reading_status",
    )
    candidates += direct_candidates(
        raw,
        topic="played_title",
        comparison_group="played_title_options",
        include_fn=lambda row: "作品別" in norm(row["source_item"]),
        option_fn=lambda row: canonical_work(row["source_option"]),
        comparability="comparable_multiple_response_title",
    )
    candidates += direct_candidates(
        raw,
        topic="played_title",
        comparison_group="played_title_count_distribution",
        include_fn=lambda row: "作品数" in norm(row["source_item"]),
        option_fn=lambda row: norm(row["source_option"]),
        comparability="comparable_mutually_exclusive_number_of_titles_played_bin",
    )
    candidates += direct_candidates(
        raw,
        topic="main_character",
        comparison_group="main_character_by_title",
        item_fn=lambda row: canonical_work(row.get("_context") or row["source_item"]),
        option_fn=lambda row: compact(row["source_option"]),
        comparability="comparable_same_title_and_character_option",
    )
    candidates += direct_candidates(
        raw,
        topic="work_rating",
        comparison_group="work_rating_by_title",
        item_fn=lambda row: canonical_work(row.get("_context") or row["source_item"]),
        option_fn=lambda row: norm(row["source_option"]),
        comparability="comparable_same_title_and_score_option",
    )
    candidates += direct_candidates(
        raw,
        topic="play_time",
        comparison_group="play_time_10h_bins",
        include_fn=lambda row: int(row["round"]) in {3, 4},
        item_fn=lambda row: canonical_work(row.get("_context") or row["source_item"]),
        option_fn=lambda row: norm(row["source_option"]),
        comparability="comparable_same_title_and_time_bin_in_rounds_3_4",
    )
    candidates += direct_candidates(
        raw,
        topic="input_device",
        comparison_group="input_device_options",
        option_fn=lambda row: norm(row["source_option"]),
    )

    # Retain only series observed in at least two rounds.  A missing round is
    # missing data, never a zero.
    series_groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        key = (row["topic"], row["comparison_group"], row["item"], row["option"])
        series_groups[key].append(row)
    trends: list[dict[str, Any]] = []
    for key, series in series_groups.items():
        distinct_rounds = sorted({int(row["round"]) for row in series})
        if len(distinct_rounds) < 2:
            continue
        # If conflicting duplicate values survive for a round, suppress that
        # series and report it instead of silently choosing one.
        per_round: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in series:
            per_round[int(row["round"])].append(row)
        conflict = any(len({(r["count"], r["denominator"]) for r in rows}) > 1 for rows in per_round.values())
        if conflict:
            warnings.append(f"conflicting duplicate trend series suppressed: {key}")
            continue
        deduped = [rows[0] for _round, rows in sorted(per_round.items())]
        previous: dict[str, Any] | None = None
        for row in deduped:
            row["series_round_count"] = len(distinct_rounds)
            if previous is not None:
                row["previous_observed_round"] = previous["round"]
                row["change_from_previous_pp"] = fmt_decimal(
                    Decimal(str(row["percent"])) - Decimal(str(previous["percent"])), 6
                )
            trends.append(row)
            previous = row
    trends.sort(key=lambda row: (row["topic"], row["comparison_group"], row["item"], row["option"], int(row["round"])))
    return trends, warnings


def trend_deltas(trends: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in trends:
        grouped[(row["topic"], row["comparison_group"], row["item"], row["option"])].append(row)
    output: list[dict[str, Any]] = []
    for (topic, group, item, option), rows in grouped.items():
        ordered = sorted(rows, key=lambda row: int(row["round"]))
        first, last = ordered[0], ordered[-1]
        observed = [int(row["round"]) for row in ordered]
        missing = [round_no for round_no in range(observed[0], observed[-1] + 1) if round_no not in observed]
        output.append(
            {
                "topic": topic,
                "comparison_group": group,
                "item": item,
                "option": option,
                "first_round": first["round"],
                "first_count": first["count"],
                "first_denominator": first["denominator"],
                "first_percent": first["percent"],
                "last_round": last["round"],
                "last_count": last["count"],
                "last_denominator": last["denominator"],
                "last_percent": last["percent"],
                "change_pp": fmt_decimal(Decimal(str(last["percent"])) - Decimal(str(first["percent"])), 6),
                "rounds_observed": len(observed),
                "observed_rounds_json": json.dumps(observed, separators=(",", ":")),
                "missing_rounds_json": json.dumps(missing, separators=(",", ":")),
                "source_url_first": first["source_url"],
                "source_url_last": last["source_url"],
            }
        )
    output.sort(key=lambda row: (row["topic"], row["comparison_group"], row["item"], row["option"]))
    return output


def question_inventory(raw: list[dict[str, Any]], trends: list[dict[str, Any]]) -> list[dict[str, Any]]:
    included = {(int(row["round"]), topic) for row in trends for topic in [row["topic"]]}
    grouped: dict[tuple[int, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in raw:
        grouped[(int(row["round"]), row["topic"], row["source_question_id"], row["question"])].append(row)
    output: list[dict[str, Any]] = []
    for (round_no, topic, question_id, question), rows in grouped.items():
        is_included = (round_no, topic) in included
        if is_included:
            trend_status = "included_in_comparable_trend"
            exclusion_reason = ""
        elif topic == "cross_tab":
            trend_status = "excluded_cross_tab"
            exclusion_reason = "aggregate cross-tab retained, but not joined into an individual response path"
        elif topic in {"books", "lastVote", "parents", "th21", "triggerVote"}:
            trend_status = "raw_only_single_round_question"
            exclusion_reason = "question is available in only one round within scope"
        elif topic in {"event_attendance", "favorite_work"}:
            trend_status = "raw_only_incompatible_repeated_design"
            exclusion_reason = "similarly themed rounds use materially different question/ranking definitions"
        elif topic in {"main_character", "work_rating"}:
            trend_status = "raw_only_no_repeated_item_option"
            exclusion_reason = "question repeats, but the title/item set changes and no same item-option series spans two rounds"
        elif topic in {"other", "demographics_other"}:
            trend_status = "raw_only_one_off_or_unmapped"
            exclusion_reason = "one-off numeric question or component outside a repeatable cross-round definition"
        else:
            trend_status = "raw_only_no_two_round_series"
            exclusion_reason = "no same-definition option series appears in at least two rounds"
        output.append(
            {
                "round": round_no,
                "topic": topic,
                "source_question_id": question_id,
                "question": question,
                "rows": len(rows),
                "numeric_rows": sum(isinstance(row["count"], int) for row in rows),
                "rows_with_denominator": sum(isinstance(row["denominator"], int) for row in rows),
                "included_in_any_comparable_trend": is_included,
                "trend_status": trend_status,
                "exclusion_reason": exclusion_reason,
                "source_url": ";".join(dict.fromkeys(row["source_url"] for row in rows if row["source_url"])),
            }
        )
    output.sort(key=lambda row: (int(row["round"]), row["topic"], row["source_question_id"]))
    return output


def topic_round_coverage(raw: list[dict[str, Any]], trends: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_counts: dict[tuple[str, int], int] = defaultdict(int)
    trend_counts: dict[tuple[str, int], int] = defaultdict(int)
    for row in raw:
        if isinstance(row.get("count"), int):
            raw_counts[(row["topic"], int(row["round"]))] += 1
    for row in trends:
        trend_counts[(row["topic"], int(row["round"]))] += 1
    topics = sorted(set(topic for topic, _round in raw_counts) | set(topic for topic, _round in trend_counts))
    output = []
    for topic in topics:
        for round_no in range(ROUND_MIN, ROUND_MAX + 1):
            output.append(
                {
                    "topic": topic,
                    "round": round_no,
                    "raw_numeric_rows": raw_counts.get((topic, round_no), 0),
                    "comparable_trend_rows": trend_counts.get((topic, round_no), 0),
                    "status": (
                        "comparable_trend_available"
                        if trend_counts.get((topic, round_no), 0)
                        else "raw_only_or_not_comparable"
                        if raw_counts.get((topic, round_no), 0)
                        else "question_not_offered_or_not_present"
                    ),
                }
            )
    return output


def make_findings(deltas: list[dict[str, Any]]) -> dict[str, Any]:
    preferred_groups = [
        "age_broad_groups",
        "sex_options",
        "domestic_overseas",
        "cognition_release_cohorts",
        "trigger_channels",
        "voting_experience_common_bins",
        "charm_7_options",
        "event_participation_overall",
        "event_intention_among_participants",
        "event_intention_all_respondents",
        "event_type_limited_response_group",
        "purchase_method_options",
        "friends_count_options",
        "subnumber_title_options",
        "user_activity_options",
    ]
    findings: dict[str, Any] = {}
    for group in preferred_groups:
        rows = [row for row in deltas if row["comparison_group"] == group]
        ranked = sorted(rows, key=lambda row: abs(Decimal(str(row["change_pp"]))), reverse=True)
        findings[group] = ranked[:10]
    return findings


def markdown_report(
    raw: list[dict[str, Any]],
    trends: list[dict[str, Any]],
    deltas: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    warnings: list[str],
) -> str:
    topic_rounds: dict[str, set[int]] = defaultdict(set)
    for row in trends:
        topic_rounds[row["topic"]].add(int(row["round"]))
    lines = [
        "# 日文官方第3—21回アンケート可比趋势",
        "",
        f"由 `{rel(Path(__file__))}` 使用本地官方数值生成；分析版本 `{ANALYSIS_VERSION}`。",
        "",
        "## 口径",
        "",
        f"- 原始数值长表共 {len(raw):,} 行；可比趋势表共 {len(trends):,} 行；端点变化表共 {len(deltas):,} 条序列。",
        "- 待审文章的叙述时点截至第20回；数据复核与趋势文件额外覆盖最新的第21回。",
        "- 每个趋势点仍是一个届次、一个题目/规范化选项的汇总值；没有把不同题目的回答拼接成个人路径。",
        "- 比例统一由本地程序按 `count / denominator × 100` 重算。多选题各项比例之和可以超过100%。",
        "- 只保留至少出现于两届的同定义序列；缺题届次保持缺测，不补0。",
        "- 年龄按固定年龄带重算；视频渠道在拆项届次按互斥选项加总；第19回起的参投经历细桶重新合成为“4回以上”。",
        "- 单年龄中的100岁等官方极端值不做主观删除，统一进入50岁以上；原值和来源行仍可追溯。",
        "- 即卖会目的在第17回发生分母范围变化，活动类型在第19/20回间也有分母断点；报告分别成组，禁止跨断点计算变化。",
        "- 样本是自愿参加人气投票者的重复横截面，不代表全部东方受众，也不能解释为同一批人的迁移。",
        "",
        "## 可比覆盖",
        "",
        "| 主题 | 可比届次 | 趋势行数 |",
        "|---|---:|---:|",
    ]
    for topic in sorted(topic_rounds):
        rounds = sorted(topic_rounds[topic])
        round_text = ",".join(map(str, rounds))
        count = sum(1 for row in trends if row["topic"] == topic)
        lines.append(f"| {topic} | {round_text} | {count:,} |")

    labels = {
        "age_broad_groups": "年龄大类",
        "sex_options": "性别",
        "domestic_overseas": "日本国内/海外",
        "cognition_release_cohorts": "知晓时期（作品区间）",
        "trigger_channels": "知晓契机",
        "voting_experience_common_bins": "参投经历",
        "charm_7_options": "魅力（多选）",
        "event_participation_overall": "即卖会参加/未参加（全体回答者）",
        "event_intention_among_participants": "即卖会参加目的（第12—16回，参加者内多选）",
        "event_intention_all_respondents": "即卖会参加目的（第17—21回，全体回答者内多选）",
        "event_type_limited_response_group": "活动类型（第20—21回，同范围回答群内多选）",
        "purchase_method_options": "原作购买方式",
        "friends_count_options": "可交流的东方同好人数",
        "subnumber_title_options": "整数作以外作品",
        "user_activity_options": "东方相关活动（多选）",
    }
    lines += ["", "## 数值变化摘要", ""]
    for group, title in labels.items():
        rows = [row for row in deltas if row["comparison_group"] == group]
        if not rows:
            continue
        lines += [f"### {title}", "", "| 选项 | 起点 | 终点 | 变化（百分点） | 观测届数 |", "|---|---:|---:|---:|---:|"]
        ranked = sorted(rows, key=lambda row: abs(Decimal(str(row["change_pp"]))), reverse=True)[:8]
        for row in ranked:
            item = f"{row['item']} / " if row["item"] else ""
            lines.append(
                f"| {item}{row['option']} | 第{row['first_round']}回 {Decimal(str(row['first_percent'])):.3f}% "
                f"({row['first_count']}/{row['first_denominator']}) | 第{row['last_round']}回 "
                f"{Decimal(str(row['last_percent'])):.3f}% ({row['last_count']}/{row['last_denominator']}) | "
                f"{Decimal(str(row['change_pp'])):+.3f} | {row['rounds_observed']} |"
            )
        lines.append("")

    lines += [
        "## 题制变化",
        "",
        "| 主题 | 届次 | 变化 | 处理 |",
        "|---|---:|---|---|",
    ]
    for topic, round_no, change_type, detail, treatment in CHANGE_ROWS:
        lines.append(f"| {topic} | {round_no} | `{change_type}`：{detail} | {treatment} |")
    if warnings:
        lines += ["", "## 程序警告", ""] + [f"- {warning}" for warning in warnings]
    lines += [
        "",
        "## 文件说明",
        "",
        "- `questionnaire_numeric_long.csv`：第3—21回全部已规范化数值行，未因不可比而丢弃。",
        "- `comparable_trends_long.csv`：至少跨两届、口径可说明的趋势点及逐行来源组件。",
        "- `trend_deltas.csv`：各可比序列的首末数值与百分点变化。",
        "- `question_inventory.csv`：逐届逐题覆盖和数值/分母完整性。",
        "- `topic_round_coverage.csv`：主题×届次覆盖矩阵，区分未设题与仅原始不可比。",
        "- `question_changes.csv`：题目、选项和分桶变更。",
        "- `summary.json`、`validation.json`：机器可读摘要、哈希和校验结果。",
        "",
    ]
    return "\n".join(lines)


def validate(raw: list[dict[str, Any]], trends: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    if {int(row["round"]) for row in raw} != set(range(ROUND_MIN, ROUND_MAX + 1)):
        issues.append("raw table does not cover every round 3--21")
    required = {"round", "source_question_id", "question", "option", "count", "denominator", "percent", "source_url"}
    for index, row in enumerate(trends, start=2):
        missing = [field for field in required if row.get(field) in (None, "")]
        if missing:
            issues.append(f"trend row {index} missing {missing}")
            continue
        expected = computed_percent(int(row["count"]), int(row["denominator"]))
        actual = Decimal(str(row["percent"]))
        if expected is None or abs(expected - actual) > Decimal("0.000001"):
            issues.append(f"trend row {index} percentage mismatch")
        if not str(row["source_url"]).startswith("http"):
            issues.append(f"trend row {index} missing official HTTP source URL")
        if any(marker in str(row["question"]) for marker in ("年齢別", "知った時期別", "きっかけ時期")):
            issues.append(f"trend row {index} improperly includes cross-tab question")
    series_rounds: dict[tuple[str, str, str, str], set[int]] = defaultdict(set)
    seen_points: set[tuple[str, str, str, str, int]] = set()
    for row in trends:
        series = (row["topic"], row["comparison_group"], row["item"], row["option"])
        point = (*series, int(row["round"]))
        if point in seen_points:
            issues.append(f"duplicate trend point: {point}")
        seen_points.add(point)
        series_rounds[series].add(int(row["round"]))
    for series, rounds in series_rounds.items():
        if len(rounds) < 2:
            issues.append(f"single-round series leaked into trends: {series}")
    partition_groups = {
        "age_fixed_bins",
        "age_broad_groups",
        "sex_options",
        "location_regions",
        "domestic_overseas",
        "voting_experience_common_bins",
        "event_participation_overall",
        "purchase_method_options",
        "friends_count_options",
    }
    partitions: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in trends:
        if row["comparison_group"] in partition_groups:
            partitions[(row["comparison_group"], int(row["round"]))].append(row)
        group = row["comparison_group"]
        round_no = int(row["round"])
        if group == "event_intention_among_participants" and round_no > 16:
            issues.append("participant-denominator intention series crosses round-17 scope break")
        if group == "event_intention_all_respondents" and round_no < 17:
            issues.append("all-respondent intention series crosses round-17 scope break")
        if group == "event_type_limited_response_group" and round_no < 20:
            issues.append("event-type series crosses round-20 scope break")
        if group == "title_clear_level_early_overall" and round_no > 4:
            issues.append("early clear-level series crosses round-5 scope break")
        if group == "title_clear_level_legacy_player_subcohort" and not 5 <= round_no <= 10:
            issues.append("legacy player-subcohort clear-level series crosses its scope")
        if group == "title_clear_level_all_respondents" and round_no < 11:
            issues.append("all-respondent clear-level series crosses round-11 scope break")
    for (group, round_no), rows in partitions.items():
        denominators = {int(row["denominator"]) for row in rows}
        if len(denominators) != 1:
            issues.append(f"partition {group} round {round_no} has multiple denominators")
            continue
        denominator = denominators.pop()
        if sum(int(row["count"]) for row in rows) != denominator:
            issues.append(f"partition {group} round {round_no} does not sum to denominator")
    expected_partition_sizes = {
        "age_fixed_bins": 8,
        "age_broad_groups": 3,
        "location_regions": 21,
        "domestic_overseas": 2,
        "voting_experience_common_bins": 3,
        "event_participation_overall": 2,
        "purchase_method_options": 3,
        "friends_count_options": 5,
    }
    for (group, round_no), rows in partitions.items():
        expected_size = expected_partition_sizes.get(group)
        if expected_size is not None and len(rows) != expected_size:
            issues.append(
                f"partition {group} round {round_no} has {len(rows)} items instead of {expected_size}"
            )
        if group == "sex_options":
            expected_size = 3 if round_no >= 18 else 2
            if len(rows) != expected_size:
                issues.append(
                    f"partition sex_options round {round_no} has {len(rows)} items instead of {expected_size}"
                )
    fixed_age_rounds = {
        int(row["round"])
        for row in trends
        if row["comparison_group"] == "age_fixed_bins"
    }
    if fixed_age_rounds != set(range(5, ROUND_MAX + 1)):
        issues.append("fixed age bins do not cover every offered round 5--21")
    age_detail_rounds = {
        int(row["round"])
        for row in trends
        if row["comparison_group"] == "age_40plus_detail"
    }
    if age_detail_rounds != ({5} | set(range(7, ROUND_MAX + 1))):
        issues.append("40+ age detail must cover round 5 and rounds 7--21, with round 6 missing")
    for round_no in sorted(age_detail_rounds):
        detail_options = {
            row["option"]
            for row in trends
            if row["comparison_group"] == "age_40plus_detail"
            and int(row["round"]) == round_no
        }
        if detail_options != {"40-49", "50+"}:
            issues.append(f"40+ age detail round {round_no} has unexpected options {sorted(detail_options)}")
    location_counts = defaultdict(int)
    for row in trends:
        if row["comparison_group"] == "location_regions":
            location_counts[int(row["round"])] += 1
    for round_no, count in sorted(location_counts.items()):
        if count != 21:
            issues.append(f"location round {round_no} has {count} canonical regions instead of 21")
    return issues


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    raw = load_raw_rows()
    trends, warnings = build_trends(raw)
    deltas = trend_deltas(trends)
    inventory = question_inventory(raw, trends)
    coverage = topic_round_coverage(raw, trends)
    issues = validate(raw, trends)

    numeric_path = OUT_ROOT / "questionnaire_numeric_long.csv"
    trends_path = OUT_ROOT / "comparable_trends_long.csv"
    deltas_path = OUT_ROOT / "trend_deltas.csv"
    inventory_path = OUT_ROOT / "question_inventory.csv"
    coverage_path = OUT_ROOT / "topic_round_coverage.csv"
    changes_path = OUT_ROOT / "question_changes.csv"
    report_path = OUT_ROOT / "README.md"
    summary_path = OUT_ROOT / "summary.json"
    validation_path = OUT_ROOT / "validation.json"

    write_csv(numeric_path, ({field: row.get(field, "") for field in RAW_FIELDS} for row in raw), RAW_FIELDS)
    write_csv(trends_path, trends, TREND_FIELDS)
    delta_fields = [
        "topic", "comparison_group", "item", "option", "first_round", "first_count", "first_denominator",
        "first_percent", "last_round", "last_count", "last_denominator", "last_percent", "change_pp",
        "rounds_observed", "observed_rounds_json", "missing_rounds_json", "source_url_first", "source_url_last",
    ]
    write_csv(deltas_path, deltas, delta_fields)
    inventory_fields = [
        "round", "topic", "source_question_id", "question", "rows", "numeric_rows", "rows_with_denominator",
        "included_in_any_comparable_trend", "trend_status", "exclusion_reason", "source_url",
    ]
    write_csv(inventory_path, inventory, inventory_fields)
    write_csv(coverage_path, coverage, ["topic", "round", "raw_numeric_rows", "comparable_trend_rows", "status"])
    write_csv(
        changes_path,
        (
            {"topic": topic, "round": round_no, "change_type": change_type, "detail": detail, "trend_treatment": treatment}
            for topic, round_no, change_type, detail, treatment in CHANGE_ROWS
        ),
        ["topic", "round", "change_type", "detail", "trend_treatment"],
    )
    report_path.write_text(markdown_report(raw, trends, deltas, inventory, warnings), encoding="utf-8")

    topic_summary: dict[str, Any] = {}
    for topic in sorted({row["topic"] for row in trends}):
        topic_rows = [row for row in trends if row["topic"] == topic]
        topic_summary[topic] = {
            "rounds": sorted({int(row["round"]) for row in topic_rows}),
            "trend_rows": len(topic_rows),
            "series": len({(row["comparison_group"], row["item"], row["option"]) for row in topic_rows}),
        }
    summary = {
        "schema_version": 1,
        "analysis_version": ANALYSIS_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "region": "jp",
            "round_min": ROUND_MIN,
            "data_round_max": ROUND_MAX,
            "article_round_max": ARTICLE_ROUND_MAX,
            "note": "article narrative ends at round 20; local verification and trends include round 21",
        },
        "inputs": [
            {"path": rel(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in (LEGACY_CSV, MODERN_CSV, MODERN_MANIFEST)
        ],
        "rules": {
            "individual_path_linkage": False,
            "missing_rounds_filled_with_zero": False,
            "manual_or_estimated_numeric_values": 0,
            "percent_formula": "count / denominator * 100",
            "trend_minimum_distinct_rounds": 2,
            "multiple_response_percent_sums_may_exceed_100": True,
        },
        "row_counts": {
            "questionnaire_numeric_long": len(raw),
            "comparable_trends_long": len(trends),
            "trend_series": len(deltas),
            "question_inventory": len(inventory),
            "question_changes": len(CHANGE_ROWS),
        },
        "topics": topic_summary,
        "findings": make_findings(deltas),
        "warnings": warnings,
        "issues": issues,
        "valid": not issues,
    }
    json_dump(summary_path, summary)

    output_paths = [numeric_path, trends_path, deltas_path, inventory_path, coverage_path, changes_path, report_path, summary_path]
    validation = {
        "schema_version": 1,
        "analysis_version": ANALYSIS_VERSION,
        "outputs": [
            {"path": rel(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in output_paths
        ],
        "issues": issues,
        "warnings": warnings,
        "valid": not issues,
    }
    json_dump(validation_path, validation)
    print(
        json.dumps(
            {
                "raw_rows": len(raw),
                "trend_rows": len(trends),
                "series": len(deltas),
                "warnings": len(warnings),
                "issues": len(issues),
                "valid": not issues,
                "output": str(OUT_ROOT),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
