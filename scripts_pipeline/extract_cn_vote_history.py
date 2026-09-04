"""Extract the complete CN character ranking history from the local workbook.

The workbook is the normalized local copy of all eleven Chinese community polls.
The script preserves the published per-round fields and does not compare weighted
scores across rule changes.
"""

from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "TouhouVote_cn.xlsx"
OUT = ROOT / "metadata" / "cn_vote_history_all_characters.csv"
CROSSWALK_SOURCE = ROOT / "fun.xlsx"
CROSSWALK_OUT = ROOT / "metadata" / "character_name_crosswalk.csv"


def main() -> None:
    workbook = load_workbook(SOURCE, read_only=True, data_only=True)
    rows: list[dict[str, object]] = []
    for sheet_name in workbook.sheetnames:
        sheet = workbook[sheet_name]
        values = sheet.iter_rows(values_only=True)
        headers = [str(value).strip() if value is not None else "" for value in next(values)]
        for raw in values:
            item = dict(zip(headers, raw))
            if item.get("名次") is None or item.get("译名") is None:
                continue
            rows.append(
                {
                    "round": int(sheet_name),
                    "rank": item.get("名次"),
                    "character_cn": item.get("译名"),
                    "vote_count": item.get("票数"),
                    "primary_count": item.get("本命数"),
                    "primary_rate": item.get("本命率"),
                    "weighted_score": item.get("本命加权"),
                    "vote_share": item.get("票数占比"),
                    "primary_share": item.get("本命占比"),
                    "male_count": item.get("男性数"),
                    "male_rate": item.get("男性比例"),
                    "female_count": item.get("女性数"),
                    "female_rate": item.get("女性比例"),
                    "source_path": SOURCE.name,
                    "source_sheet": sheet_name,
                }
            )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUT}")

    mapping_book = load_workbook(CROSSWALK_SOURCE, read_only=True, data_only=True)
    mapping_sheet = mapping_book.active
    mapping_values = mapping_sheet.iter_rows(values_only=True)
    mapping_headers = [str(value).strip() if value is not None else "" for value in next(mapping_values)]
    mapping_rows: list[dict[str, object]] = []
    for raw in mapping_values:
        item = dict(zip(mapping_headers, raw))
        if not item.get("日文名") or not item.get("译名"):
            continue
        mapping_rows.append(
            {
                "character_jp": item["日文名"],
                "character_jp_normalized": str(item["日文名"]).replace(" ", "").replace("　", ""),
                "character_cn": item["译名"],
                "first_appearance_work_id": item.get("首次出现作品"),
                "source_path": CROSSWALK_SOURCE.name,
                "source_sheet": mapping_sheet.title,
            }
        )
    with CROSSWALK_OUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(mapping_rows[0]))
        writer.writeheader()
        writer.writerows(mapping_rows)
    print(f"wrote {len(mapping_rows)} rows to {CROSSWALK_OUT}")


if __name__ == "__main__":
    main()
