#!/usr/bin/env python3
"""Build portable analysis tables from the already-downloaded vote data.

Ranking-derived character/music metrics cover CN1-11 and JP3-22. CN10/11
ordinary rankings and CP results come from the complete modern GraphQL base
snapshots; missing values stay empty instead of being turned into zero. A
single comparison table combines official CP rows with co-vote fallback rows
and retains the source marker for every observation.
"""

from __future__ import annotations

import csv
import difflib
import gzip
import hashlib
import json
import math
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping
from zipfile import ZipFile
from xml.etree import ElementTree

try:
    from vote_explorer.data_chunks import logical_file_exists, read_csv_rows
except ImportError:  # pragma: no cover - direct execution from a non-root cwd
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from vote_explorer.data_chunks import logical_file_exists, read_csv_rows


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "vote_explorer" / "data"
ALLOWED_CN = set(range(1, 12))
ADVANCED_CN = set(range(5, 12))
ALLOWED_JP = set(range(3, 23))

# Strict, source-oriented character groups used by the analysis workbench.
# The first four are the same four groups shown by the reference article's
# faceted network.  The remaining entries are ordinary original-setting
# groups.  Membership is deliberately conservative: a character is included
# only when the original material/THBWiki identifies a relationship with the
# group.  Characters that merely appear in a work receive a separate
# ``作品首登：…`` tag below, so a work cohort is never mistaken for a formal
# organisation.
FACTION_ORDER = [
    "红魔馆", "地灵殿", "秘封俱乐部", "神灵庙",
    "博丽神社", "白玉楼", "永远亭", "守矢神社", "命莲寺",
    "妖怪之山", "天界", "地狱", "畜生界", "月之都", "魔界", "妖精", "外界",
]
FACTION_MEMBERS = {
    "红魔馆": ["芙兰朵露·斯卡蕾特", "蕾米莉亚·斯卡蕾特", "十六夜咲夜", "红美铃", "帕秋莉·诺蕾姬", "小恶魔"],
    "地灵殿": ["古明地觉", "古明地恋", "火焰猫燐", "灵乌路空"],
    "秘封俱乐部": ["宇佐见莲子", "莲子（宇佐见莲子）", "玛艾露贝莉·赫恩", "玛艾露贝莉·赫恩（梅莉）", "梅莉（玛艾露贝莉·赫恩）", "宇佐见堇子"],
    "神灵庙": ["丰聪耳神子", "物部布都", "苏我屠自古", "霍青娥", "宫古芳香"],
    "博丽神社": ["博丽灵梦", "高丽野阿吽"],
    "白玉楼": ["西行寺幽幽子", "魂魄妖梦", "魂魄妖忌"],
    "永远亭": ["蓬莱山辉夜", "八意永琳", "铃仙·优昙华院·因幡", "因幡帝", "因幡天为（因幡帝）", "永远亭的妖怪兔", "兔子（玉兔、永远亭的妖怪兔等）", "铃仙二号"],
    "守矢神社": ["东风谷早苗", "八坂神奈子", "洩矢诹访子"],
    "命莲寺": ["圣白莲", "云居一轮", "云山", "村纱水蜜", "寅丸星", "封兽鵺", "幽谷响子"],
    "妖怪之山": ["射命丸文", "犬走椛", "河城荷取", "键山雏", "姬海棠果", "饭纲丸龙", "菅牧典", "天狗", "河童", "河童（含山童）", "河童（山童）"],
    "天界": ["比那名居天子", "永江衣玖"],
    "地狱": ["四季映姬·夜摩仙那度", "小野塚小町"],
    "畜生界": ["骊驹早鬼", "吉吊八千慧", "饕餮尤魔", "庭渡久侘歌", "埴安神袿姬", "杖刀偶磨弓", "天火人血枪", "豫母都日狭美", "日白残无"],
    "月之都": ["绵月丰姬", "绵月依姬", "嫦娥", "月夜见", "月之兔（玉兔）", "月之都的门卫"],
    "魔界": ["神绮", "魅魔", "萨丽爱尔", "露易兹", "梦子", "幻月", "梦月"],
    "妖精": ["琪露诺", "大妖精", "桑尼米尔克", "露娜切露德", "斯塔萨菲雅", "爱塔妮缇拉尔瓦", "克劳恩皮丝", "莉莉霍瓦特（莉莉白）", "莉莉霍瓦特"],
    "外界": ["宇佐见堇子"],
}

# The legacy CN work page is the maintained local translation source.  Recent
# JP ballots contain several works that did not exist when that page was
# captured, so keep their short, user-facing translations here as a small
# auditable supplement.  Unknown titles deliberately fall back to the source
# name instead of silently inventing a translation.
MANUAL_WORK_TRANSLATIONS = {
    "バレットフィリア達の闇市場": "弹幕狂们的黑市",
    "東方獣王園": "东方兽王园",
    "七夕坂夢幻能": "七夕坂梦幻能",
    "東方幻存神籤": "东方幻存神签",
    "東方錦上京": "东方锦上京",
    "霊長新益京": "灵长新益京",
    "虹色のセプテントリオン": "虹色的七星",
    "東方智霊奇伝 反則探偵さとり": "东方智灵奇传 反则侦探觉",
    "東方Project人妖名鑑 宵闇編": "东方Project人妖名鉴 宵暗篇",
    "東方Project人妖名鑑 常世編": "东方Project人妖名鉴 常世篇",
    "東方求聞史紀 / 東方求聞口授": "东方求闻史纪 / 东方求闻口授",
    "東方Project人妖名鑑": "东方Project人妖名鉴",
    "東方文花帖（書籍）": "东方文花帖（书籍）",
    "幺樂団の歴史": "幺乐团的历史",
    "東方剛欲異聞": "东方刚欲异闻",
    "東方靈異伝": "东方灵异传",
    "東方虹龍洞": "东方虹龙洞",
    "The Grimoire of Marisa": "魔理沙的魔导书",
    "The Grimoire of Usami": "宇佐见的魔导书",
    "The Grimoire of Usami 秘封倶楽部異界撮影記録": "宇佐见的魔导书 秘封俱乐部异界摄影记录",
    "蓬莱人形": "蓬莱人形",
}

# ``order`` comes from the local work catalogue and is intentionally kept as
# a stable release-order token rather than a popularity rank.  The supplement
# follows the same monotonic token scheme for works introduced after the
# captured catalogue.
MANUAL_WORK_ORDERS = {
    "バレットフィリア達の闇市場": "game185",
    "東方獣王園": "game190",
    "七夕坂夢幻能": "music110",
    "東方幻存神籤": "novel018",
    "東方錦上京": "game200",
    "霊長新益京": "game210",
    "虹色のセプテントリオン": "music100",
    "東方文花帖（書籍）": "novel003",
    "東方剛欲異聞": "game175",
    "東方求聞史紀 / 東方求聞口授": "novel005",
    "東方Project人妖名鑑": "novel016",
    "The Grimoire of Marisa": "novel007",
    "The Grimoire of Usami": "novel013",
    "The Grimoire of Usami 秘封倶楽部異界撮影記録": "novel013",
    "東方靈異伝": "game010",
    "東方虹龍洞": "game180",
    "蓬莱人形": "music010",
    "東方智霊奇伝 反則探偵さとり": "novel014",
    "東方Project人妖名鑑 宵闇編": "novel016",
    "東方Project人妖名鑑 常世編": "novel017",
    "幺樂団の歴史": "music015",
}

# Calendar order used across games, music CDs and publications.  Dates are the
# first public release/serialization date at month precision where the local
# source does not expose a day.  The display keeps that precision; the numeric
# key simply makes unlike work categories sortable on one timeline.
WORK_RELEASE_DATES = {
    "東方靈異伝": "1997-08", "東方霊異伝": "1997-08", "東方封魔録": "1997-08", "東方夢時空": "1997-12",
    "東方幻想郷": "1998-08", "東方怪綺談": "1998-12", "東方紅魔郷": "2002-08", "蓬莱人形": "2002-12",
    "東方妖々夢": "2003-08", "蓮台野夜行": "2003-12", "東方香霖堂": "2004-01", "東方永夜抄": "2004-08",
    "東方萃夢想": "2004-12", "夢違科学世紀": "2004-12", "東方三月精": "2005-03", "東方文花帖（書籍）": "2005-08",
    "東方花映塚": "2005-08", "東方文花帖": "2005-12", "幺樂団の歴史": "2006-05", "卯酉東海道": "2006-05",
    "大空魔術": "2006-08", "東方求聞史紀 / 東方求聞口授": "2006-12", "東方儚月抄": "2007-06", "東方風神録": "2007-08",
    "東方緋想天": "2008-05", "東方地霊殿": "2008-08", "The Grimoire of Marisa": "2009-07",
    "東方星蓮船": "2009-08", "東方非想天則": "2009-08", "ダブルスポイラー": "2010-03", "東方茨歌仙": "2010-07",
    "妖精大戦争": "2010-08", "未知の花 魅知の旅": "2011-05", "未知の花　魅知の旅": "2011-05",
    "東方神霊廟": "2011-08", "鳥船遺跡": "2012-04", "伊弉諾物質": "2012-08", "東方鈴奈庵": "2012-10",
    "東方心綺楼": "2013-05", "東方輝針城": "2013-08", "弾幕アマノジャク": "2014-05", "東方深秘録": "2015-05",
    "東方紺珠伝": "2015-08", "燕石博物誌": "2016-05", "旧約酒場": "2016-08", "東方文果真報": "2017-03",
    "東方天空璋": "2017-08", "東方憑依華": "2017-12", "秘封ナイトメアダイアリー": "2018-08",
    "The Grimoire of Usami 秘封倶楽部異界撮影記録": "2019-04", "東方鬼形獣": "2019-08",
    "東方智霊奇伝 反則探偵さとり": "2019-10", "東方酔蝶華": "2019-11", "東方Project人妖名鑑 宵闇編": "2020-03",
    "東方Project人妖名鑑 常世編": "2020-10", "東方虹龍洞": "2021-05", "東方剛欲異聞": "2021-10",
    "虹色のセプテントリオン": "2021-12", "バレットフィリア達の闇市場": "2022-08", "東方獣王園": "2023-08",
    "七夕坂夢幻能": "2024-05", "東方幻存神籤": "2024-08", "東方錦上京": "2025-08", "霊長新益京": "2025-12",
}


def read_csv(path: Path, compressed: bool = False) -> list[dict[str, str]]:
    return read_csv_rows(path, compressed=compressed)


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_csv_gzip(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8-sig", newline="", compresslevel=9) as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _work_order_value(order: str, fallback: int = 999999) -> int:
    """Turn catalogue order tokens (game060/music050/novel015) into a key."""
    match = re.fullmatch(r"(game|music|novel)(\d+)(?:.*)?", str(order or "").casefold())
    if not match:
        return fallback
    group = {"game": 0, "music": 1, "novel": 2}[match.group(1)]
    return group * 10000 + int(match.group(2))


def _work_release_date_value(value: str, fallback: int = 99999999) -> int:
    match = re.fullmatch(r"(\d{4})-(\d{2})(?:-(\d{2}))?", str(value or ""))
    if not match:
        return fallback
    return int(match.group(1)) * 10000 + int(match.group(2)) * 100 + int(match.group(3) or 1)


def build_work_catalog() -> list[dict]:
    """Build the shared Chinese work-name/release-order catalogue.

    Every chart that displays a work uses this file.  The source catalogue is
    parsed from the checked-in CN page (which contains ``name``, ``jpname`` and
    the stable ``order`` token); JP modern additions are merged by their
    Japanese title and receive the maintained supplement translation/order.
    """
    rows_by_key: dict[str, dict] = {}
    source = ROOT / "data_raw" / "cn_official_legacy" / "round_09" / "raw" / "pages" / "work" / "m_work__type_workchara.html"
    if source.exists():
        text = source.read_text(encoding="utf-8", errors="replace")
        # The embedded JSON is intentionally kept on one line by the source
        # page.  Reading that line avoids a greedy regex crossing into the
        # neighbouring page configuration objects.
        rows_text = ""
        for line in text.splitlines():
            marker = line.find('"rows"')
            if marker >= 0:
                rows_text = line[line.find(":", marker) + 1 :].strip().rstrip(",")
                break
        if rows_text:
            try:
                source_rows = json.loads(rows_text)
            except json.JSONDecodeError:
                source_rows = []
            for item in source_rows:
                jp = str(item.get("jpname") or item.get("name") or "").strip()
                cn = str(item.get("name") or jp).strip()
                key = normalize_work_name(jp)
                if not key:
                    continue
                order = str(item.get("order") or "").strip()
                # Some legacy rows reuse a Japanese title for a game and a
                # book (文花帖 is the notable case).  Keep the first source
                # row as the canonical game entry; the modern JP rows carry a
                # disambiguating suffix and are added separately below.
                if key in rows_by_key:
                    continue
                rows_by_key[key] = {
                    "catalog_key": key,
                    "entity_id": str(item.get("id") or ""),
                    "name_jp": jp,
                    "name_cn": cn,
                    "release_order": _work_order_value(order),
                    "release_code": order,
                    "source": "cn_legacy_work_catalog",
                }

    # Merge every JP title seen in the normalized rankings so old JP pages and
    # new JP22 works are represented even when the CN catalogue predates them.
    ranking_path = OUT / "rankings.csv"
    ranking_rows = read_csv(ranking_path) if ranking_path.exists() else []
    for item in ranking_rows:
        if item.get("category") != "work" or item.get("region") != "jp":
            continue
        jp = str(item.get("entity_name") or "").strip()
        key = normalize_work_name(jp)
        if not key:
            continue
        row = rows_by_key.get(key)
        if row is None:
            order = MANUAL_WORK_ORDERS.get(jp, "")
            row = {
                "catalog_key": key,
                "entity_id": str(item.get("entity_id") or ""),
                "name_jp": jp,
                "name_cn": MANUAL_WORK_TRANSLATIONS.get(jp, jp),
                "release_order": _work_order_value(order),
                "release_code": order,
                "source": "jp_ranking_fallback",
            }
            rows_by_key[key] = row
        else:
            # Prefer the modern source's canonical ID when available; legacy
            # rows may not carry an entity ID at all.
            if not row.get("entity_id") and item.get("entity_id"):
                row["entity_id"] = str(item.get("entity_id"))
        if jp in MANUAL_WORK_TRANSLATIONS and (not row.get("name_cn") or row["name_cn"] == row.get("name_jp")):
            row["name_cn"] = MANUAL_WORK_TRANSLATIONS[jp]
        if jp in MANUAL_WORK_ORDERS and not row.get("release_code"):
            order = MANUAL_WORK_ORDERS[jp]
            row["release_code"] = order
            row["release_order"] = _work_order_value(order)

    # Add CN-only compilation entries as well.  Their source list does not
    # always expose a JP title, but preserving the Chinese label is still more
    # useful than dropping a selectable work from the all-round dataset.
    for item in ranking_rows:
        if item.get("category") != "work" or item.get("region") != "cn":
            continue
        cn = str(item.get("entity_name_localized") or item.get("entity_name") or "").strip()
        key = normalize_work_name(cn)
        # A translated CN row normally already has a corresponding legacy
        # catalogue entry under its Japanese key.  Match by the catalogue's
        # existing Chinese label first to avoid duplicate work records such as
        # 東方紅魔郷/东方红魔乡.
        existing_cn = next((catalog_key for catalog_key, catalog_row in rows_by_key.items()
                            if normalize_work_name(catalog_row.get("name_cn")) == key), "")
        if existing_cn:
            continue
        # Reuse the maintained JP key when the CN source has a translated
        # spelling that is not Unicode-equivalent to its Japanese title.
        alias_jp = next((jp for jp, translated in MANUAL_WORK_TRANSLATIONS.items()
                         if normalize_work_name(translated) == key), "")
        if alias_jp:
            key = normalize_work_name(alias_jp)
        if not key or key in rows_by_key:
            continue
        rows_by_key[key] = {
            "catalog_key": key,
            "entity_id": str(item.get("entity_id") or ""),
            "name_jp": alias_jp,
            "name_cn": cn,
            "release_order": _work_order_value(MANUAL_WORK_ORDERS.get(alias_jp, "")),
            "release_code": MANUAL_WORK_ORDERS.get(alias_jp, ""),
            "source": "cn_ranking_fallback",
        }

    # Keep maintained modern aliases available even when a title is present
    # only in a questionnaire option (for example the generic 人妖名鑑 entry)
    # and therefore never appears as a ranked JP entity in the local snapshot.
    for jp, cn in MANUAL_WORK_TRANSLATIONS.items():
        key = normalize_work_name(jp)
        if not key or key in rows_by_key:
            continue
        order = MANUAL_WORK_ORDERS.get(jp, "")
        rows_by_key[key] = {
            "catalog_key": key,
            "entity_id": "",
            "name_jp": jp,
            "name_cn": cn,
            "release_order": _work_order_value(order),
            "release_code": order,
            "source": "maintained_modern_translation",
        }

    # Collapse spelling variants that resolve to the same Chinese display
    # name (霊/靈 is the common old/new Japanese variant).  Keep the richer
    # row with a known date and stable source metadata.
    dedup_by_cn: dict[str, dict] = {}
    for row in rows_by_key.values():
        cn_key = normalize_work_name(row.get("name_cn"))
        if not cn_key:
            continue
        previous = dedup_by_cn.get(cn_key)
        if previous is None or (
            not previous.get("name_jp") and row.get("name_jp")
        ) or (
            previous.get("source") == "cn_ranking_fallback" and row.get("source") != "cn_ranking_fallback"
        ):
            dedup_by_cn[cn_key] = row
    rows_by_key = {row["catalog_key"]: row for row in dedup_by_cn.values()}

    for row in rows_by_key.values():
        jp_name = str(row.get("name_jp") or "")
        if jp_name in MANUAL_WORK_TRANSLATIONS:
            row["name_cn"] = MANUAL_WORK_TRANSLATIONS[jp_name]
        release_date = WORK_RELEASE_DATES.get(jp_name, "")
        row["release_date"] = release_date
        if release_date:
            row["release_order"] = _work_release_date_value(release_date)
        else:
            row["release_order"] = 99999999
    output = sorted(rows_by_key.values(), key=lambda row: (integer(row.get("release_order"), 99999999), row.get("name_cn", ""), row.get("name_jp", "")))
    fields = ["catalog_key", "entity_id", "name_jp", "name_cn", "release_date", "release_order", "release_code", "source"]
    write_csv(OUT / "analysis_work_catalog.csv", output, fields)
    return output


def num(value, default=None):
    try:
        return float(value) if str(value).strip() else default
    except (TypeError, ValueError):
        return default


def integer(value, default=0) -> int:
    try:
        return int(float(value)) if str(value).strip() else default
    except (TypeError, ValueError):
        return default


def normalize_name(value: str) -> str:
    return re.sub(r"[\s・･·\-—_]+", "", value or "").casefold()


def normalize_music_title(value: str) -> str:
    """Normalize title punctuation/width without changing entity-name keys.

    The local music tag table mixes translated titles, ASCII punctuation and
    Japanese full-width punctuation (for example ``?`` vs ``？``).  A title
    key may safely ignore Unicode punctuation/symbols, while character
    identity keys continue to use the stricter ``normalize_name`` function.
    """
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    # ``Stone Goddess`` is an editorial suffix found on a few legacy CN rows,
    # not part of the source song title.  Remove only this audited suffix;
    # other ``〜 subtitle`` fragments remain available for exact matching.
    text = re.sub(r"\s*[~〜～]\s*stone\s+goddess\s*$", "", text, flags=re.IGNORECASE)
    return "".join(ch for ch in text if not unicodedata.category(ch).startswith(("P", "S", "Z")))


def _music_title_keys(value: str) -> list[str]:
    """Return exact and conservative alias keys for a music title.

    The local vote tables contain the same song with different punctuation,
    optional ``～ subtitle`` fragments, and occasional parenthesised aliases.
    The full normalized title is always emitted first.  Short aliases are only
    used when the catalogue has a unique match, so similarly named songs are
    not merged merely because they share a word.
    """
    raw = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not raw:
        return []
    keys: list[str] = []
    def add(text: str) -> None:
        key = normalize_music_title(text)
        if key and key not in keys:
            keys.append(key)
    add(raw)
    # A number of legacy tables wrap a title that itself contains a subtitle
    # in parentheses, for example ``天衣无缝（天衣无缝 ～ Yellow Lily）``.
    # Splitting the raw text at ``～`` first leaves an unmatched opening
    # parenthesis, so also emit keys from the parenthesis-stripped form.
    # This keeps the full key first (important for exact matches) while making
    # the base title available for conservative catalogue aliases below.
    without_parenthesised = re.sub(r"[（(][^）)]*[）)]", "", raw).strip()
    if without_parenthesised != raw:
        add(without_parenthesised)
    # Keep the part before a Japanese/ASCII tilde as a useful alias.  This is
    # how the workbook represents titles such as ``少女綺想曲`` while older
    # rounds often include ``～ Dream Battle`` or ``～ Capriccio``.
    for part in re.split(r"\s*[～〜~]\s*", raw):
        part = re.sub(r"[（(][^）)]*[）)]", "", part).strip()
        add(part)
    # Parenthesised title variants (e.g. ``星幽剣士（星幽天使）``) are also
    # valid aliases when they are unique in the authoritative workbook.
    for part in re.findall(r"[（(]([^）)]*)[）)]", raw):
        add(part)
    # Chinese translations in older rounds vary on connective characters
    # (与/和, 的/之).  These compact keys are accepted only when the workbook
    # catalogue has a unique match.
    for key in list(keys):
        compact = re.sub(r"[的之与和]", "", key)
        if compact and compact not in keys:
            keys.append(compact)
    return keys


def _xlsx_cell_value(cell, namespace: str) -> str:
    inline = cell.find(f"{{{namespace}}}is")
    if inline is not None:
        return "".join(node.text or "" for node in inline.iter(f"{{{namespace}}}t"))
    value = cell.find(f"{{{namespace}}}v")
    return (value.text or "") if value is not None else ""


def load_music_catalog() -> tuple[dict[str, dict], dict[str, dict], list[dict]]:
    """Read the root ``TouhouMusicInfo.xlsx`` without requiring openpyxl.

    The workbook is a small single-sheet file whose columns D/E are the
    authoritative Japanese title and Chinese translation.  Reading its XML
    directly keeps this analysis builder usable with the Python standard
    library and avoids a second, subtly different spreadsheet parser.
    """
    path = ROOT / "TouhouMusicInfo.xlsx"
    if not path.exists():
        return {}, {}, []
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    try:
        with ZipFile(path) as archive:
            xml = archive.read("xl/worksheets/sheet1.xml")
        root = ElementTree.fromstring(xml)
    except (OSError, KeyError, ElementTree.ParseError):
        return {}, {}, []
    exact: dict[str, dict] = {}
    aliases: dict[str, list[dict]] = defaultdict(list)
    items: list[dict] = []
    seen_items: set[tuple[str, str]] = set()
    for row in root.findall(f".//{{{namespace}}}row"):
        cells: dict[int, str] = {}
        for cell in row.findall(f"{{{namespace}}}c"):
            ref = str(cell.get("r") or "")
            match = re.match(r"([A-Z]+)", ref)
            if not match:
                continue
            column = 0
            for char in match.group(1):
                column = column * 26 + ord(char) - ord("A") + 1
            cells[column] = _xlsx_cell_value(cell, namespace).strip()
        jp, cn = cells.get(4, ""), cells.get(5, "")
        if not jp and not cn:
            continue
        # The first row is a header in the user-maintained workbook.  It is
        # not a song and must never become an alias for a real source title.
        if jp in {"曲目", "译名"} or cn in {"曲目", "译名"}:
            continue
        item = {"name_jp": jp, "name_cn": cn, "owner": cells.get(9, "")}
        item_key = (jp, cn)
        if item_key not in seen_items:
            seen_items.add(item_key)
            items.append(item)
        for value in (jp, cn):
            for key in _music_title_keys(value)[:1]:
                if key:
                    exact.setdefault(key, item)
            for key in _music_title_keys(value)[1:]:
                if key:
                    aliases[key].append(item)
    unique_aliases = {key: values[0] for key, values in aliases.items()
                      if values and len({(item.get("name_jp"), item.get("name_cn")) for item in values}) == 1}
    return exact, unique_aliases, items


MUSIC_CATALOG_EXACT, MUSIC_CATALOG_ALIASES, MUSIC_CATALOG_ITEMS = load_music_catalog()


def _catalog_base_title(item: dict) -> str:
    """Return the title used by the repaired workbook's theme merge rule."""
    title = item.get("name_cn") or item.get("name_jp") or ""
    # Rows with an owner are the same intentional theme groups used by
    # ``build_music_canonical.py``.  Their subtitle is descriptive metadata,
    # not a separate identity (e.g. 妖々跋扈 ～ Speed Fox!).
    if item.get("owner"):
        title = re.split(r"\s*[～〜~]\s*", title, maxsplit=1)[0]
        title = re.sub(r"[（(][^）)]*[）)]", "", title).strip()
    return title


# Keep all candidates, not only unique aliases.  Prefix aliases are only used
# for a source title when the workbook has a single owned/theme row for that
# base.  This prevents a titled arrangement such as ``花映塚 ～ Higan Retour``
# from being silently collapsed into the unrelated bare ``花映塚`` row while
# still joining the repaired ``少女綺想曲 ～ Capriccio`` variants.
MUSIC_CATALOG_BASE_CANDIDATES: dict[str, list[dict]] = defaultdict(list)
for _item in MUSIC_CATALOG_ITEMS:
    _base_values = [_catalog_base_title(_item)]
    for _value in (_item.get("name_jp", ""), _item.get("name_cn", "")):
        _base_values.extend(_music_title_keys(_value)[1:])
    for _value in _base_values:
        _key = normalize_music_title(_value)
        if _key and _item not in MUSIC_CATALOG_BASE_CANDIDATES[_key]:
            MUSIC_CATALOG_BASE_CANDIDATES[_key].append(_item)


# A small, auditable alias layer for translations used by the old CN tables.
# Targets are Japanese workbook titles, so the displayed names still always
# come from ``TouhouMusicInfo.xlsx``.  Ambiguous placeholders (Plastic Space,
# 曲名不详, 演者選択, etc.) deliberately remain unmatched and are reported in
# ``analysis_music_catalog_unmatched.csv`` rather than being guessed.
MUSIC_MANUAL_ALIAS_TARGETS = {
    "春之岸边": "春の湊に",
    "飞翔在夜晚的鸠山": "夜の鳩山を飛ぶ",
    "飞翔在夜晚的鸠山－Power MIX": "夜の鳩山を飛ぶ",
    "飞翔夜晚的鸠山-Power MIX": "夜の鳩山を飛ぶ",
    "飞越夜晚的鸠山-Power MIX": "夜の鳩山を飛ぶ",
    "玩偶裁判 ～ 玩弄人形的少女": "人形裁判",
    "旅人1969": "ヴォヤージュ1969",
    "旅人1970": "ヴォヤージュ1970",
    "会被稻田公主骂的啦": "稲田姫様に叱られるから",
    "只听见歌声": "もう歌しか聞こえない",
    "战车娘的梦想": "戦車むすめのみるゆめ",
    "天真无邪的二人的博物志": "他愛も無い二人の博物誌",
    "僵硬的乐园": "リジッドパラダイス",
    "古老的叙述者": "古きユアンシェン",
    "天空遗迹": "スカイルーイン",
    "虚假的草莓": "フォルスストロベリー",
    "星空旅人2008": "スターヴォヤージュ2008",
    "桑尼金红石折射": "サニールチルフレクション",
    "境界民俗": "外界フォークロア",
    "妖怪山间无色风": "色無き風は妖怪の山に",
    "到达有顶天": "有頂天変　～ Wonderful Heaven",
    "揭开宴会的秘密": "明かされる深秘",
    "泳于樱色之海": "桜色の海を泳いで",
    "午夜符卡": "ミッドナイトスペルカード",
    "月的另一侧": "向こう側の月",
    "酒鬼的Lamuria": "呑んべぇのレムリア",
}
MUSIC_MANUAL_ALIASES: dict[str, dict] = {}
for _alias, _target in MUSIC_MANUAL_ALIAS_TARGETS.items():
    _target_key = normalize_music_title(_target)
    _target_item = MUSIC_CATALOG_EXACT.get(_target_key)
    if _target_item:
        MUSIC_MANUAL_ALIASES[normalize_music_title(_alias)] = _target_item


def match_music_catalog(*values: str) -> dict | None:
    """Match a source title to the workbook's canonical row."""
    for value in values:
        keys = _music_title_keys(value)
        if not keys:
            continue
        # Only the complete source key is eligible for an exact match.  The
        # remaining keys are aliases (base titles, parenthesised variants), so
        # treating them as exact would incorrectly turn ``妖々跋扈 ～ Speed
        # Fox!`` into the unrelated bare ``妖々跋扈`` row.
        item = MUSIC_CATALOG_EXACT.get(keys[0])
        if item:
            return item
        for key in keys:
            item = MUSIC_MANUAL_ALIASES.get(key)
            if item:
                return item
    for value in values:
        keys = _music_title_keys(value)
        if not keys:
            continue
        has_subtitle = bool(re.search(r"[～〜~]", str(value or "")))
        for key in keys[1:]:
            candidates = MUSIC_CATALOG_BASE_CANDIDATES.get(key, [])
            if not candidates:
                continue
            # Prefer the single owned/theme row.  If a source has a subtitle
            # and the only candidate is an unowned bare row, leave it for the
            # audit report instead of guessing a merge.
            owned = [candidate for candidate in candidates if candidate.get("owner")]
            if has_subtitle and owned:
                if len(owned) == 1:
                    return owned[0]
                continue
            if has_subtitle:
                continue
            if len(candidates) == 1:
                return candidates[0]
    # A few downloaded translations reorder words or use a near-synonym (for
    # example “幽灵客船的时空穿越之旅” vs “幽灵客船的穿越时空之旅”).
    # Resolve only a clearly unique close match; otherwise retain the source
    # title rather than risking a false merge between songs.
    source_keys = []
    fuzzy_threshold = 0.80
    for value in values:
        keys = _music_title_keys(value)
        if not keys:
            continue
        # For titled variants compare the complete title only.  Including a
        # stripped base here would re-introduce the false ``妖々跋扈``/
        # ``花映塚`` merges that the conservative alias pass intentionally
        # avoids.  Untitled translations may still use all generated keys.
        if re.search(r"[～〜~]", str(value or "")):
            source_keys.extend(key for key in keys[:1] if len(key) >= 5)
            fuzzy_threshold = max(fuzzy_threshold, 0.90)
        else:
            source_keys.extend(key for key in keys if len(key) >= 5)
    scored: list[tuple[float, dict]] = []
    for item in MUSIC_CATALOG_ITEMS:
        item_keys = _music_title_keys(item.get("name_jp", "")) + _music_title_keys(item.get("name_cn", ""))
        score = max((difflib.SequenceMatcher(None, source, target).ratio()
                     for source in source_keys for target in item_keys), default=0.0)
        if score >= 0.80:
            scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if scored and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.06):
        return scored[0][1]
    return None


def normalize_work_name(value: str) -> str:
    """Return a tolerant key for work titles used by different source eras."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    # Work titles occasionally differ only by decorative spaces, punctuation,
    # or the old ``DS`` prefix used in the CN legacy table.
    text = re.sub(r"^ds", "", text)
    return "".join(ch for ch in text if not unicodedata.category(ch).startswith(("P", "S", "Z")))


def round_label(region: str, round_no: int) -> str:
    return f"{'CN' if region == 'cn' else 'JP'}{round_no}"


def allowed(region: str, round_no: int) -> bool:
    return round_no in (ALLOWED_CN if region == "cn" else ALLOWED_JP if region == "jp" else set())


def rank_desc(rows: list[dict], value_key: str, out_key: str) -> None:
    available = [row for row in rows if row.get(value_key) not in (None, "")]
    ordered = sorted(available, key=lambda r: (-float(r[value_key]), integer(r.get("rank"), 999999), r.get("name_jp", "")))
    previous = object()
    previous_rank = 0
    for index, row in enumerate(ordered, 1):
        value = float(row[value_key])
        if value != previous:
            previous_rank = index
            previous = value
        row[out_key] = previous_rank


def load_name_maps() -> tuple[dict[str, str], dict[str, str]]:
    jp_to_cn: dict[str, str] = {}
    cn_to_jp: dict[str, str] = {}
    for row in read_csv(ROOT / "metadata" / "character_name_crosswalk.csv"):
        jp = row.get("character_jp", "").strip()
        cn = row.get("character_cn", "").strip()
        if not cn:
            continue
        for value in (jp, row.get("character_jp_normalized", "")):
            if value:
                jp_to_cn[normalize_name(value)] = cn
        if jp:
            cn_to_jp[normalize_name(cn)] = jp
    # JP22 introduced a few characters that are not yet present in the
    # historical crosswalk.  The theme-tag table is the authoritative local
    # mapping for those additions (and is also useful as a fallback for any
    # future JP round-specific names).
    tags_path = ROOT / "metadata" / "jp22_character_theme_tags.csv"
    if tags_path.exists():
        for row in read_csv(tags_path):
            jp = row.get("character_name_jp", "").strip()
            cn = row.get("character_name_cn", "").strip()
            if not jp or not cn:
                continue
            jp_to_cn[normalize_name(jp)] = cn
            cn_to_jp[normalize_name(cn)] = jp
    return jp_to_cn, cn_to_jp


def build_character_metrics(jp_to_cn: dict[str, str], cn_to_jp: dict[str, str]) -> list[dict]:
    rankings = read_csv(OUT / "rankings.csv")
    ballot_map = {
        (row["region"], integer(row["round"]), row["category"]): integer(row.get("valid_vote_count"))
        for row in read_csv(OUT / "ballot_totals.csv")
    }
    detail_items = {
        (integer(row["round"]), normalize_name(row.get("source_name", ""))): row
        for row in read_csv(ROOT / "data_processed" / "jp_official" / "detail_items.csv")
        if row.get("source_category") == "character"
    }

    demographics: dict[tuple[int, str], dict[str, float]] = defaultdict(dict)
    overall_gender: dict[tuple[int, str], float] = {}
    for row in read_csv(ROOT / "data_processed" / "jp_official" / "detail_questionnaire_long.csv"):
        if row.get("source_category") != "character" or row.get("question_key") not in {"sex", "age"}:
            continue
        rnd = integer(row["round"])
        if rnd not in ALLOWED_JP:
            continue
        key = (rnd, normalize_name(row.get("source_name", "")))
        rate = num(row.get("rate"), float("nan"))
        total = num(row.get("total"), float("nan"))
        if row["question_key"] == "sex":
            field = {"男性": "male_rate", "女性": "female_rate", "その他": "other_gender_rate"}.get(row.get("label", ""))
            if field and math.isfinite(rate):
                demographics[key][field] = rate
            if field and math.isfinite(total):
                overall_gender[(rnd, field)] = total
        elif row.get("label") in {"～9歳", "10～14歳", "15～19歳"} and math.isfinite(rate):
            demographics[key]["under20_rate"] = demographics[key].get("under20_rate", 0.0) + rate

    output: list[dict] = []
    for source in rankings:
        region, rnd = source.get("region", ""), integer(source.get("round"))
        if source.get("category") != "character" or not allowed(region, rnd):
            continue
        source_name = source.get("entity_name", "")
        if region == "jp":
            name_jp = source_name
            name_cn = source.get("entity_name_localized", "") or jp_to_cn.get(normalize_name(source_name), "")
        else:
            name_cn = source.get("entity_name_localized", "") or source_name
            name_jp = cn_to_jp.get(normalize_name(name_cn), "")
        detail = detail_items.get((rnd, normalize_name(source_name)), {}) if region == "jp" else {}
        points = num(source.get("points"))
        primary = num(detail.get("primary")) if detail else num(source.get("first_choice_count"))
        secondary = num(detail.get("secondary")) if detail and str(detail.get("secondary", "")).strip() else None
        source_selection = num(source.get("vote_count"))
        if source_selection is not None:
            selection = source_selection
        elif points is not None and primary is not None:
            selection = points - 2 * primary - secondary if rnd >= 21 and secondary is not None else points - primary
        else:
            selection = None
        other = selection - primary - (secondary or 0) if selection is not None and primary is not None else None
        ballots = ballot_map.get((region, rnd, "character"), 0) or None
        demo = demographics.get((rnd, normalize_name(source_name)), {}) if region == "jp" else {}
        canonical = normalize_name(name_cn or name_jp or source_name)
        output.append({
            "region": region, "round": rnd, "round_label": round_label(region, rnd), "category": "character",
            "entity_id": source.get("entity_id", ""), "canonical_name": canonical,
            "name_jp": name_jp, "name_cn": name_cn, "rank": integer(source.get("rank")),
            "points": points if points is not None else "", "primary_count": primary if primary is not None else "",
            "secondary_count": secondary if secondary is not None else "", "other_count": other if other is not None else "",
            "selection_count": selection if selection is not None else "", "ballots": ballots or "",
            "primary_rate": primary / selection if primary is not None and selection else "",
            "secondary_rate": secondary / selection if secondary is not None and selection else "",
            "top2_rate": (primary + secondary) / selection if primary is not None and secondary is not None and selection else "",
            "selection_rate": selection / ballots if selection is not None and ballots else "",
            "male_rate": demo.get("male_rate", ""), "female_rate": demo.get("female_rate", ""),
            "other_gender_rate": demo.get("other_gender_rate", ""), "under20_rate": demo.get("under20_rate", ""),
            "overall_male_rate": overall_gender.get((rnd, "male_rate"), "") if region == "jp" else "",
            "overall_female_rate": overall_gender.get((rnd, "female_rate"), "") if region == "jp" else "",
            "overall_other_gender_rate": overall_gender.get((rnd, "other_gender_rate"), "") if region == "jp" else "",
            "source_type": source.get("source_type", ""),
        })

    by_round: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in output:
        by_round[(row["region"], row["round"])].append(row)
    for rows in by_round.values():
        rank_desc(rows, "selection_count", "equal_rank")

    counterfactual_path = ROOT / "analysis_results" / "social_triangulation" / "round21_character_scoring_counterfactual.csv"
    counterfactual = read_csv(counterfactual_path) if counterfactual_path.exists() else []
    cf_map = {normalize_name(row.get("name", "")): row for row in counterfactual}
    for row in output:
        if row["region"] == "jp" and row["round"] == 21:
            cf = cf_map.get(normalize_name(row["name_jp"]), {})
            row["old_2_1_rank"] = integer(cf.get("counterfactual_rank_2_1")) or ""
            row["old_2_1_points"] = integer(cf.get("counterfactual_points_2_1")) or ""
        elif row["region"] == "jp" and row["round"] <= 20:
            row["old_2_1_rank"], row["old_2_1_points"] = row["rank"], row["points"]
        else:
            row["old_2_1_rank"], row["old_2_1_points"] = "", ""
        row["equal_rank_change"] = row["rank"] - row["equal_rank"] if row.get("equal_rank") else ""

    fields = [
        "region", "round", "round_label", "category", "entity_id", "canonical_name", "name_jp", "name_cn",
        "rank", "equal_rank", "old_2_1_rank", "points", "old_2_1_points", "primary_count", "secondary_count",
        "other_count", "selection_count", "ballots", "primary_rate", "secondary_rate", "top2_rate", "selection_rate",
        "male_rate", "female_rate", "other_gender_rate", "under20_rate", "overall_male_rate", "overall_female_rate",
        "overall_other_gender_rate", "equal_rank_change", "source_type",
    ]
    output.sort(key=lambda r: (0 if r["region"] == "cn" else 1, r["round"], r["rank"], r["canonical_name"]))
    write_csv(OUT / "analysis_character_metrics_all.csv", output, fields)
    return output


def build_character_factions() -> list[dict]:
    """Build an auditable original-setting faction crosswalk.

    THBWiki's character index is used for the source URL and first-appearance
    work.  Formal group memberships below are the conservative hand-curated
    set in ``FACTION_MEMBERS``; a first-appearance tag is emitted separately
    as ``作品首登：…``.  This keeps a work cohort useful for analysis without
    asserting that every character in a game belongs to the same organisation.
    """
    metric_path = OUT / "analysis_character_metrics_all.csv"
    metric_rows = read_csv(metric_path) if metric_path.exists() else []
    unique: dict[str, dict] = {}
    for row in metric_rows:
        key = normalize_name(row.get("canonical_name") or row.get("name_cn") or row.get("name_jp"))
        if key and key not in unique:
            unique[key] = row

    thb_rows = read_csv(ROOT / "metadata" / "thbwiki_official_character_list.csv")
    thb_by_key: dict[str, dict] = {}
    for row in thb_rows:
        for raw in (row.get("canonical_cn_fun", ""), row.get("character_cn_thb", ""), row.get("character_jp", "")):
            key = normalize_name(raw)
            if key and key not in thb_by_key:
                thb_by_key[key] = row

    explicit: dict[str, set[str]] = defaultdict(set)
    for faction, names in FACTION_MEMBERS.items():
        for name in names:
            explicit[normalize_name(name)].add(faction)

    def explicit_for(*values: str) -> set[str]:
        keys = [normalize_name(value) for value in values if value]
        found: set[str] = set()
        for key in keys:
            found.update(explicit.get(key, set()))
            # Some legacy labels append a parenthesised alias or a source
            # qualifier.  Match only a clearly longer alias to avoid broad
            # substring guesses (e.g. a generic "兔子" row).
            for alias, groups in explicit.items():
                if len(alias) >= 4 and ((key.startswith(alias) and len(key) - len(alias) <= 8) or (alias.startswith(key) and len(alias) - len(key) <= 8)):
                    found.update(groups)
        return found

    output: list[dict] = []
    for key, metric in unique.items():
        name_cn = (metric.get("name_cn") or "").strip()
        name_jp = (metric.get("name_jp") or "").strip()
        thb = thb_by_key.get(key) or thb_by_key.get(normalize_name(name_cn)) or thb_by_key.get(normalize_name(name_jp)) or {}
        groups = explicit_for(name_cn, name_jp, key)
        first_work = str(thb.get("first_appearance") or "").strip()
        if first_work:
            groups.add(f"作品首登：{first_work}")
        if not groups:
            groups.add("未分类（暂无可核对原作群体）")
        ordered = sorted(groups, key=lambda value: (FACTION_ORDER.index(value) if value in FACTION_ORDER else (len(FACTION_ORDER) if value.startswith("作品首登：") else len(FACTION_ORDER) + 1), value))
        if any(value in FACTION_ORDER for value in ordered):
            basis = "THBWiki角色资料/原作关系的保守群体映射；可同时属于作品首登标签。"
        elif first_work:
            basis = "仅按THBWiki整理的首次登场作品分组；不等同正式组织阵营。"
        else:
            basis = "暂无足够的一设群体资料，保留为未分类，不参与正式阵营推断。"
        output.append({
            "canonical_name": key,
            "name_cn": name_cn,
            "name_jp": name_jp,
            "factions": ";".join(ordered),
            "primary_faction": next((value for value in ordered if value in FACTION_ORDER), ordered[0]),
            "basis": basis,
            "thbwiki_url": thb.get("thbwiki_url", ""),
            "first_appearance": first_work,
        })
    output.sort(key=lambda row: (row["primary_faction"], row["name_cn"] or row["name_jp"]))
    fields = ["canonical_name", "name_cn", "name_jp", "factions", "primary_faction", "basis", "thbwiki_url", "first_appearance"]
    write_csv(OUT / "analysis_character_factions.csv", output, fields)
    return output


def load_arrangement_counts(region: str = "jp") -> dict[tuple[int, str], dict]:
    """Load THBWiki original-song arrangement counts by vote round and region.

    CN and JP round ordinals are independent calendars.  Keeping the region in
    the source field (``cn_vote_round``/``jp_vote_round``) prevents CN11 from
    accidentally inheriting JP11's release window.
    """
    normalized = str(region or "jp").lower()
    if normalized not in {"jp", "cn"}:
        normalized = "jp"
    suffix = "cn" if normalized == "cn" else "jp"
    path = ROOT / "data_raw" / "thwiki_music" / f"original_song_arrangement_counts_{suffix}_vote_windows.csv"
    output: dict[tuple[int, str], dict] = {}
    if not path.exists():
        return output
    try:
        rows = read_csv(path)
    except (OSError, UnicodeError):
        return output
    for row in rows:
        rnd = integer(row.get(f"{suffix}_vote_round"), 0)
        if rnd <= 0:
            continue
        keys = set()
        for value in (row.get("original_name_jp", ""), row.get("original_name_cn", ""), row.get("original_page", "")):
            keys.update(_music_title_keys(value))
        for key in keys:
            current = output.get((rnd, key))
            if current is None or num(row.get("arrangement_count"), 0) > num(current.get("arrangement_count"), 0):
                output[(rnd, key)] = row
    return output


def load_arrangement_totals() -> dict[str, dict]:
    """Load the crawl-time all-history total for each THBWiki original song.

    ``original_song_arrangement_counts_jp_vote_windows.csv`` stores the
    *increment* between consecutive Japanese vote ends.  The sibling totals
    file stores the all-history count observed by the crawler.  Keeping both
    values separate prevents a window increment from being mislabeled as a
    cumulative total in cross-analysis charts.
    """
    path = ROOT / "data_raw" / "thwiki_music" / "original_song_arrangement_counts.csv"
    output: dict[str, dict] = {}
    if not path.exists():
        return output
    try:
        rows = read_csv(path)
    except (OSError, UnicodeError):
        return output
    for row in rows:
        keys = set()
        for value in (row.get("original_name_jp", ""), row.get("original_name_cn", ""), row.get("original_page", "")):
            keys.update(_music_title_keys(value))
        for key in keys:
            current = output.get(key)
            if current is None or num(row.get("arrangement_count"), 0) > num(current.get("arrangement_count"), 0):
                output[key] = row
    return output


def build_music_metrics() -> list[dict]:
    rankings = read_csv(OUT / "rankings.csv")
    ballot_map = {
        (row["region"], integer(row["round"]), row["category"]): integer(row.get("valid_vote_count"))
        for row in read_csv(OUT / "ballot_totals.csv")
    }
    details = {
        (integer(row["round"]), normalize_name(row.get("source_name", ""))): row
        for row in read_csv(ROOT / "data_processed" / "jp_official" / "detail_items.csv")
        if row.get("source_category") == "music"
    }
    arrangement_counts = {
        "jp": load_arrangement_counts("jp"),
        "cn": load_arrangement_counts("cn"),
    }
    arrangement_totals = load_arrangement_totals()
    output = []
    for source in rankings:
        region, rnd = source.get("region", ""), integer(source.get("round"))
        if source.get("category") != "music" or not allowed(region, rnd):
            continue
        name = source.get("entity_name", "")
        localized = source.get("entity_name_localized", "")
        catalog = match_music_catalog(name, localized)
        standard_jp = (catalog or {}).get("name_jp", "")
        standard_cn = (catalog or {}).get("name_cn", "")
        detail = details.get((rnd, normalize_name(name)), {}) if region == "jp" else {}
        points = num(source.get("points"))
        primary = num(detail.get("primary")) if detail else num(source.get("first_choice_count"))
        secondary = num(detail.get("secondary")) if detail and str(detail.get("secondary", "")).strip() else None
        source_selection = num(source.get("vote_count"))
        if source_selection is not None:
            selection = source_selection
        elif points is not None and primary is not None:
            selection = points - 2 * primary - secondary if rnd >= 21 and secondary is not None else points - primary
        else:
            selection = None
        ballots = ballot_map.get((region, rnd, "music"), 0) or None
        standard_title = _catalog_base_title(catalog) if catalog else (localized or name)
        # JP and CN have separate vote calendars.  A CN round with the same
        # ordinal number (for example CN11) must use the CN release window,
        # never the same-numbered JP interval.
        arrangement = None
        arrangement_total = None
        region_arrangements = arrangement_counts.get(region, {})
        if region in {"jp", "cn"}:
            for value in (standard_jp, standard_cn, name, localized, standard_title):
                for key in _music_title_keys(value):
                    if arrangement is None:
                        arrangement = region_arrangements.get((rnd, key))
                    if arrangement_total is None:
                        arrangement_total = arrangement_totals.get(key)
                    if arrangement and arrangement_total:
                        break
                if arrangement and arrangement_total:
                    break
        output.append({
            "region": region, "round": rnd, "round_label": round_label(region, rnd), "category": "music",
            # Use TouhouMusicInfo.xlsx as the canonical title/translation
            # source whenever a row matches.  This collapses historical
            # punctuation, width, subtitle and translation variants before
            # cross-round joins are calculated; unmatched songs retain their
            # downloaded names and the tolerant fallback key.
            "entity_id": source.get("entity_id", ""),
            # Owned workbook rows use the same subtitle-stripped theme key as
            # the repaired ``local_music_merged.csv`` groups.  This is what
            # joins e.g. 妖々跋扈, Speed Fox and Who done it across every
            # round, while unowned titled arrangements remain distinct.
            "canonical_name": normalize_music_title(standard_title or standard_jp or standard_cn or localized or name),
            "name_jp": standard_jp or (name if region == "jp" else ""),
            "name_cn": standard_cn or (localized or name if region == "cn" else localized),
            "rank": integer(source.get("rank")), "points": points if points is not None else "",
            "primary_count": primary if primary is not None else "", "secondary_count": secondary if secondary is not None else "",
            "selection_count": selection if selection is not None else "", "ballots": ballots or "",
            "primary_rate": primary / selection if primary is not None and selection else "",
            "selection_rate": selection / ballots if selection is not None and ballots else "",
            "comment_count": source.get("comment_count", ""), "source_type": source.get("source_type", ""),
            "catalog_matched": "1" if catalog else "",
            "catalog_owner": (catalog or {}).get("owner", ""),
            "arrangement_count": num(arrangement.get("arrangement_count"), None) if arrangement else "",
            "arrangement_cumulative_count": num(arrangement.get("arrangement_cumulative_count"), None) if arrangement else "",
            "undated_arrangement_count": num(arrangement.get("undated_arrangement_count"), None) if arrangement else "",
            "arrangement_total_count": num(arrangement_total.get("arrangement_count"), None) if arrangement_total else "",
        })

    # Several legacy workbooks list the same canonical track more than once
    # (reprints with different subtitles).  Keep one row per canonical song
    # and round so trend charts do not draw overlapping duplicate series.  The
    # additive vote fields are summed; the official merged rank/score is used
    # when the maintained canonical table provides it, otherwise the best
    # source rank is retained.
    merged_rank: dict[tuple[str, int, str], dict] = {}
    merged_path = ROOT / "data_processed" / "music_canonical" / "local_music_merged.csv"
    if merged_path.exists():
        for merged in read_csv(merged_path):
            site, mrnd = merged.get("site", ""), integer(merged.get("round"))
            if not allowed(site, mrnd):
                continue
            values = [merged.get("canonical_track", "")]
            for field in ("source_titles_jp_json", "source_titles_cn_json"):
                try:
                    values.extend(json.loads(merged.get(field) or "[]"))
                except (TypeError, json.JSONDecodeError):
                    pass
            catalog = None
            for value in values:
                catalog = match_music_catalog(value)
                if catalog:
                    break
            base = _catalog_base_title(catalog) if catalog else (merged.get("canonical_track") or "")
            key = normalize_music_title(base)
            if key:
                merged_rank[(site, mrnd, key)] = merged

    grouped: dict[tuple[str, int, str], list[dict]] = defaultdict(list)
    for row in output:
        grouped[(row["region"], row["round"], row["canonical_name"])].append(row)
    aggregated: list[dict] = []
    additive_fields = ("points", "primary_count", "secondary_count", "selection_count", "comment_count")
    for key, rows_for_song in grouped.items():
        row = dict(min(rows_for_song, key=lambda item: integer(item.get("rank"), 999999)))
        for field in additive_fields:
            values = [num(item.get(field), None) for item in rows_for_song]
            values = [value for value in values if value is not None]
            row[field] = sum(values) if values else ""
        merged = merged_rank.get(key)
        if merged:
            row["rank"] = integer(merged.get("merged_rank"), integer(row.get("rank"), 999999))
            merged_score = num(merged.get("score"), None)
            if merged_score is not None:
                row["points"] = merged_score
            for field, source_field in (("primary_count", "primary_count"), ("comment_count", "comment_count")):
                merged_value = num(merged.get(source_field), None)
                if merged_value is not None:
                    row[field] = merged_value
        ballots = [num(item.get("ballots"), None) for item in rows_for_song]
        ballots = [value for value in ballots if value is not None]
        row["ballots"] = ballots[0] if ballots else ""
        primary = num(row.get("primary_count"), None)
        secondary = num(row.get("secondary_count"), None)
        selection = num(row.get("selection_count"), None)
        ballots_value = num(row.get("ballots"), None)
        row["primary_rate"] = primary / selection if primary is not None and selection else ""
        row["selection_rate"] = selection / ballots_value if selection is not None and ballots_value else ""
        row["catalog_matched"] = "1" if any(item.get("catalog_matched") for item in rows_for_song) else ""
        arrangement_values = [num(item.get("arrangement_count"), None) for item in rows_for_song]
        cumulative_values = [num(item.get("arrangement_cumulative_count"), None) for item in rows_for_song]
        undated_values = [num(item.get("undated_arrangement_count"), None) for item in rows_for_song]
        total_values = [num(item.get("arrangement_total_count"), None) for item in rows_for_song]
        arrangement_values = [value for value in arrangement_values if value is not None]
        cumulative_values = [value for value in cumulative_values if value is not None]
        undated_values = [value for value in undated_values if value is not None]
        total_values = [value for value in total_values if value is not None]
        row["arrangement_count"] = max(arrangement_values) if arrangement_values else ""
        row["arrangement_cumulative_count"] = max(cumulative_values) if cumulative_values else ""
        row["undated_arrangement_count"] = max(undated_values) if undated_values else ""
        row["arrangement_total_count"] = max(total_values) if total_values else ""
        row["source_type"] = ";".join(dict.fromkeys(item.get("source_type", "") for item in rows_for_song if item.get("source_type")))
        row["source_row_count"] = len(rows_for_song)
        aggregated.append(row)
    output = aggregated
    by_round: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in output:
        by_round[(row["region"], row["round"])].append(row)
    for rows in by_round.values():
        rank_desc(rows, "selection_count", "equal_rank")
    fields = [
        "region", "round", "round_label", "category", "entity_id", "canonical_name", "name_jp", "name_cn",
        "rank", "equal_rank", "points", "primary_count", "secondary_count", "selection_count", "ballots",
        "primary_rate", "selection_rate", "comment_count", "arrangement_count", "arrangement_cumulative_count", "undated_arrangement_count", "arrangement_total_count", "source_type", "catalog_matched", "catalog_owner", "source_row_count",
    ]
    output.sort(key=lambda r: (0 if r["region"] == "cn" else 1, r["round"], r["rank"], r["canonical_name"]))
    write_csv(OUT / "analysis_music_metrics_all.csv", output, fields)
    return output


CHARACTER_LINK_METRICS = [
    "rank", "equal_rank", "old_2_1_rank", "points", "old_2_1_points", "primary_count", "secondary_count",
    "other_count", "selection_count", "ballots", "primary_rate", "secondary_rate", "top2_rate", "selection_rate",
    "male_rate", "female_rate", "other_gender_rate", "under20_rate", "overall_male_rate", "overall_female_rate",
    "overall_other_gender_rate",
]
MUSIC_LINK_METRICS = [
    "rank", "equal_rank", "points", "primary_count", "secondary_count", "selection_count", "ballots",
    "primary_rate", "selection_rate", "comment_count", "arrangement_count", "arrangement_cumulative_count", "undated_arrangement_count", "arrangement_total_count",
]


def build_character_music_links(characters: list[dict], music: list[dict], jp_to_cn: dict[str, str]) -> list[dict]:
    """Materialise the user's music→character tags as an analysis dataset.

    ``local_music_merged.csv`` is keyed by site/round/rank and contains the
    curated ``mapped_characters_json`` field.  Matching by rank within the
    same ballot avoids trying to infer identity from translated song titles.
    Every emitted row points at the canonical keys used by the metrics tables,
    so the workbench can aggregate either side without fuzzy matching.
    """
    source_path = ROOT / "data_processed" / "music_canonical" / "local_music_merged.csv"
    if not source_path.exists():
        empty_fields = [
            "region", "round", "round_label", "character_canonical", "character_name_cn", "character_name_jp",
            "music_canonical", "music_name_cn", "music_name_jp", "association_source",
        ] + [f"character_{field}" for field in CHARACTER_LINK_METRICS] + [f"music_{field}" for field in MUSIC_LINK_METRICS]
        write_csv(OUT / "analysis_character_music_links_all.csv", [], empty_fields)
        return []

    character_index: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in characters:
        character_index[(row.get("region", ""), integer(row.get("round")))].append(row)
    # Ranks are not unique in the official tables (ties are common), so a
    # rank-only dictionary silently drops songs.  Index by normalized title
    # first and keep a list per rank only as a conservative fallback.  Titles
    # use a punctuation/width-tolerant key because the local table mixes
    # translated and Japanese spellings.
    music_by_name: dict[tuple[str, int, str], list[dict]] = defaultdict(list)
    music_by_rank: dict[tuple[str, int, int], list[dict]] = defaultdict(list)
    for row in music:
        site, rnd = row.get("region", ""), integer(row.get("round"))
        for title in (row.get("name_jp", ""), row.get("name_cn", ""), row.get("canonical_name", "")):
            for key in _music_title_keys(title):
                music_by_name[(site, rnd, key)].append(row)
        music_by_rank[(site, rnd, integer(row.get("rank")))].append(row)
    output: list[dict] = []
    for merged in read_csv(source_path):
        site = merged.get("site", "")
        rnd = integer(merged.get("round"))
        if not allowed(site, rnd):
            continue
        try:
            ranks = json.loads(merged.get("source_ranks_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            ranks = []
        rank = integer(ranks[0]) if ranks else integer(merged.get("merged_rank"))
        music_row = None
        title_candidates = [merged.get("canonical_track", "")]
        for field in ("source_titles_jp_json", "source_titles_cn_json"):
            try:
                title_candidates.extend(json.loads(merged.get(field) or "[]"))
            except (TypeError, json.JSONDecodeError):
                pass
        for title in title_candidates:
            keys = _music_title_keys(title)
            catalog = match_music_catalog(title)
            if catalog:
                keys.extend(key for key in _music_title_keys(catalog.get("name_jp", "")) if key not in keys)
            for key in keys:
                candidates = music_by_name.get((site, rnd, key), [])
                if candidates:
                    same_rank = [candidate for candidate in candidates if integer(candidate.get("rank"), -1) == rank]
                    music_row = same_rank[0] if same_rank else candidates[0]
                    break
            if music_row is not None:
                break
        if music_row is None:
            ranked_candidates = music_by_rank.get((site, rnd, rank), [])
            if ranked_candidates:
                music_row = ranked_candidates[0]
        if not music_row:
            continue
        try:
            mapped = json.loads(merged.get("mapped_characters_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            mapped = []
        expanded: list[str] = []
        for value in mapped:
            # Some repaired workbook cells contain several roles in one tag.
            expanded.extend(part.strip() for part in str(value).split("|") if part.strip())
        for raw_character in dict.fromkeys(expanded):
            candidate = None
            raw_key = normalize_name(raw_character)
            for row in character_index[(site, rnd)]:
                if raw_key in {normalize_name(row.get("name_cn", "")), normalize_name(row.get("name_jp", ""))}:
                    candidate = row
                    break
            if not candidate and site == "jp":
                translated = jp_to_cn.get(raw_key, "")
                candidate = next((row for row in character_index[(site, rnd)]
                                  if normalize_name(row.get("name_cn", "")) == normalize_name(translated)), None)
            if not candidate:
                continue
            relation = {
                "region": site, "round": rnd, "round_label": round_label(site, rnd),
                "character_canonical": candidate.get("canonical_name", ""),
                "character_name_cn": candidate.get("name_cn", ""), "character_name_jp": candidate.get("name_jp", ""),
                "music_canonical": music_row.get("canonical_name", ""),
                "music_name_cn": music_row.get("name_cn", ""), "music_name_jp": music_row.get("name_jp", ""),
                "association_source": "local_music_merged.mapped_characters_json",
            }
            relation.update({f"character_{field}": candidate.get(field, "") for field in CHARACTER_LINK_METRICS})
            relation.update({f"music_{field}": music_row.get(field, "") for field in MUSIC_LINK_METRICS})
            output.append(relation)
    fields = [
        "region", "round", "round_label", "character_canonical", "character_name_cn", "character_name_jp",
        "music_canonical", "music_name_cn", "music_name_jp", "association_source",
    ] + [f"character_{field}" for field in CHARACTER_LINK_METRICS] + [f"music_{field}" for field in MUSIC_LINK_METRICS]
    output.sort(key=lambda row: (0 if row["region"] == "cn" else 1, row["round"], integer(row["character_rank"], 999999), integer(row["music_rank"], 999999)))
    write_csv(OUT / "analysis_character_music_links_all.csv", output, fields)
    return output


def build_character_music_covote(characters: list[dict], music: list[dict], jp_to_cn: dict[str, str]) -> list[dict]:
    """Extract official character→music conditional voting counts.

    JP17–22 detail pages and CN10/11 advanced-condition checkpoints publish,
    for every character, the music selected by that character's voters.
    ``count`` is therefore the observable character/music intersection and
    ``rate`` is P(music | character voters who used the music department),
    not an estimate from marginal popularity.
    """
    fields = [
        "region", "round", "round_label", "character_canonical", "character_name_cn", "character_name_jp",
        "character_rank", "character_selection_count", "character_ballots", "music_canonical",
        "music_name_cn", "music_name_jp", "music_rank", "music_selection_count", "music_ballots",
        "intersection_count", "conditional_denominator", "conditional_rate", "music_overall_rate", "lift", "source",
    ]
    output: list[dict] = []
    # A title can occur more than once in a tied/legacy table; keep all rows
    # and prefer an exact rank match when resolving a conditional entry.
    music_by_name: dict[tuple[str, int, str], list[dict]] = defaultdict(list)
    for row in music:
        rnd = integer(row.get("round"))
        for value in (row.get("name_jp", ""), row.get("name_cn", "")):
            for key in _music_title_keys(value):
                music_by_name[(row.get("region", ""), rnd, key)].append(row)
    character_by_name = {
        (integer(row.get("round")), normalize_name(row.get("name_jp") or row.get("name_cn", ""))): row
        for row in characters if row.get("region") == "jp"
    }
    raw_root = ROOT / "data_raw" / "jp_official"
    for rnd in sorted(ALLOWED_JP):
        detail_dir = raw_root / f"round_{rnd}" / "detail" / "character"
        if not detail_dir.exists():
            continue
        for path in sorted(detail_dir.glob("*.json"), key=lambda item: integer(item.stem, 999999)):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                data = payload.get("data", {})
            except (OSError, json.JSONDecodeError):
                continue
            source_name = str(data.get("name", "")).strip()
            character = character_by_name.get((rnd, normalize_name(source_name)))
            if not character:
                # A few source pages use spacing variants; fall back to the
                # translated crosswalk and then canonical Chinese key.
                translated = jp_to_cn.get(normalize_name(source_name), "")
                character = next((row for (rr, _), row in character_by_name.items()
                                  if rr == rnd and normalize_name(row.get("name_cn", "")) == normalize_name(translated)), None)
            if not character:
                continue
            others = data.get("others") or {}
            music_section = others.get("music") or {}
            entries = music_section.get("count") or []
            if isinstance(entries, dict):
                entries = [entries]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                title = str(entry.get("label", "")).strip()
                music_row = None
                keys = _music_title_keys(title)
                catalog = match_music_catalog(title)
                if catalog:
                    keys.extend(key for key in _music_title_keys(catalog.get("name_jp", "")) if key not in keys)
                for key in keys:
                    candidates = music_by_name.get(("jp", rnd, key), [])
                    if candidates:
                        music_row = candidates[0]
                        break
                if not music_row:
                    continue
                intersection = num(entry.get("count"))
                conditional_rate = num(entry.get("rate"))
                overall_rate = num(entry.get("total"))
                lift = conditional_rate / overall_rate if conditional_rate is not None and overall_rate else None
                output.append({
                    "region": "jp", "round": rnd, "round_label": round_label("jp", rnd),
                    "character_canonical": character.get("canonical_name", ""),
                    "character_name_cn": character.get("name_cn", ""), "character_name_jp": character.get("name_jp", ""),
                    "character_rank": character.get("rank", ""), "character_selection_count": character.get("selection_count", ""),
                    "character_ballots": character.get("ballots", ""),
                    "music_canonical": music_row.get("canonical_name", ""),
                    "music_name_cn": music_row.get("name_cn", ""), "music_name_jp": music_row.get("name_jp", ""),
                    "music_rank": music_row.get("rank", ""), "music_selection_count": music_row.get("selection_count", ""),
                    "music_ballots": music_row.get("ballots", ""), "intersection_count": intersection or "",
                    "conditional_denominator": (intersection / conditional_rate) if intersection is not None and conditional_rate else "",
                    "conditional_rate": conditional_rate if conditional_rate is not None else "",
                    "music_overall_rate": overall_rate if overall_rate is not None else "",
                    "lift": lift if lift is not None else "",
                    "source": f"jp_official/round_{rnd}/detail/character/{path.stem}.json",
                })
    # CN10/11 checkpoints contain the same direction explicitly: a character
    # condition followed by the complete music ranking for that cohort.  Use
    # numMusic as the conditional denominator so P(music|character) is
    # compared with the music-department marginal on the same eligibility
    # basis. This is the cross-department analogue of ordinary lift.
    for rnd in (10, 11):
        response_dir = ROOT / "data_raw" / "cn_official" / f"round_{rnd:02d}" / "advanced_conditions" / "responses" / "character_any"
        if not response_dir.exists():
            continue
        character_by_cn = {normalize_name(row.get("name_cn") or row.get("name_jp")): row
                           for row in characters if row.get("region") == "cn" and integer(row.get("round")) == rnd}
        for path in sorted(response_dir.glob("source_*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                context, data = payload.get("context", {}), payload.get("data", {})
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                continue
            character = character_by_cn.get(normalize_name(str(context.get("sourceName") or "")))
            global_stats = data.get("queryGlobalStats") or {}
            conditional_denominator = integer(global_stats.get("numMusic"), 0)
            entries = (data.get("queryMusicRanking") or {}).get("entries") or []
            if not character or not conditional_denominator or not isinstance(entries, list):
                continue
            for entry in entries:
                title = str(entry.get("name") or "").strip() if isinstance(entry, dict) else ""
                if not title:
                    continue
                music_row = None
                keys = _music_title_keys(title)
                catalog = match_music_catalog(title)
                if catalog:
                    keys.extend(key for key in _music_title_keys(catalog.get("name_cn", "")) if key not in keys)
                    keys.extend(key for key in _music_title_keys(catalog.get("name_jp", "")) if key not in keys)
                for key in keys:
                    candidates = music_by_name.get(("cn", rnd, key), [])
                    if candidates:
                        music_row = candidates[0]
                        break
                if not music_row:
                    continue
                intersection = num(entry.get("voteCount"), None)
                overall_rate = num(music_row.get("selection_rate"), None)
                if intersection is None or not overall_rate:
                    continue
                conditional_rate = intersection / conditional_denominator
                output.append({
                    "region": "cn", "round": rnd, "round_label": round_label("cn", rnd),
                    "character_canonical": character.get("canonical_name", ""), "character_name_cn": character.get("name_cn", ""),
                    "character_name_jp": character.get("name_jp", ""), "character_rank": character.get("rank", ""),
                    "character_selection_count": character.get("selection_count", ""), "character_ballots": character.get("ballots", ""),
                    "music_canonical": music_row.get("canonical_name", ""), "music_name_cn": music_row.get("name_cn", ""),
                    "music_name_jp": music_row.get("name_jp", ""), "music_rank": music_row.get("rank", ""),
                    "music_selection_count": music_row.get("selection_count", ""), "music_ballots": music_row.get("ballots", ""),
                    "intersection_count": intersection, "conditional_denominator": conditional_denominator,
                    "conditional_rate": conditional_rate, "music_overall_rate": overall_rate,
                    "lift": conditional_rate / overall_rate,
                    "source": str(path.relative_to(ROOT)).replace("\\", "/"),
                })
    output.sort(key=lambda row: (row["region"], row["round"], integer(row.get("character_rank"), 999999), -num(row.get("intersection_count"), 0), row.get("music_name_jp", "")))
    write_csv(OUT / "analysis_character_music_covote_all.csv", output, fields)
    return output


def _split_combination_members(value: str) -> list[str]:
    """Split a CP/combination label while preserving its official order."""
    return [part.strip() for part in re.split(r"\s*(?:×|x|X|＊|\*|／|/|，|,|、|\|)\s*", str(value or "")) if part.strip() and part.strip() not in {"-", "－"}]


def build_cp_metrics() -> list[dict]:
    """Normalize official CP/组合 rankings into a dedicated analysis table."""
    rankings = read_csv(OUT / "rankings.csv")
    ballot_map = {(r.get("region", ""), integer(r.get("round")), r.get("category", "")): integer(r.get("valid_vote_count"), 0) for r in read_csv(OUT / "ballot_totals.csv")}
    output: list[dict] = []
    for row in rankings:
        if row.get("category") != "cp" or not allowed(row.get("region", ""), integer(row.get("round"))):
            continue
        members = _split_combination_members(row.get("entity_name_localized") or row.get("entity_name"))
        if len(members) < 2:
            continue
        region, rnd = row.get("region", ""), integer(row.get("round"))
        label = " × ".join(members)
        key_members = [normalize_name(m) for m in members]
        # Two-member CP relations are unordered for cross-round matching;
        # preserve the official order for three-member combinations.
        combination_key = (
            "|".join(sorted(key_members))
            if len(members) == 2
            else "|".join(key_members)
        )
        votes = num(row.get("vote_count"), None)
        ballots = ballot_map.get((region, rnd, "cp"), 0) or None
        output.append({
            "region": region, "round": rnd, "round_label": round_label(region, rnd),
            "combination_key": combination_key,
            "combination_label": label, "member_count": len(members),
            "name_a": members[0], "name_b": members[1], "name_c": members[2] if len(members) > 2 else "",
            "rank": integer(row.get("rank")), "vote_count": votes if votes is not None else "",
            "first_choice_count": num(row.get("first_choice_count"), None) if row.get("first_choice_count") not in (None, "") else "",
            "points": num(row.get("points"), None) if row.get("points") not in (None, "") else "",
            "vote_rate": votes / ballots if votes is not None and ballots else "", "ballots": ballots or "",
            "source_type": row.get("source_type", ""), "source_path": row.get("source_path", ""),
        })
    output.sort(key=lambda r: (0 if r["region"] == "cn" else 1, r["round"], r["rank"], r["combination_label"]))
    fields = ["region", "round", "round_label", "combination_key", "combination_label", "member_count", "name_a", "name_b", "name_c", "rank", "vote_count", "first_choice_count", "points", "vote_rate", "ballots", "source_type", "source_path"]
    write_csv(OUT / "analysis_cp_metrics_all.csv", output, fields)
    return output


def build_vote_combinations(cp_rows: list[dict], covote_rows: list[dict]) -> list[dict]:
    """Create one comparison-ready table for official CP and co-vote fallback.

    Every row carries ``data_source`` and ``fallback_used``.  Consumers can
    compare a combination across rounds without mistaking a co-vote estimate
    for an official CP ballot: official CP rows win whenever available for a
    given round/key, while a co-vote row fills only a missing CP observation.
    """
    output: list[dict] = []
    official_keys: set[tuple[str, int, str]] = set()
    for row in cp_rows:
        key = (row.get("region", ""), integer(row.get("round")), row.get("combination_key", ""))
        official_keys.add(key)
        if not row.get("name_c", ""):
            official_keys.add((row.get("region", ""), integer(row.get("round")), "|".join(sorted(normalize_name(m) for m in (row.get("name_a", ""), row.get("name_b", ""))))))
        output.append({
            "region": row.get("region", ""), "round": integer(row.get("round")), "round_label": row.get("round_label", ""),
            "combination_key": row.get("combination_key", ""), "combination_label": row.get("combination_label", ""),
            "name_a": row.get("name_a", ""), "name_b": row.get("name_b", ""), "name_c": row.get("name_c", ""),
            "rank": row.get("rank", ""), "comparison_count": row.get("vote_count", ""), "comparison_rate": row.get("vote_rate", ""),
            "cp_rank": row.get("rank", ""), "cp_vote_count": row.get("vote_count", ""), "covote_count": "",
            "data_source": "official_cp", "fallback_used": "false", "source_type": row.get("source_type", ""), "source_path": row.get("source_path", ""),
        })
    # Co-vote pairs become fallback observations only for rounds where the
    # same ordered member key has no official CP result.  A pair key is sorted
    # because co-vote matrices are symmetric, whereas CP labels retain member
    # order in their own key.
    for row in covote_rows:
        # Music×music pairs are kept for the dedicated concentration/network
        # analysis, but must not be presented as CP fallback combinations.
        if row.get("source_type") == "cn10_11_official_music_covote_matrix":
            continue
        members = [str(row.get("name_a_cn") or row.get("name_a") or "").strip(), str(row.get("name_b_cn") or row.get("name_b") or "").strip()]
        if not all(members) or normalize_name(members[0]) == normalize_name(members[1]):
            continue
        key_members = sorted(normalize_name(m) for m in members)
        key = (row.get("region", ""), integer(row.get("round")), "|".join(key_members))
        if key in official_keys:
            continue
        output.append({
            "region": row.get("region", ""), "round": integer(row.get("round")), "round_label": row.get("round_label", ""),
            "combination_key": "|".join(key_members), "combination_label": " × ".join(members),
            "name_a": members[0], "name_b": members[1], "name_c": "", "rank": "",
            "comparison_count": row.get("intersection_count", ""), "comparison_rate": row.get("share", ""),
            "cp_rank": "", "cp_vote_count": "", "covote_count": row.get("intersection_count", ""),
            "data_source": "co-vote_fallback", "fallback_used": "true", "source_type": row.get("source_type", ""), "source_path": row.get("source_path", ""),
        })
    fields = ["region", "round", "round_label", "combination_key", "combination_label", "name_a", "name_b", "name_c", "rank", "comparison_count", "comparison_rate", "cp_rank", "cp_vote_count", "covote_count", "data_source", "fallback_used", "source_type", "source_path"]
    output.sort(key=lambda r: (0 if r["region"] == "cn" else 1, r["round"], -num(r.get("comparison_count"), 0), r["combination_label"]))
    write_csv(OUT / "analysis_vote_combinations_all.csv", output, fields)
    return output


def build_covote_pairs(metrics: list[dict], jp_to_cn: dict[str, str], music_metrics: list[dict] | None = None) -> list[dict]:
    """Build all in-scope co-vote rows.

    JP rows come from the unified directional association extract.  CN10/11
    additionally have complete reconstructed character matrices under
    ``data_raw/cn_official/round_XX/covote/characters.json``; those cells are
    imported with the same metrics and an explicit source marker.
    """
    metric_map = {(row["region"], row["round"], normalize_name(row["name_jp"] or row["name_cn"])): row for row in metrics}
    directions: dict[tuple[int, str, str], dict] = {}
    source = ROOT / "data_processed" / "jp_unified" / "entity_association_long.csv.gz"
    with gzip.open(source, "rt", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            rnd = integer(row.get("round"))
            if rnd not in ALLOWED_JP or row.get("source_category") != "character" or row.get("target_category") != "character":
                continue
            a, b = row.get("source_name", ""), row.get("target_name", "")
            if not a or not b or normalize_name(a) == normalize_name(b):
                continue
            key = (rnd, normalize_name(a), normalize_name(b))
            current = directions.get(key)
            if current is None or integer(row.get("intersection_count")) > integer(current.get("intersection_count")):
                directions[key] = row

    pair_directions: dict[tuple[int, str, str], list[dict]] = defaultdict(list)
    for (rnd, source_key, target_key), row in directions.items():
        a, b = sorted((source_key, target_key))
        pair_directions[(rnd, a, b)].append(row)

    output: list[dict] = []
    for (rnd, a_key, b_key), rows in pair_directions.items():
        ma = metric_map.get(("jp", rnd, a_key)); mb = metric_map.get(("jp", rnd, b_key))
        if not ma or not mb:
            continue
        intersections = [integer(row.get("intersection_count")) for row in rows if str(row.get("intersection_count", "")).strip()]
        if not intersections:
            continue
        ab = max(intersections)
        count_a, count_b = integer(ma.get("selection_count")), integer(mb.get("selection_count"))
        ballots = integer(ma.get("ballots"))
        baseline = count_a * count_b / ballots if ballots and count_a and count_b else None
        lift = ab / baseline if baseline else None
        excess = ab - baseline if baseline is not None else None
        denom = math.sqrt(count_a * (ballots - count_a) * count_b * (ballots - count_b)) if ballots and count_a and count_b else 0
        phi = (ab * ballots - count_a * count_b) / denom if denom else None
        output.append({
            "region": "jp", "round": rnd, "round_label": round_label("jp", rnd),
            "name_a": ma["name_jp"], "name_b": mb["name_jp"],
            "name_a_cn": ma.get("name_cn") or jp_to_cn.get(a_key, ""), "name_b_cn": mb.get("name_cn") or jp_to_cn.get(b_key, ""),
            "canonical_a": ma["canonical_name"], "canonical_b": mb["canonical_name"],
            "rank_a": ma["rank"], "rank_b": mb["rank"], "count_a": count_a or "", "count_b": count_b or "",
            "ballots": ballots or "", "intersection_count": ab,
            "direction_a_to_b": ab / count_a if count_a else "", "direction_b_to_a": ab / count_b if count_b else "",
            "share": ab / ballots if ballots else "", "baseline_count": baseline if baseline is not None else "",
            "lift": lift if lift is not None else "", "excess_count": excess if excess is not None else "",
            "phi": phi if phi is not None else "", "asymmetry": ab / count_a - ab / count_b if count_a and count_b else "",
            "anomaly": "true" if len(set(intersections)) > 1 else "false",
            "anomaly_difference": max(intersections) - min(intersections) if len(set(intersections)) > 1 else 0,
            "directions_found": len(rows), "source_type": "jp_official_entity_association", "source_path": "data_processed/jp_unified/entity_association_long.csv.gz",
        })

    # CN10/11 official conditional matrices are symmetric m00 cells.  The
    # archived JSON includes the full ranking universe, not only the display
    # top-N, so no arbitrary truncation is applied here.
    for rnd in sorted(ALLOWED_CN):
        if rnd < 10:
            continue
        source_path = ROOT / "data_raw" / "cn_official" / f"round_{rnd:02d}" / "covote" / "characters.json"
        if not source_path.exists():
            continue
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
            items = payload.get("data", {}).get("queryCharsCovote", {}).get("items", [])
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            items = []
        if not isinstance(items, list):
            continue
        # CN modern metrics use Chinese display names directly; retain a
        # fallback through the JP→CN crosswalk for any mixed-source cell.
        cn_metrics = {
            normalize_name(row.get("name_cn") or row.get("name_jp")): row
            for row in metrics if row.get("region") == "cn" and integer(row.get("round")) == rnd
        }
        for item in items:
            if not isinstance(item, dict):
                continue
            a_raw, b_raw = str(item.get("a") or "").strip(), str(item.get("b") or "").strip()
            if not a_raw or not b_raw or normalize_name(a_raw) == normalize_name(b_raw):
                continue
            ma = cn_metrics.get(normalize_name(a_raw))
            mb = cn_metrics.get(normalize_name(b_raw))
            if not ma or not mb:
                continue
            try:
                intersection = int(item.get("m00"))
            except (TypeError, ValueError):
                continue
            count_a = integer(ma.get("selection_count"), 0)
            count_b = integer(mb.get("selection_count"), 0)
            ballots = integer(ma.get("ballots"), 0)
            baseline = count_a * count_b / ballots if ballots and count_a and count_b else None
            lift = intersection / baseline if baseline else None
            excess = intersection - baseline if baseline is not None else None
            denom = math.sqrt(count_a * (ballots - count_a) * count_b * (ballots - count_b)) if ballots and count_a and count_b else 0
            phi = (intersection * ballots - count_a * count_b) / denom if denom else None
            output.append({
                "region": "cn", "round": rnd, "round_label": round_label("cn", rnd),
                "name_a": a_raw, "name_b": b_raw,
                "name_a_cn": a_raw, "name_b_cn": b_raw,
                "canonical_a": ma.get("canonical_name", normalize_name(a_raw)),
                "canonical_b": mb.get("canonical_name", normalize_name(b_raw)),
                "rank_a": ma.get("rank", ""), "rank_b": mb.get("rank", ""),
                "count_a": count_a or "", "count_b": count_b or "", "ballots": ballots or "",
                "intersection_count": intersection,
                "direction_a_to_b": intersection / count_a if count_a else "",
                "direction_b_to_a": intersection / count_b if count_b else "",
                "share": intersection / ballots if ballots else "",
                "baseline_count": baseline if baseline is not None else "",
                "lift": lift if lift is not None else "", "excess_count": excess if excess is not None else "",
                "phi": phi if phi is not None else "",
                "asymmetry": intersection / count_a - intersection / count_b if count_a and count_b else "",
                "anomaly": "false", "anomaly_difference": 0, "directions_found": 1,
                "source_type": "cn10_11_official_covote_matrix", "source_path": str(source_path.relative_to(ROOT)).replace("\\", "/"),
            })
        # CN10/11 also publish a complete reconstructed music×music matrix.
        # Keep it in the same portable pair table; source_type lets the UI
        # and concentration analysis distinguish it from character pairs.
        music_path = ROOT / "data_raw" / "cn_official" / f"round_{rnd:02d}" / "covote" / "music.json"
        if music_path.exists() and music_metrics:
            try:
                payload = json.loads(music_path.read_text(encoding="utf-8"))
                items = payload.get("data", {}).get("queryMusicsCovote", {}).get("items", [])
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                items = []
            music_map = {normalize_name(row.get("name_cn") or row.get("name_jp")): row
                         for row in music_metrics if row.get("region") == "cn" and integer(row.get("round")) == rnd}
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                a_raw, b_raw = str(item.get("a") or "").strip(), str(item.get("b") or "").strip()
                if not a_raw or not b_raw or normalize_name(a_raw) == normalize_name(b_raw):
                    continue
                ma, mb = music_map.get(normalize_name(a_raw)), music_map.get(normalize_name(b_raw))
                if not ma or not mb:
                    continue
                try:
                    intersection = int(item.get("m00"))
                except (TypeError, ValueError):
                    continue
                count_a, count_b = integer(ma.get("selection_count"), 0), integer(mb.get("selection_count"), 0)
                ballots = integer(ma.get("ballots"), 0)
                baseline = count_a * count_b / ballots if ballots and count_a and count_b else None
                lift = intersection / baseline if baseline else None
                excess = intersection - baseline if baseline is not None else None
                denom = math.sqrt(count_a * (ballots - count_a) * count_b * (ballots - count_b)) if ballots and count_a and count_b else 0
                phi = (intersection * ballots - count_a * count_b) / denom if denom else None
                output.append({
                    "region": "cn", "round": rnd, "round_label": round_label("cn", rnd),
                    "name_a": a_raw, "name_b": b_raw, "name_a_cn": a_raw, "name_b_cn": b_raw,
                    "canonical_a": ma.get("canonical_name", normalize_name(a_raw)), "canonical_b": mb.get("canonical_name", normalize_name(b_raw)),
                    "rank_a": ma.get("rank", ""), "rank_b": mb.get("rank", ""), "count_a": count_a or "", "count_b": count_b or "", "ballots": ballots or "",
                    "intersection_count": intersection, "direction_a_to_b": intersection / count_a if count_a else "", "direction_b_to_a": intersection / count_b if count_b else "",
                    "share": intersection / ballots if ballots else "", "baseline_count": baseline if baseline is not None else "", "lift": lift if lift is not None else "", "excess_count": excess if excess is not None else "", "phi": phi if phi is not None else "",
                    "asymmetry": intersection / count_a - intersection / count_b if count_a and count_b else "", "anomaly": "false", "anomaly_difference": 0, "directions_found": 1,
                    "source_type": "cn10_11_official_music_covote_matrix", "source_path": str(music_path.relative_to(ROOT)).replace("\\", "/"),
                })
    fields = [
        "region", "round", "round_label", "name_a", "name_b", "name_a_cn", "name_b_cn", "canonical_a", "canonical_b",
        "rank_a", "rank_b", "count_a", "count_b", "ballots", "intersection_count", "direction_a_to_b",
        "direction_b_to_a", "share", "baseline_count", "lift", "excess_count", "phi", "asymmetry", "anomaly",
        "anomaly_difference", "directions_found", "source_type", "source_path",
    ]
    output.sort(key=lambda r: (r["round"], -r["intersection_count"], r["name_a"], r["name_b"]))
    write_csv(OUT / "analysis_covote_pairs_all.csv", output, fields)
    return output


def _cn_question_key(question: str) -> str:
    """Map legacy CN questionnaire labels to the shared analysis keys.

    CN1–4 publish static HTML tables rather than the later conditional API.
    Their numbering and wording vary slightly by round, so only the stable
    concepts used by the workbench receive a shared key; all other questions
    retain a deterministic ``cn_`` key instead of being guessed into a JP
    question.
    """

    cleaned = re.sub(r"^\s*\d+(?:\.\d+)*[.、．]\s*", "", str(question or "")).strip(" ：:")
    aliases = {
        "性别": "sex",
        "您的性别": "sex",
        "年龄阶段": "age",
        "年龄": "age",
        "您的年龄阶段": "age",
        "正式接触东方Project多久": "cognition",
        "正式接触东方多久": "cognition",
        "接触东方的时间": "cognition",
        "接触东方时间": "cognition",
        "参与东方的方式": "usertype",
        "您参与东方的方式": "usertype",
    }
    if cleaned in aliases:
        return aliases[cleaned]
    # Modern CN10/11 wording adds privacy/explanatory parentheticals to the
    # same stable concepts used by CN1–9.  Match only these audited stems so
    # the shared analysis keys remain comparable without broadly guessing.
    if "性别" in cleaned:
        return "sex"
    if "年龄" in cleaned:
        return "age"
    if "从什么时间段开始" in cleaned or "从何时开始" in cleaned or "入坑时间" in cleaned:
        return "cognition"
    if "正式接触东方" in cleaned or cleaned.startswith("接触东方"):
        return "cognition"
    if "参与东方的方式" in cleaned:
        return "usertype"
    key = normalize_name(cleaned)
    return f"cn_{key}" if key else "cn_unknown"


def _cn_questionnaire_rows() -> list[dict]:
    """Normalize the static questionnaire pages published for CN1–9.

    CN1–4 use one table per question (the question is a title row followed by
    ``[answer, count, percent]`` rows).  CN5–9 moved most distributions behind
    the conditional API; their static page only has a compact ``sexTab``
    summary, which is extracted separately.  Tables such as ``基本信息`` and
    ``投票演进`` are deliberately ignored so their column headings cannot be
    mistaken for a question.
    """

    output: list[dict] = []
    for round_number in sorted(ALLOWED_CN):
        path = ROOT / "data_raw" / "cn_official_legacy" / f"round_{round_number:02d}" / "processed" / "questionnaire" / "html_tables.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        tables = payload.get("tables", []) if isinstance(payload, dict) else []
        if not isinstance(tables, list):
            continue
        all_text = " ".join(
            str(cell.get("text", ""))
            for table in tables
            if isinstance(table, dict)
            for row in table.get("rows", [])
            if isinstance(row, list)
            for cell in row
            if isinstance(cell, dict)
        )
        denominator_match = re.search(r"(?:总(?:有效票数|有效问卷数)|问卷[：:]\s*)([0-9][0-9,]*)", all_text)
        denominator = int(denominator_match.group(1).replace(",", "")) if denominator_match else ""

        for table_index, table in enumerate(tables):
            if not isinstance(table, dict):
                continue
            table_id = str(table.get("id") or "").strip()
            heading = str(table.get("heading") or "").strip()
            rows = table.get("rows", [])
            if not isinstance(rows, list) or len(rows) < 2:
                continue

            # CN2/3 expose a second ``stable3`` table for per-entity
            # geography.  It is useful raw evidence, but its province names
            # are not questionnaire options and would otherwise appear as
            # fabricated questions (for example ``cn_广东``) in the
            # workbench's aggregate questionnaire chart.
            if table_id == "stable3":
                continue

            # CN5–9's sexTab embeds the only useful static distribution in a
            # prose summary.  Keep it as the same ``sex`` key used by CN1–4.
            if round_number >= 5 and table_id == "sexTab":
                summary = " ".join(
                    str(cell.get("text", ""))
                    for row in rows
                    if isinstance(row, list)
                    for cell in row
                    if isinstance(cell, dict)
                )
                for answer, pattern in (("男性", r"男性问卷[：:]\s*([0-9][0-9,]*)\s*（?男性比例[：:]\s*([0-9]+(?:\.[0-9]+)?)%"),
                                         ("女性", r"女性问卷[：:]\s*([0-9][0-9,]*)\s*（?女性比例[：:]\s*([0-9]+(?:\.[0-9]+)?)%")):
                    match = re.search(pattern, summary)
                    if not match:
                        continue
                    output.append({
                        "region": "cn", "round": round_number, "round_label": round_label("cn", round_number),
                        "question_key": "sex", "node_path": f"cn/{round_number}/table/{table_index}",
                        "label": answer, "label_jp": "", "work_release_date": "", "work_release_order": "",
                        "value": 0 if answer == "男性" else 1, "count": int(match.group(1).replace(",", "")),
                        "rate": float(match.group(2)) / 100, "denominator": denominator,
                    })
                continue

            # No later static question distributions are present in CN5–9;
            # skipping these tables also avoids emitting ``cn_项目投票人数``.
            if round_number >= 5:
                continue
            if heading in {"调查问卷", "投票群相关"} and table_id not in {"stable", "stable3"}:
                continue

            def cell_text(cell: object) -> str:
                return str(cell.get("text", "")).strip() if isinstance(cell, dict) else ""

            cell_rows = [
                [cell for cell in row if isinstance(cell, dict)]
                for row in rows
                if isinstance(row, list)
            ]
            cell_rows = [row for row in cell_rows if row]
            if not cell_rows:
                continue
            # CN1–4's question title is the first row with no numeric value;
            # location tables may have a heading row plus a separate data
            # table, so the same test naturally skips ``+ 数据`` controls.
            first = cell_rows[0]
            question = " ".join(cell_text(cell) for cell in first).strip(" ：:")
            if not question or question in {"调查问卷", "投票群相关", "原作相关调查", "二次同人相关", "日常相关"}:
                continue
            if question in {"+ 图表", "+ 数据"}:
                continue
            question_key = _cn_question_key(question)
            for option_index, row in enumerate(cell_rows[1:]):
                label = cell_text(row[0]).strip(" ：:") if row else ""
                if not label or label.startswith(("+", "说明", "点击")):
                    continue
                tail_text = " ".join(cell_text(cell) for cell in row[1:])
                # CN1 places ``男性：`` and its statistic in separate cells;
                # accepting the first-cell suffix also covers compact variants.
                stat_text = tail_text or cell_text(row[0])
                count_match = re.search(r"([0-9][0-9,]*)\s*(?:票|人|名)", stat_text)
                if not count_match and tail_text:
                    count_match = re.search(r"([0-9][0-9,]*)", tail_text)
                if not count_match:
                    continue
                rate_match = re.search(r"(?:占|比例[：:]?)\s*([0-9]+(?:\.[0-9]+)?)\s*%", stat_text)
                output.append({
                    "region": "cn", "round": round_number, "round_label": round_label("cn", round_number),
                    "question_key": question_key, "node_path": f"cn/{round_number}/table/{table_index}",
                    "label": label, "label_jp": "", "work_release_date": "", "work_release_order": "",
                    "value": option_index, "count": int(count_match.group(1).replace(",", "")),
                    "rate": float(rate_match.group(1)) / 100 if rate_match else "",
                    "denominator": denominator,
                })
    return output


def _cn_modern_questionnaire_rows() -> list[dict]:
    """Read CN10/11 categorical questionnaire option counts.

    The modern site stores option definitions in ``questionnaire/options.json``
    and archives one filtered GraphQL response per option under ``conditions``.
    Using the published ``totalAnswers`` denominator keeps multi-select
    percentages meaningful (they are allowed to sum above 100%).
    """
    output: list[dict] = []
    for rnd in (10, 11):
        root = ROOT / "data_raw" / "cn_official" / f"round_{rnd:02d}"
        options_path = root / "questionnaire" / "options.json"
        categorical_path = root / "questionnaire" / "categorical_results.json"
        if not options_path.exists():
            continue
        try:
            options = json.loads(options_path.read_text(encoding="utf-8-sig"))
            cat_payload = json.loads(categorical_path.read_text(encoding="utf-8-sig")) if categorical_path.exists() else {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        total_answers: dict[int, int] = {}
        try:
            entries = cat_payload.get("data", {}).get("queryQuestionnaire", {}).get("entries", [])
            for entry in entries if isinstance(entries, list) else []:
                if isinstance(entry, Mapping):
                    raw_qid = str(entry.get("questionId", "")).strip().lstrip("qQ")
                    if not raw_qid.isdigit():
                        continue
                    total = num(entry.get("totalAnswers"), None)
                    if total is not None:
                        total_answers[int(raw_qid)] = int(total)
        except (AttributeError, TypeError, ValueError):
            pass
        for option in options if isinstance(options, list) else []:
            if not isinstance(option, Mapping) or str(option.get("questionType") or "").strip() not in {"Single", "Multiple"}:
                continue
            qid, aid = str(option.get("questionId") or "").strip(), str(option.get("answerId") or "").strip()
            if not qid or not aid:
                continue
            response_path = root / "conditions" / f"q{qid}_a{aid}.json"
            if not response_path.exists():
                continue
            try:
                response = json.loads(response_path.read_text(encoding="utf-8-sig"))
                stats = response.get("data", {}).get("queryGlobalStats", {})
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                continue
            count = num(stats.get("numVote"), None) if isinstance(stats, Mapping) else None
            if count is None:
                continue
            qid_int = int(qid)
            denominator = total_answers.get(qid_int) or num(stats.get("numVote"), None)
            question = str(option.get("question") or "").strip()
            output.append({
                "region": "cn", "round": rnd, "round_label": round_label("cn", rnd),
                "question_key": _cn_question_key(question),
                "node_path": f"cn/{rnd}/question/{qid}/option/{aid}",
                "label": str(option.get("content") or "").strip(), "label_jp": "",
                "work_release_date": "", "work_release_order": "",
                "value": num(option.get("optionIndex"), None), "count": int(count),
                "rate": count / denominator if denominator else "", "denominator": denominator or "",
            })
    return output


def build_questionnaire(work_catalog: list[dict] | None = None) -> list[dict]:
    catalog = work_catalog or []
    by_key: dict[str, dict] = {}
    for item in catalog:
        for raw in (item.get("name_jp", ""), item.get("name_cn", "")):
            key = normalize_work_name(raw)
            if key:
                by_key[key] = item
    output = []
    for row in read_csv(ROOT / "data_processed" / "jp_official" / "questionnaire_long.csv"):
        rnd = integer(row.get("round"))
        if rnd not in ALLOWED_JP:
            continue
        raw_label = row.get("label", "")
        work = by_key.get(normalize_work_name(raw_label))
        output.append({
            "region": "jp", "round": rnd, "round_label": round_label("jp", rnd),
            "question_key": row.get("question_key", ""), "node_path": row.get("node_path", ""),
            "label": work.get("name_cn") if work else raw_label,
            "label_jp": raw_label if work else "",
            "work_release_date": work.get("release_date", "") if work else "",
            "work_release_order": work.get("release_order", "") if work else "",
            "value": row.get("value", ""), "count": row.get("count", ""),
            "rate": row.get("rate", ""),
            "denominator": row.get("conditional_denominator_derived", "") or row.get("valid_count", ""),
        })
    # CN1–4 aggregate pages are static questionnaire result tables.  They are
    # not the later conditional advanced-search API, but are still useful for
    # age/sex/cognition comparisons and must not be silently omitted. CN5–9
    # only expose the compact static sex summary; their detailed conditions
    # are read from the dedicated advanced extract below.
    output.extend(_cn_questionnaire_rows())
    output.extend(_cn_modern_questionnaire_rows())
    fields = ["region", "round", "round_label", "question_key", "node_path", "label", "label_jp", "work_release_date", "work_release_order", "value", "count", "rate", "denominator"]
    write_csv(OUT / "analysis_questionnaire_all.csv", output, fields)
    return output


def build_entity_questionnaire(jp_to_cn: dict[str, str], work_catalog: list[dict] | None = None,
                               character_metrics: list[dict] | None = None,
                               music_metrics: list[dict] | None = None) -> list[dict]:
    work_by_key: dict[str, dict] = {}
    for item in work_catalog or []:
        for raw in (item.get("name_jp", ""), item.get("name_cn", "")):
            key = normalize_work_name(raw)
            if key:
                work_by_key[key] = item
    entity_totals: dict[tuple[str, int, str, str], float] = {}
    for category, rows in (("character", character_metrics or []), ("music", music_metrics or [])):
        for item in rows:
            total = num(item.get("selection_count"), None)
            if total is None:
                continue
            for raw in (item.get("canonical_name", ""), item.get("name_cn", ""), item.get("name_jp", "")):
                key = normalize_name(str(raw or ""))
                if key:
                    entity_totals[(item.get("region", ""), integer(item.get("round")), category, key)] = total
    aggregate_rates: dict[tuple[str, int, str, str], float] = {}
    questionnaire_path = OUT / "analysis_questionnaire_all.csv"
    if questionnaire_path.exists():
        for item in read_csv(questionnaire_path):
            rate = num(item.get("rate"), None)
            if rate is not None:
                aggregate_rates[(item.get("region", ""), integer(item.get("round")), item.get("question_key", ""), str(item.get("label", "")).strip())] = rate
    output = []
    for row in read_csv(ROOT / "data_processed" / "jp_official" / "detail_questionnaire_long.csv"):
        rnd = integer(row.get("round"))
        category = row.get("source_category", "")
        if rnd not in ALLOWED_JP or category not in {"character", "music", "work"}:
            continue
        name = row.get("source_name", "")
        work = work_by_key.get(normalize_work_name(name)) if category == "work" else None
        canonical_source = jp_to_cn.get(normalize_name(name), name) if category == "character" else (work.get("name_cn") if work else name)
        output.append({
            "region": "jp", "round": rnd, "round_label": round_label("jp", rnd), "category": category,
            "entity_id": row.get("source_id", ""),
            "entity_key": f"jp:{rnd:02d}:{category}:{row.get('source_id', '')}" if row.get("source_id", "") else f"jp:{rnd:02d}:{category}:name:{normalize_name(name)}",
            "canonical_name": normalize_work_name(canonical_source) if category == "work" else normalize_name(canonical_source),
            "entity_name": name, "entity_name_localized": work.get("name_cn") if work else (jp_to_cn.get(normalize_name(name), "") if category == "character" else ""),
            "work_release_date": work.get("release_date", "") if work else "",
            "work_release_order": work.get("release_order", "") if work else "",
            "rank": row.get("source_rank", ""), "question_key": row.get("question_key", ""),
            "answer_label": row.get("label", ""), "count": row.get("count", ""), "rate": row.get("rate", ""),
            "overall_rate": row.get("total", ""), "difference_points": row.get("diff", ""),
            "denominator": row.get("conditional_denominator_derived", ""),
            "source_kind": "jp_detail_questionnaire",
        })
    # CN2–4 detail pages publish per-entity vote-group marginals (gender,
    # age, cognition and several round-specific questions).  They predate the
    # CN5–9 conditional API, so keep their provenance explicit while exposing
    # the same matrix/scatter fields to the explorer.
    cn_detail_path = OUT / "cn_legacy_detail_demographics.csv.gz"
    if cn_detail_path.exists():
        for row in read_csv(cn_detail_path, compressed=True):
            rnd = integer(row.get("round"))
            if rnd not in ALLOWED_CN:
                continue
            category = row.get("category", "")
            if category not in {"character", "music", "work"}:
                continue
            entity_name = row.get("entity_name", "")
            localized = row.get("entity_name_localized", "") or entity_name
            count = row.get("count", "")
            denominator = row.get("denominator", "")
            count_n = num(count)
            denom_n = num(denominator)
            rate = num(row.get("rate"), None)
            if rate is None and count_n is not None and denom_n:
                rate = count_n / denom_n
            output.append({
                "region": "cn", "round": rnd, "round_label": round_label("cn", rnd), "category": category,
                "entity_id": row.get("entity_id", ""),
                "entity_key": row.get("entity_key", "") or (f"cn:{rnd:02d}:{category}:{row.get('entity_id', '')}" if row.get("entity_id", "") else f"cn:{rnd:02d}:{category}:name:{normalize_name(localized)}"),
                "canonical_name": normalize_name(localized),
                "entity_name": entity_name, "entity_name_localized": localized,
                "work_release_date": "", "work_release_order": "",
                "rank": "",
                "question_key": row.get("question_key", ""),
                "answer_label": row.get("answer_label", ""),
                "count": count, "rate": rate if rate is not None else "",
                "overall_rate": row.get("overall_rate", ""), "difference_points": "",
                "denominator": denominator,
                "source_kind": row.get("source_kind", "cn_legacy_detail_demographics"),
            })

    # CN5–11 has a bounded official advanced-search extract produced by
    # ``build_vote_dataset.py``.  Merge its questionnaire-conditioned entity
    # rows into the same portable table so the explorer can use the existing
    # question-matrix/scatter views for both regions.  CN1 has no per-entity
    # table; CN2–4 are supplied by the detail-page extract above.  The unified
    # file adds CN10/11 and may contain modern CP aggregate rows, which are
    # kept as their own category instead of being folded into character/music.
    cn_path = OUT / "cn_advanced_questionnaire.csv"
    if not logical_file_exists(cn_path):
        # A pre-unification dataset remains readable for users who have not
        # rebuilt the canonical vote dataset yet.
        cn_path = OUT / "cn_legacy_advanced_questionnaire.csv"
    if logical_file_exists(cn_path):
        for row in read_csv(cn_path):
            rnd = integer(row.get("round"))
            if rnd not in ADVANCED_CN or row.get("condition_family") != "questionnaire_answer":
                continue
            category = row.get("target_category", "")
            if category not in {"character", "music", "work", "cp"}:
                continue
            entity_name = row.get("entity_name", "")
            localized = row.get("entity_name_localized", "")
            count = row.get("vote_count", "")
            cohort_denominator = row.get("expected_cohort", "")
            count_n = num(count)
            question_key = _cn_question_key(row.get("question", ""))
            answer_label = str(row.get("answer", "")).strip()
            entity_key = normalize_name(localized or entity_name)
            entity_total = entity_totals.get(("cn", rnd, category, entity_key))
            # The advanced endpoint conditions on the questionnaire answer,
            # so vote_count/expected_cohort is P(entity|answer).  Entity
            # profiles need the inverse composition P(answer|entity), whose
            # denominator is the entity's overall selection count.
            if category in {"character", "music"} and count_n is not None and entity_total:
                rate = count_n / entity_total
                denominator = entity_total
            else:
                cohort_n = num(cohort_denominator)
                rate = count_n / cohort_n if count_n is not None and cohort_n else ""
                denominator = cohort_denominator
            overall_rate = aggregate_rates.get(("cn", rnd, question_key, answer_label))
            difference = (rate - overall_rate) * 100 if rate != "" and overall_rate is not None else ""
            output.append({
                "region": "cn", "round": rnd, "round_label": round_label("cn", rnd), "category": category,
                "entity_id": row.get("entity_id", ""),
                "entity_key": row.get("entity_key", "") or (f"cn:{rnd:02d}:{category}:{row.get('entity_id', '')}" if row.get("entity_id", "") else f"cn:{rnd:02d}:{category}:name:{normalize_name(localized or entity_name)}"),
                "canonical_name": normalize_name(localized or entity_name),
                "entity_name": entity_name, "entity_name_localized": localized,
                "work_release_date": "", "work_release_order": "",
                "rank": row.get("rank", ""),
                "question_key": question_key,
                "answer_label": answer_label,
                "count": count, "rate": rate, "overall_rate": overall_rate if overall_rate is not None else "",
                "difference_points": difference, "denominator": denominator,
                "source_kind": "cn_advanced_questionnaire",
            })
    fields = [
        "region", "round", "round_label", "category", "entity_id", "entity_key", "canonical_name", "entity_name", "entity_name_localized", "work_release_date", "work_release_order", "rank",
        "question_key", "answer_label", "count", "rate", "overall_rate", "difference_points", "denominator", "source_kind",
    ]
    output.sort(key=lambda r: (r["round"], r["category"], integer(r["rank"], 999999), r["question_key"], r["answer_label"]))
    write_csv_gzip(OUT / "analysis_entity_questionnaire_all.csv.gz", output, fields)
    return output


def build_cn_advanced_pairs() -> list[dict]:
    """Expose the normalized official CN5–11 pair cells to the app data."""

    source = OUT / "cn_advanced_pairs.csv.gz"
    if not source.exists():
        source = OUT / "cn_legacy_advanced_pairs.csv.gz"
    output = []
    if source.exists():
        for row in read_csv(source, compressed=True):
            rnd = integer(row.get("round"))
            if row.get("region") == "cn" and rnd in ADVANCED_CN:
                output.append(row)
    fields = [
        "region", "round", "question1_index", "question1", "question1_token",
        "question1_option_index", "question1_option", "question2_index", "question2",
        "question2_token", "question2_option_index", "question2_option", "count",
        "percent_within_question1_option", "percent_within_question2_option",
        "question1_multi", "question2_multi", "source_path",
    ]
    write_csv_gzip(OUT / "analysis_cn_advanced_pairs_all.csv.gz", output, fields)
    return output


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
        return digest.hexdigest()


def write_music_catalog_unmatched(music: list[dict]) -> list[dict]:
    """Write an auditable list of source songs absent from the standard table."""
    grouped: dict[tuple[str, int, str, str], dict] = {}
    for row in music:
        if row.get("catalog_matched"):
            continue
        key = (row.get("region", ""), integer(row.get("round")), row.get("name_jp", ""), row.get("name_cn", ""))
        item = grouped.setdefault(key, {
            "region": key[0], "round": key[1], "round_label": round_label(key[0], key[1]),
            "name_jp": key[2], "name_cn": key[3], "occurrence_count": 0, "rounds": set(),
        })
        item["occurrence_count"] += integer(row.get("source_row_count"), 1)
        item["rounds"].add(round_label(key[0], key[1]))
    output = []
    for item in grouped.values():
        output.append({**item, "rounds": ",".join(sorted(item["rounds"], key=lambda value: (value[:2], integer(value[2:]))))})
    output.sort(key=lambda row: (0 if row["region"] == "cn" else 1, row["round"], -row["occurrence_count"], row["name_cn"] or row["name_jp"]))
    fields = ["region", "round", "round_label", "name_jp", "name_cn", "occurrence_count", "rounds"]
    write_csv(OUT / "analysis_music_catalog_unmatched.csv", output, fields)
    return output


def main() -> None:
    jp_to_cn, cn_to_jp = load_name_maps()
    work_catalog = build_work_catalog()
    metrics = build_character_metrics(jp_to_cn, cn_to_jp)
    character_factions = build_character_factions()
    music = build_music_metrics()
    unmatched_music = write_music_catalog_unmatched(music)
    character_music_links = build_character_music_links(metrics, music, jp_to_cn)
    character_music_covote = build_character_music_covote(metrics, music, jp_to_cn)
    pairs = build_covote_pairs(metrics, jp_to_cn, music)
    cp_metrics = build_cp_metrics()
    vote_combinations = build_vote_combinations(cp_metrics, pairs)
    questionnaire = build_questionnaire(work_catalog)
    entity_questionnaire = build_entity_questionnaire(jp_to_cn, work_catalog, metrics, music)
    cn_advanced_pairs = build_cn_advanced_pairs()
    # Carry the canonical CN advanced-search coverage contract into the
    # portable analysis manifest when the vote-dataset builder has already
    # produced it.  This is metadata-only; an older bundle remains usable.
    canonical_manifest_path = ROOT / "datasets" / "votes_cn1-9_jp3-22" / "manifest.json"
    canonical_advanced = {}
    if canonical_manifest_path.exists():
        try:
            canonical_manifest = json.loads(canonical_manifest_path.read_text(encoding="utf-8"))
            canonical_advanced = canonical_manifest.get("cn_advanced", {})
        except (OSError, json.JSONDecodeError):
            canonical_advanced = {}
    files = [
        "analysis_character_metrics_all.csv", "analysis_music_metrics_all.csv", "analysis_covote_pairs_all.csv",
        "analysis_cp_metrics_all.csv", "analysis_vote_combinations_all.csv",
        "analysis_character_factions.csv",
        "analysis_questionnaire_all.csv", "analysis_entity_questionnaire_all.csv.gz",
        "analysis_character_music_links_all.csv", "analysis_character_music_covote_all.csv",
        "analysis_work_catalog.csv",
        "analysis_music_catalog_unmatched.csv",
        "analysis_cn_advanced_pairs_all.csv.gz",
    ]
    counts = {
        "analysis_character_metrics_all.csv": len(metrics),
        "analysis_music_metrics_all.csv": len(music),
        "analysis_covote_pairs_all.csv": len(pairs),
        "analysis_cp_metrics_all.csv": len(cp_metrics),
        "analysis_vote_combinations_all.csv": len(vote_combinations),
        "analysis_character_factions.csv": len(character_factions),
        "analysis_questionnaire_all.csv": len(questionnaire),
        "analysis_entity_questionnaire_all.csv.gz": len(entity_questionnaire),
        "analysis_character_music_links_all.csv": len(character_music_links),
        "analysis_character_music_covote_all.csv": len(character_music_covote),
        "analysis_work_catalog.csv": len(work_catalog),
        "analysis_music_catalog_unmatched.csv": len(unmatched_music),
        "analysis_cn_advanced_pairs_all.csv.gz": len(cn_advanced_pairs),
    }
    link_coverage = {}
    for region, rounds in (("cn", ALLOWED_CN), ("jp", ALLOWED_JP)):
        for rnd in sorted(rounds):
            music_rows = [row for row in music if row.get("region") == region and integer(row.get("round")) == rnd]
            link_rows = [row for row in character_music_links if row.get("region") == region and integer(row.get("round")) == rnd]
            link_coverage[round_label(region, rnd)] = {
                "music_rows": len(music_rows),
                "tagged_music_rows": len({row.get("music_canonical", "") for row in link_rows if row.get("music_canonical")}),
                "character_music_relations": len(link_rows),
            }
    manifest = {
        "schema_version": 9,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {"cn_rounds": sorted(ALLOWED_CN), "jp_rounds": sorted(ALLOWED_JP)},
        "excluded_scope": {},
        "availability": {
            "ranking_metrics": "CN1-11, JP3-22",
            "music_metrics": "CN1-11, JP3-22",
            "jp_rich_character_metrics": "JP17-22 (fields vary by round)",
            "covote": "JP11-22 plus complete CN10/11 character and music matrices; source_type distinguishes departments and origins",
            "cp": "Official CP/组合 rankings where published (CN2-11); combination table falls back to co-vote pairs when a CP row is absent",
            "questionnaire": "CN1-11 static/modern aggregate tables plus JP17-22 (question availability varies by round)",
            "entity_questionnaire_links": "CN2-4 official detail-page vote-group marginals, CN5-11 questionnaire-conditioned character/music/CP rows, plus JP17-22 character/music/work",
            "cn_advanced_search": "CN5-11 normalized atomic questionnaire/entity conditions; CN5-9 include the official questionnaire pair matrix; CN10-11 expose Boolean AND/OR queries on demand but no legacy all-answer pair endpoint",
            "cn_advanced_search_contract": "scripts_pipeline/cn_advanced_contract.py",
            "work_catalog": "CN legacy translated catalogue plus maintained JP modern additions; release_order is independent of vote rank",
            "character_factions": "THBWiki-backed conservative original-setting groups plus separate first-appearance work cohorts; unverified characters remain unclassified",
            "character_music_links": "CN1-11, JP3-22 from local_music_merged mapped_character tags",
            "character_music_covote": "CN10-11 official advanced-condition checkpoints plus JP17-22 official character detail pages; count=P(character and music), rate=P(music|character voters participating in music)",
            "music_arrangement_counts": "JP4-22 and CN2-11 THBWiki original-song inter-vote increments, cumulative dated counts through each vote end, and crawl-time all-history totals; CN1 is baseline-only and same-numbered JP/CN rounds use independent calendars",
            "music_arrangement_cross": "JP4-22 and CN2-11 song-vote and character-vote scatter analysis with three selectable x-axis scopes: inter-vote increment, cumulative dated count through vote end, or crawl-time cumulative total; CN1 has no inter-vote increment; character totals deduplicate mapped canonical original songs",
            "music_catalog_standardization": {
                "source": "TouhouMusicInfo.xlsx D/E columns",
                "matched_rows": sum(1 for row in music if row.get("catalog_matched")),
                "total_rows": len(music),
                "coverage": (sum(1 for row in music if row.get("catalog_matched")) / len(music)) if music else 0,
                "unmatched_unique_rows": len(unmatched_music),
                "unmatched_output": "analysis_music_catalog_unmatched.csv",
                "note": "Unmatched titles are retained with source names; no ambiguous fuzzy merge is forced.",
            },
        },
        "character_music_link_coverage": link_coverage,
        "cn_advanced_contract": canonical_advanced,
        "outputs": {name: {"rows": counts[name], "sha256": sha256(OUT / name)} for name in files},
    }
    (OUT / "analysis_data_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"character metrics: {len(metrics)} (CN1-11, JP3-22)")
    print(f"music metrics: {len(music)} (CN1-11, JP3-22)")
    print(f"character-music links: {len(character_music_links)} (CN1-11, JP3-22)")
    print(f"character-music co-vote rows: {len(character_music_covote)} (CN10-11 + JP17-22; official conditional detail)")
    print(f"co-vote pairs: {len(pairs)} (JP11-22 + CN10/11 official matrices)")
    print(f"CP metrics: {len(cp_metrics)}; unified combinations: {len(vote_combinations)} (official CP with co-vote fallback)")
    print(f"questionnaire rows: {len(questionnaire)} (CN1-11 static/modern aggregates + JP17-22; question availability varies)")
    print(f"entity-questionnaire rows: {len(entity_questionnaire)} (CN2-4 detail marginals + CN5-11 advanced + JP17-22)")


if __name__ == "__main__":
    main()
