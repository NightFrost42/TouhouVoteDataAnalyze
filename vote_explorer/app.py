"""东方人气投票数据查询与可视化工具。

只使用 Python 标准库和 Tkinter，便于在 Windows 上直接运行和用 PyInstaller
打包。数据随程序放在 data/ 目录，默认范围为 CN1-11 与 JP3-22。
"""

from __future__ import annotations

import csv
import html
import math
import os
import sys
import traceback
import unicodedata
import webbrowser
from collections import defaultdict
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:  # package import (tests) and direct script import (Windows launcher)
    from .resource_paths import BUNDLED_ROOT, DATA_DIR
except ImportError:  # pragma: no cover - exercised by the Windows launcher
    from resource_paths import BUNDLED_ROOT, DATA_DIR

ROOT = BUNDLED_ROOT
RANKINGS_PATH = DATA_DIR / "rankings.csv"
BALLOTS_PATH = DATA_DIR / "ballot_totals.csv"

REGION_LABELS = {"": "全部地区", "cn": "中国区 CN", "jp": "日本区 JP"}
CATEGORY_LABELS = {
    "character": "角色",
    "music": "音乐",
    "work": "作品",
    "cp": "CP/组合",
    "partner": "搭档",
    "spell": "符卡",
    "spell_system": "符卡系统",
    "spell_user_overall": "符卡使用者总榜",
    "overall": "综合榜",
}
METRIC_LABELS = {
    "points": "积分 / 分数",
    "vote_count": "总票数 / 选择人数",
    "weighted_score": "加权分",
    "rank": "名次",
    "first_choice_count": "第一顺位 / 本命票",
}
COLORS = ["#d1495b", "#00798c", "#edae49", "#30638e", "#6a4c93", "#2a9d8f"]
FONT = ("Microsoft YaHei UI", 10)


def normalize_work_name(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.removeprefix("ds")
    return "".join(ch for ch in text if not unicodedata.category(ch).startswith(("P", "S", "Z")))


def load_work_name_map() -> dict[str, str]:
    path = DATA_DIR / "analysis_work_catalog.csv"
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
    except OSError:
        return {}
    mapping: dict[str, str] = {}
    for row in rows:
        cn = str(row.get("name_cn") or "").strip()
        if not cn:
            continue
        for raw in (row.get("name_jp", ""), row.get("name_cn", "")):
            key = normalize_work_name(raw)
            if key:
                mapping[key] = cn
    return mapping


WORK_NAME_MAP = load_work_name_map()


def load_work_order_map() -> dict[str, float]:
    path = DATA_DIR / "analysis_work_catalog.csv"
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
    except OSError:
        return {}
    mapping: dict[str, float] = {}
    for row in rows:
        try:
            order = float(row.get("release_order") or 999999)
        except (TypeError, ValueError):
            order = 999999
        for raw in (row.get("name_jp", ""), row.get("name_cn", "")):
            key = normalize_work_name(raw)
            if key:
                mapping[key] = order
    return mapping


WORK_ORDER_MAP = load_work_order_map()


def read_rows(path: Path) -> list[dict]:
    """读取 UTF-8 CSV，并把可用数值转换成便于排序的类型。"""
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        row["round_int"] = as_int(row.get("round"))
        row["rank_int"] = as_int(row.get("rank"))
        for key in (
            "points",
            "vote_count",
            "first_choice_count",
            "weighted_score",
            "vote_share",
            "first_choice_share",
            "valid_vote_count",
            "valid_primary_count",
            "respondent_count",
        ):
            row[f"{key}_num"] = as_float(row.get(key))
    return rows


def as_int(value: str | None) -> int | None:
    try:
        return int(str(value).strip()) if str(value).strip() else None
    except (TypeError, ValueError):
        return None


def as_float(value: str | None) -> float | None:
    try:
        return float(str(value).strip()) if str(value).strip() else None
    except (TypeError, ValueError):
        return None


def fmt_number(value: float | int | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and value.is_integer():
        return f"{int(value):,}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return f"{value:,}"


def fmt_percent(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.2f}%"


def region_round_label(region: str, round_no: int | None) -> str:
    if round_no is None:
        return "—"
    return f"{'CN' if region == 'cn' else 'JP'}{round_no}"


def metric_value(row: dict, metric: str) -> float | None:
    if metric == "rank":
        return row.get("rank_int")
    return row.get(f"{metric}_num")


def display_name(row: dict) -> str:
    localized = row.get("entity_name_localized")
    if row.get("category") == "work":
        localized = localized or WORK_NAME_MAP.get(normalize_work_name(row.get("entity_name")))
    return localized or row.get("entity_name") or row.get("entity_id") or "（未命名）"


def work_order(row: dict) -> float:
    try:
        if str(row.get("work_release_order") or "").strip():
            return float(row["work_release_order"])
    except (TypeError, ValueError):
        pass
    return WORK_ORDER_MAP.get(normalize_work_name(row.get("entity_name")), 999999)


def xml_text(value: object) -> str:
    return html.escape(str(value), quote=True)


def svg_header(width: int, height: int, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="100%" height="100%" fill="#fffdf8"/>'
        f'<text x="24" y="30" font-family="Microsoft YaHei, sans-serif" font-size="18" '
        f'font-weight="bold" fill="#263238">{xml_text(title)}</text>'
    )


def build_bar_svg(rows: list[dict], metric: str, title: str, width: int = 1100, height: int = 650) -> str:
    rows = rows[:20]
    longest = max((len(display_name(row)) for row in rows), default=8)
    left = min(int(width * .44), max(250, 55 + longest * 11))
    left, top, right, bottom = left, 58, 34, 46
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [metric_value(row, metric) for row in rows]
    numeric = [v for v in values if v is not None]
    if metric == "rank" and numeric:
        ceiling = max(numeric) + 1
        draw_values = [ceiling - (v or ceiling) for v in values]
    else:
        draw_values = [v or 0 for v in values]
    maximum = max(draw_values or [1]) or 1
    chunks = [svg_header(width, height, title)]
    chunks.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#718096"/>')
    for idx, (row, draw_value) in enumerate(zip(rows, draw_values)):
        slot = plot_h / max(1, len(rows))
        y = top + idx * slot + slot * 0.18
        bh = max(6, slot * 0.62)
        bar_w = plot_w * draw_value / maximum
        label = display_name(row)
        shown = f"#{row.get('rank_int')}" if metric == "rank" else fmt_number(metric_value(row, metric))
        chunks.append(f'<text x="{left - 10}" y="{y + bh * .72:.0f}" text-anchor="end" font-family="Microsoft YaHei, sans-serif" font-size="12" fill="#263238">{xml_text(label)}</text>')
        chunks.append(f'<rect x="{left}" y="{y:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" rx="4" fill="{COLORS[idx % len(COLORS)]}"/>')
        chunks.append(f'<text x="{left + bar_w + 7:.1f}" y="{y + bh * .72:.0f}" font-family="Microsoft YaHei, sans-serif" font-size="11" fill="#263238">{xml_text(shown)}</text>')
    chunks.append('</svg>')
    return "".join(chunks)


def build_line_svg(series: list[tuple[str, list[tuple[str, float]]]], metric: str, title: str, width: int = 1100, height: int = 650) -> str:
    left, top, right, bottom = 72, 58, 28, 62
    plot_w, plot_h = width - left - right, height - top - bottom
    all_values = [(-v if metric == "rank" else v) for _, points in series for _, v in points]
    if not all_values:
        return svg_header(width, height, title) + '<text x="80" y="100" font-family="Microsoft YaHei, sans-serif" font-size="14">没有足够数据</text></svg>'
    lo, hi = min(all_values), max(all_values)
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    labels = sorted({x for _, points in series for x, _ in points}, key=lambda x: (x[:2], as_int(x[2:]) or 0))
    chunks = [svg_header(width, height, title)]
    for i in range(5):
        frac = i / 4
        y = top + plot_h * frac
        value = hi - (hi - lo) * frac
        shown_value = -value if metric == "rank" else value
        chunks.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" stroke="#e2e8f0"/>')
        chunks.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" font-family="Microsoft YaHei, sans-serif" font-size="10" fill="#52606d">{xml_text(fmt_number(shown_value))}</text>')
    if labels:
        for i, label in enumerate(labels):
            x = left + plot_w * i / max(1, len(labels) - 1)
            chunks.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_h}" stroke="#edf2f7" stroke-dasharray="2,5"/>')
            chunks.append(f'<text x="{x:.1f}" y="{top + plot_h + 25}" text-anchor="middle" font-family="Microsoft YaHei, sans-serif" font-size="10" fill="#52606d">{xml_text(label)}</text>')
    chunks.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#718096"/>')
    chunks.append(f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#718096"/>')
    for sidx, (name, points) in enumerate(series):
        coords = []
        for label, value in points:
            idx = labels.index(label) if label in labels else 0
            x = left + plot_w * idx / max(1, len(labels) - 1)
            plot_value = -value if metric == "rank" else value
            y = top + (hi - plot_value) / (hi - lo) * plot_h
            coords.append((x, y))
        if len(coords) > 1:
            chunks.append(f'<polyline fill="none" stroke="{COLORS[sidx % len(COLORS)]}" stroke-width="3" points="{" ".join(f"{x:.1f},{y:.1f}" for x,y in coords)}"/>')
        for x, y in coords:
            chunks.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{COLORS[sidx % len(COLORS)]}"/>')
        ly = 38 + sidx * 18
        chunks.append(f'<rect x="{width - 220}" y="{ly - 10}" width="11" height="11" fill="{COLORS[sidx % len(COLORS)]}"/>')
        chunks.append(f'<text x="{width - 202}" y="{ly}" font-family="Microsoft YaHei, sans-serif" font-size="11" fill="#263238">{xml_text(name[:20])}</text>')
    chunks.append('</svg>')
    return "".join(chunks)


class VoteExplorerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("东方人气投票数据查询器（CN1-11 / JP3-22）")
        self.root.geometry("1480x940")
        self.root.minsize(1080, 720)
        self.rows = read_rows(RANKINGS_PATH)
        self.ballots = read_rows(BALLOTS_PATH)
        self.filtered_rows: list[dict] = []
        self.last_bar_rows: list[dict] = []
        self.last_trend_series: list[tuple[str, list[tuple[str, float]]]] = []
        self.last_ballot_series: list[tuple[str, list[tuple[str, float]]]] = []
        self.analysis_workbench = None
        self._build_vars()
        self._build_ui()
        self._populate_filters()
        self.refresh()

    def _build_vars(self) -> None:
        self.region_var = tk.StringVar(value="")
        self.round_var = tk.StringVar(value="全部")
        self.category_var = tk.StringVar(value="全部")
        self.category_display_var = tk.StringVar(value="全部")
        self.search_var = tk.StringVar()
        self.metric_var = tk.StringVar(value="points")
        self.metric_display_var = tk.StringVar(value=METRIC_LABELS["points"])
        self.top_var = tk.StringVar(value="20")
        self.status_var = tk.StringVar()
        self.note_var = tk.StringVar()

    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=25, font=FONT)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))

        filters = ttk.LabelFrame(self.root, text="快速查询")
        filters.pack(fill="x", padx=10, pady=(8, 4))
        for col in range(10):
            filters.columnconfigure(col, weight=0)
        filters.columnconfigure(7, weight=1)
        self._label_combo(filters, 0, "地区", self.region_var, [], self.on_region_changed, width=15)
        self.round_combo = self._label_combo(filters, 2, "届次", self.round_var, [], self.refresh, width=10)
        self.category_combo = self._label_combo(filters, 4, "榜单", self.category_display_var, [], self.on_category_changed, width=18)
        ttk.Label(filters, text="搜索实体").grid(row=0, column=6, padx=(12, 4), pady=8, sticky="e")
        search_entry = ttk.Entry(filters, textvariable=self.search_var, width=28)
        search_entry.grid(row=0, column=7, padx=4, pady=8, sticky="ew")
        search_entry.bind("<Return>", lambda _event: self.refresh())
        ttk.Button(filters, text="查询", command=self.refresh).grid(row=0, column=8, padx=4, pady=8)
        ttk.Button(filters, text="清空", command=self.clear_search).grid(row=0, column=9, padx=(0, 8), pady=8)

        second = ttk.Frame(self.root)
        second.pack(fill="x", padx=10, pady=(0, 4))
        ttk.Label(second, text="图表指标").pack(side="left")
        self.metric_combo = ttk.Combobox(second, textvariable=self.metric_display_var, state="readonly", width=20, values=list(METRIC_LABELS.values()))
        self.metric_combo.pack(side="left", padx=(5, 14))
        self.metric_combo.bind("<<ComboboxSelected>>", lambda _event: self.on_metric_changed())
        ttk.Label(second, text="显示前").pack(side="left")
        self.top_combo = ttk.Combobox(second, textvariable=self.top_var, state="readonly", width=5, values=["10", "20", "30", "50"])
        self.top_combo.pack(side="left", padx=5)
        self.top_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        ttk.Button(second, text="打开文章分析工作台", command=self.open_analysis).pack(side="left", padx=(14, 4))
        ttk.Button(second, text="导出筛选 CSV", command=self.export_csv).pack(side="right", padx=4)
        ttk.Button(second, text="导出当前图 SVG", command=self.export_svg).pack(side="right", padx=4)
        ttk.Button(second, text="打开数据目录", command=self.open_data_dir).pack(side="right", padx=4)

        self.note_label = ttk.Label(self.root, textvariable=self.note_var, foreground="#52606d")
        self.note_label.pack(fill="x", padx=12, pady=(0, 4))

        table_frame = ttk.LabelFrame(self.root, text="查询结果（双击一行可将实体名放入搜索框）")
        table_frame.pack(fill="both", expand=True, padx=10, pady=4)
        columns = ("region", "round", "category", "rank", "name", "points", "votes", "first", "share", "source")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=14)
        headings = {
            "region": "地区", "round": "届次", "category": "榜单", "rank": "名次", "name": "实体",
            "points": "积分", "votes": "总票数/选择人数", "first": "一押/本命", "share": "票占比", "source": "来源",
        }
        widths = {"region": 90, "round": 65, "category": 100, "rank": 60, "name": 250, "points": 95, "votes": 125, "first": 95, "share": 85, "source": 190}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="center" if col not in ("name", "source") else "w")
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", self.on_tree_double_click)

        charts = ttk.LabelFrame(self.root, text="图表（参考分析文章的历届对比思路；积分制度不同的届次请谨慎横向比较）")
        charts.pack(fill="both", expand=True, padx=10, pady=(4, 8))
        self.notebook = ttk.Notebook(charts)
        self.notebook.pack(fill="both", expand=True)
        self.bar_canvas = tk.Canvas(self.notebook, background="#fffdf8", highlightthickness=0)
        self.trend_canvas = tk.Canvas(self.notebook, background="#fffdf8", highlightthickness=0)
        self.ballot_canvas = tk.Canvas(self.notebook, background="#fffdf8", highlightthickness=0)
        self.notebook.add(self.bar_canvas, text="当前榜单柱状图")
        self.notebook.add(self.trend_canvas, text="历届趋势图")
        self.notebook.add(self.ballot_canvas, text="有效投票总量")
        self.bar_canvas.bind("<Configure>", lambda _event: self.draw_bar_chart())
        self.trend_canvas.bind("<Configure>", lambda _event: self.draw_trend_chart())
        self.ballot_canvas.bind("<Configure>", lambda _event: self.draw_ballot_chart())
        self.notebook.bind("<<NotebookTabChanged>>", lambda _event: self.refresh_status())
        self.status = ttk.Label(self.root, textvariable=self.status_var, relief="sunken", anchor="w")
        self.status.pack(fill="x", padx=10, pady=(0, 8))

    def _label_combo(self, parent, col, label, variable, values, callback, width=12):
        ttk.Label(parent, text=label).grid(row=0, column=col, padx=(10 if col else 8, 4), pady=8, sticky="e")
        combo = ttk.Combobox(parent, textvariable=variable, state="readonly", width=width, values=values)
        combo.grid(row=0, column=col + 1, padx=4, pady=8, sticky="w")
        combo.bind("<<ComboboxSelected>>", lambda _event: callback())
        return combo

    def _populate_filters(self) -> None:
        # 第一个组合框没有保存在属性中，直接从 LabelFrame 中按类型查找更稳妥。
        filter_frame = self.root.winfo_children()[0]
        combos = [w for w in filter_frame.winfo_children() if isinstance(w, ttk.Combobox)]
        self.region_combo = combos[0]
        self.region_combo["values"] = [REGION_LABELS[x] for x in ("", "cn", "jp")]
        self.region_combo.bind("<<ComboboxSelected>>", lambda _event: self.on_region_changed())
        self.region_var.set(REGION_LABELS[""])
        self.update_round_and_category_values()

    def selected_region_code(self) -> str:
        value = self.region_var.get()
        reverse = {label: code for code, label in REGION_LABELS.items()}
        return reverse.get(value, value if value in ("cn", "jp") else "")

    def _set_combo_labels(self, combo, labels, variable, value):
        combo["values"] = labels
        variable.set(value)

    def update_round_and_category_values(self) -> None:
        region = self.selected_region_code()
        region_rows = [r for r in self.rows if not region or r.get("region") == region]
        rounds = sorted({r["round_int"] for r in region_rows if r.get("round_int") is not None})
        cats = sorted({r.get("category", "") for r in region_rows if r.get("category")})
        round_values = ["全部"] + [str(x) for x in rounds]
        cat_values = ["全部"] + cats
        if self.round_var.get() not in round_values:
            self.round_var.set("全部")
        if self.category_var.get() not in cat_values:
            self.category_var.set("全部")
        self.round_combo["values"] = round_values
        self.category_combo["values"] = ["全部"] + [CATEGORY_LABELS.get(x, x) for x in cats]
        self.category_display_var.set(CATEGORY_LABELS.get(self.category_var.get(), "全部") if self.category_var.get() != "全部" else "全部")

    def on_region_changed(self) -> None:
        self.update_round_and_category_values()
        self.refresh()

    def on_category_changed(self) -> None:
        reverse = {label: code for code, label in CATEGORY_LABELS.items()}
        self.category_var.set(reverse.get(self.category_display_var.get(), "全部"))
        self.update_round_and_category_values()
        self.refresh()

    def on_metric_changed(self) -> None:
        reverse = {label: code for code, label in METRIC_LABELS.items()}
        self.metric_var.set(reverse.get(self.metric_display_var.get(), "points"))
        self.refresh()

    def clear_search(self) -> None:
        self.search_var.set("")
        self.refresh()

    def filter_rows(self, include_round=True) -> list[dict]:
        region = self.selected_region_code()
        round_value = self.round_var.get()
        category = self.category_var.get()
        query = self.search_var.get().strip().casefold()
        result = []
        for row in self.rows:
            if region and row.get("region") != region:
                continue
            if include_round and round_value != "全部" and row.get("round_int") != as_int(round_value):
                continue
            if category != "全部" and row.get("category") != category:
                continue
            haystack = " ".join((row.get("entity_name", ""), row.get("entity_name_localized", ""), display_name(row), row.get("entity_id", ""))).casefold()
            if query and query not in haystack:
                continue
            result.append(row)
        if category == "work":
            return sorted(result, key=lambda r: (r.get("region", ""), r.get("round_int") or 0, work_order(r), r.get("rank_int") or 999999, display_name(r)))
        return sorted(result, key=lambda r: (r.get("region", ""), r.get("round_int") or 0, r.get("rank_int") or 999999, display_name(r)))

    def refresh(self) -> None:
        self.filtered_rows = self.filter_rows()
        for item in self.tree.get_children():
            self.tree.delete(item)
        shown = self.filtered_rows[:1000]
        for row in shown:
            self.tree.insert("", "end", values=(
                REGION_LABELS.get(row.get("region"), row.get("region")),
                region_round_label(row.get("region", ""), row.get("round_int")),
                CATEGORY_LABELS.get(row.get("category"), row.get("category", "")),
                row.get("rank_int") or "—",
                display_name(row),
                fmt_number(row.get("points_num")),
                fmt_number(row.get("vote_count_num")),
                fmt_number(row.get("first_choice_count_num")),
                fmt_percent(row.get("vote_share_num")),
                row.get("source_type", ""),
            ))
        self.draw_bar_chart()
        self.draw_trend_chart()
        self.draw_ballot_chart()
        self.note_var.set(self.query_note())
        self.refresh_status()

    def query_note(self) -> str:
        if self.round_var.get() == "全部" and self.category_var.get() == "全部":
            return "提示：当前未指定届次和榜单；柱状图会自动取各地区最新的角色榜（如有），趋势图仍按全部届次计算。"
        if self.metric_var.get() in ("points", "weighted_score"):
            return "提示：CN 与 JP、以及不同届次的积分/加权规则可能不同；图表适合看同一地区同一榜单内的趋势。"
        return ""

    def refresh_status(self) -> None:
        self.status_var.set(f"筛选结果 {len(self.filtered_rows):,} 行；表格最多显示前 1,000 行。数据范围：CN1–11、JP3–22。")

    def selected_chart_rows(self) -> list[dict]:
        rows = list(self.filtered_rows)
        if not rows:
            return []
        if self.round_var.get() == "全部":
            # 每个地区取最新届次，避免把不同届次挤在一张柱状图里。
            latest_by_region = {}
            for row in rows:
                key = row.get("region")
                latest_by_region[key] = max(latest_by_region.get(key, 0), row.get("round_int") or 0)
            rows = [r for r in rows if r.get("round_int") == latest_by_region.get(r.get("region"))]
        if self.category_var.get() == "全部":
            preferred = "character" if any(r.get("category") == "character" for r in rows) else sorted({r.get("category") for r in rows})[0]
            rows = [r for r in rows if r.get("category") == preferred]
        if self.category_var.get() == "work":
            return sorted(rows, key=lambda r: (work_order(r), r.get("rank_int") or 999999, display_name(r)))[: int(self.top_var.get())]
        return sorted(rows, key=lambda r: (r.get("rank_int") or 999999, display_name(r)))[: int(self.top_var.get())]

    def draw_bar_chart(self) -> None:
        canvas = self.bar_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 700)
        height = max(canvas.winfo_height(), 300)
        rows = self.selected_chart_rows()
        self.last_bar_rows = rows
        title = f"当前榜单：{CATEGORY_LABELS.get(self.category_var.get(), self.category_var.get())} / 指标 {METRIC_LABELS.get(self.metric_var.get(), self.metric_var.get())}"
        if self.round_var.get() == "全部":
            title += "（各地区最新届次）"
        if not rows:
            self.draw_empty(canvas, "当前筛选没有可绘制的榜单数据")
            return
        metric = self.metric_var.get()
        values = [metric_value(r, metric) for r in rows]
        if metric == "rank":
            ceiling = max(v for v in values if v is not None) + 1
            draw_values = [ceiling - (v or ceiling) for v in values]
        else:
            draw_values = [v or 0 for v in values]
        maximum = max(draw_values or [1]) or 1
        longest = max((len(display_name(row)) for row in rows), default=8)
        left = min(int(width * .44), max(220, 50 + longest * 10))
        left, top, right, bottom = left, 50, 70, 35
        plot_w, plot_h = width - left - right, height - top - bottom
        self.draw_title(canvas, title, width)
        self.draw_grid(canvas, left, top, plot_w, plot_h, maximum)
        slot = plot_h / max(len(rows), 1)
        for idx, (row, value) in enumerate(zip(rows, draw_values)):
            y = top + idx * slot + slot * 0.18
            bh = max(8, slot * 0.62)
            bar_w = plot_w * value / maximum
            name = display_name(row)
            canvas.create_text(left - 8, y + bh / 2, text=name, anchor="e", font=("Microsoft YaHei UI", 9 if longest <= 28 else 8), fill="#263238")
            canvas.create_rectangle(left, y, left + bar_w, y + bh, fill=COLORS[idx % len(COLORS)], outline="")
            shown = f"#{row.get('rank_int')}" if metric == "rank" else fmt_number(metric_value(row, metric))
            canvas.create_text(left + bar_w + 8, y + bh / 2, text=shown, anchor="w", font=("Microsoft YaHei UI", 9), fill="#263238")

    def trend_series(self) -> list[tuple[str, list[tuple[str, float]]]]:
        rows = self.filter_rows(include_round=False)
        if self.category_var.get() == "全部":
            preferred = "character" if any(r.get("category") == "character" for r in rows) else (sorted({r.get("category") for r in rows})[0] if rows else "")
            rows = [r for r in rows if r.get("category") == preferred]
        grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for row in rows:
            value = metric_value(row, self.metric_var.get())
            if value is not None:
                grouped[(row.get("region", ""), display_name(row))].append(row)
        latest = sorted(grouped.items(), key=lambda item: (min(r.get("rank_int") or 999999 for r in item[1]), item[0][1]))
        chosen = latest[:5]
        labels = sorted({region_round_label(r.get("region", ""), r.get("round_int")) for _, rs in chosen for r in rs}, key=lambda x: (x[:2], as_int(x[2:]) or 0))
        output = []
        for (region, name), group in chosen:
            by_label = {region_round_label(r.get("region", ""), r.get("round_int")): metric_value(r, self.metric_var.get()) for r in group}
            points = [(label, by_label[label]) for label in labels if label in by_label and by_label[label] is not None]
            if points:
                output.append((f"{REGION_LABELS.get(region, region)} · {name}", points))
        return output

    def draw_trend_chart(self) -> None:
        canvas = self.trend_canvas
        canvas.delete("all")
        canvas._line_points = []
        canvas.delete("line_overlay")
        width = max(canvas.winfo_width(), 700)
        height = max(canvas.winfo_height(), 300)
        series = self.trend_series()
        self.last_trend_series = series
        title = f"历届趋势：{CATEGORY_LABELS.get(self.category_var.get(), self.category_var.get())} / {METRIC_LABELS.get(self.metric_var.get(), self.metric_var.get())}"
        if self.search_var.get().strip():
            title += f"（搜索：{self.search_var.get().strip()}）"
        if not series:
            self.draw_empty(canvas, "没有足够的跨届数据；JP 某些榜单的积分或票数可能为空")
            return
        self.draw_line_canvas(canvas, series, title, width, height, self.metric_var.get())

    def ballot_series(self) -> list[tuple[str, list[tuple[str, float]]]]:
        region = self.selected_region_code()
        category = self.category_var.get()
        rows = [r for r in self.ballots if (not region or r.get("region") == region) and (category == "全部" or r.get("category") == category)]
        if category == "全部":
            preferred = "character" if any(r.get("category") == "character" for r in rows) else (sorted({r.get("category") for r in rows})[0] if rows else "")
            rows = [r for r in rows if r.get("category") == preferred]
        grouped = defaultdict(list)
        for row in rows:
            value = row.get("valid_vote_count_num")
            if value is not None:
                grouped[row.get("region", "")].append((region_round_label(row.get("region", ""), row.get("round_int")), value))
        return [(f"{REGION_LABELS.get(region, region)} · 有效票", sorted(points, key=lambda p: as_int(p[0][2:]) or 0)) for region, points in sorted(grouped.items())]

    def draw_ballot_chart(self) -> None:
        canvas = self.ballot_canvas
        canvas.delete("all")
        canvas._line_points = []
        canvas.delete("line_overlay")
        width = max(canvas.winfo_width(), 700)
        height = max(canvas.winfo_height(), 300)
        series = self.ballot_series()
        self.last_ballot_series = series
        title = f"有效投票总量：{CATEGORY_LABELS.get(self.category_var.get(), self.category_var.get())}"
        if not series:
            self.draw_empty(canvas, "当前筛选没有有效投票总量数据")
            return
        self.draw_line_canvas(canvas, series, title, width, height, "valid_vote_count")

    def _bind_line_interaction(self, canvas: tk.Canvas) -> None:
        if getattr(canvas, "_line_interaction_bound", False):
            return
        canvas._line_interaction_bound = True
        canvas.bind("<Motion>", self._on_line_motion)
        canvas.bind("<Button-1>", self._on_line_click)
        canvas.bind("<Leave>", self._on_line_leave)

    @staticmethod
    def _line_hit(canvas: tk.Canvas, x: float, y: float):
        points = getattr(canvas, "_line_points", [])
        if not points:
            return None
        nearest = min(points, key=lambda point: (point["x"] - x) ** 2 + (point["y"] - y) ** 2)
        distance = math.hypot(nearest["x"] - x, nearest["y"] - y)
        if distance <= 13:
            return nearest
        best = None
        for left, right in zip(points, points[1:]):
            if left["series_index"] != right["series_index"]:
                continue
            dx, dy = right["x"] - left["x"], right["y"] - left["y"]
            length_sq = dx * dx + dy * dy
            if not length_sq:
                continue
            t = max(0.0, min(1.0, ((x - left["x"]) * dx + (y - left["y"]) * dy) / length_sq))
            px, py = left["x"] + t * dx, left["y"] + t * dy
            d = math.hypot(px - x, py - y)
            if best is None or d < best[0]:
                best = (d, left if t < .5 else right)
        return best[1] if best and best[0] <= 10 else None

    @staticmethod
    def _show_line_tooltip(canvas: tk.Canvas, point: dict) -> None:
        canvas.delete("line_overlay")
        width = max(canvas.winfo_width(), 700)
        height = max(canvas.winfo_height(), 300)
        top = point.get("plot_top", 50); bottom = point.get("plot_bottom", height - 55)
        x, y = point["x"], point["y"]
        canvas.create_line(x, top, x, bottom, fill="#2563eb", dash=(5, 3), width=2, tags="line_overlay")
        shown = f"#{int(round(point['value']))}" if point.get("metric") == "rank" else fmt_number(point.get("value"))
        lines = [str(point.get("series", "")), f"{point.get('category', '')}：{shown}"]
        box_w = max(150, min(340, 12 * max(len(line) for line in lines) + 24))
        box_h = 18 * len(lines) + 14
        tx = clamp(x + 14, 8 + box_w / 2, width - 8 - box_w / 2)
        ty = clamp(y - box_h - 12, 8 + box_h / 2, height - 8 - box_h / 2)
        canvas.create_rectangle(tx - box_w / 2, ty - box_h / 2, tx + box_w / 2, ty + box_h / 2,
                                fill="#fffef5", outline="#2563eb", width=1, tags="line_overlay")
        canvas.create_text(tx, ty, text="\n".join(lines), justify="left", anchor="center",
                           font=("Microsoft YaHei UI", 9), fill="#1e293b", tags="line_overlay")
        canvas.tag_raise("line_overlay")

    def _on_line_motion(self, event) -> None:
        point = self._line_hit(event.widget, event.x, event.y)
        if point:
            self._show_line_tooltip(event.widget, point)
        else:
            event.widget.delete("line_overlay")

    def _on_line_click(self, event) -> None:
        point = self._line_hit(event.widget, event.x, event.y)
        if point:
            self._show_line_tooltip(event.widget, point)

    @staticmethod
    def _on_line_leave(event) -> None:
        event.widget.delete("line_overlay")

    def draw_line_canvas(self, canvas, series, title, width, height, metric) -> None:
        left, top, right, bottom = 72, 50, 28, 55
        self._bind_line_interaction(canvas)
        canvas._line_points = []
        canvas._point_points = []
        canvas.delete("line_overlay")
        points_all = [(-v if metric == "rank" else v) for _, points in series for _, v in points]
        lo, hi = min(points_all), max(points_all)
        if lo == hi:
            lo, hi = lo - 1, hi + 1
        labels = sorted({label for _, points in series for label, _ in points}, key=lambda x: (x[:2], as_int(x[2:]) or 0))
        plot_w, plot_h = width - left - right, height - top - bottom
        self.draw_title(canvas, title, width)
        for i in range(5):
            frac = i / 4
            y = top + plot_h * frac
            value = hi - (hi - lo) * frac
            shown_value = -value if metric == "rank" else value
            canvas.create_line(left, y, left + plot_w, y, fill="#e2e8f0")
            canvas.create_text(left - 8, y, text=fmt_number(shown_value), anchor="e", font=("Microsoft YaHei UI", 9), fill="#52606d")
        canvas.create_line(left, top, left, top + plot_h, fill="#718096")
        canvas.create_line(left, top + plot_h, left + plot_w, top + plot_h, fill="#718096")
        for i, label in enumerate(labels):
            x = left + plot_w * i / max(1, len(labels) - 1)
            canvas.create_line(x, top, x, top + plot_h, fill="#edf2f7", dash=(1, 5))
            canvas.create_text(x, top + plot_h + 20, text=label, font=("Microsoft YaHei UI", 9), fill="#52606d")
        for sidx, (name, points) in enumerate(series):
            coords = []
            for label, value in points:
                if label not in labels:
                    continue
                idx = labels.index(label)
                x = left + plot_w * idx / max(1, len(labels) - 1)
                plot_value = -value if metric == "rank" else value
                y = top + (hi - plot_value) / (hi - lo) * plot_h
                coords.append((x, y))
                canvas._line_points.append({
                    "x": x, "y": y, "series_index": sidx, "series": name,
                    "category": label, "value": value, "metric": metric,
                    "plot_top": top, "plot_bottom": top + plot_h,
                })
            if len(coords) > 1:
                # Keep the exact piecewise-linear trend; smoothing can create
                # values between rounds that were never observed.
                canvas.create_line(*[coord for point in coords for coord in point], fill=COLORS[sidx % len(COLORS)], width=3)
            for x, y in coords:
                canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill=COLORS[sidx % len(COLORS)], outline="")
            canvas.create_rectangle(width - 220, 25 + sidx * 18, width - 209, 36 + sidx * 18, fill=COLORS[sidx % len(COLORS)], outline="")
            canvas.create_text(width - 202, 31 + sidx * 18, text=name[:20], anchor="w", font=("Microsoft YaHei UI", 9), fill="#263238")

    def draw_grid(self, canvas, left, top, plot_w, plot_h, maximum):
        for i in range(5):
            x = left + plot_w * i / 4
            value = maximum * i / 4
            canvas.create_line(x, top, x, top + plot_h, fill="#e2e8f0")
            canvas.create_text(x, top + plot_h + 16, text=fmt_number(value), font=("Microsoft YaHei UI", 9), fill="#52606d")
        canvas.create_line(left, top, left, top + plot_h, fill="#718096")
        canvas.create_line(left, top + plot_h, left + plot_w, top + plot_h, fill="#718096")

    def draw_title(self, canvas, title, width):
        canvas.create_text(18, 18, text=title, anchor="w", font=("Microsoft YaHei UI", 13, "bold"), fill="#263238")

    def draw_empty(self, canvas, message):
        canvas.create_text(max(canvas.winfo_width() / 2, 350), max(canvas.winfo_height() / 2, 150), text=message, font=("Microsoft YaHei UI", 12), fill="#718096")

    def on_tree_double_click(self, _event):
        item = self.tree.focus()
        values = self.tree.item(item, "values")
        if values:
            self.search_var.set(values[4])
            self.refresh()

    def export_csv(self) -> None:
        if not self.filtered_rows:
            messagebox.showinfo("没有数据", "当前筛选没有可导出的数据。")
            return
        path = filedialog.asksaveasfilename(title="导出筛选结果", defaultextension=".csv", filetypes=[("CSV 文件", "*.csv")])
        if not path:
            return
        fieldnames = [k for k in self.rows[0] if not k.endswith("_num") and k not in ("round_int", "rank_int")]
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.filtered_rows)
        messagebox.showinfo("导出完成", f"已导出 {len(self.filtered_rows):,} 行：\n{path}")

    def export_svg(self) -> None:
        tab = self.notebook.index(self.notebook.select())
        if tab == 0:
            if not self.last_bar_rows:
                messagebox.showinfo("没有图表", "当前没有可导出的柱状图。")
                return
            title = "东方投票当前榜单"
            svg = build_bar_svg(self.last_bar_rows, self.metric_var.get(), title)
        elif tab == 1:
            if not self.last_trend_series:
                messagebox.showinfo("没有图表", "当前没有可导出的趋势图。")
                return
            svg = build_line_svg(self.last_trend_series, self.metric_var.get(), "东方投票历届趋势")
        else:
            if not self.last_ballot_series:
                messagebox.showinfo("没有图表", "当前没有可导出的票数图。")
                return
            svg = build_line_svg(self.last_ballot_series, "valid_vote_count", "东方投票有效票数趋势")
        path = filedialog.asksaveasfilename(title="导出 SVG 图表", defaultextension=".svg", filetypes=[("SVG 矢量图", "*.svg")])
        if not path:
            return
        Path(path).write_text(svg, encoding="utf-8")
        messagebox.showinfo("导出完成", f"SVG 图表已保存：\n{path}")

    def open_data_dir(self) -> None:
        try:
            os.startfile(str(DATA_DIR))  # type: ignore[attr-defined]
        except AttributeError:
            webbrowser.open(DATA_DIR.as_uri())

    def open_analysis(self) -> None:
        try:
            if self.analysis_workbench and self.analysis_workbench.window.winfo_exists():
                self.analysis_workbench.window.deiconify()
                self.analysis_workbench.window.lift()
                return
        except tk.TclError:
            self.analysis_workbench = None
        from analysis_workbench import open_workbench
        try:
            self.analysis_workbench = open_workbench(self.root)
        except FileNotFoundError:
            messagebox.showerror(
                "缺少分析表",
                "文章分析工作台需要先生成全届分析表。\n\n"
                "请双击 vote_explorer/build_analysis_data.bat 后再试。",
                parent=self.root,
            )


def run() -> None:
    # Python 3.14 bundles Tcl/Tk under ``_tcl_data``/``_tk_data``.  In a
    # one-file PyInstaller extraction Tcl otherwise searches only the host
    # installation and the window closes before an error can be shown.
    if getattr(sys, "frozen", False):
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        tcl_base = bundle_root / "_tcl_data"
        tk_base = bundle_root / "_tk_data"
        tcl_library = tcl_base / "library" if (tcl_base / "library").is_dir() else tcl_base
        tk_library = tk_base / "library" if (tk_base / "library").is_dir() else tk_base
        if tcl_library.is_dir():
            os.environ.setdefault("TCL_LIBRARY", str(tcl_library))
        if tk_library.is_dir():
            os.environ.setdefault("TK_LIBRARY", str(tk_library))
    root = tk.Tk()
    VoteExplorerApp(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        run()
    except BaseException:
        details = traceback.format_exc()
        log_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        log_path = log_dir / "launcher_error.log"
        try:
            log_path.write_text(details, encoding="utf-8")
        except OSError:
            pass
        try:
            messagebox.showerror("东方投票分析工具", f"程序启动失败。\n\n错误日志：{log_path}\n\n{details[-1200:]}")
        except Exception:
            raise
