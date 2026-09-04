"""Build a reproducible THBWiki character-list reference snapshot.

The graphical list exposes 179 public character cards in the page HTML.  This
script records the card fields while preserving THBWiki's explicit disclaimer:
its inclusion standard is a wiki standard, not an official Touhou opinion.
Nicknames are emitted as low-confidence search vocabulary and are not treated
as canon names or automatically normalized poll labels.
"""

from __future__ import annotations

import csv
import re
import unicodedata
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from lxml import html


ROOT = Path(__file__).resolve().parents[1]
METADATA = ROOT / "metadata"
LIST_URL = "https://thbwiki.cc/官方角色列表"
LIST_STANDARD = "thbwiki_not_official_opinion"


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE).lower()


def text_of(node, xpath: str) -> str:
    values = node.xpath(xpath)
    if not values:
        return ""
    value = values[0]
    if hasattr(value, "text_content"):
        value = value.text_content()
    return re.sub(r"\s+", " ", str(value)).strip()


def fetch_page(url: str) -> bytes:
    parts = urlsplit(url)
    encoded_url = urlunsplit((parts.scheme, parts.netloc, quote(parts.path), parts.query, parts.fragment))
    request = urllib.request.Request(
        encoded_url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; TouhouResearchIndex/1.0; read-only public snapshot)",
            "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def load_crosswalk() -> tuple[dict[str, str], dict[str, str]]:
    by_cn: dict[str, str] = {}
    by_jp: dict[str, str] = {}
    path = METADATA / "character_name_crosswalk.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            cn = row.get("character_cn", "").strip()
            jp = row.get("character_jp", "").strip()
            if cn:
                by_cn.setdefault(normalize_name(cn), cn)
            if cn and jp:
                by_jp.setdefault(normalize_name(jp), cn)
    return by_cn, by_jp


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    document = html.fromstring(fetch_page(LIST_URL), base_url=LIST_URL)
    by_cn, by_jp = load_crosswalk()
    observed = date.today().isoformat()
    rows: list[dict] = []
    for item in document.xpath(
        "//div[contains(concat(' ', normalize-space(@class), ' '), ' chara-item ')]"
    ):
        cn = text_of(item, ".//a[contains(@class,'chara-cnname')]")
        jp = text_of(item, ".//div[contains(@class,'chara-jpname')]")
        en = text_of(item, ".//div[contains(@class,'chara-enname')]")
        nickname = text_of(item, ".//div[contains(@class,'chara-nickname')]")
        first = text_of(item, ".//div[contains(@class,'chara-first')]")
        description = text_of(item, ".//div[contains(@class,'chara-desc')]")
        href = text_of(item, ".//a[contains(@class,'chara-cnname')]/@href")
        if not cn or not href:
            continue
        canonical = by_jp.get(normalize_name(jp), "") or by_cn.get(normalize_name(cn), "")
        if canonical:
            mapping_status = "matched_fun_by_jp_or_cn"
        else:
            mapping_status = "not_in_fun_crosswalk"
        rows.append(
            {
                "character_key_thb": item.get("data-chara", "").strip(),
                "character_cn_thb": cn,
                "character_jp": jp,
                "character_en": en,
                "canonical_cn_fun": canonical,
                "fun_mapping_status": mapping_status,
                "thbwiki_url": urljoin(LIST_URL, href),
                "first_appearance": first,
                "reference_identity_or_title": description,
                "community_nicknames_thb": nickname,
                "appearance_count_thb": item.get("data-showcount", "").strip(),
                "character_type_thb": item.get("data-charatype", "").strip(),
                "source_group_thb": item.get("data-tag", "").strip(),
                "source_type": "thbwiki_official_character_list",
                "list_standard": LIST_STANDARD,
                "observation_date": observed,
                "usage_note": "基础索引字段；角色卡称号、昵称和登场次数是THBWiki整理值，不等于官方认证或人气指标。",
            }
        )

    fields = [
        "character_key_thb", "character_cn_thb", "character_jp", "character_en",
        "canonical_cn_fun", "fun_mapping_status", "thbwiki_url", "first_appearance",
        "reference_identity_or_title", "community_nicknames_thb", "appearance_count_thb",
        "character_type_thb", "source_group_thb", "source_type", "list_standard",
        "observation_date", "usage_note",
    ]
    write_csv(METADATA / "thbwiki_official_character_list.csv", rows, fields)

    candidates: list[dict] = []
    alias_targets: defaultdict[str, set[str]] = defaultdict(set)
    for row in rows:
        canonical = row["canonical_cn_fun"]
        if not canonical:
            continue
        source_name = row["character_cn_thb"]
        if source_name:
            candidates.append(
                {
                    "alias_cn": source_name,
                    "canonical_cn": canonical,
                    "alias_type": "thbwiki_cn_reference_name",
                    "source_character_cn_thb": source_name,
                    "source_character_jp": row["character_jp"],
                    "source_url": row["thbwiki_url"],
                    "mapping_status": "matched_fun_by_jp_or_cn",
                    "confidence": "high",
                    "use_scope": "poll_normalization_and_search",
                }
            )
            alias_targets[normalize_name(source_name)].add(canonical)
        for alias in re.split(r"[，、,;/／；]+", row["community_nicknames_thb"]):
            alias = alias.strip()
            if not alias:
                continue
            candidates.append(
                {
                    "alias_cn": alias,
                    "canonical_cn": canonical,
                    "alias_type": "thbwiki_community_nickname_candidate",
                    "source_character_cn_thb": source_name,
                    "source_character_jp": row["character_jp"],
                    "source_url": row["thbwiki_url"],
                    "mapping_status": "search_only_not_poll_normalized",
                    "confidence": "low",
                    "use_scope": "search_vocabulary_only",
                }
            )
            alias_targets[normalize_name(alias)].add(canonical)

    unique: dict[tuple[str, str, str], dict] = {}
    for row in candidates:
        key = (normalize_name(row["alias_cn"]), row["canonical_cn"], row["alias_type"])
        targets = alias_targets[normalize_name(row["alias_cn"])]
        if len(targets) > 1:
            row["mapping_status"] = "ambiguous_source_characters"
            row["confidence"] = "low"
            row["use_scope"] = "manual_review_only"
        unique.setdefault(key, row)
    alias_rows = sorted(unique.values(), key=lambda row: (row["alias_cn"], row["canonical_cn"], row["alias_type"]))
    alias_fields = [
        "alias_cn", "canonical_cn", "alias_type", "source_character_cn_thb",
        "source_character_jp", "source_url", "mapping_status", "confidence", "use_scope",
    ]
    write_csv(METADATA / "thbwiki_character_alias_candidates_cn.csv", alias_rows, alias_fields)

    print(
        f"THBWiki cards={len(rows)}; fun-mapped={sum(bool(row['canonical_cn_fun']) for row in rows)}; "
        f"alias candidates={len(alias_rows)}"
    )


if __name__ == "__main__":
    main()
