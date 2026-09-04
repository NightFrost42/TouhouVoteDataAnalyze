"""Build a directly usable CN1-11 / JP3-22 popularity-vote dataset.

This is an offline-only builder.  CN1-9 use the archived legacy pages and
workbooks, while CN10-11 use the complete modern GraphQL ``base.json``
responses.  The original scoring fields remain separate because the voting
rules changed over time and between regions.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from json import JSONDecoder
from pathlib import Path
from typing import Any, Iterable, Mapping

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "datasets" / "votes_cn1-9_jp3-22"

RANK_FIELDS = [
    "region",
    "round",
    "category",
    "rank",
    "entity_id",
    "entity_name",
    "entity_name_localized",
    "points",
    "vote_count",
    "first_choice_count",
    "comment_count",
    "rank_prev",
    "rank_prev2",
    "weighted_score",
    "vote_share",
    "first_choice_share",
    "male_count",
    "male_rate",
    "female_count",
    "female_rate",
    "source_type",
    "source_path",
    "entity_key",
    "alignment_status",
    "alignment_name_source",
    "notes",
]

# The detail crawler uses ``chara`` while the portable vote dataset uses the
# human-readable ``character`` category.  Keep the conversion in one place so
# ranking rows and advanced-search rows can share the same entity keys.
CN_DETAIL_CATEGORIES = {
    "character": "chara",
    "chara": "chara",
    "music": "music",
    "work": "work",
    "cp": "cp",
}
CN_DATASET_CATEGORIES = {
    "chara": "character",
    "music": "music",
    "work": "work",
    "cp": "cp",
}
CN_GENERIC_DETAIL_HEADINGS = {
    "角色信息",
    "音乐信息",
    "作品信息",
    "组合信息",
    "投票群体信息",
    "投票群体",
    "关联角色同投情况",
    "角色与主动方倾向信息",
    "基本信息",
    "投票演进",
    "说明",
}

ADVANCED_RANK_FIELDS = [
    "region",
    "round",
    "condition_family",
    "condition_kind",
    "source_category",
    "source_index",
    "source_id",
    "source_name",
    "question_index",
    "question_group",
    "question",
    "question_token",
    "answer_index",
    "answer_id",
    "answer",
    "expected_cohort",
    "expected_cohort_source",
    "official_filter_description",
    "target_category",
    "entity_id",
    "entity_key",
    "entity_name",
    "entity_name_localized",
    "rank",
    "vote_count",
    "first_choice_count",
    "weighted_score",
    "male_count",
    "female_count",
    "source_path",
    "alignment_status",
    "notes",
]

ADVANCED_PAIR_FIELDS = [
    "region",
    "round",
    "question1_index",
    "question1",
    "question1_token",
    "question1_option_index",
    "question1_option",
    "question2_index",
    "question2",
    "question2_token",
    "question2_option_index",
    "question2_option",
    "count",
    "percent_within_question1_option",
    "percent_within_question2_option",
    "question1_multi",
    "question2_multi",
    "source_path",
]

CN_DETAIL_DEMOGRAPHIC_FIELDS = [
    "region",
    "round",
    "category",
    "entity_id",
    "entity_key",
    "entity_name",
    "entity_name_localized",
    "question_key",
    "question",
    "answer_label",
    "count",
    "rate",
    "overall_rate",
    "denominator",
    "source_kind",
    "source_path",
    "alignment_status",
    "notes",
]

# One row per official CN1–9 detail entity.  This is the bridge between the
# crawler's item/detail/API inventory and the vote/advanced-search tables: a
# consumer can start with a crawl item id and follow ``entity_key`` without
# trying to reconcile translated names again.
CN_ENTITY_INVENTORY_FIELDS = [
    "region",
    "round",
    "category",
    "entity_id",
    "entity_key",
    "entity_name",
    "aliases",
    "detail_status",
    "detail_path",
    "parsed_path",
    "item_api_votedate",
    "item_api_votesex",
    "item_api_votegeo",
    "item_api_votepaper",
    "item_api_complete",
    "ranking_row_count",
    "ranking_ranks",
    "advanced_row_count",
    "advanced_questionnaire_row_count",
    "demographic_row_count",
    "alignment_status",
    "notes",
]

TOTAL_FIELDS = [
    "region",
    "round",
    "category",
    "valid_vote_count",
    "valid_primary_count",
    "respondent_count",
    "source_type",
    "source_path",
    "notes",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def decode_html(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "euc_jp", "cp932", "shift_jis", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def html_text(path: Path) -> str:
    text = decode_html(path)
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def number(value: Any) -> int | float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    text = str(value).replace(",", "").strip()
    if text in {"", "-", "--", "－", "―", "None", "null"}:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    raw = match.group(0)
    try:
        result = float(raw) if "." in raw else int(raw)
        return result
    except ValueError:
        return None


def jp_selection_count_from_score(
    round_number: int,
    points: int | float | None,
    primary: int | float | None,
    secondary: int | float | None = None,
) -> int | float | None:
    """Recover the published entity selection count from the JP score.

    JP3–20 use the 2/1 rule, so ``points = selections + primary``.
    JP21–22 use the 3/2/1 rule, so ``points = selections + 2*primary
    + secondary``.  The latter is only recoverable when the separately
    published second-choice count is available.  Invalid/incomplete inputs
    remain missing rather than being presented as zero.
    """

    if points is None or primary is None:
        return None
    if round_number >= 21:
        if secondary is None:
            return None
        selection = points - 2 * primary - secondary
        minimum = primary + secondary
    else:
        selection = points - primary
        minimum = primary
    if selection < minimum or selection < 0:
        return None
    return int(selection) if float(selection).is_integer() else selection


def percent(value: Any) -> float | None:
    n = number(value)
    if n is None:
        return None
    # CN4's embedded JS stores percentages as 23.71, while later pages use
    # strings such as "23.71%" and workbooks already store 0.2371.
    return float(n) / 100 if abs(float(n)) > 1 else float(n)


def text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def translation_key(value: Any) -> str:
    """Normalize JP/CN names for joining the user's local crosswalks."""

    normalized = unicodedata.normalize("NFKC", text(value)).casefold()
    return re.sub(r"[\s・･·\-—_~〜～（）()［］【】「」『』.,，。！？!?…]+", "", normalized)


# The legacy CN pages were translated by different editors over time.  Keep
# the handful of audited spelling/alias changes here instead of fuzzy matching
# (which could join two distinct songs or characters).  Values are deliberately
# written in the spelling used by the detail index; the lookup below applies
# the same canonical token to both ranking and detail names.
CN_NAME_ALIASES: dict[str, dict[str, str]] = {
    "character": {
        "四季映姬·夜摩仙那度": "四季映姬·亚玛萨那度",
        "因幡天为（因幡帝）": "因幡帝",
        "姬海棠羽立": "姬海棠果",
        "莉莉霍瓦特（莉莉白）": "莉莉白",
        "露娜切露德": "露娜切尔德",
        "蕾蒂·霍瓦特洛克": "蕾蒂·霍瓦特洛克",
        # Parenthesised/numeric suffixes on these rows are editorial
        # footnote markers, not separate entities.  The corresponding detail
        # pages expose the unsuffixed canonical item.
        "玛艾露贝莉·赫恩（梅莉）1": "玛艾露贝莉·赫恩",
        "求闻史纪中的受访人群2": "求闻史纪中的受访人群",
        "儚月抄召唤诸神1": "儚月抄召唤诸神",
        "地精2": "地精",
        "人偶（含上海人偶、哥利亚人偶）2": "人偶（含上海人偶、哥利亚人偶）",
        "STG作品中没有名称的角色3": "STG作品中没有名称的角色",
        "雷兽（务光）4": "雷兽（务光）",
        "天照大御神5": "天照大御神",
        "天宇受卖命5": "天宇受卖命",
        "石凝老命5": "石凝老命",
        "伊豆能卖5": "伊豆能卖",
    },
    "music": {
        "恋色Master spark（恋色Magic）": "恋色Magic（恋色Master spark）",
        "恋色Magic（恋色Master spark）": "恋色Magic（恋色Master spark）",
        "恋色マジック": "恋色Magic（恋色Master spark）",
        "人偶裁判　～ 玩弄人形的少女": "玩偶裁判 ～ 玩弄人形的少女",
        "人形裁判 ～ 人の形弄びし少女": "玩偶裁判 ～ 玩弄人形的少女",
        "伏瓦鲁魔法图书馆": "巴瓦鲁魔法图书馆",
        "ヴワル魔法図書館": "巴瓦鲁魔法图书馆",
        "哈德曼的妖怪少女": "哈特曼的妖怪少女",
        "ハルトマンの妖怪少女": "哈特曼的妖怪少女",
        "春之岸边": "春之岸",
        "春の湊に": "春之岸",
        "地灵们的归家": "地灵们的归宅",
        "地霊達の帰宅": "地灵们的归宅",
        "另一侧的月": "月的另一侧",
        "向こう側の月": "月的另一侧",
        "卫星露天咖啡座": "卫星露天咖啡屋",
        "衛星カフェテラス": "卫星露天咖啡屋",
        "午夜的妖精舞会": "午夜中的妖精舞会",
        "真夜中のフェアリーダンス": "午夜中的妖精舞会",
        "珍奇的上海古牌": "好奇的上海古牌",
        "キュアリアス上海古牌": "好奇的上海古牌",
        "宵暗的魔术师": "宵闇の魔術師",
        "宵闇の魔術師": "宵闇の魔術師",
        "旧世界的冒险酒馆": "旧世界的冒险酒吧",
        "旧世界の冒険酒場": "旧世界的冒险酒吧",
        "机械马戏团　～ Reverie": "机械马戏团 ～ Reverie（马戏团幻想）",
        "机械马戏团 ～ Reverie": "机械马戏团 ～ Reverie（马戏团幻想）",
        "機械サーカス ~ Reverie": "机械马戏团 ～ Reverie（马戏团幻想）",
        "飞翔在夜晚的鸠山 －Power MIX": "飞越夜晚的鸠山 - Power MIX",
        "夜の鳩山を飛ぶ －Power MIX": "飞越夜晚的鸠山 - Power MIX",
        "神秘的人偶 ～ God Knows": "神秘的人偶 ～ God Knows",
        "エニグマティクドール ~ God Knows": "神秘的人偶 ～ God Knows",
        "活泼的纯情小姑娘（活泼纯情小姑娘的冒险）": "活泼的纯情小姑娘",
        "おてんば恋娘": "活泼的纯情小姑娘",
    },
}

# Some CN detail/editorial rows append a provenance tag such as
# ``〜 Stone Goddess`` to an otherwise normal song title.  It is not part of
# the official title and prevents a deterministic join to the user's music
# workbook, so remove this one known suffix only (other subtitles remain
# untouched).
CN_MUSIC_EDITORIAL_SUFFIX = re.compile(r"\s*[~〜～]\s*stone\s+goddess\s*$", re.IGNORECASE)


def _cn_alias_key(category: str, value: Any) -> str:
    """Return a stable token after applying only audited CN aliases."""

    raw = _strip_html(value)
    if category == "music":
        raw = CN_MUSIC_EDITORIAL_SUFFIX.sub("", raw).strip()
    aliases = CN_NAME_ALIASES.get(category, {})
    # First try exact spelling (important for the editorial footnote suffixes),
    # then normalized spelling for harmless punctuation/width differences.
    canonical = aliases.get(raw)
    if canonical is None:
        raw_key = translation_key(raw)
        canonical = next(
            (target for source, target in aliases.items() if translation_key(source) == raw_key),
            raw,
        )
    return translation_key(canonical)


def _strip_html(value: Any) -> str:
    return re.sub(r"<[^>]+>", "", text(value)).strip()


def _cn_entity_name_key(category: str, value: Any) -> str:
    """Return a conservative key for a CN detail/ranking entity name.

    CPs are kept as ordered member tuples.  Sorting or flattening the members
    would make distinct active-side combinations collide, so only separators
    are removed while member order remains significant.
    """

    raw = _strip_html(value)
    if category == "cp":
        members = [part.strip() for part in re.split(r"\s*[×xX＊*，,、/／|]\s*", raw) if part.strip()]
        members = [_cn_alias_key("character", part) for part in members if part not in {"-", "－"}]
        return "|".join(members)
    return _cn_alias_key(category, raw)


def _detail_title_prefix(value: Any) -> str:
    title = _strip_html(value)
    # CN5+ detail titles append a round/site suffix.  A title may itself
    # contain a hyphen, hence split only on the known suffix marker first.
    match = re.search(r"\s*[–-]\s*东方Project人气投票", title)
    return title[: match.start()].strip() if match else title


def _valid_detail_heading(value: Any) -> bool:
    heading = _strip_html(value)
    if not heading or heading in CN_GENERIC_DETAIL_HEADINGS:
        return False
    if heading in {"", "-", "－"}:
        return False
    # Explanatory headings are not entity names.  Keep parenthesised aliases
    # such as ``（包含蓬莱人形版本）`` out of the canonical member list while
    # still allowing them to be added as aliases by the caller if needed.
    if heading.startswith(("（", "(", "[", "【")) and "版本" in heading:
        return False
    return True


def _cn_detail_aliases(row: Mapping[str, Any], payload: Mapping[str, Any], category: str) -> list[str]:
    """Extract display-name aliases from a parsed CN detail document."""

    headings = [_strip_html(value) for value in payload.get("headings", [])]
    aliases: list[str] = []
    def add(value: Any) -> None:
        candidate = _strip_html(value)
        if candidate and candidate not in aliases and _valid_detail_heading(candidate):
            aliases.append(candidate)

    title_prefix = _detail_title_prefix(row.get("title"))
    if category == "cp":
        # Round 4 stores the members as separate headings, while CN5+ also
        # stores a comma-joined member title.  Emit both spellings.
        members = [heading for heading in headings if _valid_detail_heading(heading)]
        if title_prefix:
            add(title_prefix)
            for separator in ("，", " × "):
                if separator in title_prefix:
                    members = [part.strip() for part in title_prefix.split(separator) if part.strip()]
                    break
        if members:
            add("，".join(members))
            add(" × ".join(members))
        # A CP title may have been added above but the first generic heading
        # still appears in ``members``; remove it before constructing aliases.
        for member in members:
            add(member)
        return aliases

    add(title_prefix)
    add(row.get("primary_heading"))
    for heading in headings:
        add(heading)
    # Parsed table headings are useful for CN1–4 pages whose index heading is
    # occasionally blank even though the first table carries the entity name.
    for table in payload.get("tables", []):
        add(table.get("heading"))
    return aliases


def load_cn_legacy_entity_index(
    rounds: Iterable[int] = range(1, 10),
) -> tuple[dict[tuple[int, str, str], list[dict[str, Any]]], set[Path]]:
    """Load CN1–9 detail entities and index every known display alias.

    The returned index deliberately stores lists: duplicate display names are
    possible (especially music aliases), and callers must treat an ambiguous
    name as manual review rather than guessing an ID.  ``inputs`` contains
    both detail indexes and parsed JSON files so manifests can account for all
    evidence used by the alignment.
    """

    index: dict[tuple[int, str, str], list[dict[str, Any]]] = defaultdict(list)
    inputs: set[Path] = set()
    for round_number in rounds:
        if not 1 <= int(round_number) <= 9:
            continue
        path = ROOT / "data_raw" / "cn_official_legacy" / f"round_{int(round_number):02d}" / "processed" / "details" / "index.csv"
        if not path.exists():
            continue
        inputs.add(path)
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for raw in csv.DictReader(fh):
                detail_category = text(raw.get("category"))
                category = CN_DATASET_CATEGORIES.get(detail_category)
                if not category:
                    continue
                parsed_path = ROOT / text(raw.get("parsed_path"))
                payload: Mapping[str, Any] = {}
                if parsed_path.exists():
                    inputs.add(parsed_path)
                    try:
                        loaded = read_json(parsed_path)
                        if isinstance(loaded, Mapping):
                            payload = loaded
                    except (OSError, json.JSONDecodeError):
                        payload = {}
                entity = {
                    "region": "cn",
                    "round": int(round_number),
                    "category": category,
                    "detail_category": detail_category,
                    "entity_id": text(raw.get("id")),
                    "entity_name": "",
                    "aliases": [],
                    "name_source": "",
                    "detail_path": rel(ROOT / text(raw.get("html_path"))) if raw.get("html_path") else "",
                    "parsed_path": rel(parsed_path) if parsed_path.exists() else text(raw.get("parsed_path")),
                    "status": text(raw.get("status")),
                }
                aliases = _cn_detail_aliases(raw, payload, category)
                if aliases:
                    entity["entity_name"] = aliases[0]
                    entity["aliases"] = aliases
                    entity["name_source"] = "title" if _detail_title_prefix(raw.get("title")) else "parsed_headings"
                for alias in aliases:
                    key = _cn_entity_name_key(category, alias)
                    if not key:
                        continue
                    bucket = index[(int(round_number), category, key)]
                    if not any(item["entity_id"] == entity["entity_id"] for item in bucket):
                        bucket.append(entity)
    return dict(index), inputs


def augment_cn_music_aliases(
    entity_index: Mapping[tuple[int, str, str], list[dict[str, Any]]],
    rounds: Iterable[int] = range(1, 10),
) -> tuple[dict[tuple[int, str, str], list[dict[str, Any]]], set[Path]]:
    """Add maintained CN↔JP music aliases to the detail index.

    Early CN pages often expose only a Japanese/English heading while the
    user's vote workbook uses a Chinese translation.  ``TouhouMusicInfo.xlsx``
    and ``local_music_merged.csv`` already contain the maintained translation
    pairs; using those pairs is safer than fuzzy matching short song titles.
    """

    augmented: dict[tuple[int, str, str], list[dict[str, Any]]] = {
        key: list(records) for key, records in entity_index.items()
    }
    inputs: set[Path] = set()
    pairs: list[tuple[str, str]] = []
    workbook = ROOT / "TouhouMusicInfo.xlsx"
    if workbook.exists():
        inputs.add(workbook)
        try:
            wb = load_workbook(workbook, read_only=True, data_only=True)
            ws = wb.active
            rows = ws.iter_rows(values_only=True)
            header = [text(value) for value in next(rows, ())]
            jp_i = header.index("曲目") if "曲目" in header else None
            cn_i = header.index("译名") if "译名" in header else None
            if jp_i is not None and cn_i is not None:
                for raw in rows:
                    if jp_i < len(raw) and cn_i < len(raw):
                        jp_name, cn_name = text(raw[jp_i]), text(raw[cn_i])
                        if jp_name and cn_name:
                            pairs.append((cn_name, jp_name))
        except (OSError, StopIteration, ValueError):
            pass

    merged = ROOT / "data_processed" / "music_canonical" / "local_music_merged.csv"
    if merged.exists():
        inputs.add(merged)
        with merged.open("r", encoding="utf-8-sig", newline="") as fh:
            for raw in csv.DictReader(fh):
                if text(raw.get("site")) != "cn":
                    continue
                try:
                    cn_names = json.loads(raw.get("source_titles_cn_json") or "[]")
                    jp_names = json.loads(raw.get("source_titles_jp_json") or "[]")
                except json.JSONDecodeError:
                    continue
                for cn_name in cn_names:
                    for jp_name in jp_names:
                        if text(cn_name) and text(jp_name):
                            pairs.append((text(cn_name), text(jp_name)))

    for round_number in rounds:
        round_number = int(round_number)
        if not 1 <= round_number <= 9:
            continue
        for cn_name, jp_name in pairs:
            candidates = augmented.get((round_number, "music", translation_key(jp_name)), [])
            if len(candidates) != 1:
                continue
            key = (round_number, "music", translation_key(cn_name))
            bucket = augmented.setdefault(key, [])
            if not any(item.get("entity_id") == candidates[0].get("entity_id") for item in bucket):
                bucket.append(candidates[0])
    return augmented, inputs


def _entity_index_by_id(
    entity_index: Mapping[tuple[int, str, str], list[dict[str, Any]]],
    round_number: int,
    category: str,
) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for (rnd, cat, _), records in entity_index.items():
        if rnd != int(round_number) or cat != category:
            continue
        for record in records:
            entity_id = text(record.get("entity_id"))
            if entity_id:
                by_id.setdefault(entity_id, record)
    return by_id


def _entity_id_lookup(
    entity_index: Mapping[tuple[int, str, str], list[dict[str, Any]]],
) -> dict[tuple[int, str, str], dict[str, Any]]:
    lookup: dict[tuple[int, str, str], dict[str, Any]] = {}
    for (round_number, category, _), records in entity_index.items():
        for record in records:
            entity_id = text(record.get("entity_id"))
            if entity_id:
                lookup.setdefault((int(round_number), category, entity_id), record)
    return lookup


def _align_cn_entity(
    row: Mapping[str, Any],
    entity_index: Mapping[tuple[int, str, str], list[dict[str, Any]]],
    entity_id_lookup: Mapping[tuple[int, str, str], dict[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, str, str]:
    """Resolve one CN row to a detail entity without fuzzy guessing."""

    round_number = int(row["round"])
    category = text(row.get("category"))
    detail_category = CN_DETAIL_CATEGORIES.get(category, category)
    entity_id = text(row.get("entity_id"))
    # IDs from CN5+ CP summary rows are display ordinals; those rows carry the
    # real detail ID in ``info`` and are corrected in ``cn_record``.  An ID is
    # accepted only when it exists in the corresponding detail index.
    by_id = entity_id_lookup or _entity_id_lookup(entity_index)
    if entity_id and (round_number, category, entity_id) in by_id:
        return by_id[(round_number, category, entity_id)], "matched_id", "source_id"

    key = _cn_entity_name_key(category, row.get("entity_name"))
    candidates = entity_index.get((round_number, category, key), [])
    if len(candidates) == 1:
        return candidates[0], "matched_name", "detail_alias"
    if len(candidates) > 1:
        return None, "ambiguous_name_manual_review", "detail_alias"
    # A category without a details index is a known scope limitation, not a
    # failed crawl.  This is currently CN1–3 CP and is surfaced explicitly.
    has_category = any(rnd == round_number and cat == category for rnd, cat, _ in entity_index)
    if not has_category:
        return None, "official_detail_not_available", ""
    return None, "unmatched_manual_review", ""


def align_cn_rankings(
    rankings: Iterable[dict[str, Any]],
    entity_index: Mapping[tuple[int, str, str], list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Attach stable entity IDs/keys to CN ranking rows and return an audit."""

    aligned: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    entity_id_lookup = _entity_id_lookup(entity_index)
    for row in rankings:
        item = dict(row)
        entity, status, name_source = _align_cn_entity(item, entity_index, entity_id_lookup)
        if entity:
            item["entity_id"] = text(entity.get("entity_id"))
            # Preserve the workbook/summary display name in ``entity_name``;
            # the detail's canonical display is evidence for the join and is
            # only used as a fallback localized label.
            item["entity_name_localized"] = text(item.get("entity_name_localized")) or text(entity.get("entity_name"))
            item["entity_key"] = f"cn:{int(item['round']):02d}:{item['category']}:{item['entity_id']}"
        else:
            # Keep a deterministic name key for rows with no official detail
            # page.  It is explicitly not an entity ID and cannot be mistaken
            # for one by downstream joins.
            name_key = _cn_entity_name_key(text(item.get("category")), item.get("entity_name"))
            item["entity_key"] = f"cn:{int(item['round']):02d}:{item['category']}:name:{name_key}" if name_key else ""
        item["alignment_status"] = status
        item["alignment_name_source"] = name_source
        if status not in {"matched_id", "matched_name"}:
            audit.append({
                "region": "cn",
                "round": int(item["round"]),
                "category": text(item.get("category")),
                "rank": item.get("rank"),
                "entity_id": text(item.get("entity_id")),
                "entity_key": item.get("entity_key", ""),
                "entity_name": text(item.get("entity_name")),
                "alignment_status": status,
                "source_path": text(item.get("source_path")),
            })
        aligned.append(item)
    return aligned, audit


def _read_gzip_json(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8-sig") as fh:
        return json.load(fh)


def _advanced_context_row(
    round_number: int,
    context: Mapping[str, Any],
    target_category: str,
    raw: Mapping[str, Any],
    source_path: Path,
    entity_index: Mapping[tuple[int, str, str], list[dict[str, Any]]],
    entity_id_lookup: Mapping[tuple[int, str, str], dict[str, Any]] | None = None,
    overview: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    entity_id = text(raw.get("id"))
    entity_name = text(raw.get("name"))
    condition_family = text(context.get("condition_family"))
    condition_kind = text(context.get("condition_kind"))
    if condition_family == "questionnaire_answer":
        condition_kind = "answer"
    source_category_raw = text(context.get("source_category"))
    source_category = CN_DATASET_CATEGORIES.get(
        source_category_raw, source_category_raw
    )
    ranking_row = {
        "round": int(round_number),
        "category": target_category,
        "entity_id": entity_id,
        "entity_name": entity_name,
    }
    entity, alignment_status, _ = _align_cn_entity(ranking_row, entity_index, entity_id_lookup)
    if entity:
        entity_id = text(entity.get("entity_id"))
        entity_name_localized = text(entity.get("entity_name")) or entity_name
        entity_key = f"cn:{int(round_number):02d}:{target_category}:{entity_id}"
    else:
        entity_name_localized = entity_name
        name_key = _cn_entity_name_key(target_category, entity_name)
        entity_key = f"cn:{int(round_number):02d}:{target_category}:name:{name_key}" if name_key else ""
    return {
        "region": "cn",
        "round": int(round_number),
        "condition_family": condition_family,
        "condition_kind": condition_kind,
        "source_category": source_category,
        "source_index": context.get("source_index", ""),
        "source_id": text(context.get("source_id")),
        "source_name": text(context.get("source_name")),
        "question_index": context.get("question_index", ""),
        "question_group": text(context.get("question_group")),
        "question": text(context.get("question")),
        "question_token": text(context.get("question_token")),
        "answer_index": context.get("answer_index", ""),
        "answer_id": text(context.get("answer_id")),
        "answer": text(context.get("answer")),
        "expected_cohort": context.get("expected_cohort", ""),
        "expected_cohort_source": text(context.get("expected_cohort_source")),
        "official_filter_description": text((overview or {}).get("official_filter_description")),
        "target_category": target_category,
        "entity_id": entity_id,
        "entity_key": entity_key,
        "entity_name": entity_name,
        "entity_name_localized": entity_name_localized,
        "rank": raw.get("rank_by_vote", raw.get("server_order", "")),
        "vote_count": raw.get("vote", ""),
        "first_choice_count": raw.get("first", ""),
        "weighted_score": raw.get("weight", ""),
        "male_count": raw.get("male", ""),
        "female_count": raw.get("female", ""),
        "source_path": rel(source_path),
        "alignment_status": alignment_status,
        "notes": "",
    }


def load_cn_legacy_advanced_data(
    entity_index: Mapping[tuple[int, str, str], list[dict[str, Any]]],
    rounds: Iterable[int] = range(1, 10),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], set[Path], dict[str, Any]]:
    """Normalize the bounded CN5–9 advanced-search extracts.

    The first list contains both questionnaire-answer and entity-conditioned
    ranking rows.  The second is the questionnaire-only subset (written as a
    convenient standalone table), and the third contains the official
    two-question cross-table cells.  CN1–4 intentionally return no rows; the
    caller records those rounds as ``official_not_offered``.
    """

    advanced_rows: list[dict[str, Any]] = []
    questionnaire_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    inputs: set[Path] = set()
    coverage: dict[str, Any] = {}
    entity_id_lookup = _entity_id_lookup(entity_index)
    for round_number in rounds:
        round_number = int(round_number)
        if not 5 <= round_number <= 9:
            coverage[str(round_number)] = {"status": "official_not_offered", "rows": 0, "pairs": 0}
            continue
        base = ROOT / "data_raw" / "cn_official_legacy" / f"round_{round_number:02d}" / "processed" / "advanced"
        if not base.exists():
            coverage[str(round_number)] = {"status": "missing_local_extract", "rows": 0, "pairs": 0}
            continue
        round_count = 0
        round_questionnaire_count = 0
        entity_dir = base / "entity" / "conditions"
        questionnaire_dir = base / "questionnaire" / "conditions"
        for directory in (entity_dir, questionnaire_dir):
            if not directory.exists():
                continue
            for path in sorted(directory.rglob("target_*.json.gz")):
                inputs.add(path)
                try:
                    payload = _read_gzip_json(path)
                except (OSError, json.JSONDecodeError):
                    continue
                context = payload.get("context", {}) if isinstance(payload, Mapping) else {}
                if not isinstance(context, Mapping):
                    context = {}
                target_raw = text(context.get("target_category")) or path.name.removesuffix(".json.gz").removeprefix("target_")
                target_category = CN_DATASET_CATEGORIES.get(target_raw, target_raw)
                for raw in payload.get("rows", []) if isinstance(payload, Mapping) else []:
                    if not isinstance(raw, Mapping):
                        continue
                    overview = payload.get("overview", {}) if isinstance(payload, Mapping) else {}
                    record = _advanced_context_row(round_number, context, target_category, raw, path, entity_index, entity_id_lookup, overview)
                    advanced_rows.append(record)
                    round_count += 1
                    if record["condition_family"] == "questionnaire_answer":
                        questionnaire_rows.append(dict(record))
                        round_questionnaire_count += 1

        pair_cells = base / "questionnaire" / "pair_cells.csv.gz"
        pair_index = base / "questionnaire" / "pair_index.csv"
        question_index = base / "questionnaire" / "questions.csv"
        entity_index_path = base / "entity" / "condition_index.csv"
        condition_index = base / "questionnaire" / "condition_index.csv"
        summary_path = base / "summary.json"
        for metadata_path in (summary_path, pair_cells, pair_index, question_index, entity_index_path, condition_index):
            if metadata_path.exists():
                inputs.add(metadata_path)
        pair_count = 0
        if pair_cells.exists():
            try:
                with gzip.open(pair_cells, "rt", encoding="utf-8-sig", newline="") as fh:
                    for raw in csv.DictReader(fh):
                        item = dict(raw)
                        item["region"] = "cn"
                        item["round"] = round_number
                        item["source_path"] = text(raw.get("source")) or rel(pair_cells)
                        pair_rows.append(item)
                        pair_count += 1
            except OSError:
                pass
        coverage[str(round_number)] = {
            "status": "available" if round_count or pair_count else "empty_local_extract",
            "ranking_rows": round_count,
            "questionnaire_rows": round_questionnaire_count,
            "pair_rows": pair_count,
        }
    return advanced_rows, questionnaire_rows, pair_rows, inputs, coverage


def load_cn_modern_advanced_data(
    rounds: Iterable[int] = (10, 11),
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    set[Path],
    dict[str, Any],
]:
    """Normalize the CN10/11 GraphQL advanced-search checkpoints.

    The modern responses contain all three aggregate ranking departments in
    one JSON response.  Emit the same long-row vocabulary used by the CN5--9
    extract (questionnaire answer vs. entity vote, any vs. first, and a
    target department) while retaining the original response path.  The old
    The modern site has no bulk questionnaire cross-table endpoint.  Its
    crawler therefore archives every explicit Boolean answer intersection;
    those real counts are normalized into the same pair-cell schema as CN5--9.
    """

    output: list[dict[str, Any]] = []
    questionnaire_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    inputs: set[Path] = set()
    coverage: dict[str, Any] = {}
    ranking_keys = {
        "character": "queryCharacterRanking",
        "music": "queryMusicRanking",
        "cp": "queryCPRanking",
    }

    def response_rows(
        round_number: int,
        context: Mapping[str, Any],
        path: Path,
        payload: Mapping[str, Any],
    ) -> None:
        data = payload.get("data", {})
        if not isinstance(data, Mapping):
            return
        for target_category, graphql_key in ranking_keys.items():
            result = data.get(graphql_key, {})
            if not isinstance(result, Mapping):
                continue
            entries = result.get("entries", [])
            if not isinstance(entries, list):
                continue
            for raw in entries:
                if not isinstance(raw, Mapping):
                    continue
                cp = raw.get("cp") if isinstance(raw.get("cp"), Mapping) else {}
                name = text(raw.get("name"))
                if target_category == "cp" and not name:
                    name = " × ".join(
                        text(cp.get(key)) for key in ("a", "b", "c") if text(cp.get(key))
                    )
                if not name:
                    continue
                localized = name
                entity_id = text(raw.get("id"))
                key_category = target_category
                entity_key = (
                    f"cn:{round_number:02d}:{key_category}:{entity_id}"
                    if entity_id
                    else f"cn:{round_number:02d}:{key_category}:name:{_cn_entity_name_key(key_category, name)}"
                )
                condition_family = text(context.get("condition_family"))
                condition_kind = text(
                    context.get("condition_kind") or context.get("conditionKind")
                )
                # Keep questionnaire conditions in the same canonical
                # vocabulary as the legacy extract.  The legacy CSV leaves
                # this column blank, so ``answer`` is the explicit normalized
                # value used by the unified view.
                if condition_family == "questionnaire_answer":
                    condition_kind = "answer"
                record = {
                    "region": "cn",
                    "round": round_number,
                    "condition_family": condition_family,
                    "condition_kind": condition_kind,
                    "source_category": CN_DATASET_CATEGORIES.get(
                        text(
                            context.get("source_category")
                            or context.get("sourceCategory")
                        ),
                        text(
                            context.get("source_category")
                            or context.get("sourceCategory")
                        ),
                    ),
                    "source_index": context.get(
                        "source_index", context.get("sourceIndex", "")
                    ),
                    "source_id": text(
                        context.get("source_id") or context.get("sourceId")
                    ),
                    "source_name": text(
                        context.get("source_name") or context.get("sourceName")
                    ),
                    "question_index": context.get(
                        "question_index",
                        context.get("questionIndex", context.get("question_id", "")),
                    ),
                    "question_group": "",
                    "question": text(context.get("question") or context.get("questionText")),
                    "question_token": "",
                    "answer_index": "",
                    "answer_id": text(
                        context.get("answer_id") or context.get("answerId")
                    ),
                    "answer": text(context.get("answer") or context.get("answerText")),
                    "expected_cohort": context.get(
                        "expected_cohort", context.get("expectedCohort", "")
                    ),
                    "expected_cohort_source": text(
                        context.get("expected_cohort_source")
                        or context.get("expectedCohortSource")
                    ),
                    "official_filter_description": "",
                    "target_category": target_category,
                    "entity_id": entity_id,
                    "entity_key": entity_key,
                    "entity_name": name,
                    "entity_name_localized": localized,
                    "rank": raw.get("rank", raw.get("displayRank", "")),
                    "vote_count": raw.get("voteCount", ""),
                    "first_choice_count": raw.get("firstVoteCount", ""),
                    "weighted_score": "",
                    "male_count": "",
                    "female_count": "",
                    "source_path": rel(path),
                    "alignment_status": "modern_graphql_name_key",
                    "notes": "modern GraphQL response; CP rows use cp.a/cp.b/cp.c",
                }
                output.append(record)
                if record["condition_family"] == "questionnaire_answer":
                    questionnaire_rows.append(dict(record))

    for round_number in rounds:
        round_number = int(round_number)
        root = ROOT / "data_raw" / "cn_official" / f"round_{round_number:02d}"
        index_path = root / "advanced_conditions" / "index.json"
        if not index_path.exists():
            coverage[str(round_number)] = {
                "status": "missing_local_extract",
                "ranking_rows": 0,
                "questionnaire_rows": 0,
                "pair_status": "pending",
            }
            continue
        inputs.add(index_path)
        combination_catalog_path = root / "advanced_conditions" / "combination_catalog.json"
        if combination_catalog_path.exists():
            inputs.add(combination_catalog_path)
        try:
            index = read_json(index_path)
        except (OSError, json.JSONDecodeError):
            coverage[str(round_number)] = {
                "status": "invalid_local_extract",
                "ranking_rows": 0,
                "questionnaire_rows": 0,
                "pair_status": "pending",
            }
            continue
        before = len(output)
        q_records = index.get("questionnaireAnswerConditions", [])
        e_records = index.get("entityConditions", [])
        q_records = q_records if isinstance(q_records, list) else []
        e_records = e_records if isinstance(e_records, list) else []
        q_type_counts = Counter(text(item.get("questionType")) for item in q_records if isinstance(item, Mapping))
        e_source_counts = Counter(text(item.get("sourceCategory")) for item in e_records if isinstance(item, Mapping))
        e_kind_counts = Counter(text(item.get("conditionKind")) for item in e_records if isinstance(item, Mapping))
        e_status_counts = Counter(text(item.get("status")) for item in e_records if isinstance(item, Mapping))
        categorical_q_records = [
            item for item in q_records
            if isinstance(item, Mapping) and text(item.get("questionType")) in {"Single", "Multiple"}
        ]
        cohort_by_answer: dict[tuple[int, int], int] = {}
        for source_record, family in (
            (q_records, "questionnaire_answer"),
            (e_records, "entity_vote"),
        ):
            if not isinstance(source_record, list):
                continue
            for item in source_record:
                if not isinstance(item, Mapping):
                    continue
                raw_path = item.get("responsePath")
                if not raw_path:
                    continue
                response_path = ROOT / str(raw_path)
                if not response_path.exists():
                    continue
                inputs.add(response_path)
                try:
                    payload = read_json(response_path)
                except (OSError, json.JSONDecodeError):
                    continue
                context = dict(item)
                context["condition_family"] = family
                stats = payload.get("data", {}).get("queryGlobalStats", {})
                if family == "questionnaire_answer" and isinstance(stats, Mapping):
                    context["expected_cohort"] = stats.get("numVote", "")
                    context["expected_cohort_source"] = "official filtered GraphQL global stats"
                    try:
                        cohort_by_answer[
                            (int(item["questionId"]), int(item["answerId"]))
                        ] = int(stats["numVote"])
                    except (KeyError, TypeError, ValueError):
                        pass
                if family == "questionnaire_answer":
                    context["question_id"] = item.get("questionId", "")
                    context["source_category"] = "questionnaire"
                else:
                    context["source_category"] = item.get("sourceCategory", "")
                response_rows(round_number, context, response_path, payload)

        pair_plan_path = root / "advanced_conditions" / "questionnaire_pair_plan.json"
        pair_expected = 0
        pair_cells_expected = 0
        if pair_plan_path.exists():
            inputs.add(pair_plan_path)
            try:
                pair_plan = read_json(pair_plan_path)
                pair_expected = int(pair_plan.get("unorderedQuestionPairCount", 0))
                pair_cells_expected = int(pair_plan.get("answerCellCount", 0))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                pass
        if not pair_expected or not pair_cells_expected:
            # Validation must know the real parity target before the new pair
            # stage has ever run (and therefore before its plan file exists).
            options_path = root / "questionnaire" / "options.json"
            if options_path.exists():
                inputs.add(options_path)
                try:
                    option_definitions = read_json(options_path)
                    option_counts = Counter(
                        int(item["questionId"])
                        for item in option_definitions
                        if isinstance(item, Mapping)
                        and text(item.get("questionType")) in {"Single", "Multiple"}
                    )
                    counts = list(option_counts.values())
                    pair_expected = len(counts) * (len(counts) - 1) // 2
                    pair_cells_expected = sum(
                        left * right
                        for offset, left in enumerate(counts)
                        for right in counts[offset + 1 :]
                    )
                except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                    pass
        pair_available = 0
        pair_cells_available = 0
        pair_root = root / "advanced_conditions" / "questionnaire_pairs"
        for pair_path in sorted(pair_root.glob("q_*__q_*.json")):
            inputs.add(pair_path)
            try:
                pair_payload = read_json(pair_path)
                question1 = pair_payload["question1"]
                question2 = pair_payload["question2"]
                cells = pair_payload["cells"]
                if not isinstance(cells, list):
                    continue
                expected_cell_count = int(pair_payload["expectedCellCount"])
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            valid_in_file = 0
            for cell in cells:
                if not isinstance(cell, Mapping):
                    continue
                try:
                    question1_id = int(question1["questionId"])
                    question2_id = int(question2["questionId"])
                    answer1_id = int(cell["question1AnswerId"])
                    answer2_id = int(cell["question2AnswerId"])
                    count = int(cell["count"])
                    response_count = int(
                        cell["officialResponse"]["data"]["queryGlobalStats"]["numVote"]
                    )
                    if count < 0 or count != response_count:
                        continue
                except (KeyError, TypeError, ValueError):
                    continue
                denominator1 = cohort_by_answer.get((question1_id, answer1_id))
                denominator2 = cohort_by_answer.get((question2_id, answer2_id))
                pair_rows.append(
                    {
                        "region": "cn",
                        "round": round_number,
                        "question1_index": question1_id,
                        "question1": text(question1.get("question")),
                        "question1_token": f"q{question1_id}",
                        "question1_option_index": cell.get("question1OptionIndex", ""),
                        "question1_option": text(cell.get("question1Option")),
                        "question2_index": question2_id,
                        "question2": text(question2.get("question")),
                        "question2_token": f"q{question2_id}",
                        "question2_option_index": cell.get("question2OptionIndex", ""),
                        "question2_option": text(cell.get("question2Option")),
                        "count": count,
                        "percent_within_question1_option": (
                            round(count * 100 / denominator1, 2)
                            if denominator1
                            else ""
                        ),
                        "percent_within_question2_option": (
                            round(count * 100 / denominator2, 2)
                            if denominator2
                            else ""
                        ),
                        "question1_multi": int(question1.get("questionType") == "Multiple"),
                        "question2_multi": int(question2.get("questionType") == "Multiple"),
                        "source_path": rel(pair_path),
                    }
                )
                valid_in_file += 1
            pair_cells_available += valid_in_file
            if valid_in_file == expected_cell_count:
                pair_available += 1
        round_rows = len(output) - before
        pair_status = (
            "available_crawled"
            if pair_expected and pair_available == pair_expected
            and pair_cells_available == pair_cells_expected
            else "partial"
            if pair_cells_available
            else "pending"
        )
        coverage[str(round_number)] = {
            "status": "available" if round_rows else "empty_local_extract",
            "ranking_rows": round_rows,
            "questionnaire_rows": sum(
                1
                for row in output[before:]
                if row.get("condition_family") == "questionnaire_answer"
            ),
            "questionnaire_condition_counts": dict(q_type_counts),
            "questionnaire_categorical_expected": len(categorical_q_records),
            "questionnaire_categorical_available": sum(
                text(item.get("status")) == "available_crawled"
                for item in categorical_q_records
            ),
            "entity_condition_counts": {
                "sourceCategory": dict(e_source_counts),
                "conditionKind": dict(e_kind_counts),
                "status": dict(e_status_counts),
            },
            "entity_condition_expected": len(e_records),
            "entity_condition_available": sum(
                text(item.get("status")) == "available_crawled"
                for item in e_records
            ),
            "pair_status": pair_status,
            "pair_expected": pair_expected,
            "pair_available": pair_available,
            "pair_cells_expected": pair_cells_expected,
            "pair_cells_available": pair_cells_available,
            "pair_reason": (
                "modern GraphQL has no legacy all-answer questionnaire "
                "cross-tab endpoint; the crawler enumerates every explicit "
                "Boolean answer cell"
            ),
        }
    return output, questionnaire_rows, pair_rows, inputs, coverage


def load_cn_legacy_detail_demographics(
    entity_index: Mapping[tuple[int, str, str], list[dict[str, Any]]],
    rounds: Iterable[int] = (2, 3, 4),
) -> tuple[list[dict[str, Any]], set[Path], dict[str, Any]]:
    """Extract the early CN per-entity ``投票群体信息`` tables.

    CN2–4 expose demographic/questionnaire marginals inside each detail page,
    before the CN5–9 conditional-search API existed.  They are a different
    official source and therefore remain marked ``cn_legacy_detail_demographics``
    instead of being folded into the API extract.  Only rows with an explicit
    count are emitted; explanatory rows and ``占全部男性/女性比例`` rows are
    retained as ``overall_rate`` on their corresponding gender answer.
    """

    output: list[dict[str, Any]] = []
    inputs: set[Path] = set()
    coverage: dict[str, Any] = {}
    by_id = _entity_id_lookup(entity_index)
    for round_number in rounds:
        round_number = int(round_number)
        if round_number not in {2, 3, 4}:
            continue
        index_path = ROOT / "data_raw" / "cn_official_legacy" / f"round_{round_number:02d}" / "processed" / "details" / "index.csv"
        if not index_path.exists():
            coverage[str(round_number)] = {"status": "missing_local_extract", "rows": 0}
            continue
        inputs.add(index_path)
        round_count = 0
        category_counts: Counter[str] = Counter()
        with index_path.open("r", encoding="utf-8-sig", newline="") as fh:
            for raw in csv.DictReader(fh):
                detail_category = text(raw.get("category"))
                category = CN_DATASET_CATEGORIES.get(detail_category)
                if not category:
                    continue
                parsed_path = ROOT / text(raw.get("parsed_path"))
                if not parsed_path.exists():
                    continue
                inputs.add(parsed_path)
                try:
                    payload = read_json(parsed_path)
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(payload, Mapping):
                    continue
                entity_id = text(raw.get("id"))
                entity = by_id.get((round_number, category, entity_id))
                entity_name = text((entity or {}).get("entity_name")) or _detail_title_prefix(raw.get("title")) or entity_id
                entity_key = f"cn:{round_number:02d}:{category}:{entity_id}" if entity_id else ""
                tables = payload.get("tables", [])
                if not isinstance(tables, list):
                    continue
                entity_denominator = ""
                for base_table in tables[:1]:
                    if not isinstance(base_table, Mapping):
                        continue
                    for base_row in base_table.get("rows", []) if isinstance(base_table.get("rows", []), list) else []:
                        if not isinstance(base_row, list) or not base_row:
                            continue
                        if not isinstance(base_row[0], Mapping) or text(base_row[0].get("text")) != "票数":
                            continue
                        for base_cell in base_row[1:]:
                            if isinstance(base_cell, Mapping) and base_cell.get("number") is not None:
                                parsed_denominator = number(base_cell.get("number"))
                                # Zero is a valid published denominator for a
                                # zero-vote entity; keep it distinct from a
                                # missing value for downstream rate checks.
                                entity_denominator = (
                                    parsed_denominator
                                    if parsed_denominator is not None
                                    else ""
                                )
                                break
                        if entity_denominator != "":
                            break
                for table_index, table in enumerate(tables):
                    if not isinstance(table, Mapping):
                        continue
                    heading = _strip_html(table.get("heading"))
                    if heading not in {"投票群体信息", "投票群体"}:
                        continue
                    # ``stable3`` is the per-entity geography chart on CN2/3
                    # pages, not a question distribution.  Keep the raw table
                    # available but do not turn each province into a fake
                    # ``cn_*`` questionnaire answer.
                    if text(table.get("id")) == "stable3":
                        continue
                    rows = table.get("rows", [])
                    if not isinstance(rows, list) or not rows:
                        continue
                    cell_rows: list[list[Mapping[str, Any]]] = []
                    for row in rows:
                        if not isinstance(row, list):
                            continue
                        cell_rows.append([cell for cell in row if isinstance(cell, Mapping)])
                    if not cell_rows:
                        continue

                    # Gender tables are the only early format with a paired
                    # ``占全部男性/女性比例`` row.  Capture those percentages
                    # first, then attach them to the answer row below.
                    gender_overall: dict[str, Any] = {}
                    for row in cell_rows:
                        if not row:
                            continue
                        label = text(row[0].get("text"))
                        match = re.search(r"占全部(男性|女性)比例", label)
                        if match:
                            for cell in row[1:]:
                                if cell.get("percent") is not None:
                                    gender_overall[match.group(1)] = float(cell["percent"]) / 100
                                    break

                    first = cell_rows[0]
                    first_text = text(first[0].get("text")) if first else ""
                    # A normal question table starts with a single title row;
                    # gender rows start directly with ``男性票数``.
                    is_gender_table = any(
                        re.fullmatch(r"(?:男性|女性)票数", text(row[0].get("text")))
                        for row in cell_rows
                        if row
                    )
                    if is_gender_table:
                        question = "您的性别"
                        question_key = "sex"
                        option_rows = cell_rows
                    else:
                        # CN4 and mirrored pages prefix question titles with a
                        # number (for example ``1.1.``).  Strip only that
                        # leading marker so keys are stable across rounds.
                        question = re.sub(
                            r"^\s*\d+(?:\.\d+)*[.、．]\s*", "", first_text
                        ).strip(" ：:")
                        if not question or question in CN_GENERIC_DETAIL_HEADINGS:
                            continue
                        question_key = {
                            "年龄阶段": "age",
                            "年龄": "age",
                            "您的年龄阶段": "age",
                            "接触东方的时间": "cognition",
                            "接触东方时间": "cognition",
                            "正式接触东方Project多久": "cognition",
                        }.get(question, "cn_" + translation_key(question))
                        # Early detail pages put the question in a one-cell
                        # title row, followed by [answer, count, percent].
                        option_rows = cell_rows[1:]

                    for option_index, row in enumerate(option_rows):
                        if not row:
                            continue
                        label = text(row[0].get("text")).strip(" ：:")
                        if not label or label.startswith(("+", "说明", "点击")):
                            continue
                        if is_gender_table and label in {"占全部男性比例", "占全部女性比例"}:
                            continue
                        tail_text = " ".join(text(cell.get("text")) for cell in row[1:])
                        count_value = None
                        for cell in row[1:]:
                            if cell.get("number") is not None:
                                count_value = number(cell.get("number"))
                                break
                        if count_value is None:
                            match = re.search(r"([0-9][0-9,]*)\s*(?:票|人|名)", tail_text)
                            if match:
                                count_value = int(match.group(1).replace(",", ""))
                        rate_value = None
                        for cell in row[1:]:
                            if cell.get("percent") is not None:
                                rate_value = float(cell.get("percent")) / 100
                                break
                        if rate_value is None:
                            match = re.search(r"(?:占|比例)?\s*([0-9]+(?:\.[0-9]+)?)\s*%", tail_text)
                            if match:
                                rate_value = float(match.group(1)) / 100
                        if count_value is None:
                            # CN1-style labels can carry their statistic in
                            # the same cell; detail tables normally do not,
                            # but accepting this form keeps the parser robust.
                            match = re.search(r"：\s*([0-9][0-9,]*)", label)
                            if match:
                                count_value = int(match.group(1).replace(",", ""))
                        if count_value is None:
                            continue
                        overall_rate = ""
                        if is_gender_table:
                            gender = "男性" if label.startswith("男性") else "女性" if label.startswith("女性") else ""
                            overall_rate = gender_overall.get(gender, "")
                        output.append({
                            "region": "cn",
                            "round": round_number,
                            "category": category,
                            "entity_id": entity_id,
                            "entity_key": entity_key,
                            "entity_name": entity_name,
                            "entity_name_localized": entity_name,
                            "question_key": question_key,
                            "question": question,
                            "answer_label": re.sub(r"票数$", "", label),
                            "count": count_value,
                            "rate": rate_value if rate_value is not None else "",
                            "overall_rate": overall_rate,
                            "denominator": entity_denominator,
                            "source_kind": "cn_legacy_detail_demographics",
                            "source_path": rel(parsed_path),
                            "alignment_status": "matched_id" if entity else "unmatched_manual_review",
                            "notes": f"detail table {table_index}",
                        })
                        round_count += 1
                        category_counts[category] += 1
        coverage[str(round_number)] = {
            "status": "available" if round_count else "empty_local_extract",
            "rows": round_count,
            "rows_by_category": dict(category_counts),
        }
    return output, inputs, coverage


def round_from_sheet_title(value: Any) -> int | None:
    match = re.match(r"\s*(\d+)", text(value))
    return int(match.group(1)) if match else None


def load_translation_maps() -> tuple[dict[str, dict[tuple[int, str], str]], set[Path]]:
    """Load the existing root-level JP→CN crosswalks.

    The character/music workbooks are the user's maintained translations for
    JP3–20.  The character crosswalk and canonical music merge contain the
    newer JP21–22 translations.  No guessed translations are generated.
    """

    maps: dict[str, dict[tuple[int, str], str]] = {
        "character": {},
        "music": {},
    }
    inputs: set[Path] = set()

    workbook_specs = (
        ("character", ROOT / "TouhouVote_jp.xlsx", "日文名", ("译名", "译名 ")),
        ("music", ROOT / "TouhouVote_music_jp.xlsx", "曲目", ("译名",)),
    )
    for category, path, source_header, translated_headers in workbook_specs:
        if not path.exists():
            continue
        inputs.add(path)
        workbook = load_workbook(path, read_only=True, data_only=True)
        for sheet in workbook.worksheets:
            round_number = round_from_sheet_title(sheet.title)
            if round_number is None:
                continue
            rows = sheet.iter_rows(values_only=True)
            header = next(rows, None)
            if not header:
                continue
            names = {text(value): index for index, value in enumerate(header) if text(value)}
            source_index = names.get(source_header)
            translated_index = next((names.get(name) for name in translated_headers if names.get(name) is not None), None)
            if source_index is None or translated_index is None:
                continue
            for row in rows:
                if source_index >= len(row) or translated_index >= len(row):
                    continue
                source_name = text(row[source_index])
                translated_name = text(row[translated_index])
                if source_name and translated_name:
                    maps[category].setdefault((round_number, translation_key(source_name)), translated_name)

    crosswalk = ROOT / "metadata" / "character_name_crosswalk.csv"
    if crosswalk.exists():
        inputs.add(crosswalk)
        with crosswalk.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                source_name = text(row.get("character_jp"))
                translated_name = text(row.get("character_cn"))
                if not source_name or not translated_name:
                    continue
                key = translation_key(source_name)
                for round_number in range(3, 23):
                    maps["character"].setdefault((round_number, key), translated_name)

    music_crosswalk = ROOT / "data_processed" / "music_canonical" / "local_music_merged.csv"
    if music_crosswalk.exists():
        inputs.add(music_crosswalk)
        with music_crosswalk.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                if text(row.get("site")) != "jp":
                    continue
                round_number = number(row.get("round"))
                if round_number is None:
                    continue
                try:
                    jp_names = json.loads(row.get("source_titles_jp_json") or "[]")
                    cn_names = json.loads(row.get("source_titles_cn_json") or "[]")
                except json.JSONDecodeError:
                    continue
                translated_name = next((text(name) for name in cn_names if text(name)), "")
                if not translated_name:
                    continue
                for source_name in jp_names:
                    if text(source_name):
                        maps["music"].setdefault((int(round_number), translation_key(source_name)), translated_name)

    return maps, inputs


def clean_cell(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value.get("value")
    return value


def json_array_after(source: str, marker: str) -> list[dict[str, Any]] | None:
    pos = source.find(marker)
    if pos < 0:
        return None
    tail = source[pos + len(marker) :].lstrip()
    try:
        value, _ = JSONDecoder().raw_decode(tail)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, list) else None


def embedded_rows(path: Path) -> list[dict[str, Any]] | None:
    source = decode_html(path)
    # V5+ uses a FooTable "rows" array; V4 uses a JavaScript "vote" array.
    return json_array_after(source, '"rows":') or json_array_after(source, "var vote =")


def static_cn_rows(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    for table in payload.get("tables", []):
        rows = table.get("rows", [])
        if len(rows) < 2:
            continue
        headers = [text(cell.get("text")) for cell in rows[0]]
        if not any(h in headers for h in ("名次", "順位")):
            continue
        result: list[dict[str, Any]] = []
        for raw in rows[1:]:
            cells = [text(cell.get("text")) for cell in raw]
            if not cells:
                continue
            result.append(dict(zip(headers, cells)))
        if result:
            return result
    return []


def cn_name(row: Mapping[str, Any], category: str) -> str:
    if category == "work":
        return text(row.get("name") or row.get("作品名"))
    if category == "cp":
        members = [
            row.get("charaName1") or row.get("c1name") or row.get("角色A"),
            row.get("charaName2") or row.get("c2name") or row.get("角色B"),
            row.get("charaName3") or row.get("c3name") or row.get("角色C"),
        ]
        members = [re.sub(r"<[^>]+>", "", text(x)) for x in members]
        members = [x for x in members if x and x not in {"-", "－"}]
        return " × ".join(members)
    return text(row.get("name") or row.get("角色名") or row.get("音乐名"))


def cn_record(round_number: int, category: str, row: Mapping[str, Any], source_type: str, source_path: Path, fallback_rank: int) -> dict[str, Any] | None:
    rank = number(row.get("index") or row.get("名次") or row.get("順位") or fallback_rank)
    name = cn_name(row, category)
    if rank is None or not name:
        return None
    vote = clean_cell(row.get("vote"))
    if category == "work":
        if round_number == 4 and "sum" in row:
            # V4's embedded work rows call the weighted score ``total`` and
            # the unweighted three-position sum ``sum``; later V5+ rows use
            # the explicit ``weight``/``total`` names.
            vote = row.get("sum")
            points = row.get("total")
        else:
            vote = row.get("total") or row.get("总票数") or row.get("相加票数")
            points = row.get("weight") or row.get("计算票数") or row.get("加权票数")
        first = row.get("1st") or row.get("一位票")
        first_rate = row.get("ratio1") or row.get("一位率")
        male = clean_cell(row.get("male"))
        female = clean_cell(row.get("female"))
        male_rate = row.get("hmratio")
        female_rate = row.get("hfratio")
    elif category == "cp":
        vote = clean_cell(row.get("vote")) or row.get("total") or row.get("总票数")
        points = vote
        first = row.get("first") or row.get("本命数")
        first_rate = row.get("ratio") or row.get("本命率")
        male = clean_cell(row.get("male"))
        female = clean_cell(row.get("female"))
        male_rate = row.get("hmratio") or row.get("男性比例")
        female_rate = row.get("hfratio") or row.get("女性比例")
    else:
        points = clean_cell(row.get("weight")) or row.get("本命加权")
        first = clean_cell(row.get("first")) or row.get("本命数")
        first_rate = row.get("ratio") or row.get("本命率")
        male = clean_cell(row.get("male")) or row.get("男性数") or row.get("男性")
        female = clean_cell(row.get("female")) or row.get("女性数") or row.get("女性")
        male_rate = row.get("hmratio") or row.get("男性比例") or row.get("男性比")
        female_rate = row.get("hfratio") or row.get("女性比例") or row.get("女性比")
    vote_share = row.get("vratio") or row.get("票数占比")
    first_share = row.get("fratio") or row.get("本命占比")
    raw_entity_id = text(row.get("id"))
    # CN5+ summary tables use a one-based display ordinal in ``id`` for CP
    # rows, while the linked detail URL carries the stable zero-padded CP ID.
    # Prefer that URL ID whenever present; ordinary character/music/work rows
    # use the same ID in both locations.
    info = text(row.get("info"))
    info_match = re.search(r"type=[^&'\"]+&id=([0-9A-Za-z_-]+)", info)
    if info_match:
        raw_entity_id = info_match.group(1)
    return {
        "region": "cn",
        "round": round_number,
        "category": category,
        "rank": int(rank),
        "entity_id": raw_entity_id,
        "entity_name": name,
        "entity_name_localized": name,
        "points": number(points),
        "vote_count": number(vote),
        "first_choice_count": number(first),
        "comment_count": None,
        "rank_prev": None,
        "rank_prev2": None,
        "weighted_score": number(points),
        "vote_share": percent(vote_share),
        "first_choice_share": percent(first_share or first_rate),
        "male_count": number(male),
        "male_rate": percent(male_rate),
        "female_count": number(female),
        "female_rate": percent(female_rate),
        "source_type": source_type,
        "source_path": rel(source_path),
        "entity_key": "",
        "alignment_status": "unresolved",
        "alignment_name_source": "",
        "notes": "",
    }


def cn_category_path(round_number: int, category: str) -> tuple[Path | None, str]:
    base = ROOT / "data_raw" / "cn_official_legacy" / f"round_{round_number:02d}"
    if round_number == 1:
        names = {"work": "pages__work__mod_work__step_1.html.tables.json"}
    elif round_number in (2, 3):
        names = {
            "work": "pages__work__m_3__s_1.html.tables.json",
            "cp": "pages__cp__m_4__t_1.html.tables.json",
        }
    elif round_number == 4:
        names = {
            "work": "raw/pages/work/m_work__t_full.html",
            "cp": "raw/pages/cp/m_cp__s_1.html",
        }
    else:
        names = {
            "work": "raw/pages/work/m_work__type_simple.html",
            "cp": "raw/pages/cp/m_cp__type_simple.html",
        }
    if category not in names:
        return None, ""
    relative = names[category]
    if round_number <= 3:
        path = base / "processed" / "summary_tables" / relative
    else:
        path = base / relative
    if not path.exists():
        return None, ""
    return path, ("cn_legacy_html_embedded_json" if path.suffix == ".html" else "cn_legacy_html_table_json")


def workbook_cn_rows(path: Path, category: str) -> tuple[list[dict[str, Any]], set[Path]]:
    wb = load_workbook(path, read_only=True, data_only=True)
    rows: list[dict[str, Any]] = []
    for sheet_name in wb.sheetnames:
        try:
            round_number = int(sheet_name)
        except ValueError:
            continue
        if not 1 <= round_number <= 9:
            continue
        ws = wb[sheet_name]
        values = ws.iter_rows(values_only=True)
        try:
            headers = [text(v) for v in next(values)]
        except StopIteration:
            continue
        for raw in values:
            item = dict(zip(headers, raw))
            rank = number(item.get("名次"))
            name = text(item.get("译名") or item.get("角色名") or item.get("音乐名"))
            if rank is None or not name:
                continue
            vote = item.get("票数")
            primary = item.get("本命数")
            score = item.get("本命加权")
            male = item.get("男性数") or item.get("男性")
            female = item.get("女性数") or item.get("女性")
            male_rate = item.get("男性比例") or item.get("男性比") or item.get("男性率")
            female_rate = item.get("女性比例") or item.get("女性比") or item.get("女性率")
            rows.append(
                {
                    "region": "cn",
                    "round": round_number,
                    "category": category,
                    "rank": int(rank),
                    "entity_id": "",
                    "entity_name": name,
                    "entity_name_localized": name,
                    "points": number(score),
                    "vote_count": number(vote),
                    "first_choice_count": number(primary),
                    "comment_count": None,
                    "rank_prev": None,
                    "rank_prev2": None,
                    "weighted_score": number(score),
                    "vote_share": percent(item.get("票数占比")),
                    "first_choice_share": percent(item.get("本命占比") or item.get("本命率")),
                    "male_count": number(male),
                    "male_rate": percent(male_rate),
                    "female_count": number(female),
                    "female_rate": percent(female_rate),
                    "source_type": "cn_normalized_workbook",
                    "source_path": rel(path),
                    "entity_key": "",
                    "alignment_status": "unresolved",
                    "alignment_name_source": "",
                    "notes": "",
                }
            )
    return rows, {path}


def load_cn_modern_base_rows(
    rounds: Iterable[int] = (10, 11),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[Path], dict[str, Any]]:
    """Load the complete CN10/CN11 ordinary rankings from GraphQL snapshots.

    ``advanced_conditions`` contains conditional rankings, but the ordinary
    result is already archived in ``graphql/base.json``.  Those responses have
    no stable numeric entity id, so a deterministic name/ordered-member key is
    used and the source is marked explicitly as modern GraphQL.  The global
    stats fields (``numChar``/``numMusic``/``numCp``) are the published valid
    selection counts for each department and are emitted as ballot totals.
    """

    rows: list[dict[str, Any]] = []
    totals: list[dict[str, Any]] = []
    inputs: set[Path] = set()
    coverage: dict[str, Any] = {}
    ranking_specs = {
        "character": ("queryCharacterRanking", "numChar"),
        "music": ("queryMusicRanking", "numMusic"),
        "cp": ("queryCPRanking", "numCp"),
    }
    for raw_round in rounds:
        round_number = int(raw_round)
        path = ROOT / "data_raw" / "cn_official" / f"round_{round_number:02d}" / "graphql" / "base.json"
        if not path.exists():
            coverage[str(round_number)] = {"status": "missing_local_extract", "ranking_rows": 0, "totals": 0}
            continue
        inputs.add(path)
        try:
            payload = read_json(path)
        except (OSError, json.JSONDecodeError):
            coverage[str(round_number)] = {"status": "invalid_local_extract", "ranking_rows": 0, "totals": 0}
            continue
        data = payload.get("data", {}) if isinstance(payload, Mapping) else {}
        if not isinstance(data, Mapping):
            coverage[str(round_number)] = {"status": "invalid_local_extract", "ranking_rows": 0, "totals": 0}
            continue
        stats = data.get("queryGlobalStats", {})
        if not isinstance(stats, Mapping):
            stats = {}
        before = len(rows)
        total_count = 0
        for category, (graphql_key, stat_key) in ranking_specs.items():
            result = data.get(graphql_key, {})
            entries = result.get("entries", []) if isinstance(result, Mapping) else []
            if not isinstance(entries, list):
                entries = []
            published_total = number(stats.get(stat_key))
            if published_total is not None:
                totals.append({
                    "region": "cn", "round": round_number, "category": category,
                    "valid_vote_count": int(published_total), "valid_primary_count": None,
                    "respondent_count": number(stats.get("numVote")),
                    "source_type": "cn_modern_official_graphql_global_stats",
                    "source_path": rel(path),
                    "notes": f"queryGlobalStats.{stat_key}",
                })
                total_count += 1
            for index, raw in enumerate(entries, start=1):
                if not isinstance(raw, Mapping):
                    continue
                cp = raw.get("cp") if isinstance(raw.get("cp"), Mapping) else {}
                if category == "cp":
                    members = [text(cp.get(key)) for key in ("a", "b", "c") if text(cp.get(key)) and text(cp.get(key)) not in {"-", "－"}]
                    name = " × ".join(members)
                    # Keep an ordered member key: active-side order is part of
                    # the official CP definition and must not be sorted away.
                    entity_token = _cn_entity_name_key("cp", name)
                else:
                    name = text(raw.get("name"))
                    entity_token = _cn_entity_name_key(category, name)
                if not name or not entity_token:
                    continue
                entity_id = text(raw.get("id"))
                rows.append({
                    "region": "cn", "round": round_number, "category": category,
                    "rank": int(number(raw.get("rank") or raw.get("displayRank") or index) or index),
                    "entity_id": entity_id,
                    "entity_name": name,
                    "entity_name_localized": name,
                    "points": number(raw.get("firstVoteCountWeighted")) if category in {"character", "music", "cp"} else None,
                    "vote_count": number(raw.get("voteCount")),
                    "first_choice_count": number(raw.get("firstVoteCount")),
                    "comment_count": None,
                    "rank_prev": None,
                    "rank_prev2": None,
                    "weighted_score": number(raw.get("firstVoteCountWeighted")),
                    "vote_share": percent(raw.get("votePercentage")),
                    "first_choice_share": percent(raw.get("firstVotePercentage")),
                    "male_count": number(raw.get("maleVoteCount")),
                    "male_rate": percent(raw.get("malePercentagePerChar")),
                    "female_count": number(raw.get("femaleVoteCount")),
                    "female_rate": percent(raw.get("femalePercentagePerChar")),
                    "source_type": "cn_modern_official_graphql_base",
                    "source_path": rel(path),
                    "entity_key": f"cn:{round_number:02d}:{category}:{entity_id}" if entity_id else f"cn:{round_number:02d}:{category}:name:{entity_token}",
                    "alignment_status": "modern_graphql_name_key",
                    "alignment_name_source": "graphql_name" if category != "cp" else "graphql_cp_members",
                    "notes": "complete ordinary ranking snapshot; CP name is ordered cp.a × cp.b × cp.c",
                })
        coverage[str(round_number)] = {
            "status": "available" if len(rows) > before else "empty_local_extract",
            "ranking_rows": len(rows) - before,
            "totals": total_count,
        }
    return rows, totals, inputs, coverage


def jp_cells(row: Mapping[str, Any]) -> list[str]:
    return [text(cell.get("text")) for cell in row.get("cells", [])]


def jp_tables(path: Path) -> list[tuple[str, list[str], list[list[str]]]]:
    payload = read_json(path)
    result = []
    for table in payload.get("numeric_tables", []):
        raw_rows = table.get("rows", [])
        if not raw_rows:
            continue
        headers = jp_cells(raw_rows[0])
        result.append((text(table.get("context_heading")), headers, [jp_cells(r) for r in raw_rows[1:]]))
    return result


def jp_col(headers: list[str], *names: str) -> int | None:
    for name in names:
        if name in headers:
            return headers.index(name)
    return None


def at(row: list[str], index: int | None) -> str:
    return row[index] if index is not None and index < len(row) else ""


def jp_record(round_number: int, category: str, headers: list[str], row: list[str], source_path: Path, notes: str = "") -> dict[str, Any] | None:
    rank_i = jp_col(headers, "順位")
    name_i = jp_col(headers, "名前", "曲名", "スペルカード名")
    if rank_i is None or name_i is None:
        return None
    rank = number(at(row, rank_i))
    name = at(row, name_i)
    if rank is None or not name:
        return None
    point_i = jp_col(headers, "ポイント", "ポイント合計")
    if point_i is None and category == "overall":
        point_i = jp_col(headers, "合計")
    if point_i is None:
        point_i = jp_col(headers, "合計")
    prev_i = jp_col(headers, "前回")
    prev2_i = jp_col(headers, "前々")
    primary_i = jp_col(headers, "1押し", "一押し")
    comment_i = jp_col(headers, "コメント")
    support_i = jp_col(headers, "支援作品", "支援リンク")
    points = number(at(row, point_i))
    primary = number(at(row, primary_i))
    comments = number(at(row, comment_i))
    support = number(at(row, support_i))
    selection = jp_selection_count_from_score(round_number, points, primary) if category in {"character", "music", "work"} else None
    return {
        "region": "jp",
        "round": round_number,
        "category": category,
        "rank": int(rank),
        "entity_id": "",
        "entity_name": name,
        "entity_name_localized": "",
        "points": points,
        "vote_count": selection,
        "first_choice_count": primary,
        "comment_count": comments,
        "rank_prev": number(at(row, prev_i)),
        "rank_prev2": number(at(row, prev2_i)),
        "weighted_score": points,
        "vote_share": None,
        "first_choice_share": None,
        "male_count": None,
        "male_rate": None,
        "female_count": None,
        "female_rate": None,
        "source_type": "jp_legacy_official_html_table",
        "source_path": rel(source_path),
        "notes": notes or (f"支援数={support}" if support is not None else ""),
    }


def jp_old_rows(translation_maps: dict[str, dict[tuple[int, str], str]] | None = None) -> tuple[list[dict[str, Any]], set[Path]]:
    rows: list[dict[str, Any]] = []
    inputs: set[Path] = set()
    translation_maps = translation_maps or {}
    for round_number in range(3, 17):
        base = ROOT / "data_raw" / "jp_official_legacy" / f"round_{round_number:02d}"
        specs: list[tuple[str, Path, str | None]] = []
        if round_number <= 10:
            specs += [
                ("character", base / "aggregate/result_char.html.tables.json", None),
                ("music", base / "aggregate/result_music.html.tables.json", None),
            ]
            if round_number == 3:
                specs += [
                    ("spell", base / "aggregate/result_spell.html.tables.json", None),
                    ("spell_system", base / "aggregate/result_spell_b.html.tables.json", None),
                    ("spell_user_overall", base / "aggregate/result_etc.html.tables.json", "■スペルカード使用者ランキング"),
                    ("overall", base / "aggregate/result_etc.html.tables.json", "■総合ランキング"),
                ]
            elif (base / "aggregate/result_etc.html.tables.json").exists():
                specs.append(("overall", base / "aggregate/result_etc.html.tables.json", "■総合ランキング"))
        else:
            specs += [
                ("character", base / "lists/result_list_character.php.html.tables.json", None),
                ("music", base / "lists/result_list_music.php.html.tables.json", None),
            ]
            if 12 <= round_number <= 16:
                specs.append(("work", base / "lists/result_list_title.php.html.tables.json", None))
            if round_number == 13:
                specs.append(("partner", base / "lists/result_list_partner.php.html.tables.json", None))
        for category, path, context in specs:
            if not path.exists():
                continue
            inputs.add(path)
            for table_context, headers, table_rows in jp_tables(path):
                if context and table_context != context:
                    continue
                for raw in table_rows:
                    record = jp_record(round_number, category, headers, raw, path)
                    if record:
                        if category in translation_maps:
                            record["entity_name_localized"] = translation_maps[category].get(
                                (round_number, translation_key(record["entity_name"])), ""
                            )
                        rows.append(record)
                if context is None:
                    break
    return rows, inputs


def jp_modern_rows(translation_maps: dict[str, dict[tuple[int, str], str]] | None = None) -> tuple[list[dict[str, Any]], set[Path]]:
    rows: list[dict[str, Any]] = []
    inputs: set[Path] = set()
    translation_maps = translation_maps or {}
    detail_secondary: dict[tuple[int, str, str], int | float] = {}
    detail_path = ROOT / "data_processed" / "jp_official" / "detail_items.csv"
    if detail_path.exists():
        inputs.add(detail_path)
        with detail_path.open("r", encoding="utf-8-sig", newline="") as f:
            for detail in csv.DictReader(f):
                secondary = number(detail.get("secondary"))
                if secondary is None:
                    continue
                key = (int(detail["round"]), text(detail.get("source_category")), text(detail.get("source_id")))
                detail_secondary[key] = secondary
    for round_number in range(17, 23):
        base = ROOT / "data_raw" / "jp_official" / f"round_{round_number:02d}" / "aggregate"
        for category in ("character", "music", "work"):
            path = base / f"{category}.json"
            if not path.exists():
                continue
            inputs.add(path)
            payload = read_json(path)
            for item in payload.get("data", []):
                points = number(item.get("point"))
                primary = number(item.get("primary_num"))
                secondary = number(item.get("secondary_num"))
                if secondary is None:
                    secondary = detail_secondary.get((round_number, category, text(item.get("code"))))
                selection = jp_selection_count_from_score(round_number, points, primary, secondary)
                localized = translation_maps.get(category, {}).get(
                    (round_number, translation_key(item.get("name"))), ""
                )
                rows.append(
                    {
                        "region": "jp",
                        "round": round_number,
                        "category": category,
                        "rank": number(item.get("rank")),
                        "entity_id": text(item.get("code")),
                        "entity_name": text(item.get("name")),
                        "entity_name_localized": localized,
                        "points": points,
                        "vote_count": selection,
                        "first_choice_count": primary,
                        "comment_count": number(item.get("comment_num")),
                        "rank_prev": number(item.get("rank_prev")),
                        "rank_prev2": number(item.get("rank_prev2")),
                        "weighted_score": points,
                        "vote_share": None,
                        "first_choice_share": None,
                        "male_count": None,
                        "male_rate": None,
                        "female_count": None,
                        "female_rate": None,
                        "source_type": "jp_modern_official_json",
                        "source_path": rel(path),
                        "notes": "",
                    }
                )
    return rows, inputs


def extract_cn_totals(round_number: int, category: str, source_path: Path) -> dict[str, Any] | None:
    base = ROOT / "data_raw" / "cn_official_legacy" / f"round_{round_number:02d}" / "raw/pages"
    index = base / category / "index.html"
    path = index if index.exists() else source_path
    if not path.exists():
        return None
    raw = html_text(path)
    match = re.search(r"总有效票数[^0-9]{0,120}([0-9][0-9,]*)", raw)
    if not match:
        return None
    # V1–V4 write the values inline (``总有效票数6365，总本命票数5358``),
    # while V5+ render a two-row table where the two numbers follow the
    # adjacent headers.  Looking only after the second header would otherwise
    # accidentally capture the first value in the V5+ table.
    primary_value = None
    inline = re.search(r"总有效票数\s*([0-9][0-9,]*)[^0-9]{0,40}总本命票数\s*([0-9][0-9,]*)", raw)
    if inline:
        primary_value = int(inline.group(2).replace(",", ""))
    else:
        table = re.search(r"总有效票数\s+总本命票数[^0-9]{0,100}([0-9][0-9,]*)\s+([0-9][0-9,]*)", raw)
        if table:
            primary_value = int(table.group(2).replace(",", ""))
    return {
        "region": "cn",
        "round": round_number,
        "category": category,
        "valid_vote_count": int(match.group(1).replace(",", "")),
        "valid_primary_count": primary_value,
        "respondent_count": None,
        "source_type": "cn_legacy_official_summary",
        "source_path": rel(path),
        "notes": "",
    }


def jp_legacy_totals() -> tuple[list[dict[str, Any]], set[Path]]:
    rows: list[dict[str, Any]] = []
    inputs: set[Path] = set()
    labels = {
        "character": ("人妖部門", "キャラ部門"),
        "music": ("音楽部門",),
        "work": ("作品部門",),
        "partner": ("ベストパートナー部門",),
        "spell": ("スペルカード部門",),
    }
    for round_number in range(3, 17):
        path = ROOT / "data_raw" / "jp_official_legacy" / f"round_{round_number:02d}" / "aggregate/index.html"
        if not path.exists():
            continue
        inputs.add(path)
        raw = html_text(path)
        for category, candidates in labels.items():
            value = None
            for label in candidates:
                # Require the colon used by the published total line.  A
                # bare label also occurs in navigation links (e.g. 音楽部門
                # 結果), which can make a loose search capture the previous
                # category's count.
                m = re.search(re.escape(label) + r"\s*[：:]\s*([0-9][0-9,]*)\s*(?:票|件|個)", raw)
                if m:
                    value = int(m.group(1).replace(",", ""))
                    break
            if value is not None:
                primary = None
                rows.append(
                    {
                        "region": "jp",
                        "round": round_number,
                        "category": category,
                        "valid_vote_count": value,
                        "valid_primary_count": primary,
                        "respondent_count": None,
                        "source_type": "jp_legacy_official_summary",
                        "source_path": rel(path),
                        "notes": "",
                    }
                )
    return rows, inputs


def jp_modern_totals() -> tuple[list[dict[str, Any]], set[Path]]:
    rows: list[dict[str, Any]] = []
    inputs: set[Path] = set()
    for round_number in range(17, 23):
        path = ROOT / "data_raw" / "jp_official" / f"round_{round_number:02d}" / "aggregate/count.json"
        if not path.exists():
            continue
        inputs.add(path)
        payload = read_json(path).get("data", {})
        for category in ("character", "music", "work"):
            if category in payload:
                rows.append(
                    {
                        "region": "jp",
                        "round": round_number,
                        "category": category,
                        "valid_vote_count": number(payload[category]),
                        "valid_primary_count": None,
                        "respondent_count": None,
                        "source_type": "jp_modern_official_count_json",
                        "source_path": rel(path),
                        "notes": "count.json category total",
                    }
                )
    return rows, inputs


def write_csv(path: Path, fields: list[str], rows: Iterable[Mapping[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) if row.get(field) is not None else "" for field in fields})
            count += 1
    return count


def write_csv_gzip(path: Path, rows: Iterable[Mapping[str, Any]], fields: list[str]) -> int:
    """Write a UTF-8-with-BOM CSV stream compressed with gzip.

    Advanced-search extracts are large enough that keeping their portable
    copies compressed is useful.  Keep the same empty-value policy as
    ``write_csv`` so the two output formats are interchangeable to readers.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with gzip.open(path, "wt", encoding="utf-8-sig", newline="", compresslevel=9) as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) if row.get(field) is not None else "" for field in fields})
            count += 1
    return count


def build_cn_entity_inventory(
    entity_index: Mapping[tuple[int, str, str], list[dict[str, Any]]],
    rankings: Iterable[Mapping[str, Any]],
    advanced_rows: Iterable[Mapping[str, Any]] = (),
    demographic_rows: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Build the complete CN1–9 crawl-item ↔ vote-data bridge.

    The detail index is the authoritative item inventory.  Ranking rows that
    cannot be matched by id/name remain in ``cn_alignment_audit.csv``; every
    successfully crawled item still gets a stable key and an explicit status.
    Item-level API paths are read from the crawler's per-round index when
    present (CN5–9), while earlier rounds keep those fields empty.
    """

    entities: dict[tuple[int, str, str], dict[str, Any]] = {}
    for records in entity_index.values():
        for entity in records:
            round_number = int(entity.get("round") or 0)
            category = text(entity.get("category"))
            entity_id = text(entity.get("entity_id"))
            if round_number and category and entity_id:
                entities.setdefault((round_number, category, entity_id), entity)

    api_by_key: dict[tuple[int, str, str], dict[str, Any]] = {}
    for round_number in range(1, 10):
        path = ROOT / "data_raw" / "cn_official_legacy" / f"round_{round_number:02d}" / "processed" / "item_apis" / "index.csv"
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                for raw in csv.DictReader(fh):
                    category = CN_DATASET_CATEGORIES.get(text(raw.get("category")), text(raw.get("category")))
                    entity_id = text(raw.get("id"))
                    if category and entity_id:
                        api_by_key[(round_number, category, entity_id)] = {
                            "item_api_votedate": text(raw.get("votedate")),
                            "item_api_votesex": text(raw.get("votesex")),
                            "item_api_votegeo": text(raw.get("votegeo")),
                            "item_api_votepaper": text(raw.get("votepaper")),
                            "item_api_complete": text(raw.get("complete")),
                        }
        except (OSError, UnicodeError):
            continue

    rank_counts: Counter[tuple[int, str, str]] = Counter()
    rank_values: defaultdict[tuple[int, str, str], list[int]] = defaultdict(list)
    for row in rankings:
        key = (int(row.get("round") or 0), text(row.get("category")), text(row.get("entity_id")))
        if not key[0] or not key[1] or not key[2]:
            continue
        rank_counts[key] += 1
        rank = number(row.get("rank"))
        if rank is not None:
            rank_values[key].append(int(rank))

    advanced_counts: Counter[tuple[int, str, str]] = Counter()
    advanced_questionnaire_counts: Counter[tuple[int, str, str]] = Counter()
    for row in advanced_rows:
        key = (int(row.get("round") or 0), text(row.get("target_category")), text(row.get("entity_id")))
        if not key[0] or not key[1] or not key[2]:
            continue
        advanced_counts[key] += 1
        if text(row.get("condition_family")) == "questionnaire_answer":
            advanced_questionnaire_counts[key] += 1

    demographic_counts: Counter[tuple[int, str, str]] = Counter()
    for row in demographic_rows:
        key = (int(row.get("round") or 0), text(row.get("category")), text(row.get("entity_id")))
        if all(key):
            demographic_counts[key] += 1

    output: list[dict[str, Any]] = []
    for key in sorted(entities):
        round_number, category, entity_id = key
        entity = entities[key]
        api = api_by_key.get(key, {})
        rank_count = rank_counts.get(key, 0)
        output.append({
            "region": "cn", "round": round_number, "category": category,
            "entity_id": entity_id, "entity_key": f"cn:{round_number:02d}:{category}:{entity_id}",
            "entity_name": text(entity.get("entity_name")),
            "aliases": " | ".join(text(value) for value in entity.get("aliases", []) if text(value)),
            "detail_status": text(entity.get("status")),
            "detail_path": text(entity.get("detail_path")),
            "parsed_path": text(entity.get("parsed_path")),
            "item_api_votedate": api.get("item_api_votedate", ""),
            "item_api_votesex": api.get("item_api_votesex", ""),
            "item_api_votegeo": api.get("item_api_votegeo", ""),
            "item_api_votepaper": api.get("item_api_votepaper", ""),
            "item_api_complete": api.get("item_api_complete", ""),
            "ranking_row_count": rank_count,
            "ranking_ranks": ",".join(str(value) for value in sorted(rank_values.get(key, []))),
            "advanced_row_count": advanced_counts.get(key, 0),
            "advanced_questionnaire_row_count": advanced_questionnaire_counts.get(key, 0),
            "demographic_row_count": demographic_counts.get(key, 0),
            "alignment_status": "matched_ranking" if rank_count else "detail_not_in_ranking",
            "notes": "",
        })
    return output


def build_readme(rankings: list[dict[str, Any]], totals: list[dict[str, Any]]) -> str:
    counts = Counter((r["region"], int(r["round"]), r["category"]) for r in rankings)
    categories = sorted({r["category"] for r in rankings})
    lines = [
        "# CN1–11 / JP3–22 投票结果数据集",
        "",
        "本目录是从工作区已有的本地爬取资料离线整理出的可直接读取数据集。普通名次表范围为中国区 CN1–11 与日区 JP3–22。CN1–9 使用旧版排行页/工作簿，CN10–11 使用完整现代 GraphQL base.json；CSV 使用 UTF-8 with BOM，便于 Excel、pandas 和 R 直接打开。",
        "",
        "## 文件",
        "",
        "- `rankings.csv`：统一长表，每行一个地区、届次、榜单类别和实体。",
        "- `ballot_totals.csv`：源页面明确发布的各届各类别有效票数；无法可靠取得的字段留空。",
        "- `cn_alignment_audit.csv`：CN1–9 投票榜中未能唯一对齐详情实体的行（保留原名和原因）；CN10–11 现代榜使用名称键并在 `alignment_status` 标明。",
        "- `cn_legacy_advanced_rankings.csv.gz`：CN5–9 官方问卷条件榜与实体条件榜，已带稳定实体键。",
        "- `cn_legacy_advanced_questionnaire.csv`：上述高级结果中的问卷答案条件子集。",
        "- `cn_legacy_advanced_pairs.csv.gz`：CN5–9 官方问卷两两交叉（pair）单元格。",
        "- `cn_advanced_rankings.csv.gz`：统一 CN5–11 高级搜索原子条件榜；CN10/11 还保留现代站的 CP 聚合结果。",
        "- `cn_advanced_questionnaire.csv`：统一 CN5–11 问卷答案原子条件榜（仅分类 Single/Multiple；Input/open text 保留元数据但不作为数值答案）。",
        "- `cn_advanced_pairs.csv.gz`：CN5–11 统一问卷两两交叉单元格；CN10/11 没有旧版批量端点，数据来自逐格归档的官方 Boolean 查询。",
        "- `cn_legacy_detail_demographics.csv.gz`：CN2–4 详情页公开的逐实体投票群体统计（性别、年龄、接触时间等）；这是早期静态详情口径，不冒充后期高级搜索 API。",
        "- `cn_entity_inventory.csv`：CN1–9 每个已抓取详情项的稳定键、显示名别名、普通榜行数、高级条件行数、早期群体统计行数和 item API 文件清单；可用它逐项核对抓取与投票结果。CN10–11 的现代榜没有旧版详情索引，直接追溯 `graphql/base.json`。",
        "- `manifest.json`：输入/输出 SHA-256、行数、覆盖范围和校验结果。",
        "",
        "## 字段约定",
        "",
        "`points` / `weighted_score` 保留源站的加权分或积分；`vote_count` 是该实体的总选择人数：CN 使用源站总票数，JP 在官方同时公开积分和所需顺位数时按当届 2/1 或 3/2/1 计分规则精确还原。无法唯一还原的 JP 榜单仍留空，不会估算或写成 0。`first_choice_count` 是 CN 本命数或 JP 一押数。`vote_share` 是实体总选择人数除以该届该类别有效投票人数。百分比字段统一转换为 0–1 比例。`rank_prev`、`rank_prev2` 是源站公布的上两届名次。缺失值为空字符串。",
        "",
        "CN 规则、可投票数量和加权方式在历届有变化；JP 旧版与现代版也不是同一计分制度。因此不要把不同地区/届次的 `points` 或 `weighted_score` 当成可直接横向比较的统一分数。并列名次会保留源站名次，使用 `(region, round, category, rank, entity_name)` 作为稳定行键。",
        "",
        "## 纳入的榜单类别",
        "",
        f"当前输出类别：{', '.join(categories)}。CN 的作品/组合榜来自可恢复的官方排行页，CN10–11 的角色、曲子、CP榜来自完整现代 GraphQL；JP3 的 spell、spell_system、spell_user_overall、overall 等榜单按不同类别保留，避免与角色榜混淆。CN1 没有逐实体投票群体详情；CN2–4 的详情页包含逐实体群体统计，另存为 `cn_legacy_detail_demographics.csv.gz`；CN5–9 的后期高级条件榜、实体条件榜和官方两两交叉表另存为 `cn_legacy_advanced_*`；CN10/11 的现代 GraphQL 原子条件和逐格问卷交叉数据合并进 `cn_advanced_*`。",
        "",
        "## 覆盖概览",
        "",
        f"共 {len(rankings):,} 行排行、{len(totals):,} 行票数汇总。详细分组行数见 `manifest.json` 的 `row_counts_by_region_round_category`。",
        "",
        "## 来源与复现",
        "",
        "构建脚本为 `scripts_pipeline/build_vote_dataset.py`，只读取本地 `data_raw/`、`data_processed/` 和现有规范化工作簿，不联网。每条排行记录都保留 `source_type` 与 `source_path`，可沿路径回溯到原始 HTML 表、HTML 内嵌数组、现代 JSON 或现有工作簿；`entity_key` 是可跨表连接的稳定键，`alignment_status` 明确区分已匹配、歧义、未提供详情和待人工复核。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    rankings: list[dict[str, Any]] = []
    totals: list[dict[str, Any]] = []
    inputs: set[Path] = set()
    translation_maps, translation_inputs = load_translation_maps()
    inputs |= translation_inputs

    entity_index, detail_inputs = load_cn_legacy_entity_index()
    entity_index, music_alias_inputs = augment_cn_music_aliases(entity_index)
    inputs |= detail_inputs | music_alias_inputs

    cn_char, cn_char_inputs = workbook_cn_rows(ROOT / "TouhouVote_cn.xlsx", "character")
    cn_music, cn_music_inputs = workbook_cn_rows(ROOT / "TouhouVote_music_cn.xlsx", "music")
    rankings.extend(cn_char)
    rankings.extend(cn_music)
    inputs |= cn_char_inputs | cn_music_inputs

    for category in ("work", "cp"):
        for round_number in range(1, 10):
            path, source_type = cn_category_path(round_number, category)
            if path is None:
                continue
            raw_rows = embedded_rows(path) if path.suffix == ".html" else static_cn_rows(path)
            if not raw_rows:
                continue
            inputs.add(path)
            for i, raw in enumerate(raw_rows, start=1):
                record = cn_record(round_number, category, raw, source_type, path, i)
                if record:
                    rankings.append(record)

    # Resolve every CN1–9 ranking row after all four source families have been
    # collected.  Unmatched rows stay in the dataset and are written to an
    # audit table; no vote row is silently discarded.  CN10/11 modern rows
    # already carry deterministic GraphQL name keys and must not be sent
    # through the legacy detail-index aligner.
    cn_rows, cn_alignment_audit = align_cn_rankings(
        [row for row in rankings if row.get("region") == "cn"], entity_index
    )

    modern_cn_rows, modern_cn_totals, modern_cn_inputs, modern_cn_coverage = load_cn_modern_base_rows()
    inputs |= modern_cn_inputs

    jp_old, jp_old_inputs = jp_old_rows(translation_maps)
    jp_modern, jp_modern_inputs = jp_modern_rows(translation_maps)
    rankings = cn_rows + modern_cn_rows + jp_old + jp_modern
    inputs |= jp_old_inputs | jp_modern_inputs

    advanced_rankings, advanced_questionnaire, advanced_pairs, advanced_inputs, advanced_coverage = load_cn_legacy_advanced_data(entity_index)
    inputs |= advanced_inputs
    (
        modern_advanced_rankings,
        modern_advanced_questionnaire,
        modern_advanced_pairs,
        modern_advanced_inputs,
        modern_advanced_coverage,
    ) = load_cn_modern_advanced_data()
    inputs |= modern_advanced_inputs
    # Keep the historical CN5–9 filenames stable for existing consumers, and
    # add a unified CN5–11 view for cross-round advanced-search analysis.
    unified_advanced_rankings = advanced_rankings + modern_advanced_rankings
    unified_advanced_questionnaire = advanced_questionnaire + modern_advanced_questionnaire
    unified_advanced_pairs = advanced_pairs + modern_advanced_pairs
    detail_demographics, demographic_inputs, demographic_coverage = load_cn_legacy_detail_demographics(entity_index)
    inputs |= demographic_inputs

    # Category totals are added only for categories present in rankings.  The
    # modern CN10/11 global stats are already authoritative and are appended
    # directly; legacy CN totals continue to come from the archived summary
    # pages.
    categories_present = {(r["region"], int(r["round"]), r["category"]) for r in rankings}
    for round_number in range(1, 10):
        for category in ("character", "music", "work", "cp"):
            if ("cn", round_number, category) not in categories_present:
                continue
            source = ROOT / "TouhouVote_cn.xlsx" if category == "character" else ROOT / "TouhouVote_music_cn.xlsx" if category == "music" else cn_category_path(round_number, category)[0]
            if source is None:
                continue
            total = extract_cn_totals(round_number, {"character": "chara", "music": "music", "work": "work", "cp": "cp"}[category], source)
            if total:
                total["category"] = category
                totals.append(total)
                inputs.add(ROOT / "data_raw" / "cn_official_legacy" / f"round_{round_number:02d}" / "raw/pages" / {"character": "chara", "music": "music", "work": "work", "cp": "cp"}[category] / "index.html")

    totals.extend([r for r in modern_cn_totals if (r["region"], int(r["round"]), r["category"]) in categories_present])
    old_totals, old_total_inputs = jp_legacy_totals()
    modern_totals, modern_total_inputs = jp_modern_totals()
    totals.extend([r for r in old_totals + modern_totals if (r["region"], int(r["round"]), r["category"]) in categories_present])
    inputs |= old_total_inputs | modern_total_inputs

    total_map = {
        (row["region"], int(row["round"]), row["category"]): number(row.get("valid_vote_count"))
        for row in totals
    }
    for row in rankings:
        total = total_map.get((row["region"], int(row["round"]), row["category"]))
        selected = number(row.get("vote_count"))
        if row.get("vote_share") is None and selected is not None and total:
            row["vote_share"] = selected / total

    rankings.sort(key=lambda r: (r["region"], int(r["round"]), r["category"], int(r["rank"]), r["entity_name"]))
    totals.sort(key=lambda r: (r["region"], int(r["round"]), r["category"]))
    # Independent spot-checks against the already generated longitudinal
    # extracts.  Compare stable identity/rank/score fields only; zero counts in
    # the modern JSON are intentionally retained here while the older extract
    # renders them as blank.
    cn_history_path = ROOT / "metadata" / "cn_vote_history_all_characters.csv"
    jp_history_path = ROOT / "metadata" / "vote_history_all_characters.csv"
    inputs |= {cn_history_path, jp_history_path}
    with cn_history_path.open("r", encoding="utf-8-sig", newline="") as f:
        cn_history = list(csv.DictReader(f))
    with jp_history_path.open("r", encoding="utf-8-sig", newline="") as f:
        jp_history = list(csv.DictReader(f))
    cn_expected = {
        (int(r["round"]), int(r["rank"]), r["character_cn"], str(r["weighted_score"]))
        for r in cn_history
        if int(r["round"]) <= 9
    }
    cn_actual = {
        (int(r["round"]), int(r["rank"]), r["entity_name"], str(r["weighted_score"]))
        for r in rankings
        if r["region"] == "cn" and r["category"] == "character"
        and int(r["round"]) <= 9
    }
    jp_expected = {
        (int(r["round"]), int(r["rank"]), r["character"], str(r["points"]))
        for r in jp_history
        if int(r["round"]) <= 21
    }
    jp_actual = {
        (int(r["round"]), int(r["rank"]), r["entity_name"], str(r["points"]))
        for r in rankings
        if r["region"] == "jp" and r["category"] == "character"
        and int(r["round"]) <= 21
    }
    OUT.mkdir(parents=True, exist_ok=True)
    rankings_path = OUT / "rankings.csv"
    totals_path = OUT / "ballot_totals.csv"
    alignment_audit_path = OUT / "cn_alignment_audit.csv"
    advanced_rankings_path = OUT / "cn_legacy_advanced_rankings.csv.gz"
    advanced_questionnaire_path = OUT / "cn_legacy_advanced_questionnaire.csv"
    advanced_pairs_path = OUT / "cn_legacy_advanced_pairs.csv.gz"
    unified_advanced_rankings_path = OUT / "cn_advanced_rankings.csv.gz"
    unified_advanced_questionnaire_path = OUT / "cn_advanced_questionnaire.csv"
    unified_advanced_pairs_path = OUT / "cn_advanced_pairs.csv.gz"
    detail_demographics_path = OUT / "cn_legacy_detail_demographics.csv.gz"
    entity_inventory_path = OUT / "cn_entity_inventory.csv"
    entity_inventory = build_cn_entity_inventory(
        entity_index,
        cn_rows,
        advanced_rankings,
        detail_demographics,
    )
    inputs |= {
        ROOT / "data_raw" / "cn_official_legacy" / f"round_{round_number:02d}" / "processed" / "item_apis" / "index.csv"
        for round_number in range(1, 10)
        if (ROOT / "data_raw" / "cn_official_legacy" / f"round_{round_number:02d}" / "processed" / "item_apis" / "index.csv").exists()
    }
    write_csv(rankings_path, RANK_FIELDS, rankings)
    write_csv(totals_path, TOTAL_FIELDS, totals)
    write_csv(
        alignment_audit_path,
        [
            "region", "round", "category", "rank", "entity_id", "entity_key",
            "entity_name", "alignment_status", "source_path",
        ],
        cn_alignment_audit,
    )
    write_csv_gzip(advanced_rankings_path, advanced_rankings, ADVANCED_RANK_FIELDS)
    write_csv(advanced_questionnaire_path, ADVANCED_RANK_FIELDS, advanced_questionnaire)
    write_csv_gzip(advanced_pairs_path, advanced_pairs, ADVANCED_PAIR_FIELDS)
    write_csv_gzip(unified_advanced_rankings_path, unified_advanced_rankings, ADVANCED_RANK_FIELDS)
    write_csv(unified_advanced_questionnaire_path, ADVANCED_RANK_FIELDS, unified_advanced_questionnaire)
    write_csv_gzip(unified_advanced_pairs_path, unified_advanced_pairs, ADVANCED_PAIR_FIELDS)
    write_csv_gzip(detail_demographics_path, detail_demographics, CN_DETAIL_DEMOGRAPHIC_FIELDS)
    write_csv(entity_inventory_path, CN_ENTITY_INVENTORY_FIELDS, entity_inventory)
    (OUT / "README.md").write_text(build_readme(rankings, totals), encoding="utf-8")

    group_counts = Counter((r["region"], int(r["round"]), r["category"]) for r in rankings)
    duplicate_keys = [
        key for key, count in Counter((r["region"], int(r["round"]), r["category"], int(r["rank"]), r["entity_name"]) for r in rankings).items() if count > 1
    ]
    rank_checks: dict[str, Any] = {}
    for key in sorted(group_counts):
        region, round_number, category = key
        values = sorted({int(r["rank"]) for r in rankings if (r["region"], int(r["round"]), r["category"]) == key})
        rank_checks[f"{region}:{round_number}:{category}"] = {
            "rows": group_counts[key],
            "min_rank": values[0] if values else None,
            "max_rank": values[-1] if values else None,
            "distinct_ranks": len(values),
            "starts_at_one": bool(values and values[0] == 1),
            "gaps": [b for a, b in zip(values, values[1:]) if b > a + 1],
        }
    cn_entity_ids = _entity_id_lookup(entity_index)
    cn_rankings = [r for r in rankings if r.get("region") == "cn"]
    validations = {
        "regions_exact": sorted({r["region"] for r in rankings}) == ["cn", "jp"],
        "cn_rounds_1_to_11": sorted({int(r["round"]) for r in rankings if r["region"] == "cn"}) == list(range(1, 12)),
        # Backward-compatible alias retained for older validators; it now
        # reports the legacy subset rather than falsely claiming CN10/11 are
        # absent from the ordinary table.
        "cn_legacy_rounds_only_1_to_9": all(1 <= int(r["round"]) <= 9 for r in rankings if r["region"] == "cn" and r.get("source_type") != "cn_modern_official_graphql_base"),
        "jp_rounds_only_3_to_22": sorted({int(r["round"]) for r in rankings if r["region"] == "jp"}) == list(range(3, 23)),
        "cn10_cn11_present": all(any(r["region"] == "cn" and int(r["round"]) == rnd for r in rankings) for rnd in (10, 11)),
        "duplicate_stable_keys": len(duplicate_keys) == 0,
        "all_groups_start_at_rank_one": all(v["starts_at_one"] for v in rank_checks.values()),
        "cn_character_identity_score_match_metadata": cn_expected == cn_actual,
        "jp_character_identity_score_match_metadata": jp_expected == jp_actual,
        "cn_ranking_alignment_fields_present": all("entity_key" in r and "alignment_status" in r for r in cn_rankings),
        "cn_matched_entity_ids_exist": all(
            not r.get("entity_id") or r.get("alignment_status") not in {"matched_id", "matched_name"}
            or (int(r["round"]), r["category"], text(r["entity_id"])) in cn_entity_ids
            for r in cn_rankings
        ),
        "cn_advanced_early_rounds_official_not_offered": all(
            advanced_coverage.get(str(rnd), {}).get("status") == "official_not_offered" for rnd in range(1, 5)
        ),
        "cn_advanced_rounds_5_to_9_available": all(
            advanced_coverage.get(str(rnd), {}).get("status") == "available" for rnd in range(5, 10)
        ),
        "cn_detail_demographics_early_rounds_available": all(
            demographic_coverage.get(str(rnd), {}).get("status") == "available" for rnd in range(2, 5)
        ),
        "cn_advanced_excludes_cn10_cn11": not any(int(r.get("round", 0)) in (10, 11) for r in advanced_rankings + advanced_questionnaire + advanced_pairs),
        "cn_advanced_modern_rounds_available": all(
            modern_advanced_coverage.get(str(rnd), {}).get("status") == "available"
            for rnd in (10, 11)
        ),
        "cn_advanced_modern_categorical_conditions_complete": all(
            modern_advanced_coverage.get(str(rnd), {}).get("questionnaire_categorical_expected", 0)
            == modern_advanced_coverage.get(str(rnd), {}).get("questionnaire_categorical_available", -1)
            for rnd in (10, 11)
        ),
        "cn_advanced_modern_entity_conditions_complete": all(
            modern_advanced_coverage.get(str(rnd), {}).get("entity_condition_expected", 0)
            == modern_advanced_coverage.get(str(rnd), {}).get("entity_condition_available", -1)
            + modern_advanced_coverage.get(str(rnd), {})
            .get("entity_condition_counts", {})
            .get("status", {})
            .get("official_query_defect", 0)
            for rnd in (10, 11)
        ),
        "cn_advanced_modern_pairs_complete": all(
            modern_advanced_coverage.get(str(rnd), {}).get("pair_status") == "available_crawled"
            and modern_advanced_coverage.get(str(rnd), {}).get("pair_expected", 0)
            == modern_advanced_coverage.get(str(rnd), {}).get("pair_available", -1)
            and modern_advanced_coverage.get(str(rnd), {}).get("pair_cells_expected", 0)
            == modern_advanced_coverage.get(str(rnd), {}).get("pair_cells_available", -1)
            for rnd in (10, 11)
        ),
        "cn_advanced_atomic_families_normalized": all(
            row.get("condition_family") in {"questionnaire_answer", "entity_vote"}
            and row.get("condition_kind") in {"answer", "any", "first"}
            # Legacy questionnaire condition files predate the explicit
            # source_category field; their condition family already
            # identifies the source as questionnaire.  Modern rows carry the
            # explicit value.  Accept both representations while retaining
            # the strict target-category check below.
            and (
                row.get("source_category") in {"questionnaire", "character", "music"}
                or (row.get("condition_family") == "questionnaire_answer" and not row.get("source_category"))
            )
            and row.get("target_category") in {"character", "music", "cp"}
            for row in unified_advanced_rankings
        ),
    }
    manifest = {
        "schema_version": 2,
        "generated_at": utc_now(),
        "scope": {"cn_rounds": list(range(1, 12)), "jp_rounds": list(range(3, 23))},
        "excluded_scope": {},
        "outputs": {
            "rankings.csv": {"rows": len(rankings), "sha256": sha256(rankings_path)},
            "ballot_totals.csv": {"rows": len(totals), "sha256": sha256(totals_path)},
            "cn_alignment_audit.csv": {"rows": len(cn_alignment_audit), "sha256": sha256(alignment_audit_path)},
            "cn_legacy_advanced_rankings.csv.gz": {"rows": len(advanced_rankings), "sha256": sha256(advanced_rankings_path)},
            "cn_legacy_advanced_questionnaire.csv": {"rows": len(advanced_questionnaire), "sha256": sha256(advanced_questionnaire_path)},
            "cn_legacy_advanced_pairs.csv.gz": {"rows": len(advanced_pairs), "sha256": sha256(advanced_pairs_path)},
            "cn_legacy_detail_demographics.csv.gz": {"rows": len(detail_demographics), "sha256": sha256(detail_demographics_path)},
            "cn_entity_inventory.csv": {"rows": len(entity_inventory), "sha256": sha256(entity_inventory_path)},
            "cn_advanced_rankings.csv.gz": {"rows": len(unified_advanced_rankings), "sha256": sha256(unified_advanced_rankings_path)},
            "cn_advanced_questionnaire.csv": {"rows": len(unified_advanced_questionnaire), "sha256": sha256(unified_advanced_questionnaire_path)},
            "cn_advanced_pairs.csv.gz": {"rows": len(unified_advanced_pairs), "sha256": sha256(unified_advanced_pairs_path)},
            "README.md": {"sha256": sha256(OUT / "README.md")},
        },
        "input_files": [{"path": rel(p), "sha256": sha256(p)} for p in sorted(inputs) if p.exists()],
        "row_counts_by_region_round_category": {f"{k[0]}:{k[1]}:{k[2]}": v for k, v in sorted(group_counts.items())},
        "total_counts_by_region_round_category": {f"{r['region']}:{r['round']}:{r['category']}": 1 for r in totals},
        "rank_checks": rank_checks,
        "cn_alignment": {
            "rows": len([r for r in rankings if r.get("region") == "cn"]),
            "matched": sum(1 for r in rankings if r.get("region") == "cn" and r.get("alignment_status") in {"matched_id", "matched_name"}),
            "audit_rows": len(cn_alignment_audit),
            "audit_path": "cn_alignment_audit.csv",
        },
        "cn_advanced": {
            "scope": "CN5–11 official bounded advanced-search extracts; CN10–11 rebuild the legacy pair-cell surface with explicit Boolean intersection queries",
            "coverage": {**advanced_coverage, **modern_advanced_coverage},
            "required_rounds": list(range(5, 12)),
            "legacy_pair_matrix_rounds": list(range(5, 10)),
            "modern_pair_matrix_rounds": [10, 11],
            "coverage_contract": "scripts_pipeline/cn_advanced_contract.py",
            "outputs": {
                "all_condition_rankings": "cn_legacy_advanced_rankings.csv.gz",
                "questionnaire_conditions": "cn_legacy_advanced_questionnaire.csv",
                "questionnaire_pairs": "cn_legacy_advanced_pairs.csv.gz",
                "unified_condition_rankings": "cn_advanced_rankings.csv.gz",
                "unified_questionnaire_conditions": "cn_advanced_questionnaire.csv",
                "unified_questionnaire_pairs": "cn_advanced_pairs.csv.gz",
            },
        },
        "cn_detail_demographics": {
            "scope": "CN2–4 official detail-page vote-group marginals; CN1 has no per-entity demographic table",
            "coverage": demographic_coverage,
            "output": "cn_legacy_detail_demographics.csv.gz",
        },
        "cn_entity_inventory": {
            "scope": "CN1–9 official detail items joined to vote rows and available item APIs; CN10–11 ordinary rows are sourced from modern GraphQL base snapshots",
            "rows": len(entity_inventory),
            "output": "cn_entity_inventory.csv",
        },
        "validations": validations,
        "duplicate_stable_keys": duplicate_keys,
        "notes": [
            "JP points and CN weighted scores retain source scoring rules; no cross-round rescaling was applied.",
            "JP entity vote_count is the exact selection count derived from published position counts and the applicable 2/1 or 3/2/1 score rule; incomplete cases remain blank.",
            "Questionnaire distributions and game-clearance distributions are intentionally outside rankings.csv.",
            "Ties are retained; stable row key includes entity_name in addition to rank.",
        ],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    # Keep the portable application's base tables in sync with the canonical
    # dataset directory.  The analysis-data builder reads these files from
    # ``vote_explorer/data`` so a fresh rebuild (including JP22) is immediately
    # visible to both the source program and the packaged executable.
    app_data = ROOT / "vote_explorer" / "data"
    app_data.mkdir(parents=True, exist_ok=True)
    for filename in (
        "rankings.csv", "ballot_totals.csv", "cn_alignment_audit.csv",
        "cn_legacy_advanced_rankings.csv.gz", "cn_legacy_advanced_questionnaire.csv",
        "cn_legacy_advanced_pairs.csv.gz", "cn_legacy_detail_demographics.csv.gz",
        "cn_entity_inventory.csv", "README.md", "manifest.json",
        "cn_advanced_rankings.csv.gz", "cn_advanced_questionnaire.csv",
        "cn_advanced_pairs.csv.gz",
    ):
        shutil.copy2(OUT / filename, app_data / filename)
    print(json.dumps({"rankings": len(rankings), "ballot_totals": len(totals), "cn_alignment_audit": len(cn_alignment_audit), "cn_advanced_rankings": len(unified_advanced_rankings), "cn_advanced_questionnaire": len(unified_advanced_questionnaire), "cn_advanced_pairs": len(unified_advanced_pairs), "cn_detail_demographics": len(detail_demographics), "validations": validations}, ensure_ascii=False))


if __name__ == "__main__":
    main()
