"""Build reproducible community/poll alignment tables.

This script deliberately keeps platform metrics separate from poll metrics.  It
normalizes the public Bilibili search snapshot, adds candidate-pool-aware rank
percentiles to the Japanese and Chinese poll histories, and emits longitudinal
changes that can be joined to a separately sourced event timeline.
"""

from __future__ import annotations

import csv
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
METADATA = ROOT / "metadata"
OUT = ROOT / "analysis_results" / "community_poll_alignment"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def clean_number(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    multiplier = 1.0
    if text.endswith("万"):
        multiplier = 10_000.0
        text = text[:-1]
    elif text.endswith("亿"):
        multiplier = 100_000_000.0
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def integer_or_blank(value: float | None) -> int | str:
    if value is None or math.isnan(value):
        return ""
    return int(round(value))


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE).lower()


def normalize_bili_date(display: str, observed: date) -> tuple[str, str]:
    text = (display or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text, "day"
    if re.fullmatch(r"\d{2}-\d{2}", text):
        return f"{observed.year}-{text}", "day_inferred_current_year"
    if text == "昨天":
        return (observed - timedelta(days=1)).isoformat(), "day_relative"
    if text in {"今天", "刚刚"} or re.fullmatch(r"\d+小时前", text):
        return observed.isoformat(), "day_relative"
    return "", "unparsed"


DIRECT_POLL = re.compile(
    r"(?:東方|东方).{0,18}(?:人気|人气).{0,8}投票"
    r"|(?:人気|人气)投票.{0,18}(?:東方|东方)"
    r"|(?:#)?toho[_\s-]?vote\d*"
    r"|中文(?:東方|东方)(?:人気|人气)投票"
    r"|(?:東方|东方).{0,10}(?:人气王|人気王|人气排名|人気ランキング)"
    r"|历年阻止灵梦拿到人气王",
    re.IGNORECASE,
)


def bili_category(title: str) -> str:
    if re.search(r"应援|應援|支援|拉票|投.{0,5}一票|投给|投給|投票开始|投票開始|怎么投|如何投|投票教程|倒计时", title):
        return "support_or_mobilization"
    if re.search(r"规则|規則|机制|機制|刷票|作弊|异常|異常|争议|爭議|问卷|問卷|统计方法|標準化|标准化", title):
        return "rules_or_discussion"
    if re.search(r"历届|歷屆|历代|歷代|历年|歷年|走势|走勢|趋势|趨勢|变化|變化|折线|折線|统计|統計|分析|解读|解讀|比较|比較|十年", title):
        return "longitudinal_analysis"
    if re.search(r"MMD|手书|手書|二创|二創|梗|庆祝|慶祝|纪念|紀念|动画|動畫|再現|再现|会议|会議|反应|反應", title, re.IGNORECASE):
        return "meme_or_derivative"
    if re.search(r"结果|結果|速报|速報|排名|排行|名次|TOP\s*\d+|人妖部门|人妖部門|音乐部门|音樂部門|组合部门|組合部門|第.?位|冠军|冠軍|得票|一位|1位", title, re.IGNORECASE):
        return "result_or_ranking"
    return "other_direct_poll_item"


def bili_region(title: str) -> str:
    if re.search(r"中文|国区|國區|国内|國內", title):
        return "cn_poll"
    if re.search(r"日区|日區|全人類|人妖部|東方Project人気投票|东方Project人气投票|東方人気投票", title, re.IGNORECASE):
        return "jp_poll"
    return "region_unspecified"


def mentioned_rounds(title: str) -> str:
    values = []
    for match in re.finditer(r"第\s*(\d{1,2})\s*(?:回|届|屆)", title):
        value = int(match.group(1))
        if value not in values:
            values.append(value)
    return ";".join(map(str, values))


CN_ROUND_DIGITS = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def expanded_round_mentions(title: str, numeric: str = "") -> str:
    """Expand explicit round ranges in old video titles for audit only.

    This is deliberately conservative: a bare year or a generic “popularity
    vote” title is not assigned to a round.  Range expansion is used only in
    the Niconico source audit and never replaces the source title.
    """
    rounds: set[int] = set()
    for token in (numeric or "").split(";"):
        if token.isdigit():
            rounds.add(int(token))
    text = title or ""
    for match in re.finditer(r"第\s*([一二三四五六七八九十\d]{1,3})\s*回", text):
        token = match.group(1)
        if token.isdigit():
            rounds.add(int(token))
        elif token == "十":
            rounds.add(10)
        elif len(token) == 2 and token[0] == "十" and token[1] in CN_ROUND_DIGITS:
            rounds.add(10 + CN_ROUND_DIGITS[token[1]])
        elif len(token) == 2 and token[1] == "十" and token[0] in CN_ROUND_DIGITS:
            rounds.add(CN_ROUND_DIGITS[token[0]] * 10)
        elif token in CN_ROUND_DIGITS:
            rounds.add(CN_ROUND_DIGITS[token])
    range_match = re.search(
        r"第\s*([一二三四五六七八九十\d]{1,3})\s*回\s*[～〜~\-—至]\s*第\s*([一二三四五六七八九十\d]{1,3})\s*回",
        text,
    )
    if range_match:
        def as_int(token: str) -> int | None:
            if token.isdigit():
                return int(token)
            if token in CN_ROUND_DIGITS:
                return CN_ROUND_DIGITS[token]
            return None
        start, end = as_int(range_match.group(1)), as_int(range_match.group(2))
        if start is not None and end is not None and 0 < end - start <= 30:
            rounds.update(range(min(start, end), max(start, end) + 1))
    return ";".join(str(value) for value in sorted(rounds))


CURATED_ALIASES = {
    "阿求": "稗田阿求",
    "夜雀": "米斯蒂娅·萝蕾拉",
    "米斯蒂娅": "米斯蒂娅·萝蕾拉",
    "恋恋": "古明地恋",
    "芙兰": "芙兰朵露·斯卡蕾特",
    "琪露诺": "琪露诺",
    "易者": "易者",
    "正邪": "鬼人正邪",
    "哆来咪": "哆来咪·苏伊特",
    "哆来米": "哆来咪·苏伊特",
    "华扇": "茨木华扇",
    "永琳": "八意永琳",
    "尤魔": "饕餮尤魔",
    "瑞灵": "宫出口瑞灵",
    "瑞霊": "宫出口瑞灵",
    "丰姬": "绵月丰姬",
    "豊姫": "绵月丰姬",
    "神绮": "神绮",
    "神綺": "神绮",
    "莉格露": "莉格露·奈特巴格",
    "响子": "幽谷响子",
    "響子": "幽谷响子",
    "娜兹玲": "娜兹玲",
    "纳兹琳": "娜兹玲",
    "古明地觉": "古明地觉",
    "映姬": "四季映姬·夜摩仙那度",
    "四季映姬": "四季映姬·夜摩仙那度",
    "封兽鵺": "封兽鵺",
    "鵺": "封兽鵺",
    "莲子": "宇佐见莲子",
    "妹红": "藤原妹红",
    "帕露西": "水桥帕露西",
    "神玉": "神玉",
    "露易兹": "露易兹",
    "幽玄魔眼": "幽幻魔眼",
    "幽幻魔眼": "幽幻魔眼",
    "菊理": "菊理",
}


# Chinese-community forms that can safely be joined to the canonical
# ``fun.xlsx`` translation.  Nicknames are kept separately from translation
# variants in the audit output; ambiguous collective labels are intentionally
# not mapped to a single character.
CN_TRANSLATION_ALIASES = {
    "灵梦": ("博丽灵梦", "nickname_or_short_form"),
    "靈夢": ("博丽灵梦", "traditional_variant"),
    "魔理沙": ("雾雨魔理沙", "nickname_or_short_form"),
    "咲夜": ("十六夜咲夜", "nickname_or_short_form"),
    "PAD长": ("十六夜咲夜", "derivative_nickname"),
    "女仆长": ("十六夜咲夜", "derivative_nickname"),
    "大小姐": ("蕾米莉亚·斯卡蕾特", "derivative_nickname"),
    "蕾米": ("蕾米莉亚·斯卡蕾特", "nickname_or_short_form"),
    "蕾米莉亚": ("蕾米莉亚·斯卡蕾特", "nickname_or_short_form"),
    "二小姐": ("芙兰朵露·斯卡蕾特", "derivative_nickname"),
    "芙兰": ("芙兰朵露·斯卡蕾特", "nickname_or_short_form"),
    "帕秋莉": ("帕秋莉·诺蕾姬", "nickname_or_short_form"),
    "帕琪": ("帕秋莉·诺蕾姬", "nickname_or_short_form"),
    "姆Q": ("帕秋莉·诺蕾姬", "derivative_nickname"),
    "帕秋莉·诺雷姬": ("帕秋莉·诺蕾姬", "legacy_translation_variant"),
    "芙兰朵露·斯卡雷特": ("芙兰朵露·斯卡蕾特", "legacy_translation_variant"),
    "蕾米莉亚·斯卡雷特": ("蕾米莉亚·斯卡蕾特", "legacy_translation_variant"),
    "爱丽丝·玛格特罗伊德": ("爱丽丝·玛格特洛依德", "legacy_translation_variant"),
    "中国": ("红美铃", "derivative_nickname"),
    "美铃": ("红美铃", "nickname_or_short_form"),
    "妖梦": ("魂魄妖梦", "nickname_or_short_form"),
    "幽幽子": ("西行寺幽幽子", "nickname_or_short_form"),
    "紫妈": ("八云紫", "derivative_nickname"),
    "八云紫": ("八云紫", "nickname_or_short_form"),
    "蓝妈": ("八云蓝", "derivative_nickname"),
    "八云蓝": ("八云蓝", "nickname_or_short_form"),
    "文": ("射命丸文", "nickname_or_short_form"),
    "射命丸": ("射命丸文", "nickname_or_short_form"),
    "文文": ("射命丸文", "derivative_nickname"),
    "早苗": ("东风谷早苗", "nickname_or_short_form"),
    "琪露诺": ("琪露诺", "canonical_short_form"),
    "⑨": ("琪露诺", "derivative_nickname"),
    "笨蛋": ("琪露诺", "derivative_nickname"),
    "阿求": ("稗田阿求", "nickname_or_short_form"),
    "慧音": ("上白泽慧音", "nickname_or_short_form"),
    "妹红": ("藤原妹红", "nickname_or_short_form"),
    "辉夜": ("蓬莱山辉夜", "nickname_or_short_form"),
    "永琳": ("八意永琳", "nickname_or_short_form"),
    "铃仙": ("铃仙·优昙华院·因幡", "nickname_or_short_form"),
    "恋恋": ("古明地恋", "nickname_or_short_form"),
    "觉大人": ("古明地觉", "derivative_nickname"),
    "觉酱": ("古明地觉", "derivative_nickname"),
    "小五": ("古明地觉", "derivative_nickname"),
    "古明地小五": ("古明地觉", "derivative_nickname"),
    "正邪": ("鬼人正邪", "nickname_or_short_form"),
    "小碗": ("少名针妙丸", "derivative_nickname"),
    "天子": ("比那名居天子", "nickname_or_short_form"),
    "紫苑": ("依神紫苑", "nickname_or_short_form"),
    "女苑": ("依神女苑", "nickname_or_short_form"),
    "隐歧奈": ("摩多罗隐岐奈", "legacy_translation_variant"),
    "神子": ("丰聪耳神子", "nickname_or_short_form"),
    "神妈": ("八坂神奈子", "derivative_nickname"),
    "莲妈": ("圣白莲", "derivative_nickname"),
    "山田": ("四季映姬·夜摩仙那度", "derivative_nickname"),
    "大酱": ("大妖精", "derivative_nickname"),
    "华扇": ("茨木华扇", "nickname_or_short_form"),
    "丰姬": ("绵月丰姬", "nickname_or_short_form"),
    "依姬": ("绵月依姬", "nickname_or_short_form"),
    "梅莉": ("玛艾露贝莉·赫恩", "nickname_or_short_form"),
    "玛艾露贝莉·赫恩（梅莉）": ("玛艾露贝莉·赫恩", "poll_label_variant"),
    "玛艾露贝莉·赫恩（梅莉）1": ("玛艾露贝莉·赫恩", "poll_label_artifact"),
    "哆来米": ("哆来咪·苏伊特", "simplified_variant"),
    "哆来咪": ("哆来咪·苏伊特", "canonical_short_form"),
    "幽玄魔眼": ("幽幻魔眼", "legacy_translation_variant"),
    "蕾迪·霍瓦特洛克": ("蕾蒂·霍瓦特洛克", "legacy_translation_variant"),
    "蕾蒂·怀特洛可": ("蕾蒂·霍瓦特洛克", "legacy_translation_variant"),
    "露娜·切露德": ("露娜切露德", "legacy_translation_variant"),
    "莉莉霍瓦特": ("莉莉霍瓦特（莉莉白）", "short_form"),
    "因幡帝": ("因幡天为（因幡帝）", "legacy_translation_variant"),
    "占卜师（易者）": ("易者", "poll_label_variant"),
    "大地精": ("地精", "legacy_translation_variant"),
    "地精2": ("地精", "poll_label_artifact"),
    "雷兽（务光）": ("华扇的宠物（久米、竿打、雷兽（务光）、彭祖、人面犬等）", "collective_label_component"),
    "雷兽（务光）4": ("华扇的宠物（久米、竿打、雷兽（务光）、彭祖、人面犬等）", "poll_label_artifact"),
    "人偶（含上海人偶、哥利亚人偶）": ("爱丽丝的人偶（上海、蓬莱、大江户等）", "collective_label_variant"),
    "人偶（含上海人偶、哥利亚人偶）2": ("爱丽丝的人偶（上海、蓬莱、大江户等）", "poll_label_artifact"),
    "人形（含上海人形、哥利亚人形）": ("爱丽丝的人偶（上海、蓬莱、大江户等）", "collective_label_variant"),
    "Label子": ("蓬莱人形碟面的少女（Label子）", "nickname_or_short_form"),
    "夹克子": ("蓬莱人形封面的少女（夹克子）", "nickname_or_short_form"),
    "道神训子": ("道神驯子", "legacy_translation_variant"),
    "妖精": ("妖精（女仆妖精、向日葵妖精等）", "collective_label_short_form"),
    "桑妮·米尔克": ("桑尼米尔克", "legacy_translation_variant"),
    "爱丽丝的人偶们": ("爱丽丝的人偶（上海、蓬莱、大江户等）", "collective_label_short_form"),
    "影华扇": ("影华扇（断善修恶的怪臂 - 茨木童子之臂）", "short_form"),
    "萨丽艾尔": ("萨丽爱尔", "legacy_translation_variant"),
    "爱莲·蓬松头·奥瑞斯": ("爱莲", "legacy_translation_variant"),
    "伊莉丝": ("依莉斯", "legacy_translation_variant"),
    "非想天则": ("核热造神非想天则", "short_form"),
    "坂田合欢乃": ("坂田合欢", "poll_label_artifact"),
    "抗抑郁药大叔": ("抗抑郁药大叔（长相酷似周杰伦的村民）", "short_form"),
    "长相酷似周杰伦的参拜客": ("抗抑郁药大叔（长相酷似周杰伦的村民）", "descriptive_variant"),
    "瑞江浦岛子": ("水江浦岛子（瑞江浦岛子）", "legacy_translation_variant"),
    "酒吧老板": ("盐家老板", "descriptive_variant"),
}

# High-confidence reference-name variants from the THBWiki character list.
# Unlike the nickname field, these can be used to normalize an observed CN
# poll label when the same character is present in ``fun.xlsx``.  They are
# merged at build time so the project retains its user-supplied canonical CN
# names while preserving the public reference form and URL for audit.
THBWIKI_REFERENCE_ALIASES = METADATA / "thbwiki_character_alias_candidates_cn.csv"


def character_aliases() -> list[tuple[str, str]]:
    aliases: dict[str, str] = dict(CURATED_ALIASES)
    aliases.update({alias: target for alias, (target, _kind) in CN_TRANSLATION_ALIASES.items() if len(alias) >= 2})
    for row in read_csv(METADATA / "character_name_crosswalk.csv"):
        cn = row["character_cn"].strip()
        jp = row["character_jp"].strip()
        for alias in {cn, jp, normalize_name(cn), normalize_name(jp)}:
            if len(alias) >= 2:
                aliases.setdefault(alias, cn)
    return sorted(aliases.items(), key=lambda item: (-len(item[0]), item[0]))


def find_character_mentions(title: str, aliases: list[tuple[str, str]]) -> list[str]:
    normalized = normalize_name(title)
    found: list[str] = []
    for alias, canonical in aliases:
        if (alias in title or normalize_name(alias) in normalized) and canonical not in found:
            found.append(canonical)
    return found


def canonicalize_cn_name(value: str, canonical_names: dict[str, str]) -> tuple[str, str]:
    """Return (canonical Chinese name, mapping status) for a poll label."""

    raw = (value or "").strip()
    if not raw:
        return "", "blank"
    normalized = normalize_name(raw)
    if normalized in canonical_names:
        return canonical_names[normalized], "exact_fun_mapping"
    explicit = CN_TRANSLATION_ALIASES.get(raw)
    if explicit:
        target, _kind = explicit
        if normalize_name(target) in canonical_names:
            return canonical_names[normalize_name(target)], "explicit_alias"
        return target, "explicit_alias_target_not_in_fun_mapping"
    # The CN workbook occasionally appends a digit while disambiguating a
    # repeated collective label.  Strip it only when the base form is known.
    base = re.sub(r"[1-9]+$", "", raw)
    if base != raw and normalize_name(base) in canonical_names:
        return canonical_names[normalize_name(base)], "poll_label_suffix_artifact"
    # Parenthetical short names such as “梅莉” are common in CN tables.
    base = re.sub(r"（[^）]*）", "", raw).strip()
    if base != raw and normalize_name(base) in canonical_names:
        return canonical_names[normalize_name(base)], "parenthetical_variant"
    if "/" in raw or "含" in raw or "没有名称" in raw or "无名" in raw:
        return raw, "collective_or_unnamed_unresolved"
    return raw, "unmapped_manual_review"


def build_translation_alias_tables() -> dict[str, str]:
    """Materialize the fun.xlsx-based CN alias audit and unresolved conflicts."""

    crosswalk = read_csv(METADATA / "character_name_crosswalk.csv")
    canonical_names = {
        normalize_name(row.get("character_cn", "")): row.get("character_cn", "")
        for row in crosswalk
        if row.get("character_cn", "").strip()
    }
    cn_rows = read_csv(METADATA / "cn_vote_history_all_characters.csv")
    observed: defaultdict[str, dict] = defaultdict(
        lambda: {"rounds": set(), "ranks": [], "source_forms": set()}
    )
    for row in cn_rows:
        raw = row.get("character_cn", "").strip()
        if not raw:
            continue
        item = observed[raw]
        item["rounds"].add(row.get("round", ""))
        item["ranks"].append(row.get("rank", ""))
        item["source_forms"].add(row.get("source_sheet", "TouhouVote_cn.xlsx"))

    aliases: dict[str, str] = {}
    output: list[dict] = []
    for row in crosswalk:
        canonical = row.get("character_cn", "").strip()
        if not canonical:
            continue
        aliases[normalize_name(canonical)] = canonical
        output.append(
            {
                "alias_cn": canonical,
                "canonical_cn": canonical,
                "alias_type": "primary_fun_xlsx_mapping",
                "mapping_status": "verified_fun_xlsx",
                "source": row.get("source_path", "fun.xlsx"),
                "observed_rounds": "",
                "observed_forms": "",
                "confidence": "high",
                "mapping_note": "fun.xlsx译名列/character_name_crosswalk主映射；不等于官方中文译名。",
            }
        )

    for alias, (target, kind) in CN_TRANSLATION_ALIASES.items():
        canonical, status = canonicalize_cn_name(target, canonical_names)
        aliases[normalize_name(alias)] = canonical
        output.append(
            {
                "alias_cn": alias,
                "canonical_cn": canonical,
                "alias_type": kind,
                "mapping_status": status,
                "source": "curated_cn_translation_aliases",
                "observed_rounds": ";".join(sorted(observed.get(alias, {}).get("rounds", set()), key=lambda x: int(x) if str(x).isdigit() else 999)),
                "observed_forms": alias,
                "confidence": "medium" if "nickname" in kind or "derivative" in kind else "high",
                "mapping_note": "仅用于中文投票标签对齐；昵称/二设称呼不应解释为一设名称。",
            }
        )

    if THBWIKI_REFERENCE_ALIASES.exists():
        for item in read_csv(THBWIKI_REFERENCE_ALIASES):
            if item.get("alias_type") != "thbwiki_cn_reference_name":
                continue
            if item.get("mapping_status") != "matched_fun_by_jp_or_cn":
                continue
            alias = item.get("alias_cn", "").strip()
            target = item.get("canonical_cn", "").strip()
            if not alias or not target:
                continue
            canonical, status = canonicalize_cn_name(target, canonical_names)
            aliases[normalize_name(alias)] = canonical
            output.append(
                {
                    "alias_cn": alias,
                    "canonical_cn": canonical,
                    "alias_type": "thbwiki_cn_reference_name",
                    "mapping_status": status,
                    "source": item.get("source_url", "https://thbwiki.cc/官方角色列表"),
                    "observed_rounds": ";".join(sorted(observed.get(alias, {}).get("rounds", set()), key=lambda x: int(x) if str(x).isdigit() else 999)),
                    "observed_forms": alias,
                    "confidence": "high",
                    "mapping_note": "THBWiki角色表中文词条名对齐至fun.xlsx项目规范名；THBWiki明确声明其收录标准不代表官方意见。",
                }
            )

    conflict_rows: list[dict] = []
    for raw, item in sorted(observed.items()):
        canonical, status = canonicalize_cn_name(raw, canonical_names)
        if status == "exact_fun_mapping":
            continue
        if canonical and status in {"explicit_alias", "poll_label_suffix_artifact", "parenthetical_variant"}:
            aliases[normalize_name(raw)] = canonical
            output.append(
                {
                    "alias_cn": raw,
                    "canonical_cn": canonical,
                    "alias_type": "observed_cn_vote_form",
                    "mapping_status": status,
                    "source": "cn_vote_history_all_characters.csv",
                    "observed_rounds": ";".join(sorted(item["rounds"], key=lambda x: int(x) if str(x).isdigit() else 999)),
                    "observed_forms": raw,
                    "confidence": "medium",
                    "mapping_note": "历史国区表中实际出现的译名/后缀形式；已归一化但保留原始名。",
                }
            )
            continue
        conflict_rows.append(
            {
                "raw_cn_label": raw,
                "mapping_status": status,
                "suggested_canonical_cn": "",
                "observed_rounds": ";".join(sorted(item["rounds"], key=lambda x: int(x) if str(x).isdigit() else 999)),
                "rank_examples": ";".join(item["ranks"][:8]),
                "resolution_note": "组合候选/无名角色/新作描述或未在fun.xlsx映射中；禁止自动拆成单角色。",
            }
        )

    output.sort(key=lambda row: (row["canonical_cn"], row["alias_cn"], row["alias_type"]))
    write_csv(
        METADATA / "character_translation_aliases_cn.csv",
        output,
        ["alias_cn", "canonical_cn", "alias_type", "mapping_status", "source", "observed_rounds", "observed_forms", "confidence", "mapping_note"],
    )
    write_csv(
        METADATA / "character_translation_mapping_conflicts.csv",
        conflict_rows,
        ["raw_cn_label", "mapping_status", "suggested_canonical_cn", "observed_rounds", "rank_examples", "resolution_note"],
    )
    return aliases


def build_bilibili_tables() -> list[dict]:
    raw_path = METADATA / "bilibili_popularity_vote_search_raw.json"
    with raw_path.open("r", encoding="utf-8") as handle:
        source = json.load(handle)

    observed = date.fromisoformat(source["observed_at"])
    aliases = character_aliases()
    unique: dict[str, dict] = {}
    duplicate_pages: defaultdict[str, list[int]] = defaultdict(list)
    for row in source["records"]:
        bv = row.get("bv", "")
        if not bv:
            continue
        duplicate_pages[bv].append(int(row["page"]))
        unique.setdefault(bv, row)

    rows: list[dict] = []
    for bv, row in unique.items():
        title = re.sub(r"\s+", " ", row.get("title", "")).strip()
        if not DIRECT_POLL.search(title):
            continue
        author = row.get("author", "").strip()
        date_display = row.get("date_display", "").strip()
        published_date, precision = normalize_bili_date(date_display, observed)
        # Some older/lazy-loaded cards collapse their visible text into one line
        # after a transient feedback overlay.  Recover only the unambiguous tail
        # (author and displayed date); leave ambiguous metric digits blank.
        if not published_date:
            tail = row.get("raw_text", "")
            if title and title in tail:
                tail = tail.rsplit(title, 1)[-1]
            tail_match = re.search(
                r"(?P<author>.*?)\s*·\s*(?P<date>\d{4}-\d{2}-\d{2}|\d{2}-\d{2}|昨天|今天|刚刚|\d+小时前)\s*$",
                tail,
            )
            if tail_match:
                author = author or tail_match.group("author").strip()
                date_display = tail_match.group("date")
                published_date, precision = normalize_bili_date(date_display, observed)
        view_display = row.get("view_display", "").strip()
        danmaku_display = row.get("danmaku_display", "").strip()
        duration_display = row.get("duration_display", "").strip()
        if not re.fullmatch(r"\d+(?:\.\d+)?(?:万|亿)?", view_display):
            view_display = ""
        if not re.fullmatch(r"\d+(?:\.\d+)?(?:万|亿)?", danmaku_display):
            danmaku_display = ""
        if not re.fullmatch(r"(?:\d{1,2}:)?\d{1,2}:\d{2}", duration_display):
            duration_display = ""
        mentions = find_character_mentions(title, aliases)
        rows.append(
            {
                "bv": bv,
                "url": row.get("url", ""),
                "title": title,
                "author": author,
                "published_date_display": date_display,
                "published_date": published_date,
                "date_precision": precision,
                "view_display": view_display,
                "view_snapshot": integer_or_blank(clean_number(view_display)),
                "danmaku_display": danmaku_display,
                "danmaku_snapshot": integer_or_blank(clean_number(danmaku_display)),
                "duration": duration_display,
                "content_category": bili_category(title),
                "poll_region_alignment": bili_region(title),
                "mentioned_rounds": mentioned_rounds(title),
                "character_mentions_cn": ";".join(mentions),
                "search_query": source["query"],
                "first_result_page": min(duplicate_pages[bv]),
                "all_result_pages": ";".join(map(str, sorted(set(duplicate_pages[bv])))),
                "observed_at": source["observed_at"],
                "coverage_note": "34个公开搜索结果页逐页采集；按BV去重；相关性由题名规则筛选，并非全站穷尽。",
            }
        )
    rows.sort(key=lambda item: (item["published_date"] or "9999", item["bv"]))
    fields = list(rows[0]) if rows else []
    write_csv(METADATA / "bilibili_popularity_vote_videos.csv", rows, fields)

    audits = source["audits"]
    for audit in audits:
        audit["observed_at"] = source["observed_at"]
    write_csv(
        METADATA / "bilibili_search_page_audit.csv",
        audits,
        ["page", "url", "rendered_cards", "video_cards", "first_bv", "observed_at"],
    )

    by_year: Counter[tuple[str, str, str]] = Counter()
    for row in rows:
        year = row["published_date"][:4] if row["published_date"] else "unknown"
        by_year[(year, row["content_category"], row["poll_region_alignment"])] += 1
    summary = [
        {"year": year, "content_category": category, "poll_region_alignment": region, "video_count": count}
        for (year, category, region), count in sorted(by_year.items())
    ]
    write_csv(
        OUT / "bilibili_video_summary_by_year.csv",
        summary,
        ["year", "content_category", "poll_region_alignment", "video_count"],
    )

    mention_counter: Counter[tuple[str, str]] = Counter()
    for row in rows:
        for character in filter(None, row["character_mentions_cn"].split(";")):
            mention_counter[(character, row["poll_region_alignment"])] += 1
    mention_rows = [
        {
            "character_cn": character,
            "poll_region_alignment": region,
            "title_mention_video_count": count,
            "interpretation_limit": "仅为本查询题名命中数，不是角色全站作品量、支持率或投票转化量。",
        }
        for (character, region), count in mention_counter.most_common()
    ]
    write_csv(
        OUT / "bilibili_character_title_mentions.csv",
        mention_rows,
        ["character_cn", "poll_region_alignment", "title_mention_video_count", "interpretation_limit"],
    )
    return rows


def parse_supplemental_card(row: dict, observed: date, aliases: list[tuple[str, str]]) -> dict:
    """Conservatively normalize one first-page Bilibili character-search card."""

    title = re.sub(r"\s+", " ", row.get("title", "")).strip()
    raw_text = row.get("raw_text", "")
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    view_display = ""
    danmaku_display = ""
    duration = ""
    if len(lines) >= 3:
        if re.fullmatch(r"\d+(?:\.\d+)?(?:万|亿)?", lines[0]):
            view_display = lines[0]
        if re.fullmatch(r"\d+(?:\.\d+)?(?:万|亿)?", lines[1]):
            danmaku_display = lines[1]
        if re.fullmatch(r"(?:\d{1,2}:)?\d{1,2}:\d{2}", lines[2]):
            duration = lines[2]

    author = ""
    date_display = ""
    tail = raw_text.rsplit(title, 1)[-1] if title and title in raw_text else raw_text
    tail_match = re.search(
        r"(?P<author>[^·\n]{1,100})\s*·\s*(?P<date>\d{4}-\d{2}-\d{2}|\d{2}-\d{2}|昨天|今天|刚刚|\d+小时前)\s*$",
        tail,
    )
    if tail_match:
        author = tail_match.group("author").strip()
        date_display = tail_match.group("date")
    published_date, precision = normalize_bili_date(date_display, observed)

    query = row.get("query", "").strip()
    mentions = find_character_mentions(f"{query} {title}", aliases)
    region = bili_region(title) if DIRECT_POLL.search(title) else "cn_platform_context"
    if "中文人气投票" in query or "中文东方人气投票" in query:
        region = "cn_poll_query_context"
    content_category = bili_category(title) if DIRECT_POLL.search(title) else (
        "game_or_derivative_exposure" if "夜雀食堂" in query or "夜雀食堂" in title else "character_search_candidate"
    )
    return {
        "query": query,
        "page": row.get("page", ""),
        "position": row.get("position", ""),
        "bv": row.get("bv", ""),
        "url": row.get("url", ""),
        "title": title,
        "author": author,
        "published_date_display": date_display,
        "published_date": published_date,
        "date_precision": precision,
        "view_display": view_display,
        "view_snapshot": integer_or_blank(clean_number(view_display)),
        "danmaku_display": danmaku_display,
        "danmaku_snapshot": integer_or_blank(clean_number(danmaku_display)),
        "duration": duration,
        "content_category": content_category,
        "poll_region_alignment": region,
        "character_mentions_cn": ";".join(mentions),
        "observed_at": row.get("observed_at", observed.isoformat()),
        "coverage_note": "角色查询公开首屏候选；包含搜索噪声，不是全站作品量。只有题名与发布时间可作发现线索。",
    }


def build_bilibili_supplemental_table() -> list[dict]:
    raw_path = METADATA / "bilibili_character_search_supplemental_raw.json"
    if not raw_path.exists():
        return []
    with raw_path.open("r", encoding="utf-8") as handle:
        source = json.load(handle)
    observed = date.fromisoformat(source["observed_at"])
    aliases = character_aliases()
    seen: set[tuple[str, str]] = set()
    rows = []
    for raw in source.get("records", []):
        key = (raw.get("query", ""), raw.get("bv", ""))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        rows.append(parse_supplemental_card(raw, observed, aliases))
    # Additional candidates recovered through the logged-in search UI are kept
    # in a small append-only CSV so the large raw JSON crawl is not rewritten.
    extra_path = METADATA / "bilibili_character_search_additional.csv"
    if extra_path.exists():
        for extra in read_csv(extra_path):
            key = (extra.get("query", ""), extra.get("bv", ""))
            if not key[1] or key in seen:
                continue
            seen.add(key)
            rows.append(extra)
    rows.sort(key=lambda item: (item["query"], int(item["position"] or 999), item["bv"]))
    fields = [
        "query", "page", "position", "bv", "url", "title", "author",
        "published_date_display", "published_date", "date_precision",
        "view_display", "view_snapshot", "danmaku_display", "danmaku_snapshot",
        "duration", "content_category", "poll_region_alignment",
        "character_mentions_cn", "observed_at", "coverage_note",
    ]
    write_csv(METADATA / "bilibili_character_search_supplemental.csv", rows, fields)
    return rows


def normalize_tieba_round21_fulltext(cn_aliases: dict[str, str]) -> list[dict]:
    """Normalize the PC-web rank thread without inflating comment counts.

    The thread has three distinct record types: 163 rank headings, 252 visible
    nested replies and one conclusion.  Only nested replies are qualitative
    comment samples.  The displayed total reply count (535) remains a separate
    thread-level metric and is never added to the 416 captured text records.
    """

    path = METADATA / "tieba_round21_rank_evaluation_fulltext.csv"
    if not path.exists():
        return []
    source_rows = read_csv(path)
    rows: list[dict] = []
    for source in source_rows:
        raw_name = source.get("character_cn_raw", "").strip()
        canonical = cn_aliases.get(normalize_name(raw_name), raw_name)
        status = "alias_table" if canonical != raw_name else ("canonical_or_source_label" if canonical else "not_character_record")
        sample_type = source.get("sample_type", "")
        rows.append(
            {
                **source,
                "platform": "Tieba",
                "platform_region": "CN",
                "character_cn": canonical,
                "normalization_status": status,
                "poll_region_alignment": "jp",
                "related_round": "21",
                "round_status": "complete",
                "diffusion_class": "cross_region_observed",
                "event_phase": "post_result_interpretation",
                "counts_as_rank_heading_coverage": "yes" if sample_type == "rank_heading" else "no",
                "counts_as_qualitative_comment": "yes" if sample_type == "nested_reply" else "no",
                "normalization_note": (
                    "中文贴吧对日区第21回结果的赛后解释；PC网页按分页并逐页虚拟滚动采集。"
                    "标题、楼中楼与帖子总回复数分列，不能相加或当作票数。"
                ),
            }
        )
    fields = list(rows[0]) if rows else []
    if rows:
        write_csv(METADATA / "tieba_round21_rank_evaluation_normalized.csv", rows, fields)

        types = Counter(row.get("sample_type", "") for row in rows)
        rank_characters = {
            normalize_name(row.get("character_cn", ""))
            for row in rows
            if row.get("sample_type") == "rank_heading" and row.get("character_cn")
        }
        reply_characters = {
            normalize_name(row.get("character_cn", ""))
            for row in rows
            if row.get("sample_type") == "nested_reply" and row.get("character_cn")
        }
        summary = [{
            "source_url": rows[0].get("source_url", ""),
            "thread_title": rows[0].get("thread_title", ""),
            "related_round": "21",
            "poll_region_alignment": "jp",
            "platform_region": "CN",
            "event_phase": "post_result_interpretation",
            "displayed_total_reply_count": rows[0].get("total_reply_count", ""),
            "captured_pc_web_text_record_count": len(rows),
            "rank_heading_record_count": types.get("rank_heading", 0),
            "nested_reply_record_count": types.get("nested_reply", 0),
            "thread_conclusion_record_count": types.get("thread_conclusion", 0),
            "rank_heading_character_count": len(rank_characters),
            "nested_reply_character_count": len(reply_characters),
            "observed_at": rows[0].get("observed_at", "2026-08-24"),
            "metric_note": "535、416、163与252分别是帖子显示回复总数、采集文本记录、角色标题和可见楼中楼；单位不同，禁止相加。",
        }]
        write_csv(OUT / "tieba_round21_sampling_summary.csv", summary, list(summary[0]))
    return rows


def normalize_tieba_round14_fulltext() -> list[dict]:
    """Normalize the contemporaneous round-14 Twitter-ballot discussion.

    The source post displayed a second-day Twitter ballot screenshot.  Its
    top 24 is manually verified in a separate table; this function tags only
    PC-web reply text as qualitative evidence.  The displayed 177 total
    replies remain separate from the 99 captured text records.
    """

    path = METADATA / "tieba_round14_twitter_ballot_stats_fulltext.csv"
    if not path.exists():
        return []
    aliases = character_aliases()
    rows: list[dict] = []
    for source in read_csv(path):
        mentions = find_character_mentions(source.get("raw_text", ""), aliases)
        rows.append({
            **source,
            "platform": "Tieba",
            "platform_region": "CN",
            "character_cn": ";".join(mentions),
            "poll_region_alignment": "jp",
            "related_round": "14",
            "round_status": "complete",
            "diffusion_class": "cross_region_observed",
            "event_phase": "during_vote_trend_interpretation",
            "counts_as_rank_heading_coverage": "no",
            "counts_as_qualitative_comment": "yes",
            "normalization_note": (
                "中文贴吧在日区第14回投票期讨论第二日Twitter晒票统计；"
                "图片Top24另表手工复核，正文/楼中楼只作质性评论，不等于官方票数。"
            ),
        })
    if rows:
        write_csv(METADATA / "tieba_round14_twitter_ballot_stats_normalized.csv", rows, list(rows[0]))
        summary = [{
            "source_url": rows[0].get("source_url", ""),
            "thread_title": rows[0].get("thread_title", ""),
            "related_round": "14",
            "poll_region_alignment": "jp",
            "platform_region": "CN",
            "event_phase": "during_vote_trend_interpretation",
            "displayed_total_reply_count": rows[0].get("total_reply_count", ""),
            "captured_pc_web_text_record_count": len(rows),
            "main_reply_text_count": sum(row.get("sample_type") == "main_reply" for row in rows),
            "nested_reply_text_count": sum(row.get("sample_type") == "nested_reply" for row in rows),
            "character_tagged_text_record_count": sum(bool(row.get("character_cn")) for row in rows),
            "observed_at": rows[0].get("observed_at", "2026-08-24"),
            "metric_note": "177为帖子总回复数；99为已采文本记录；图片Top24另表手工复核为Twitter公开晒票样本。三类单位禁止相加。",
        }]
        write_csv(OUT / "tieba_round14_sampling_summary.csv", summary, list(summary[0]))
    return rows


def load_qualitative_samples() -> list[dict]:
    """Load curated comments plus the Tieba fulltext replies, deduplicated."""

    samples: list[dict] = []
    base = METADATA / "community_comment_danmaku_samples.csv"
    if base.exists():
        samples.extend(read_csv(base))
    tieba_curated = METADATA / "tieba_comment_samples.csv"
    if tieba_curated.exists():
        samples.extend(read_csv(tieba_curated))
    fulltext_paths = [
        METADATA / "tieba_round14_twitter_ballot_stats_normalized.csv",
        METADATA / "tieba_round21_rank_evaluation_normalized.csv",
    ]
    for tieba_full in fulltext_paths:
        if not tieba_full.exists():
            continue
        for row in read_csv(tieba_full):
            if row.get("counts_as_qualitative_comment") != "yes":
                continue
            samples.append({
                "sample_id": row.get("sample_id", ""),
                "platform": "Tieba",
                "source_url": row.get("source_url", ""),
                "content_date": row.get("posted_date", ""),
                "observed_at": row.get("observed_at", ""),
                "sample_type": "comment",
                "character_cn": row.get("character_cn", ""),
                "poll_region_alignment": row.get("poll_region_alignment", "jp"),
                "related_round": row.get("related_round", ""),
                "round_status": row.get("round_status", "complete"),
                "text_original": row.get("raw_text", ""),
                "verification_status": "verified_pc_web",
            })
    deduplicated: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in samples:
        text_value = row.get("text_original", "") or row.get("text_zh_or_note", "") or row.get("raw_text", "")
        key = (
            row.get("platform", ""),
            row.get("source_url", ""),
            normalize_name(row.get("character_cn", "")),
            normalize_name(text_value),
        )
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(row)
    return deduplicated


def build_tieba_tables(cn_aliases: dict[str, str]) -> tuple[list[dict], list[dict], list[dict]]:
    """Normalize the public Baidu Tieba sample without treating it as a poll.

    Tieba search and post pages expose a few labeled fields publicly, while
    other counters can appear as unlabeled numbers near the post controls.
    The latter are preserved verbatim in ``other_visible_counts`` and are
    never interpreted as likes, views, or votes.  Round 22 rows are explicitly
    kept as ongoing context and never flow into historical rank tables.
    """

    search_path = METADATA / "tieba_search_results.csv"
    comment_path = METADATA / "tieba_comment_samples.csv"
    if not search_path.exists():
        return [], [], []
    search_rows = read_csv(search_path)
    comment_rows = read_csv(comment_path) if comment_path.exists() else []
    aliases = character_aliases()
    # A few early rows were hand-entered before the schema was frozen.  Repair
    # them by stable record ID before writing the normalized source table; this
    # keeps the raw evidence and the explicit adjacent-poll distinction while
    # preventing field shifts from looking like a round named “complete”.
    early_schema_repairs = {
        "tieba_adjacent_r5_nicodosai_result": {
            "poll_region_alignment": "", "related_round": "", "round_status": "complete",
            "event_class": "adjacent_niconico_festival_poll", "reply_count": "99",
            "other_visible_counts": "", "excerpt": "“心绮楼大胜利”；正文继续贴出音乐部门结果及评论数，属于NICO童祭社区投票，不与官方第5回东方Project人气投票合并。",
            "metrics_note": "99为页面‘全部回复(99)’；不能解释为票数或官方东方人气投票回复。",
            "access_status": "pc_web_fulltext_available", "observed_at": "2026-08-24",
            "verification_status": "verified_visible", "character_mentions_cn": "多角色",
            "normalization_note": "相邻社区投票单独保留；官方投票对齐字段留空。",
        },
        "tieba_adjacent_r5_nicodosai_result_short": {
            "poll_region_alignment": "", "related_round": "", "round_status": "complete",
            "event_class": "adjacent_niconico_festival_poll", "reply_count": "5",
            "other_visible_counts": "", "excerpt": "正文为结果镇楼图，未展开出逐角色文字。",
            "metrics_note": "5为页面‘全部回复(5)’；不解释为票数或官方投票互动。",
            "access_status": "pc_web_fulltext_available", "observed_at": "2026-08-24",
            "verification_status": "verified_visible", "character_mentions_cn": "多角色",
            "normalization_note": "相邻社区投票单独保留；官方投票对齐字段留空。",
        },
        "tieba_cross_2003_2014_summary": {
            "poll_region_alignment": "", "related_round": "", "round_status": "complete",
            "event_class": "longitudinal_summary", "reply_count": "134",
            "other_visible_counts": "", "excerpt": "正文说明对第1—10回日区与第1—3回国区结果做长期综合整理，提供日中官方投票页面入口并提醒作者解释可能有遗漏。",
            "metrics_note": "134为页面‘全部回复(134)’；跨届汇总不等于任何一届官方票数或逐角色评论量。",
            "access_status": "pc_web_fulltext_available", "observed_at": "2026-08-24",
            "verification_status": "verified_visible", "character_mentions_cn": "全角色",
            "normalization_note": "跨届统计入口单独保存；不自动拆分成每届角色事件。",
        },
    }
    for row in search_rows:
        repair = early_schema_repairs.get(row.get("record_id", ""))
        if repair:
            row.update(repair)
        title_context = f"{row.get('post_title', '')} {row.get('excerpt', '')}"
        mentions = find_character_mentions(title_context, aliases)
        if row.get("character_cn") and row["character_cn"] not in mentions:
            mentions.insert(0, row["character_cn"])
        row["character_mentions_cn"] = ";".join(dict.fromkeys(mentions))
        round_no = as_float(row.get("related_round"))
        if round_no is not None and int(round_no) >= 22:
            row["round_status"] = "ongoing"
        row["platform"] = "Tieba"
        row["observed_at"] = row.get("observed_at") or "2026-08-23"
        row["normalization_note"] = (
            "公开帖正文与已标注回复数；other_visible_counts保留未标注数字，禁止解释为赞、浏览或票数。"
        )
    for row in comment_rows:
        row["platform"] = "Tieba"
        row["observed_at"] = row.get("observed_at") or "2026-08-23"
        row["normalization_note"] = "楼层文本为PC网页或已登录网页可见样本；未展开、图片化、删除内容不补猜。"
    search_fields = list(search_rows[0]) if search_rows else []
    comment_fields = list(comment_rows[0]) if comment_rows else []
    if search_rows:
        write_csv(search_path, search_rows, search_fields)
    if comment_rows:
        write_csv(comment_path, comment_rows, comment_fields)
    fulltext_rows = normalize_tieba_round14_fulltext() + normalize_tieba_round21_fulltext(cn_aliases)
    return search_rows, comment_rows, fulltext_rows


def rank_percentile(rank: float, candidate_count: int) -> float:
    if candidate_count <= 1:
        return 100.0
    return round(100.0 * (candidate_count - rank) / (candidate_count - 1), 4)


def as_float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def add_vote_percentiles(cn_aliases: dict[str, str] | None = None) -> tuple[list[dict], list[dict]]:
    crosswalk = read_csv(METADATA / "character_name_crosswalk.csv")
    jp_to_cn = {normalize_name(row["character_jp"]): row["character_cn"] for row in crosswalk}
    # Four round-21 source labels are absent from fun.xlsx.  Use the THBWiki
    # reference name when available and otherwise preserve the Japanese source
    # label (e.g. 先代巫女) so long-tail rows can still receive evidence.
    thb_list = METADATA / "thbwiki_official_character_list.csv"
    if thb_list.exists():
        for row in read_csv(thb_list):
            jp_name = row.get("character_jp", "").strip()
            cn_name = row.get("canonical_cn_fun", "").strip() or row.get("character_cn_thb", "").strip()
            if jp_name and cn_name:
                jp_to_cn.setdefault(normalize_name(jp_name), cn_name)

    jp_rows = read_csv(METADATA / "vote_history_all_characters.csv")
    jp_counts = Counter(int(row["round"]) for row in jp_rows)
    jp_out = []
    for row in jp_rows:
        round_no = int(row["round"])
        rank = as_float(row["rank"])
        if rank is None:
            continue
        jp_norm = normalize_name(row["character"])
        jp_out.append(
            {
                **row,
                "region": "jp",
                "character_key": jp_norm,
                "character_cn": jp_to_cn.get(jp_norm, row.get("character", "")),
                "candidate_count": jp_counts[round_no],
                "top_percentile": rank_percentile(rank, jp_counts[round_no]),
                "rank_fraction": round(rank / jp_counts[round_no], 6),
            }
        )
    write_csv(OUT / "jp_vote_rank_percentiles.csv", jp_out, list(jp_out[0]))

    cn_rows = read_csv(METADATA / "cn_vote_history_all_characters.csv")
    cn_counts = Counter(int(row["round"]) for row in cn_rows)
    cn_out = []
    canonical_names = {
        normalize_name(row.get("character_cn", "")): row.get("character_cn", "")
        for row in crosswalk
        if row.get("character_cn", "").strip()
    }
    for row in cn_rows:
        round_no = int(row["round"])
        rank = as_float(row["rank"])
        if rank is None:
            continue
        raw_name = row.get("character_cn", "")
        if cn_aliases:
            canonical_name = cn_aliases.get(normalize_name(raw_name), raw_name)
        else:
            canonical_name, _status = canonicalize_cn_name(raw_name, canonical_names)
        cn_out.append(
            {
                **row,
                "region": "cn",
                "character_cn_raw": raw_name,
                "character_cn": canonical_name,
                "character_key": normalize_name(canonical_name),
                "candidate_count": cn_counts[round_no],
                "top_percentile": rank_percentile(rank, cn_counts[round_no]),
                "rank_fraction": round(rank / cn_counts[round_no], 6),
            }
        )
    write_csv(OUT / "cn_vote_rank_percentiles.csv", cn_out, list(cn_out[0]))
    return jp_out, cn_out


def longitudinal_changes(jp_rows: list[dict], cn_rows: list[dict]) -> None:
    rows: list[dict] = []
    for region, source in (("jp", jp_rows), ("cn", cn_rows)):
        grouped: defaultdict[str, list[dict]] = defaultdict(list)
        for row in source:
            grouped[row["character_key"]].append(row)
        for character_rows in grouped.values():
            character_rows.sort(key=lambda item: int(item["round"]))
            for previous, current in zip(character_rows, character_rows[1:]):
                prev_rank = float(previous["rank"])
                rank = float(current["rank"])
                round_gap = int(current["round"]) - int(previous["round"])
                rows.append(
                    {
                        "region": region,
                        "character_key": current["character_key"],
                        "character_jp": current.get("character", ""),
                        "character_cn": current.get("character_cn", ""),
                        "previous_round": previous["round"],
                        "round": current["round"],
                        "round_gap": round_gap,
                        "consecutive_rounds": round_gap == 1,
                        "previous_rank": previous["rank"],
                        "rank": current["rank"],
                        "rank_improvement": round(prev_rank - rank, 4),
                        "previous_candidate_count": previous["candidate_count"],
                        "candidate_count": current["candidate_count"],
                        "previous_top_percentile": previous["top_percentile"],
                        "top_percentile": current["top_percentile"],
                        "top_percentile_change": round(float(current["top_percentile"]) - float(previous["top_percentile"]), 4),
                        "interpretation_limit": "名次与分位变化均为描述性；同票、候选合并、规则与投票者构成变化仍需逐届核对。",
                    }
                )
    rows.sort(
        key=lambda item: (
            item["region"],
            -abs(float(item["top_percentile_change"])),
            item["character_key"],
            int(item["round"]),
        )
    )
    write_csv(
        OUT / "longitudinal_rank_changes.csv",
        rows,
        list(rows[0]),
    )


def build_tieba_round14_twitter_snapshot_alignment(jp_rows: list[dict]) -> None:
    """Join the manually verified Twitter self-report top 24 to JP14 results."""

    path = METADATA / "tieba_round14_twitter_ballot_snapshot_top24.csv"
    if not path.exists():
        return
    final_by_cn = {
        normalize_name(row.get("character_cn", "")): row
        for row in jp_rows
        if int(row.get("round", 0)) == 14 and row.get("character_cn")
    }
    rows: list[dict] = []
    for source in read_csv(path):
        final = final_by_cn.get(normalize_name(source.get("character_cn", "")))
        snapshot_rank = int(source["rank"])
        final_rank = int(float(final["rank"])) if final else None
        rows.append({
            **source,
            "final_jp14_rank": final_rank if final_rank is not None else "",
            "final_jp14_points": final.get("points", "") if final else "",
            "final_jp14_primary_num": final.get("primary_num", "") if final else "",
            "final_jp14_candidate_count": final.get("candidate_count", "") if final else "",
            "final_rank_minus_snapshot_rank": final_rank - snapshot_rank if final_rank is not None else "",
            "join_status": "matched_final_result" if final else "unmatched_manual_review",
            "alignment_note": (
                "Twitter公开晒票计数与日区第14回最终官方结果分列；"
                "名次差只描述样本与最终结果的偏离，不代表期间净增票。"
            ),
        })
    write_csv(OUT / "tieba_round14_twitter_snapshot_vs_final.csv", rows, list(rows[0]))

    matched = [row for row in rows if row["join_status"] == "matched_final_result"]
    xs = [float(row["rank"]) for row in matched]
    ys = [float(row["final_jp14_rank"]) for row in matched]
    correlation = ""
    if len(xs) >= 2:
        xbar = sum(xs) / len(xs)
        ybar = sum(ys) / len(ys)
        numerator = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys))
        denominator = math.sqrt(sum((x - xbar) ** 2 for x in xs) * sum((y - ybar) ** 2 for y in ys))
        correlation = round(numerator / denominator, 6) if denominator else ""
    summary = [{
        "snapshot_time": rows[0].get("snapshot_time", "") if rows else "",
        "snapshot_scope": "twitter_public_ballot_self_reports_top24",
        "snapshot_character_count": len(rows),
        "matched_final_character_count": len(matched),
        "snapshot_rank_vs_final_rank_pearson": correlation,
        "official_final_top24_overlap_count": sum(float(row["final_jp14_rank"]) <= 24 for row in matched),
        "metric_note": "相关系数只描述这24个自晒头部样本的次序一致性；样本经过Top24截断且有自选择偏差，不能外推全部候选或因果。",
    }]
    write_csv(OUT / "tieba_round14_twitter_snapshot_alignment_summary.csv", summary, list(summary[0]))


def vote_index(rows: list[dict]) -> dict[tuple[str, int], dict]:
    index: dict[tuple[str, int], dict] = {}
    for row in rows:
        character = row.get("character_cn", "")
        if character:
            index[(normalize_name(character), int(row["round"]))] = row
    return index


def vote_value(row: dict | None, field: str) -> str | float:
    if not row:
        return ""
    value = row.get(field, "")
    return value if value is not None else ""


def align_events_with_polls(jp_rows: list[dict], cn_rows: list[dict]) -> list[dict]:
    event_path = METADATA / "community_event_timeline.csv"
    if not event_path.exists():
        return []
    events = read_csv(event_path)
    indexes = {"jp": vote_index(jp_rows), "cn": vote_index(cn_rows)}
    aligned = []
    for event in events:
        region = event.get("poll_region_alignment", "")
        if region not in indexes:
            # Keep character-context events (for example, a Bilibili lecture
            # with no explicit JP/CN poll target) in the audit/coverage table.
            # They are intentionally excluded from the region-aligned outputs.
            aligned.append(
                {
                    **event,
                    "character_key": normalize_name(event.get("character_cn", "")),
                    "join_status": "not_poll_aligned",
                    "alignment_limit": "未指定地区或届次；仅作社群语境旁证，不与任何投票指标相加。",
                }
            )
            continue
        character_key = normalize_name(event.get("character_cn", ""))
        before_round = int(event["poll_round_before"]) if event.get("poll_round_before") else None
        after_round = int(event["poll_round_after"]) if event.get("poll_round_after") else None
        before = indexes[region].get((character_key, before_round)) if before_round else None
        after = indexes[region].get((character_key, after_round)) if after_round else None
        before_rank = as_float(vote_value(before, "rank"))
        after_rank = as_float(vote_value(after, "rank"))
        rank_improvement = ""
        if before_rank is not None and after_rank is not None:
            rank_improvement = round(before_rank - after_rank, 4)
        aligned.append(
            {
                **event,
                "character_key": character_key,
                "before_rank": vote_value(before, "rank"),
                "after_rank": vote_value(after, "rank"),
                "rank_improvement": rank_improvement,
                "before_candidate_count": vote_value(before, "candidate_count"),
                "after_candidate_count": vote_value(after, "candidate_count"),
                "before_top_percentile": vote_value(before, "top_percentile"),
                "after_top_percentile": vote_value(after, "top_percentile"),
                "before_points_jp": vote_value(before, "points") if region == "jp" else "",
                "after_points_jp": vote_value(after, "points") if region == "jp" else "",
                "before_primary_jp": vote_value(before, "primary_num") if region == "jp" else "",
                "after_primary_jp": vote_value(after, "primary_num") if region == "jp" else "",
                "before_official_support_jp": vote_value(before, "official_support_count") if region == "jp" else "",
                "after_official_support_jp": vote_value(after, "official_support_count") if region == "jp" else "",
                "before_votes_cn": vote_value(before, "vote_count") if region == "cn" else "",
                "after_votes_cn": vote_value(after, "vote_count") if region == "cn" else "",
                "before_primary_cn": vote_value(before, "primary_count") if region == "cn" else "",
                "after_primary_cn": vote_value(after, "primary_count") if region == "cn" else "",
                "before_weighted_score_cn": vote_value(before, "weighted_score") if region == "cn" else "",
                "after_weighted_score_cn": vote_value(after, "weighted_score") if region == "cn" else "",
                "join_status": "before_and_after" if before and after else "after_only" if after else "before_only" if before else "unmatched",
                "alignment_limit": "时间相邻只支持描述性对齐；社媒互动、播放、标签量、支援数和投票指标禁止相加。",
            }
        )

    fields = list(aligned[0]) if aligned else []
    jp_domestic = [
        row for row in aligned
        if row["platform_region"] == "JP"
        and row["poll_region_alignment"] == "jp"
        and row["diffusion_class"] == "domestic_platform_poll_alignment"
    ]
    cn_domestic = [
        row for row in aligned
        if row["platform_region"] == "CN"
        and row["poll_region_alignment"] == "cn"
        and row["diffusion_class"] == "domestic_platform_poll_alignment"
    ]
    cross_region = [row for row in aligned if row["diffusion_class"] == "cross_region_observed"]
    write_csv(OUT / "jp_platform_jp_poll.csv", jp_domestic, fields)
    write_csv(OUT / "cn_platform_cn_poll.csv", cn_domestic, fields)
    write_csv(OUT / "cross_region_diffusion.csv", cross_region, fields)
    return aligned


def build_character_coverage(
    event_rows: list[dict],
    supplemental_rows: list[dict],
    tieba_rows: list[dict] | None = None,
    tieba_fulltext_rows: list[dict] | None = None,
    canon_rows: list[dict] | None = None,
) -> None:
    comments = load_qualitative_samples()
    pixiv_rows = read_csv(METADATA / "pixiv_tag_snapshots.csv")
    coverage: defaultdict[str, dict] = defaultdict(
        lambda: {
            "event_ids": set(), "platforms": set(), "poll_regions": set(),
            "event_types": set(), "dates": [], "comment_samples": 0,
            "bilibili_query_or_title_hits": 0, "tieba_evidence_count": 0,
            "tieba_rank_heading_coverage_count": 0,
            "tieba_fulltext_comment_sample_count": 0,
            "tieba_round21_nested_reply_sample_count": 0,
            "tieba_pre21_fulltext_comment_sample_count": 0,
            "pixiv_tag_count_snapshot": "", "round21_rank": "",
            "canon_verification_status": "not_round21_candidate_or_unmatched_evidence",
            "research_scope": "context_only",
        }
    )
    display_name: dict[str, str] = {}

    def ensure(character: str) -> tuple[str, dict] | None:
        character = character.strip()
        if not character or character in {"全角色", "ALL"}:
            return None
        key = normalize_name(character)
        display_name.setdefault(key, character)
        return key, coverage[key]

    for row in event_rows:
        # A pairing/ensemble work may name several roles.  Attach the same
        # source event to each named role, but keep one event_id so the work's
        # views/likes are never counted as independent heat units per role.
        for character in (row.get("character_cn", "") or "").split(";"):
            item = ensure(character)
            if not item:
                continue
            _, record = item
            record["event_ids"].add(row["event_id"])
            record["platforms"].add(row["platform"])
            record["poll_regions"].add(row["poll_region_alignment"])
            record["event_types"].add(row["event_type"])
            if row.get("event_date"):
                record["dates"].append(row["event_date"])

    for row in canon_rows or []:
        item = ensure(row.get("character_cn", ""))
        if not item:
            continue
        _, record = item
        record["round21_rank"] = row.get("round21_rank", "")
        record["canon_verification_status"] = row.get(
            "verification_status", "not_round21_candidate_or_unmatched_evidence"
        )
        record["research_scope"] = row.get("research_scope", "excluded")

    for row in comments:
        for character in row.get("character_cn", "").split(";"):
            item = ensure(character)
            if item:
                item[1]["comment_samples"] += 1

    for row in supplemental_rows:
        for character in row.get("character_mentions_cn", "").split(";"):
            item = ensure(character)
            if item:
                item[1]["bilibili_query_or_title_hits"] += 1

    for row in tieba_rows or []:
        characters = row.get("character_mentions_cn", "") or row.get("character_cn", "")
        for character in characters.split(";"):
            item = ensure(character)
            if item:
                item[1]["tieba_evidence_count"] += 1

    for row in tieba_fulltext_rows or []:
        item = ensure(row.get("character_cn", ""))
        if not item:
            continue
        if row.get("sample_type") == "rank_heading" and row.get("related_round") == "21":
            item[1]["tieba_rank_heading_coverage_count"] += 1
        elif row.get("counts_as_qualitative_comment") == "yes":
            item[1]["tieba_fulltext_comment_sample_count"] += 1
            if row.get("related_round") == "21":
                item[1]["tieba_round21_nested_reply_sample_count"] += 1
            else:
                item[1]["tieba_pre21_fulltext_comment_sample_count"] += 1

    for row in pixiv_rows:
        item = ensure(row.get("character_cn", ""))
        if item:
            item[1]["pixiv_tag_count_snapshot"] = row.get("work_count_snapshot", "")

    output = []
    for key, record in coverage.items():
        dates = sorted(record["dates"])
        output.append(
            {
                "character_cn": display_name[key],
                "character_key": key,
                "event_count": len(record["event_ids"]),
                "earliest_event_date": dates[0] if dates else "",
                "latest_event_date": dates[-1] if dates else "",
                "platforms": ";".join(sorted(record["platforms"])),
                "poll_regions": ";".join(sorted(record["poll_regions"])),
                "event_types": ";".join(sorted(record["event_types"])),
                "comment_or_danmaku_sample_count": record["comment_samples"],
                "bilibili_query_or_title_hit_count": record["bilibili_query_or_title_hits"],
                "tieba_evidence_count": record["tieba_evidence_count"],
                "tieba_rank_heading_coverage_count": record["tieba_rank_heading_coverage_count"],
                "tieba_fulltext_comment_sample_count": record["tieba_fulltext_comment_sample_count"],
                "tieba_round21_nested_reply_sample_count": record["tieba_round21_nested_reply_sample_count"],
                "tieba_pre21_fulltext_comment_sample_count": record["tieba_pre21_fulltext_comment_sample_count"],
                "pixiv_tag_count_snapshot": record["pixiv_tag_count_snapshot"],
                "round21_rank": record["round21_rank"],
                "canon_verification_status": record["canon_verification_status"],
                "research_scope": record["research_scope"],
                "coverage_limit": "事件数与题名命中数只表示本次证据表覆盖，不是角色人气或作品量排名。",
            }
        )
    output.sort(key=lambda row: (-int(row["event_count"]), row["character_cn"]))
    if output:
        write_csv(OUT / "community_character_coverage.csv", output, list(output[0]))


def build_character_canon_coverage(jp_rows: list[dict]) -> list[dict]:
    """Audit first-appearance/setting coverage for every round-21 candidate.

    Detailed claims remain limited to rows verified against individual pages.
    The broader THBWiki character-list cards are retained as ``basic_index``
    rather than being mislabeled as complete first-setting verification.
    """

    source_path = METADATA / "thbwiki_character_canon_sources.csv"
    source_rows = read_csv(source_path) if source_path.exists() else []
    by_cn = {normalize_name(row.get("character_cn", "")): row for row in source_rows}
    list_path = METADATA / "thbwiki_official_character_list.csv"
    list_rows = read_csv(list_path) if list_path.exists() else []
    list_by_cn: dict[str, dict] = {}
    list_by_jp: dict[str, dict] = {}
    for row in list_rows:
        canonical = row.get("canonical_cn_fun", "").strip()
        if canonical:
            list_by_cn.setdefault(normalize_name(canonical), row)
        source_cn = row.get("character_cn_thb", "").strip()
        source_jp = row.get("character_jp", "").strip()
        if source_cn:
            list_by_cn.setdefault(normalize_name(source_cn), row)
        if source_jp:
            list_by_jp.setdefault(normalize_name(source_jp), row)
    crosswalk = read_csv(METADATA / "character_name_crosswalk.csv")
    jp_to_cn = {normalize_name(row.get("character_jp", "")): row.get("character_cn", "") for row in crosswalk}
    candidates = [row for row in jp_rows if int(row.get("round", 0)) == 21]
    out: list[dict] = []
    for candidate in sorted(candidates, key=lambda row: (int(row.get("rank", 9999)), row.get("character", ""))):
        jp_name = candidate.get("character", "")
        indexed_by_jp = list_by_jp.get(normalize_name(jp_name), {})
        cn_name = jp_to_cn.get(normalize_name(jp_name), "")
        if not cn_name and indexed_by_jp:
            cn_name = indexed_by_jp.get("canonical_cn_fun", "").strip() or indexed_by_jp.get("character_cn_thb", "").strip()
        if not cn_name:
            cn_name = jp_name
        verified = by_cn.get(normalize_name(cn_name), {})
        has_verified = bool(verified)
        indexed = list_by_cn.get(normalize_name(cn_name), {}) or indexed_by_jp
        has_index = bool(indexed)
        first_appearance = verified.get("first_appearance", "") if has_verified else indexed.get("first_appearance", "")
        identity = verified.get("official_identity_or_ability", "") if has_verified else indexed.get("reference_identity_or_title", "")
        source_note = (
            verified.get("source_note", "")
            if has_verified
            else (
                "THBWiki官方角色列表基础索引；列表的收录标准仅代表THBWiki，不代表官方意见；身份/称号仍待逐角色一设来源复核。"
                if has_index
                else "第21回候选表中存在，但未命中THBWiki官方角色列表或已核实角色页；按本研究口径不再补一设、别名、梗或社群资料。"
            )
        )
        out.append(
            {
                "character_cn": cn_name,
                "character_jp": jp_name,
                "round21_rank": candidate.get("rank", ""),
                "first_appearance": first_appearance,
                "official_identity": identity,
                "official_ability": "",
                "canon_meme_material": verified.get("canon_meme_material", "") if has_verified else "",
                "derivative_misread_risk": verified.get("derivative_misread_risk", "") if has_verified else "",
                "thbwiki_url": verified.get("thbwiki_url", "") if has_verified else indexed.get("thbwiki_url", ""),
                "access_status": "alternate_site_verified" if has_verified else ("list_indexed_needs_primary_review" if has_index else "out_of_scope_no_thbwiki_index"),
                "verification_date": verified.get("observation_date", "") if has_verified else indexed.get("observation_date", ""),
                "source_note": source_note,
                "verification_status": "verified" if has_verified else ("basic_index_only" if has_index else "out_of_scope_no_thbwiki_index"),
                "research_scope": "included" if has_verified or has_index else "excluded",
            }
        )
    fields = [
        "character_cn", "character_jp", "round21_rank", "first_appearance",
        "official_identity", "official_ability", "canon_meme_material",
        "derivative_misread_risk", "thbwiki_url", "access_status",
        "verification_date", "source_note", "verification_status", "research_scope",
    ]
    write_csv(METADATA / "character_canon_coverage.csv", out, fields)
    return out


def build_character_community_tag_coverage(canon_rows: list[dict]) -> list[dict]:
    """Join the legacy Chinese community-tag workbook to all round-21 rows.

    These tags mix visual traits, memes, nicknames and occasional setting
    claims.  They are useful as search vocabulary only and must never fill the
    official-setting columns in ``character_canon_coverage.csv``.
    """

    source = ROOT / "Character_tag.xlsx"
    tag_by_name: dict[str, str] = {}
    if source.exists():
        import pandas as pd

        frame = pd.read_excel(source, sheet_name=0)
        for _, item in frame.iterrows():
            name = str(item.get("译名", "")).strip()
            tags = str(item.get("keywords", "")).strip()
            if name and name != "nan" and tags and tags != "nan":
                tag_by_name[normalize_name(name)] = tags
    rows: list[dict] = []
    for row in canon_rows:
        name = row.get("character_cn", "")
        in_scope = row.get("research_scope") == "included"
        tags = tag_by_name.get(normalize_name(name), "") if in_scope else ""
        rows.append(
            {
                "character_cn": name,
                "character_jp": row.get("character_jp", ""),
                "round21_rank": row.get("round21_rank", ""),
                "community_tags_cn": tags,
                "tag_status": (
                    "available_legacy_snapshot"
                    if tags
                    else "not_available_in_legacy_snapshot"
                    if in_scope
                    else "out_of_scope_no_thbwiki_index"
                ),
                "source_path": "Character_tag.xlsx" if tags else "",
                "source_scope": "中文社区百科标签/萌点旧快照；混合外观、梗、昵称和二创，非官方设定。",
                "analysis_use": (
                    "只用于检索扩展、梗候选和二设误读审计；不能自动写入一设，也不能视为角色人气。"
                    if in_scope
                    else "研究范围外；仅在完整投票结果中保留，不继续补角色资料。"
                ),
            }
        )
    write_csv(
        METADATA / "character_community_tag_coverage.csv",
        rows,
        ["character_cn", "character_jp", "round21_rank", "community_tags_cn", "tag_status", "source_path", "source_scope", "analysis_use"],
    )
    return rows


def build_coverage_summary(canon_rows: list[dict], coverage_rows: list[dict]) -> None:
    """Report candidate-level coverage counts without aggregating platform metrics."""

    candidate_count = len(canon_rows)
    scoped_rows = [row for row in canon_rows if row.get("research_scope") == "included"]
    scoped_candidate_count = len(scoped_rows)
    excluded_candidate_count = candidate_count - scoped_candidate_count
    candidate_keys = {normalize_name(row.get("character_cn", "")) for row in scoped_rows}
    coverage_rows = [row for row in coverage_rows if row.get("character_key", "") in candidate_keys]
    canon_verified = sum(row.get("verification_status") == "verified" for row in canon_rows)
    canon_basic_indexed = sum(row.get("verification_status") in {"verified", "basic_index_only"} for row in canon_rows)
    event_count = sum(int(row.get("event_count") or 0) > 0 for row in coverage_rows)
    comment_count = sum(int(row.get("comment_or_danmaku_sample_count") or 0) > 0 for row in coverage_rows)
    tieba_post_count = sum(int(row.get("tieba_evidence_count") or 0) > 0 for row in coverage_rows)
    tieba_rank_heading_count = sum(int(row.get("tieba_rank_heading_coverage_count") or 0) > 0 for row in coverage_rows)
    tieba_nested_reply_count = sum(int(row.get("tieba_round21_nested_reply_sample_count") or 0) > 0 for row in coverage_rows)
    tieba_any_count = sum(
        any(int(row.get(field) or 0) > 0 for field in (
            "tieba_evidence_count", "tieba_rank_heading_coverage_count", "tieba_fulltext_comment_sample_count"
        ))
        for row in coverage_rows
    )
    social_count = sum(
        any(platform in (row.get("platforms") or "").split(";") for platform in ("Bilibili", "X", "Pixiv"))
        for row in coverage_rows
    )
    rows = [
        {
            "round": 21,
            "round_status": "complete",
            "round21_candidate_count": candidate_count,
            "canon_research_scope_character_count": scoped_candidate_count,
            "canon_out_of_scope_no_thbwiki_index_count": excluded_candidate_count,
            "canon_verified_character_count": canon_verified,
            "canon_basic_indexed_character_count": canon_basic_indexed,
            "characters_with_poll_related_event": event_count,
            "characters_with_comment_or_danmaku_sample": comment_count,
            "characters_with_tieba_evidence": tieba_any_count,
            "characters_with_tieba_post_evidence": tieba_post_count,
            "characters_with_tieba_round21_rank_heading": tieba_rank_heading_count,
            "characters_with_tieba_round21_nested_reply": tieba_nested_reply_count,
            "characters_with_bilibili_x_pixiv_evidence": social_count,
            "coverage_note": "完整投票分母仍是第21回221个候选；一设与社群覆盖分母是命中THBWiki角色索引或已核实角色页的167名。54名无索引候选只保留原始投票结果，不继续补资料。平台证据按角色是否有记录计数，不把互动量或票数相加；第22回进行中记录不进入历史分母。",
        }
    ]
    write_csv(OUT / "community_coverage_summary.csv", rows, list(rows[0]))


def build_full_character_timeline(jp_rows: list[dict], cn_rows: list[dict], event_rows: list[dict]) -> None:
    """Emit every completed character-round result with separately joined evidence.

    A zero in the evidence columns means no record in the current curated
    evidence tables, not that no community discussion existed.  Round 22 is
    excluded because it is ongoing; its posts remain in the event tables.
    """

    comments = load_qualitative_samples()
    event_index: defaultdict[tuple[str, str, int], list[dict]] = defaultdict(list)
    for event in event_rows:
        region = event.get("poll_region_alignment", "")
        if region not in {"jp", "cn"}:
            continue
        character = normalize_name(event.get("character_cn", ""))
        for field in ("poll_round_before", "poll_round_after"):
            value = event.get(field, "")
            if not value or not str(value).isdigit() or int(value) >= 22:
                continue
            key = (region, character, int(value))
            if not any(existing.get("event_id") == event.get("event_id") for existing in event_index[key]):
                event_index[key].append(event)
    comment_index: Counter[tuple[str, str, int]] = Counter()
    for sample in comments:
        region = sample.get("poll_region_alignment", "")
        round_text = sample.get("related_round", "")
        if region not in {"jp", "cn"} or not str(round_text).isdigit() or int(round_text) >= 22:
            continue
        for character in sample.get("character_cn", "").split(";"):
            if character and character not in {"全角色", "ALL"}:
                comment_index[(region, normalize_name(character), int(round_text))] += 1

    rows: list[dict] = []
    for region, source in (("jp", jp_rows), ("cn", cn_rows)):
        for vote in source:
            round_no = int(vote.get("round", 0))
            if round_no >= 22:
                continue
            character_cn = vote.get("character_cn", "")
            key = (region, normalize_name(character_cn), round_no)
            attached = event_index.get(key, [])
            rows.append(
                {
                    "region": region,
                    "round": round_no,
                    "round_status": "complete",
                    "poll_period": vote.get("poll_period", ""),
                    "character_cn": character_cn,
                    "character_cn_raw": vote.get("character_cn_raw", character_cn),
                    "character_jp": vote.get("character", ""),
                    "rank": vote.get("rank", ""),
                    "candidate_count": vote.get("candidate_count", ""),
                    "top_percentile": vote.get("top_percentile", ""),
                    "points_jp": vote.get("points", "") if region == "jp" else "",
                    "primary_jp": vote.get("primary_num", "") if region == "jp" else "",
                    "official_support_jp": vote.get("official_support_count", "") if region == "jp" else "",
                    "votes_cn": vote.get("vote_count", "") if region == "cn" else "",
                    "primary_cn": vote.get("primary_count", "") if region == "cn" else "",
                    "weighted_score_cn": vote.get("weighted_score", "") if region == "cn" else "",
                    "community_event_count": len(attached),
                    "community_event_ids": ";".join(event.get("event_id", "") for event in attached),
                    "community_platforms": ";".join(sorted({event.get("platform", "") for event in attached if event.get("platform")})),
                    "comment_or_danmaku_sample_count": comment_index.get(key, 0),
                    "evidence_status": "curated_evidence_attached" if attached or comment_index.get(key, 0) else "no_curated_evidence_yet",
                    "timeline_limit": "0表示当前证据表未收录，不表示当届没有讨论；社媒指标与票数始终分列。",
                }
            )
    rows.sort(key=lambda row: (row["region"], int(row["round"]), int(float(row["rank"])), row["character_cn"]))
    write_csv(OUT / "character_poll_social_timeline_grid.csv", rows, list(rows[0]))


def source_access_status() -> None:
    rows = [
        {"platform": "Niconico视频", "free_source": "yes", "access_status": "public_access", "login_needed": "no", "coverage": "東方Project人気投票标签显示204条，当前可公开复核197条", "user_action_if_needed": "无"},
        {"platform": "Bilibili", "free_source": "yes", "access_status": "public_search_and_visible_sample_access", "login_needed": "yes_for_full_comment_threads", "coverage": "人气投票主查询34页；13组角色首屏510条已落盘；本轮通过已登录搜索界面补采饭纲丸龙、莲子、梅莉、日狭美、磨弓等候选；评论/弹幕仅保存可见质性样本", "user_action_if_needed": "无；若页面再次要求验证或需要不可见楼层，再提醒"},
        {"platform": "X", "free_source": "yes", "access_status": "logged_in_search_sampled", "login_needed": "already_available", "coverage": "已用登录会话回溯第7—21回，抽样原帖、回复、长期梗与小众角色；不是API全量归档", "user_action_if_needed": "当前无需操作；若平台再次要求验证再提醒"},
        {"platform": "Pixiv", "free_source": "yes", "access_status": "logged_in_artwork_and_tag_sampled", "login_needed": "already_available", "coverage": "已核实2011第8回应援、2015易者、阿求年龄企划及10个角色的2026-08-23标签累计快照；没有历年标签时间序列", "user_action_if_needed": "当前无需操作；若触发频率限制再提醒"},
        {"platform": "百度贴吧", "free_source": "yes", "access_status": "pc_web_fulltext_via_pagination_and_virtual_scroll", "login_needed": "already_available", "coverage": "PC UA网页端可读分页全文；帖子索引18条，含7条第22回与第12—21回历史材料。第14回Twitter晒票帖保存99条文本；第21回评价帖保存416条文本（163个角色标题、252条楼中楼、1条完结说明）。第10—11回部分索引原帖当前不再渲染。", "user_action_if_needed": "当前无需操作；只有页面确实删除、折叠无法展开或图片文字无法辨识时才需要截图/导出"},
        {"platform": "Yahoo!リアルタイム検索", "free_source": "yes", "access_status": "historical_limit", "login_needed": "sometimes", "coverage": "普通Yahoo日本网页搜索可用；实时/X历史窗口有限", "user_action_if_needed": "如需登录后的历史功能，请授权可用会话"},
        {"platform": "Google Trends", "free_source": "yes", "access_status": "public_but_normalized", "login_needed": "no_for_basic", "coverage": "可按时间/地区读取0—100相对搜索兴趣，不提供绝对搜索次数", "user_action_if_needed": "无"},
        {"platform": "GetDayTrends", "free_source": "yes", "access_status": "blocked_cloudflare_520", "login_needed": "unknown", "coverage": "当前无法复核", "user_action_if_needed": "如你能访问，请提供导出或授权浏览器会话"},
        {"platform": "THBWiki", "free_source": "yes", "access_status": "alternate_site_verified", "login_needed": "no", "coverage": "备用站 thbwiki.cc 可访问并核实丰姬、神绮、大妖精、小恶魔等一设；不把二次设定段落当官方设定", "user_action_if_needed": "无；若需被WAF拦截的原站历史页面，再提供授权会话或导出"},
        {"platform": "Reddit", "free_source": "yes", "access_status": "captcha_or_login_for_threads", "login_needed": "sometimes", "coverage": "只有公开索引片段，未完整读取评论串", "user_action_if_needed": "若需英语社区完整评论，请登录/完成人机验证后告知"},
    ]
    for row in rows:
        row["observed_at"] = "2026-08-25"
    write_csv(
        METADATA / "community_source_access_status.csv",
        rows,
        ["platform", "free_source", "access_status", "login_needed", "coverage", "user_action_if_needed", "observed_at"],
    )


def _question_rate(group: list[dict], question_names: set[str], option_predicate) -> tuple[float | None, int | None]:
    """Return a rate and denominator without mixing questions or metrics.

    Entity questionnaire rows repeat the same denominator for each option.  We
    therefore take the maximum denominator in the selected question and sum
    option counts, rather than summing repeated denominator cells.
    """
    rows = [row for row in group if row.get("question", "") in question_names and option_predicate(row.get("option", ""))]
    if not rows:
        return None, None
    counts = sum(float(row.get("count") or 0) for row in rows)
    den_values = []
    for row in rows:
        value = row.get("conditional_denominator")
        if value in ("", None):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isnan(number):
            den_values.append(number)
    denominator = int(round(max(den_values))) if den_values else None
    return (round(counts / denominator, 6) if denominator else None), denominator


def build_questionnaire_profiles(jp_rows: list[dict], cn_rows: list[dict]) -> None:
    """Build per-character JP questionnaire profiles and 21st-round joins.

    Rates are kept as proportions with explicit denominators.  The source has
    different question labels in rounds 11–16 and 17–21, so aliases are kept
    in the predicates below.  Round 22 is intentionally excluded: it is an
    ongoing vote and has no completed character questionnaire in the snapshot.
    """
    source = ROOT / "data_processed" / "jp_unified" / "entity_questionnaire_long.csv.gz"
    if not source.exists():
        return
    import pandas as pd

    frame = pd.read_csv(source, compression="gzip", low_memory=False)
    frame = frame[frame["round"].between(11, 21)].copy()
    rows: list[dict] = []
    age_q = {"age", "年齢回答"}
    sex_q = {"sex", "性別回答"}
    voted_q = {"voted", "人気投票への投票", "人気投票への投票回答"}
    event_q = {"intention", "同人誌即売会への参加"}
    cognition_q = {"cognition", "東方を知った時期", "東方を知った時期回答"}
    for (round_no, source_id, source_name), part in frame.groupby(["round", "source_id", "source_name"], dropna=False):
        group = part.to_dict("records")
        under20, under20_den = _question_rate(group, age_q, lambda o: bool(re.match(r"^(?:～|~)?(?:9|10|15)", o.strip())))
        female, female_den = _question_rate(group, sex_q, lambda o: o.strip() == "女性")
        first_vote, first_vote_den = _question_rate(group, voted_q, lambda o: "初" in o or "はじめて" in o)
        event_part, event_den = _question_rate(group, event_q, lambda o: o.strip() == "参加している")
        cognition_2019, cognition_den = _question_rate(group, cognition_q, lambda o: "2019年8月" in o or "鬼形獣～虹龍洞" in o or "鬼形獣〜虹龍洞" in o or "虹龍洞～" in o or "虹龍洞〜" in o or "バレットフィリア" in o or "獣王園" in o)
        rows.append({
            "region": "jp", "round": int(round_no), "source_id": str(source_id), "character_jp": source_name,
            "character_cn": "", "under20_rate": under20 or "", "under20_denominator": under20_den or "",
            "female_rate": female or "", "female_denominator": female_den or "", "first_time_voter_rate": first_vote or "",
            "first_time_voter_denominator": first_vote_den or "", "event_participation_rate": event_part or "",
            "event_participation_denominator": event_den or "", "2019plus_cognition_rate": cognition_2019 or "",
            "2019plus_cognition_denominator": cognition_den or "", "source_note": "官方角色条件问卷；各题分母不同，比例不可相加。",
        })
    crosswalk = read_csv(METADATA / "character_name_crosswalk.csv")
    jp_to_cn = {normalize_name(row["character_jp"]): row["character_cn"] for row in crosswalk}
    for row in rows:
        row["character_cn"] = jp_to_cn.get(normalize_name(row["character_jp"]), "")
    profile_fields = list(rows[0]) if rows else []
    write_csv(OUT / "jp_character_questionnaire_profiles.csv", rows, profile_fields)

    vote_by_round = {(int(row["round"]), normalize_name(row.get("character", ""))): row for row in jp_rows if int(row["round"]) == 21}
    joined = []
    for row in rows:
        if row["round"] != 21:
            continue
        vote = vote_by_round.get((21, normalize_name(row["character_jp"])))
        if vote is None:
            continue
        joined.append({
            **row,
            "poll_rank": vote.get("rank", ""), "poll_points": vote.get("points", ""),
            "poll_primary_num": vote.get("primary_num", ""), "poll_official_support_count": vote.get("official_support_count", ""),
            "poll_candidate_count": vote.get("candidate_count", ""), "poll_top_percentile": vote.get("top_percentile", ""),
            "join_note": "第21回完整历史结果与同届角色条件问卷；不是第22回进行中数据。",
        })
    if joined:
        write_csv(OUT / "jp21_character_poll_questionnaire_profiles.csv", joined, list(joined[0]))


def build_questionnaire_context() -> None:
    """Persist overall JP21 and CN10 questionnaire context separately."""
    import pandas as pd
    rows: list[dict] = []
    jp = pd.read_csv(ROOT / "data_processed" / "jp_unified" / "aggregate_questionnaire_long.csv.gz", compression="gzip", low_memory=False)
    jp = jp[jp["round"] == 21]
    jp_specs = [
        ("triggerVote", "Youtube", "人气投票得知渠道"),
        ("triggerVote", "Twitter", "人气投票得知渠道"),
        ("triggerVote", "TikTok", "人气投票得知渠道"),
        ("triggerVote", "ニコニコ動画", "人气投票得知渠道"),
        ("charm", "音楽", "东方魅力"), ("charm", "キャラクタ", "东方魅力"),
        ("charm", "世界観", "东方魅力"), ("charm", "二次創作作品", "东方魅力"),
    ]
    # JP aggregate has stable question keys in the normalized source.
    for q, token, label in jp_specs:
        part = jp[jp["question"].eq(q) & jp["option"].astype(str).str.contains(token, regex=False)]
        for _, item in part.iterrows():
            rows.append({"region": "JP", "round": 21, "scope": "overall", "question": label, "option": item["option"], "count": int(item["count"]), "rate": item["rate"], "denominator": item["denominator"], "denominator_basis": item["denominator_basis"], "question_type": "may_be_multiple_choice", "source_note": "日区第21回总体问卷，不是角色支持率。"})
    cn = pd.read_csv(ROOT / "data_processed" / "cn_official" / "questionnaire_long.csv", low_memory=False)
    cn = cn[cn["round"] == 10]
    for _, item in cn.iterrows():
        rows.append({"region": "CN", "round": 10, "scope": "overall", "question": item["question"], "option": item["answer"], "count": int(item["count"]), "rate": item["share"], "denominator": item["respondent_n"], "denominator_basis": "question-specific respondent_n", "question_type": item["question_type"], "source_note": "国区第10回选填总体问卷；题目分母不同，不是角色支持率。"})
    if rows:
        write_csv(METADATA / "community_questionnaire_context.csv", rows, list(rows[0]))


def build_niconico_early_coverage_audit() -> None:
    """Materialize the recoverable pre-2016 Niconico evidence layer.

    The Niconico tag is a source index, not a census.  This audit preserves
    every pre-2016 card currently rendered by the public tag pages, expands
    explicit round ranges, and records character names only when they occur in
    the title.  Current views/comments/mylist values remain source metrics and
    are never joined to votes as a heat score.
    """
    source = METADATA / "niconico_popularity_vote_videos.csv"
    if not source.exists():
        return
    rows = read_csv(source)
    aliases = character_aliases()
    audit: list[dict] = []
    for row in rows:
        published = (row.get("published_date") or "").strip()
        if not re.fullmatch(r"(?:200\d|201[0-5])(?:/\d{1,2}){1,2}", published):
            continue
        title = row.get("title", "")
        numeric = mentioned_rounds(title)
        expanded = expanded_round_mentions(title, numeric)
        mentions = find_character_mentions(title, aliases)
        direct = bool(expanded)
        title_poll = bool(re.search(r"(?:東方|东方).{0,20}(?:人気|人气).{0,12}投票|(?:人気|人气)投票", title, re.I))
        relevance = "round_specific" if direct else "poll_related_title" if title_poll else "unrelated_tag_card_or_context"
        audit.append(
            {
                "video_id": row.get("video_id", ""),
                "url": row.get("url", ""),
                "published_date": published,
                "title": title,
                "author": row.get("author", ""),
                "content_type": row.get("content_type", ""),
                "mentioned_rounds_raw": numeric,
                "mentioned_rounds_expanded": expanded,
                "character_mentions_cn": ";".join(mentions),
                "poll_relevance": relevance,
                "metric_1_current": row.get("metric_1_current", ""),
                "metric_2_current": row.get("metric_2_current", ""),
                "metric_3_current": row.get("metric_3_current", ""),
                "metric_4_current": row.get("metric_4_current", ""),
                "observed_at": row.get("observed_at", ""),
                "source_scope": "Niconico公开标签页当前渲染卡片；不是全站穷尽，指标为观察日累计快照。",
                "analysis_limit": "标题未点名角色时只作届次/平台证据；当前累计指标不能还原当年曝光，也不能换算投票或角色支持。",
            }
        )
    fields = list(audit[0]) if audit else [
        "video_id", "url", "published_date", "title", "author", "content_type",
        "mentioned_rounds_raw", "mentioned_rounds_expanded", "character_mentions_cn",
        "poll_relevance", "metric_1_current", "metric_2_current", "metric_3_current",
        "metric_4_current", "observed_at", "source_scope", "analysis_limit",
    ]
    write_csv(METADATA / "niconico_early_coverage_audit.csv", audit, fields)

    summary: list[dict] = []
    for round_number in range(3, 12):
        selected = [
            row for row in audit
            if str(round_number) in (row.get("mentioned_rounds_expanded", "").split(";"))
        ]
        role_rows = [row for row in selected if row.get("character_mentions_cn")]
        summary.append(
            {
                "round": round_number,
                "pre2016_niconico_video_count": len(selected),
                "round_specific_video_count": sum(row.get("poll_relevance") == "round_specific" for row in selected),
                "title_explicit_character_video_count": len(role_rows),
                "title_explicit_character_count": len({name for row in role_rows for name in row.get("character_mentions_cn", "").split(";") if name}),
                "source_note": "仅统计标签索引中标题明确提及该届的公开卡片；空值不代表当年没有视频或讨论。",
            }
        )
    write_csv(OUT / "niconico_early_round_summary.csv", summary, list(summary[0]))


def build_historical_role_coverage_gap(
    canon_rows: list[dict],
    event_rows: list[dict],
    tieba_rows: list[dict] | None = None,
    jp_rows: list[dict] | None = None,
    cn_rows: list[dict] | None = None,
) -> None:
    """Audit early-round role coverage without turning blanks into negatives.

    A role is only eligible for a round when it occurs in that region's
    official candidate/result rows.  This prevents characters introduced after
    an early poll from being reported as missing community evidence for polls
    in which they could not yet be selected.
    """
    scoped = {
        normalize_name(row.get("character_cn", "")): row.get("character_cn", "")
        for row in canon_rows
        if row.get("research_scope") == "included" and row.get("character_cn", "").strip()
    }
    canon_by_jp = {
        normalize_name(row.get("character_jp", "")): normalize_name(row.get("character_cn", ""))
        for row in canon_rows
        if row.get("research_scope") == "included"
        and row.get("character_jp", "").strip()
        and row.get("character_cn", "").strip()
    }

    def candidate_keys(rows: list[dict] | None, region: str) -> dict[int, set[str]]:
        by_round: defaultdict[int, set[str]] = defaultdict(set)
        for row in rows or []:
            round_text = row.get("round", "")
            if not str(round_text).isdigit():
                continue
            round_number = int(round_text)
            if region == "jp":
                candidate = row.get("character_cn", "").strip()
                key = normalize_name(candidate)
                if key not in scoped:
                    # Newer/long-tail Japanese labels may not yet be in the
                    # fun.xlsx mapping, but their exact JP label is present in
                    # the THBWiki-indexed canon audit.
                    key = canon_by_jp.get(normalize_name(row.get("character", "")), "")
            else:
                key = normalize_name(row.get("character_cn", ""))
            if key in scoped:
                by_round[round_number].add(key)
        return by_round

    eligible_by_region = {
        "jp": candidate_keys(jp_rows, "jp"),
        "cn": candidate_keys(cn_rows, "cn"),
    }
    comments = load_qualitative_samples()
    event_roles: defaultdict[tuple[str, int], set[str]] = defaultdict(set)
    for row in event_rows:
        region = row.get("poll_region_alignment", "")
        character = normalize_name(row.get("character_cn", ""))
        if region not in {"jp", "cn"} or character not in scoped:
            continue
        for field in ("poll_round_before", "poll_round_after"):
            value = row.get(field, "")
            if value.isdigit() and int(value) < 22:
                event_roles[(region, int(value))].add(character)
    # Tieba post indexes are historical social evidence even when they are
    # not promoted to the hand-curated event timeline.  Count only explicitly
    # named in-scope characters; “全角色/多角色” remains a post-level signal.
    for row in tieba_rows or []:
        region = row.get("poll_region_alignment", "")
        round_text = row.get("related_round", "")
        if region not in {"jp", "cn"} or not round_text.isdigit() or int(round_text) >= 22:
            continue
        for name in (row.get("character_mentions_cn", "") or row.get("character_cn", "")).split(";"):
            key = normalize_name(name)
            if key in scoped:
                event_roles[(region, int(round_text))].add(key)
    comment_roles: defaultdict[tuple[str, int], set[str]] = defaultdict(set)
    for row in comments:
        region = row.get("poll_region_alignment", "")
        round_text = row.get("related_round", "")
        if region not in {"jp", "cn"} or not round_text.isdigit() or int(round_text) >= 22:
            continue
        for name in row.get("character_cn", "").split(";"):
            key = normalize_name(name)
            if key in scoped:
                comment_roles[(region, int(round_text))].add(key)
    nico = {
        int(row["round"]): row
        for row in read_csv(OUT / "niconico_early_round_summary.csv")
        if row.get("round", "").isdigit()
    }
    rows: list[dict] = []
    for region, max_round in (("jp", 11), ("cn", 11)):
        min_round = 3 if region == "jp" else 1
        for round_number in range(min_round, max_round + 1):
            eligible = eligible_by_region[region].get(round_number, set())
            event_set = event_roles[(region, round_number)] & eligible
            comment_set = comment_roles[(region, round_number)] & eligible
            any_set = event_set | comment_set
            missing = [scoped[key] for key in eligible if key not in any_set]
            excluded = [scoped[key] for key in scoped if key not in eligible]
            nico_row = nico.get(round_number, {}) if region == "jp" else {}
            rows.append(
                {
                    "poll_region": region,
                    "round": round_number,
                    "scoped_character_count": len(eligible),
                    "eligible_character_count": len(eligible),
                    "pre_appearance_excluded_count": len(excluded),
                    "pre_appearance_excluded_character_cn": ";".join(excluded),
                    "characters_with_direct_event": len(event_set),
                    "characters_with_comment_or_danmaku": len(comment_set),
                    "characters_with_any_curated_social_evidence": len(any_set),
                    "characters_without_curated_social_evidence": len(missing),
                    "missing_character_cn": ";".join(missing),
                    "niconico_round_specific_video_count": nico_row.get("round_specific_video_count", "") if region == "jp" else "",
                    "niconico_title_explicit_character_count": nico_row.get("title_explicit_character_count", "") if region == "jp" else "",
                    "coverage_limit": "空白只表示当前精选表未收录旁证，不表示当年没有讨论；Niconico无角色点名的视频不能转换成逐角色覆盖。",
                }
            )
    write_csv(OUT / "historical_role_coverage_gap.csv", rows, list(rows[0]))


def build_character_true_coverage_gap(
    canon_rows: list[dict],
    event_rows: list[dict],
    supplemental_rows: list[dict],
    tieba_rows: list[dict] | None,
    tieba_fulltext_rows: list[dict] | None,
    jp_rows: list[dict],
    cn_rows: list[dict],
    coverage_rows: list[dict],
) -> None:
    """Materialize character-level gaps after excluding pre-eligibility rounds.

    This table is deliberately separate from the round gap table.  It answers
    "which indexed characters still have no/partial curated social evidence?"
    while retaining each region's actual candidate rounds as the denominator.
    A role is never penalized for a poll held before it appeared in that
    region's candidate/result table.
    """
    scoped_rows = [
        row for row in canon_rows
        if row.get("research_scope") == "included" and row.get("character_cn", "").strip()
    ]
    scoped = {normalize_name(row["character_cn"]): row for row in scoped_rows}
    canon_by_jp = {
        normalize_name(row.get("character_jp", "")): normalize_name(row.get("character_cn", ""))
        for row in scoped_rows if row.get("character_jp", "").strip()
    }

    def eligible(rows: list[dict], region: str) -> dict[str, list[int]]:
        result: defaultdict[str, set[int]] = defaultdict(set)
        for row in rows:
            round_text = str(row.get("round", ""))
            if not round_text.isdigit():
                continue
            if region == "jp":
                key = normalize_name(row.get("character_cn", ""))
                if key not in scoped:
                    key = canon_by_jp.get(normalize_name(row.get("character", "")), "")
            else:
                key = normalize_name(row.get("character_cn", ""))
            if key in scoped:
                result[key].add(int(round_text))
        return {key: sorted(rounds) for key, rounds in result.items()}

    eligible_jp = eligible(jp_rows, "jp")
    eligible_cn = eligible(cn_rows, "cn")

    # Round-level evidence uses only events/comments that explicitly identify
    # a poll region and round.  Context-only videos remain overall evidence but
    # are not retroactively attached to a poll round.
    round_evidence: defaultdict[tuple[str, int], set[str]] = defaultdict(set)
    for row in event_rows:
        region = row.get("poll_region_alignment", "")
        if region not in {"jp", "cn"}:
            continue
        names = (row.get("character_cn", "") or "").split(";")
        keys = {normalize_name(name) for name in names if normalize_name(name) in scoped}
        for field in ("poll_round_before", "poll_round_after"):
            value = str(row.get(field, ""))
            if value.isdigit() and int(value) < 22:
                for key in keys:
                    round_evidence[(region, int(value))].add(key)
    for row in tieba_rows or []:
        region = row.get("poll_region_alignment", "")
        value = str(row.get("related_round", ""))
        if region not in {"jp", "cn"} or not value.isdigit() or int(value) >= 22:
            continue
        names = (row.get("character_mentions_cn", "") or row.get("character_cn", "")).split(";")
        for name in names:
            key = normalize_name(name)
            if key in scoped:
                round_evidence[(region, int(value))].add(key)
    for row in load_qualitative_samples():
        region = row.get("poll_region_alignment", "")
        value = str(row.get("related_round", ""))
        if region not in {"jp", "cn"} or not value.isdigit() or int(value) >= 22:
            continue
        for name in (row.get("character_cn", "") or "").split(";"):
            key = normalize_name(name)
            if key in scoped:
                round_evidence[(region, int(value))].add(key)

    coverage_by_key = {normalize_name(row.get("character_cn", "")): row for row in coverage_rows}
    rows: list[dict] = []
    for key, canon in scoped.items():
        jp_rounds = eligible_jp.get(key, [])
        cn_rounds = eligible_cn.get(key, [])
        jp_missing = [r for r in jp_rounds if key not in round_evidence[("jp", r)]]
        cn_missing = [r for r in cn_rounds if key not in round_evidence[("cn", r)]]
        coverage = coverage_by_key.get(key, {})
        overall_evidence = any(
            int(float(coverage.get(field) or 0)) > 0
            for field in (
                "event_count", "comment_or_danmaku_sample_count",
                "bilibili_query_or_title_hit_count", "tieba_evidence_count",
                "tieba_fulltext_comment_sample_count", "pixiv_tag_count_snapshot",
            )
        )
        if not overall_evidence:
            status = "no_curated_social_evidence"
        elif jp_missing or cn_missing:
            status = "partial_round_coverage"
        else:
            status = "all_eligible_rounds_have_round_evidence"
        rows.append({
            "character_cn": canon.get("character_cn", ""),
            "first_appearance": canon.get("first_appearance", ""),
            "first_jp_eligible_round": jp_rounds[0] if jp_rounds else "",
            "first_cn_eligible_round": cn_rounds[0] if cn_rounds else "",
            "eligible_jp_rounds": ";".join(str(r) for r in jp_rounds),
            "eligible_cn_rounds": ";".join(str(r) for r in cn_rounds),
            "missing_early_jp_rounds": ";".join(str(r) for r in jp_missing),
            "missing_early_cn_rounds": ";".join(str(r) for r in cn_missing),
            "event_count": coverage.get("event_count", "0"),
            "comment_or_danmaku_sample_count": coverage.get("comment_or_danmaku_sample_count", "0"),
            "bilibili_query_or_title_hit_count": coverage.get("bilibili_query_or_title_hit_count", "0"),
            "tieba_evidence_count": coverage.get("tieba_evidence_count", "0"),
            "tieba_fulltext_comment_sample_count": coverage.get("tieba_fulltext_comment_sample_count", "0"),
            "pixiv_tag_count_snapshot": coverage.get("pixiv_tag_count_snapshot", ""),
            "eligible_jp_rounds_with_evidence": len(jp_rounds) - sum(1 for r in jp_missing),
            "eligible_cn_rounds_with_evidence": len(cn_rounds) - sum(1 for r in cn_missing),
            "eligible_jp_rounds_without_evidence": len(jp_missing),
            "eligible_cn_rounds_without_evidence": len(cn_missing),
            "gap_status": status,
            "coverage_limit": "登场前届数不进入分母；社媒样本、播放/弹幕与票数分列，空白仅表示当前精选证据未覆盖。",
        })
    rows.sort(key=lambda row: (row["gap_status"], row["character_cn"]))
    if rows:
        write_csv(OUT / "character_true_coverage_gap.csv", rows, list(rows[0]))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    build_bilibili_tables()
    supplemental_rows = build_bilibili_supplemental_table()
    cn_aliases = build_translation_alias_tables()
    tieba_rows, _tieba_comments, tieba_fulltext_rows = build_tieba_tables(cn_aliases)
    jp_rows, cn_rows = add_vote_percentiles(cn_aliases)
    longitudinal_changes(jp_rows, cn_rows)
    build_tieba_round14_twitter_snapshot_alignment(jp_rows)
    event_rows = align_events_with_polls(jp_rows, cn_rows)
    build_full_character_timeline(jp_rows, cn_rows, event_rows)
    build_niconico_early_coverage_audit()
    canon_rows = build_character_canon_coverage(jp_rows)
    build_historical_role_coverage_gap(canon_rows, event_rows, tieba_rows, jp_rows, cn_rows)
    build_character_community_tag_coverage(canon_rows)
    build_character_coverage(event_rows, supplemental_rows, tieba_rows, tieba_fulltext_rows, canon_rows)
    coverage_rows = read_csv(OUT / "community_character_coverage.csv") if (OUT / "community_character_coverage.csv").exists() else []
    build_character_true_coverage_gap(canon_rows, event_rows, supplemental_rows, tieba_rows, tieba_fulltext_rows, jp_rows, cn_rows, coverage_rows)
    build_coverage_summary(canon_rows, coverage_rows)
    build_questionnaire_profiles(jp_rows, cn_rows)
    build_questionnaire_context()
    source_access_status()


if __name__ == "__main__":
    main()
