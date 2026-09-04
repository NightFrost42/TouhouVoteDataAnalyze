"""Extract comparable character rows from the locally archived JP polls (rounds 3-21).

The legacy HTML-table parser changed column names over time, so this script maps
headers by Japanese label and keeps raw fields separate. It intentionally does
not harmonize points across scoring-rule changes.
"""

from __future__ import annotations

import csv
import glob
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "metadata" / "vote_history_longitudinal.csv"
OUT_ALL = ROOT / "metadata" / "vote_history_all_characters.csv"

TARGETS = [
    "博麗 霊夢",
    "霧雨 魔理沙",
    "十六夜 咲夜",
    "レミリア・スカーレット",
    "フランドール・スカーレット",
    "魂魄 妖夢",
    "西行寺 幽々子",
    "藤原 妹紅",
    "東風谷 早苗",
    "古明地 さとり",
    "古明地 こいし",
    "稗田 阿求",
    "チルノ",
]

ROUND_DATES = {
    3: "2004-10-17—2004-10-23",
    4: "2005-12-18—2005-12-24",
    5: "2008-02-10—2008-02-16",
    6: "2009-01-18—2009-01-24",
    7: "2010-02-07—2010-02-13",
    8: "2011-02-13—2011-02-19",
    9: "2012-02-19—2012-02-25",
    10: "2014-02-23—2014-03-01",
    11: "2015-05-24—2015-05-30",
    12: "2016-01-10—2016-01-16",
    13: "2017-01-15—2017-01-21",
    14: "2018-01-14—2018-01-20",
    15: "2019-01-27—2019-02-02",
    16: "2020-06-07—2020-06-13",
    17: "2021-09-26—2021-10-03",
    18: "2022-09-17—2022-09-24",
    19: "2023-09-17—2023-09-30",
    20: "2024-08-10—2024-08-23",
    21: "2025-08-16—2025-08-29",
}


def number(text: str) -> str:
    match = re.search(r"[-+]?\d[\d,]*", text or "")
    return match.group(0).replace(",", "") if match else ""


def legacy_path(round_no: int) -> Path:
    candidates = []
    candidates.extend(
        Path(p)
        for p in glob.glob(
            str(ROOT / f"data_raw/jp_official_legacy/round_{round_no:02d}/**/*character*.tables.json"),
            recursive=True,
        )
    )
    candidates.extend(
        Path(p)
        for p in glob.glob(
            str(ROOT / f"data_raw/jp_official_legacy/round_{round_no:02d}/**/result_char.html.tables.json"),
            recursive=True,
        )
    )
    # Prefer the aggregate/list table, not a detail table with a different shape.
    candidates = [p for p in candidates if "aggregate" in p.parts or "lists" in p.parts]
    if not candidates:
        raise FileNotFoundError(f"legacy character table not found for round {round_no}")
    return sorted(set(candidates))[0]


def legacy_rows(round_no: int, targets: set[str] | None = None) -> list[dict[str, str]]:
    path = legacy_path(round_no)
    payload = json.loads(path.read_text(encoding="utf-8"))
    table = payload["numeric_tables"][0]["rows"]
    headers = [cell["text"].strip() for cell in table[0]["cells"]]
    index = {header: i for i, header in enumerate(headers) if header}
    rows: list[dict[str, str]] = []
    for row in table[1:]:
        cells = row["cells"]
        name_index = index.get("名前", 3 if len(cells) >= 4 else 1)
        name = cells[name_index]["text"].strip()
        if targets is not None and name not in targets:
            continue

        def value(*labels: str) -> str:
            for label in labels:
                if label in index and index[label] < len(cells):
                    return cells[index[label]]["text"].strip()
            return ""

        rows.append(
            {
                "round": str(round_no),
                "poll_period": ROUND_DATES[round_no],
                "character": name,
                "rank": number(value("順位")),
                "rank_prev": number(value("前回")),
                "points": number(value("ポイント")),
                "primary_num": number(value("一押し", "1押し")),
                "comment_num": number(value("コメント")),
                "official_support_count": number(value("支援作品", "支援リンク")),
                "score_source": "legacy_official_html_table",
                "source_path": str(path.relative_to(ROOT)).replace("\\", "/"),
            }
        )
    return rows


def modern_rows(round_no: int, targets: set[str] | None = None) -> list[dict[str, str]]:
    path = ROOT / f"data_raw/jp_official/round_{round_no}/aggregate/character.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, str]] = []
    for item in payload["data"]:
        if targets is not None and item["name"] not in targets:
            continue
        rows.append(
            {
                "round": str(round_no),
                "poll_period": ROUND_DATES[round_no],
                "character": item["name"],
                "rank": str(item.get("rank", "")),
                "rank_prev": str(item.get("rank_prev", "") or ""),
                "points": str(item.get("point", "") or ""),
                "primary_num": str(item.get("primary_num", "") or ""),
                "comment_num": str(item.get("comment_num", "") or ""),
                "official_support_count": str(item.get("shien_count", "") or ""),
                "score_source": "modern_official_aggregate_json",
                "source_path": str(path.relative_to(ROOT)).replace("\\", "/"),
            }
        )
    return rows


def main() -> None:
    all_rows: list[dict[str, str]] = []
    for round_no in range(3, 22):
        all_rows.extend(legacy_rows(round_no) if round_no <= 16 else modern_rows(round_no))
    all_rows.sort(key=lambda row: (int(row["round"]), int(row["rank"] or 999999), row["character"]))
    rows = [row for row in all_rows if row["character"] in TARGETS]
    rows.sort(key=lambda row: (int(row["round"]), TARGETS.index(row["character"])))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    for path, output_rows in ((OUT, rows), (OUT_ALL, all_rows)):
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]))
            writer.writeheader()
            writer.writerows(output_rows)
        print(f"wrote {len(output_rows)} rows to {path}")


if __name__ == "__main__":
    main()
