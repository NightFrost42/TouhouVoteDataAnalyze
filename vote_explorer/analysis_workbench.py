"""文章分析工作台：模板选择、图表配置、预览和导出。"""

from __future__ import annotations

import csv
import html
import math
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:  # package import (tests/embedding) and direct script import (launcher)
    from .analysis_engine import (
        AnalysisRepository, CHARACTER_FIELDS, COVOTE_FIELDS, CP_FIELDS, ENTITY_QUESTION_LABELS,
        METRIC_LABELS, MUSIC_FIELDS, PERCENT_FIELDS, QUESTION_LABELS, TEMPLATES, questionnaire_label,
        TEMPLATE_BY_KEY, integer, number, template_chart_types,
    )
except ImportError:  # pragma: no cover - exercised by the Windows launcher
    from analysis_engine import (
        AnalysisRepository, CHARACTER_FIELDS, COVOTE_FIELDS, CP_FIELDS, ENTITY_QUESTION_LABELS,
        METRIC_LABELS, MUSIC_FIELDS, PERCENT_FIELDS, QUESTION_LABELS, TEMPLATES, questionnaire_label,
        TEMPLATE_BY_KEY, integer, number, template_chart_types,
    )


PALETTES = {
    "东方红蓝": ["#d1495b", "#00798c", "#edae49", "#30638e", "#6a4c93"],
    "红魔馆": ["#8b1e3f", "#d1495b", "#f4a7b9", "#3c1642", "#086788"],
    "幻想乡": ["#2a9d8f", "#8ab17d", "#e9c46a", "#f4a261", "#e76f51"],
    "夜空": ["#1d3557", "#457b9d", "#a8dadc", "#6a4c93", "#f1faee"],
    "灰阶": ["#263238", "#52606d", "#7b8794", "#cbd5e1", "#f1f5f9"],
}

CHART_OVERRIDES = {
    "自动（按模板）": "auto", "横向条形": "bar", "分组条形": "grouped",
    "100%堆叠": "stacked", "折线": "line", "散点/四象限": "scatter",
    "两届哑铃图": "dumbbell", "气泡散点": "bubble", "热力图/矩阵": "heatmap",
    "关系网络": "network", "仅数据表": "table",
}

SORT_OPTIONS = {"数值降序": "desc", "数值升序": "asc", "按绝对变化": "abs"}
CHANGE_DIRECTION_OPTIONS = {"全部变化": "all", "只看正数变化": "positive", "只看负数变化": "negative"}
LANGUAGE_OPTIONS = {"中文优先": "cn", "日文原名": "jp", "中日并列": "both"}
PAIR_RANGE_OPTIONS = {"两端都在区间": "both", "至少一端在区间": "either"}
RANGE_PRESETS = ["1–20", "21–40", "41–60", "61–80", "81–100", "全部", "自定义"]
RELATION_VALUE_OPTIONS = {"问卷选项比例": "rate", "相对全体差值（百分点）": "difference"}
RELATION_SORT_OPTIONS = {"按选项人数": "count", "按选项比例": "rate", "按相对全体差值": "difference"}
ANSWER_TRANSLATIONS = {
    "男性": "男性", "女性": "女性", "その他": "其他性别",
    "はい": "是", "いいえ": "否",
    "～9歳": "9岁以下", "10～14歳": "10–14岁", "15～19歳": "15–19岁", "20～24歳": "20–24岁",
    "25～29歳": "25–29岁", "30～34歳": "30–34岁", "35～39歳": "35–39岁", "40～44歳": "40–44岁",
    "45～49歳": "45–49岁", "50歳～": "50岁以上", "今回がはじめて": "本届第一次投票",
    "過去1～3回投票したことがある": "过去投过1–3届", "過去4～6回投票したことがある": "过去投过4–6届",
    "過去7～9回投票したことがある": "过去投过7–9届", "過去10回以上投票したことがある": "过去投过10届以上",
    "参加している": "参加线下活动", "うちサークル参加": "其中参加社团", "うちコスプレ参加": "其中参加Cosplay",
}

CHARACTER_METRICS = [
    "rank", "equal_rank", "old_2_1_rank", "points", "primary_count", "secondary_count",
    "other_count", "selection_count", "primary_rate", "secondary_rate", "top2_rate",
    "selection_rate", "male_rate", "female_rate", "under20_rate",
]
MUSIC_METRICS = [
    "rank", "equal_rank", "points", "primary_count", "secondary_count", "selection_count",
    "primary_rate", "selection_rate", "comment_count",
]
COVOTE_METRICS = ["intersection_count", "share", "lift", "excess_count", "phi", "asymmetry"]
CP_METRICS = ["rank", "vote_count", "first_choice_count", "points", "vote_rate"]
ARRANGEMENT_X_METRICS = ["arrangement_count", "arrangement_cumulative_count", "arrangement_total_count"]


def fmt(value, kind="number") -> str:
    if value is None or value == "":
        return "—"
    val = number(value)
    if kind == "percent":
        return f"{val * 100:.2f}%"
    if kind == "rank":
        return f"#{int(round(val))}"
    if abs(val) >= 1000:
        return f"{val:,.0f}"
    if float(val).is_integer():
        return f"{int(val):,}"
    return f"{val:.3f}"


def mix_color(a: str, b: str, t: float) -> str:
    t = min(1.0, max(0.0, t))
    av = tuple(int(a[i:i + 2], 16) for i in (1, 3, 5))
    bv = tuple(int(b[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(av, bv))


def contrast_color(color: str) -> str:
    rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    luminance = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    return "#ffffff" if luminance < 145 else "#263238"


def answer_display(value: str) -> str:
    cleaned = str(value or "").strip()
    return ANSWER_TRANSLATIONS.get(cleaned, cleaned)


def short_label(value: str, max_chars: int) -> str:
    """Keep long entity names readable inside a finite plotting margin.

    Full names remain available in the data table/CSV export; the canvas uses
    an ellipsis so labels never collide with the plot or window edge.
    """
    text = str(value or "")
    max_chars = max(4, int(max_chars))
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def scatter_axis_format(chart: dict, axis: str) -> str:
    """Return the independent display format for one scatter axis."""
    explicit = chart.get(f"{axis}_format")
    if explicit:
        return explicit
    value_format = chart.get("value_format")
    return "percent" if value_format == f"percent_{axis}" else "number"


def scatter_axis_scale(values: list[float], kind: str) -> tuple[float, float, list[float]]:
    """Build readable ticks, keeping discrete count axes strictly integral."""
    numeric = [number(value) for value in values]
    include_zero = kind != "rank"
    lo = min(numeric + ([0.0] if include_zero else []))
    hi = max(numeric + ([0.0] if include_zero else []))
    if kind in {"integer", "rank"}:
        span = max(1.0, hi - lo)
        raw_step = span / 4
        magnitude = 10 ** math.floor(math.log10(raw_step)) if raw_step > 0 else 1
        step = next((factor * magnitude for factor in (1, 2, 5, 10) if factor * magnitude >= raw_step), magnitude)
        step = max(1, int(math.ceil(step)))
        axis_lo = math.floor(lo / step) * step
        axis_hi = math.ceil(hi / step) * step
        if axis_hi == axis_lo:
            axis_hi += step
        ticks = [float(axis_lo + index * step) for index in range(int((axis_hi - axis_lo) / step) + 1)]
        return float(axis_lo), float(axis_hi), ticks
    if lo == hi:
        hi = lo + 1
    return lo, hi, [lo + (hi - lo) * index / 4 for index in range(5)]


class ChartRenderer:
    def render(self, canvas: tk.Canvas, chart: dict, options: dict) -> str:
        canvas.delete("all")
        # Interaction metadata belongs to the currently rendered chart.  Do
        # not leave the previous chart's points alive when a metric, round,
        # or questionnaire option is changed.
        canvas._line_points = []
        canvas._point_points = []
        canvas.delete("line_overlay")
        width = max(canvas.winfo_width(), 760)
        height = max(canvas.winfo_height(), 480)
        chart_type = self.effective_type(chart, options)
        title = options.get("title") or chart.get("title", "")
        palette = PALETTES[options.get("palette", "东方红蓝")]
        canvas.configure(background="#fffdf8")
        canvas.create_text(22, 22, text=title, anchor="w", font=("Microsoft YaHei UI", 15, "bold"), fill="#263238")
        if chart_type == "table":
            canvas.create_text(width / 2, height / 2, text="当前配置为仅显示数据表", font=("Microsoft YaHei UI", 13), fill="#718096")
        elif chart_type in {"bar", "grouped", "stacked", "line"} and chart.get("categories"):
            if chart_type == "line":
                self.draw_line(canvas, chart, options, palette, width, height)
            else:
                self.draw_categorical(canvas, chart, options, palette, width, height, chart_type)
        elif chart_type == "dumbbell" and chart.get("categories"):
            self.draw_dumbbell(canvas, chart, options, palette, width, height)
        elif chart_type == "scatter" and chart.get("points") is not None:
            self.draw_scatter(canvas, chart, options, palette, width, height)
        elif chart_type == "bubble" and chart.get("points") is not None:
            self.draw_bubble(canvas, chart, options, palette, width, height)
        elif chart_type == "heatmap" and chart.get("matrix") is not None:
            self.draw_heatmap(canvas, chart, options, palette, width, height)
        elif chart_type == "network" and chart.get("nodes") is not None:
            self.draw_network(canvas, chart, options, palette, width, height)
        elif chart_type == "faceted_network" and chart.get("panels") is not None:
            self.draw_faceted_network(canvas, chart, options, palette, width, height)
        else:
            canvas.create_text(width / 2, height / 2, text="该图表类型与模板数据不兼容，已在数据表中保留结果", font=("Microsoft YaHei UI", 12), fill="#b45309")
        return chart_type

    def effective_type(self, chart: dict, options: dict) -> str:
        override = options.get("chart_override", "auto")
        original = chart.get("chart_type", "table")
        allowed = set(chart.get("allowed_chart_types", ("auto", original, "table")))
        if override == "auto":
            return original
        if override == "table" and "table" in allowed:
            return "table"
        if override not in allowed:
            return original
        if chart.get("categories") and override in {"bar", "grouped", "stacked", "line", "dumbbell"}:
            return override
        if chart.get("points") is not None and override in {"scatter", "bubble"}:
            return override
        if chart.get("matrix") is not None and override == "heatmap":
            return "heatmap"
        if chart.get("nodes") is not None and override == "network":
            return "network"
        if chart.get("panels") is not None and override == "faceted_network":
            return "faceted_network"
        return original

    def draw_categorical(self, canvas, chart, options, palette, width, height, chart_type):
        categories, series = chart["categories"], chart["series"]
        longest = max((len(str(label)) for label in categories), default=8)
        # Reserve a guaranteed plot area even for very long translated names.
        left = min(int(width * .43), max(220, 55 + min(longest, 24) * 9))
        left = min(left, max(180, width - 250))
        left, top, right, bottom = left, 58, 74, 42
        plot_w, plot_h = max(120, width - left - right), max(120, height - top - bottom)
        values = [v for s in series for v in s["values"] if v is not None]
        if chart_type == "stacked":
            lo, hi = 0.0, 1.0
        else:
            lo, hi = min(values + [0]), max(values + [0])
            if lo == hi:
                hi = lo + 1
        zero_x = left + (-lo) / (hi - lo) * plot_w
        if options.get("show_grid", True):
            for i in range(5):
                x = left + plot_w * i / 4
                val = lo + (hi - lo) * i / 4
                canvas.create_line(x, top, x, top + plot_h, fill="#dbe4ec", dash=(2, 4))
                canvas.create_text(x, top + plot_h + 16, text=fmt(val, chart.get("value_format")), font=("Microsoft YaHei UI", 8), fill="#52606d")
        canvas.create_line(zero_x, top, zero_x, top + plot_h, fill="#64748b", width=1)
        slot = plot_h / max(1, len(categories))
        for idx, label in enumerate(categories):
            y0 = top + idx * slot
            if options.get("show_grid", True):
                canvas.create_line(left, y0 + slot * .5, left + plot_w, y0 + slot * .5, fill="#edf2f7", dash=(1, 5))
            font_size = 9 if longest <= 28 else 8
            canvas.create_text(left - 10, y0 + slot / 2, text=short_label(label, max(12, int((left - 24) / 9))), anchor="e", font=("Microsoft YaHei UI", font_size), fill="#263238")
            if chart_type == "stacked":
                x = left
                total = sum(max(0, s["values"][idx] or 0) for s in series) or 1
                for sidx, s in enumerate(series):
                    val = max(0, s["values"][idx] or 0) / total
                    bw = plot_w * val
                    canvas.create_rectangle(x, y0 + slot * .18, x + bw, y0 + slot * .80, fill=palette[sidx % len(palette)], outline="#fffdf8")
                    if options.get("show_labels", True) and bw > 38:
                        canvas.create_text(x + bw / 2, y0 + slot / 2, text=fmt(val, "percent"), font=("Microsoft YaHei UI", 8), fill=contrast_color(palette[sidx % len(palette)]))
                    x += bw
            else:
                group_h = slot * .72
                bh = max(3, group_h / max(1, len(series)))
                for sidx, s in enumerate(series):
                    val = s["values"][idx]
                    if val is None:
                        continue
                    x1 = left + (val - lo) / (hi - lo) * plot_w
                    y1 = y0 + slot * .14 + sidx * bh
                    color = palette[sidx % len(palette)] if val >= 0 else "#64748b"
                    canvas.create_rectangle(min(zero_x, x1), y1, max(zero_x, x1), y1 + bh * .82, fill=color, outline="")
                    if options.get("show_labels", True):
                        # Flip labels at the right/left edge and clamp their
                        # anchor so extreme values stay visible in the window.
                        edge = width - right
                        if val >= 0:
                            anchor = "e" if x1 > edge - 48 else "w"
                            tx = x1 - 5 if anchor == "e" else x1 + 5
                        else:
                            anchor = "w" if x1 < left + 48 else "e"
                            tx = x1 + 5 if anchor == "w" else x1 - 5
                        tx = clamp(tx, left + 3, edge - 3)
                        canvas.create_text(tx, y1 + bh * .4, text=fmt(val, chart.get("value_format")), anchor=anchor, font=("Microsoft YaHei UI", 8), fill="#263238")
        self.draw_legend(canvas, series, palette, width)

    @staticmethod
    def _bind_line_interaction(canvas):
        """Install one shared hover/click handler for line-chart canvases."""
        if getattr(canvas, "_chart_interaction_bound", False):
            return
        canvas._chart_interaction_bound = True
        canvas.bind("<Motion>", ChartRenderer._on_chart_motion)
        canvas.bind("<Button-1>", ChartRenderer._on_chart_click)
        canvas.bind("<Leave>", ChartRenderer._on_chart_leave)

    @staticmethod
    def _bind_point_interaction(canvas):
        """Install the same interaction handlers for scatter/bubble points."""
        ChartRenderer._bind_line_interaction(canvas)

    @staticmethod
    def _line_hit(canvas, x: float, y: float):
        points = getattr(canvas, "_line_points", [])
        if not points:
            return None
        # Prefer an actual marker, then the closest segment.  This makes
        # hovering either a point or the connecting line useful.
        nearest = min(points, key=lambda point: (point["x"] - x) ** 2 + (point["y"] - y) ** 2)
        distance = math.hypot(nearest["x"] - x, nearest["y"] - y)
        if distance <= 12:
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
                # Show the endpoint whose category is closest to the cursor;
                # the tooltip still identifies the exact series and value.
                endpoint = left if t < .5 else right
                best = (d, endpoint)
        return best[1] if best and best[0] <= 9 else None

    @staticmethod
    def _point_hit(canvas, x: float, y: float):
        points = getattr(canvas, "_point_points", [])
        if not points:
            return None
        nearest = min(points, key=lambda point: (point["x"] - x) ** 2 + (point["y"] - y) ** 2)
        distance = math.hypot(nearest["x"] - x, nearest["y"] - y)
        threshold = max(13.0, number(nearest.get("radius"), 5.0) + 4.0)
        return nearest if distance <= threshold else None

    @staticmethod
    def _show_line_tooltip(canvas, point):
        canvas.delete("line_overlay")
        width = max(canvas.winfo_width(), 760)
        height = max(canvas.winfo_height(), 480)
        top = point.get("plot_top", 62); bottom = point.get("plot_bottom", height - 98)
        x = point["x"]
        canvas.create_line(x, top, x, bottom, fill="#2563eb", dash=(5, 3), width=2, tags="line_overlay")
        lines = [str(point.get("series", "")), f"{point.get('category', '')}：{fmt(point.get('value'), point.get('value_format', 'number'))}"]
        text = "\n".join(lines)
        max_chars = max(len(line) for line in lines)
        box_w = max(150, min(320, 12 * max_chars + 24))
        box_h = 18 * len(lines) + 14
        tx = clamp(x + 14, 8 + box_w / 2, width - 8 - box_w / 2)
        ty = clamp(point["y"] - box_h - 12, 8 + box_h / 2, height - 8 - box_h / 2)
        canvas.create_rectangle(tx - box_w / 2, ty - box_h / 2, tx + box_w / 2, ty + box_h / 2,
                                fill="#fffef5", outline="#2563eb", width=1, tags="line_overlay")
        canvas.create_text(tx, ty, text=text, justify="left", anchor="center",
                           font=("Microsoft YaHei UI", 9), fill="#1e293b", tags="line_overlay")
        canvas.tag_raise("line_overlay")

    @staticmethod
    def _on_line_motion(event):
        canvas = event.widget
        point = ChartRenderer._line_hit(canvas, event.x, event.y)
        if point:
            ChartRenderer._show_line_tooltip(canvas, point)
        else:
            canvas.delete("line_overlay")

    @staticmethod
    def _on_line_click(event):
        canvas = event.widget
        point = ChartRenderer._line_hit(canvas, event.x, event.y)
        if point:
            ChartRenderer._show_line_tooltip(canvas, point)

    @staticmethod
    def _on_line_leave(event):
        event.widget.delete("line_overlay")

    @staticmethod
    def _show_point_tooltip(canvas, point):
        canvas.delete("line_overlay")
        width = max(canvas.winfo_width(), 760)
        height = max(canvas.winfo_height(), 480)
        top = point.get("plot_top", 62); bottom = point.get("plot_bottom", height - 98)
        x, y = point["x"], point["y"]
        canvas.create_line(x, top, x, bottom, fill="#2563eb", dash=(5, 3), width=2, tags="line_overlay")
        canvas.create_line(point.get("plot_left", 70), y, point.get("plot_right", width - 35), y,
                           fill="#93c5fd", dash=(3, 4), width=1, tags="line_overlay")
        x_text = fmt(point.get("x_value"), point.get("x_format", "number"))
        y_text = fmt(point.get("y_value"), point.get("y_format", "number"))
        lines = [str(point.get("label", "点")), f"{point.get('x_label', 'X')}：{x_text}", f"{point.get('y_label', 'Y')}：{y_text}"]
        if point.get("subtitle"):
            lines.append(str(point["subtitle"]))
        box_w = max(180, min(360, 12 * max(len(line) for line in lines) + 24))
        box_h = 18 * len(lines) + 14
        tx = clamp(x + 14, 8 + box_w / 2, width - 8 - box_w / 2)
        ty = clamp(y - box_h - 12, 8 + box_h / 2, height - 8 - box_h / 2)
        canvas.create_rectangle(tx - box_w / 2, ty - box_h / 2, tx + box_w / 2, ty + box_h / 2,
                                fill="#fffef5", outline="#2563eb", width=1, tags="line_overlay")
        canvas.create_text(tx, ty, text="\n".join(lines), justify="left", anchor="center",
                           font=("Microsoft YaHei UI", 9), fill="#1e293b", tags="line_overlay")
        canvas.tag_raise("line_overlay")

    @staticmethod
    def _on_chart_motion(event):
        canvas = event.widget
        point = ChartRenderer._line_hit(canvas, event.x, event.y) if getattr(canvas, "_line_points", []) else None
        if point:
            ChartRenderer._show_line_tooltip(canvas, point)
            return
        point = ChartRenderer._point_hit(canvas, event.x, event.y)
        if point:
            ChartRenderer._show_point_tooltip(canvas, point)
        else:
            canvas.delete("line_overlay")

    @staticmethod
    def _on_chart_click(event):
        canvas = event.widget
        point = ChartRenderer._line_hit(canvas, event.x, event.y) if getattr(canvas, "_line_points", []) else None
        if point:
            ChartRenderer._show_line_tooltip(canvas, point)
            return
        point = ChartRenderer._point_hit(canvas, event.x, event.y)
        if point:
            ChartRenderer._show_point_tooltip(canvas, point)

    @staticmethod
    def _on_chart_leave(event):
        event.widget.delete("line_overlay")

    def draw_line(self, canvas, chart, options, palette, width, height):
        categories, series = chart["categories"], chart["series"]
        self._bind_line_interaction(canvas)
        canvas._line_points = []
        canvas._point_points = []
        left, top, right, bottom = 86, 62, min(330, max(180, int(width * .24))), 98
        plot_w, plot_h = width - left - right, height - top - bottom
        values = [v for s in series for v in s["values"] if v is not None]
        is_rank = chart.get("rank_axis") or chart.get("value_format") == "rank"
        if not values:
            return
        lo, hi = (min(values), max(values)) if is_rank else (min(values + [0]), max(values + [0]))
        if lo == hi:
            hi = lo + 1
        for i in range(5):
            y = top + plot_h * i / 4
            val = lo + (hi - lo) * i / 4 if is_rank else hi - (hi - lo) * i / 4
            if options.get("show_grid", True):
                canvas.create_line(left, y, left + plot_w, y, fill="#dbe4ec", dash=(2, 4))
            canvas.create_text(left - 8, y, text=fmt(val, chart.get("value_format")), anchor="e", font=("Microsoft YaHei UI", 8), fill="#52606d")
        for idx, label in enumerate(categories):
            x = left + plot_w * idx / max(1, len(categories) - 1)
            if options.get("show_grid", True):
                canvas.create_line(x, top, x, top + plot_h, fill="#edf2f7", dash=(1, 5))
            short = label if len(label) < 12 else label[:11] + "…"
            canvas.create_text(x, top + plot_h + 12, text=short, anchor="n", angle=35, font=("Microsoft YaHei UI", 8), fill="#52606d")
        for sidx, s in enumerate(series):
            coords = []
            segments = []
            segment = []
            for idx, val in enumerate(s["values"]):
                if val is None:
                    if segment:
                        segments.append(segment)
                        segment = []
                    continue
                x = left + plot_w * idx / max(1, len(categories) - 1)
                y = top + ((val - lo) if is_rank else (hi - val)) / (hi - lo) * plot_h
                coords.extend([x, y])
                segment.extend([x, y])
                canvas._line_points.append({
                    "x": x, "y": y, "series_index": sidx, "series": s.get("name", ""),
                    "category": categories[idx], "value": val, "value_format": chart.get("value_format", "number"),
                    "plot_top": top, "plot_bottom": top + plot_h,
                })
            if segment:
                segments.append(segment)
            for line_segment in segments:
                if len(line_segment) >= 4:
                    # Trends are intentionally piecewise-linear between
                    # observed rounds; do not smooth or invent intermediate
                    # extrema.
                    canvas.create_line(*line_segment, fill=palette[sidx % len(palette)], width=3)
            for idx in range(0, len(coords), 2):
                canvas.create_oval(coords[idx] - 3, coords[idx + 1] - 3, coords[idx] + 3, coords[idx + 1] + 3, fill=palette[sidx % len(palette)], outline="")
        canvas.create_text(left + plot_w / 2, height - 12, text=chart.get("x_label", "届数"), font=("Microsoft YaHei UI", 10, "bold"), fill="#263238")
        canvas.create_text(16, top + plot_h / 2, text=chart.get("y_label", "指标"), angle=90, font=("Microsoft YaHei UI", 10, "bold"), fill="#263238")
        self.draw_vertical_legend(canvas, series, palette, left + plot_w + 18, top, height - bottom)

    def draw_dumbbell(self, canvas, chart, options, palette, width, height):
        categories, series = chart["categories"], chart.get("series", [])[:2]
        self._bind_line_interaction(canvas)
        canvas._line_points = []
        canvas._point_points = []
        if not categories or not series:
            return
        longest = max((len(str(label)) for label in categories), default=8)
        left = min(int(width * .47), max(225, 70 + min(longest, 24) * 9))
        left = min(left, max(180, width - 270))
        top, right, bottom = 72, 96, 50
        plot_w, plot_h = max(120, width - left - right), max(120, height - top - bottom)
        values = [v for item in series for v in item.get("values", []) if v is not None]
        if not values:
            return
        lo = 0.0 if min(values) >= 0 else min(values)
        hi = max(values)
        if hi == lo:
            hi = lo + 1
        pad = (hi - lo) * .08
        lo -= pad if lo < 0 else 0
        hi += pad
        if options.get("show_grid", True):
            for tick in range(6):
                x = left + plot_w * tick / 5
                value = lo + (hi - lo) * tick / 5
                canvas.create_line(x, top, x, top + plot_h, fill="#dbe4ec", dash=(2, 4))
                canvas.create_text(x, top + plot_h + 16, text=fmt(value, chart.get("value_format")), font=("Microsoft YaHei UI", 8), fill="#52606d")
        slot = plot_h / max(1, len(categories))
        anomalies = set(chart.get("anomaly_rows", []))
        for index, label in enumerate(categories):
            y = top + (index + .5) * slot
            if options.get("show_grid", True):
                canvas.create_line(left, y, left + plot_w, y, fill="#edf2f7", dash=(1, 5))
            canvas.create_text(left - 12, y, text=short_label(label, max(12, int((left - 26) / 9))), anchor="e", font=("Microsoft YaHei UI", 8 if longest > 28 else 9), fill="#263238")
            points = []
            for series_index, item in enumerate(series):
                value = item["values"][index]
                if value is None:
                    continue
                x = left + (value - lo) / (hi - lo) * plot_w
                points.append((x, value, series_index))
            if len(points) == 2:
                canvas.create_line(points[0][0], y, points[1][0], y, fill="#cbd5e1", width=3)
            for x, value, series_index in points:
                color = "#dd6b20" if index in anomalies and series_index == len(series) - 1 else palette[series_index % len(palette)]
                canvas.create_oval(x - 6, y - 6, x + 6, y + 6, fill=color, outline="#fffdf8", width=1)
                canvas._line_points.append({
                    "x": x, "y": y, "series_index": series_index,
                    "series": series[series_index].get("name", ""), "category": label,
                    "value": value, "value_format": chart.get("value_format", "number"),
                    "plot_top": top, "plot_bottom": top + plot_h,
                })
                if options.get("show_labels", True):
                    other_x = points[1 - series_index][0] if len(points) == 2 else x
                    close_points = len(points) == 2 and abs(x - other_x) < 30
                    if close_points:
                        anchor = "e" if series_index == 0 else "w"
                    else:
                        anchor = "e" if x > other_x else "w"
                    offset = -8 if anchor == "e" else 8
                    tx = clamp(x + offset, left + 3, width - right - 3)
                    label_y = y - 9 if not close_points or series_index == 0 else y + 13
                    canvas.create_text(tx, label_y, text=fmt(value, chart.get("value_format")), anchor=anchor, font=("Microsoft YaHei UI", 8), fill=color)
            if len(points) == 2:
                delta = points[1][1] - points[0][1]
                canvas.create_text(width - 5, y, text=f"差值 {fmt(delta, chart.get('value_format', 'number'))}",
                                   anchor="e", font=("Microsoft YaHei UI", 8), fill="#475569")
        self.draw_legend(canvas, series, palette, width)

    def draw_scatter(self, canvas, chart, options, palette, width, height):
        points = chart.get("points", [])
        self._bind_point_interaction(canvas)
        canvas._point_points = []
        canvas._line_points = []
        if not points:
            canvas.create_text(width / 2, height / 2, text="当前条件下没有散点数据", font=("Microsoft YaHei UI", 12), fill="#718096")
            return
        # The generous right gutter keeps the final tick, large point and its
        # inward-facing label inside the canvas at ordinary window sizes.
        left, top, right, bottom = 92, 65, 86, 65
        plot_w, plot_h = width - left - right, height - top - bottom
        xs, ys = [p["x"] for p in points], [p["y"] for p in points]
        x_kind, y_kind = scatter_axis_format(chart, "x"), scatter_axis_format(chart, "y")
        xlo, xhi, x_ticks = scatter_axis_scale(xs, x_kind)
        ylo, yhi, y_ticks = scatter_axis_scale(ys, y_kind)
        for index, value in enumerate(x_ticks):
            x = left + (value - xlo) / (xhi - xlo) * plot_w
            if options.get("show_grid", True):
                canvas.create_line(x, top, x, top + plot_h, fill="#dbe4ec", dash=(2, 4))
            anchor = "w" if index == 0 else ("e" if index == len(x_ticks) - 1 else "center")
            canvas.create_text(x, top + plot_h + 17, text=fmt(value, x_kind), anchor=anchor, font=("Microsoft YaHei UI", 8), fill="#52606d")
        for value in y_ticks:
            y = top + (yhi - value) / (yhi - ylo) * plot_h
            if options.get("show_grid", True):
                canvas.create_line(left, y, left + plot_w, y, fill="#dbe4ec", dash=(2, 4))
            canvas.create_text(left - 8, y, text=fmt(value, y_kind), anchor="e", font=("Microsoft YaHei UI", 8), fill="#52606d")
        zero_x = left + (-xlo) / (xhi - xlo) * plot_w; zero_y = top + yhi / (yhi - ylo) * plot_h
        if xlo <= 0 <= xhi:
            canvas.create_line(zero_x, top, zero_x, top + plot_h, fill="#64748b", width=2)
        if ylo <= 0 <= yhi:
            canvas.create_line(left, zero_y, left + plot_w, zero_y, fill="#64748b", width=2)
        x_reference = chart.get("x_reference")
        y_reference = chart.get("y_reference")
        if x_reference is not None and xlo <= number(x_reference) <= xhi:
            rx = left + (number(x_reference) - xlo) / (xhi - xlo) * plot_w
            canvas.create_line(rx, top, rx, top + plot_h, fill="#94a3b8", width=1, dash=(4, 4))
        if y_reference is not None and ylo <= number(y_reference) <= yhi:
            ry = top + (yhi - number(y_reference)) / (yhi - ylo) * plot_h
            canvas.create_line(left, ry, left + plot_w, ry, fill="#94a3b8", width=1, dash=(4, 4))
        if x_reference is not None or y_reference is not None:
            canvas.create_text(left + plot_w - 5, top + 5, text=chart.get("reference_label", "参考线"), anchor="ne", font=("Microsoft YaHei UI", 8), fill="#64748b")
        max_size = max([number(point.get("size")) for point in points] + [1])
        for idx, p in enumerate(points):
            x = left + (p["x"] - xlo) / (xhi - xlo) * plot_w
            y = top + (yhi - p["y"]) / (yhi - ylo) * plot_h
            color = palette[idx % len(palette)]
            radius = 5 + 8 * math.sqrt(max(0, number(p.get("size"))) / max_size) if p.get("size") is not None else 5
            canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=color, outline="#ffffff", width=1)
            canvas._point_points.append({
                "x": x, "y": y, "radius": radius, "label": p.get("label", "点"),
                "x_value": p.get("x"), "y_value": p.get("y"), "x_format": x_kind, "y_format": y_kind,
                "x_label": chart.get("x_label", "X"), "y_label": chart.get("y_label", "Y"),
                "subtitle": p.get("subtitle", ""), "plot_top": top, "plot_bottom": top + plot_h,
                "plot_left": left, "plot_right": left + plot_w,
            })
            if options.get("show_labels", True):
                label = short_label(p.get("label", ""), 15)
                label_x = x + 7 if x <= left + plot_w * .76 else x - 7
                anchor = "sw" if label_x >= x else "se"
                label_x = clamp(label_x, left + 3, left + plot_w - 3)
                canvas.create_text(label_x, y - 7, text=label, anchor=anchor, font=("Microsoft YaHei UI", 8), fill="#263238")
        canvas.create_text(left + plot_w / 2, height - 12, text=chart.get("x_label", "X"), font=("Microsoft YaHei UI", 10, "bold"), fill="#263238")
        canvas.create_text(14, top + plot_h / 2, text=chart.get("y_label", "Y"), angle=90, font=("Microsoft YaHei UI", 10, "bold"), fill="#263238")

    def draw_bubble(self, canvas, chart, options, palette, width, height):
        points = chart.get("points", [])
        self._bind_point_interaction(canvas)
        canvas._point_points = []
        canvas._line_points = []
        if not points:
            canvas.create_text(width / 2, height / 2, text="当前条件下没有气泡数据", font=("Microsoft YaHei UI", 12), fill="#718096")
            return
        left, top, right, bottom = 88, 68, 54, 68
        plot_w, plot_h = width - left - right, height - top - bottom
        raw_x = [max(number(point.get("x")), 1e-9) for point in points]
        use_log = bool(chart.get("x_log"))
        transformed_x = [math.log10(value) if use_log else value for value in raw_x]
        xlo, xhi = min(transformed_x), max(transformed_x)
        if xlo == xhi:
            xhi = xlo + 1
        reference = number(chart.get("y_reference"), 1.0)
        ys = [number(point.get("y")) for point in points]
        ylo, yhi = min(ys + [reference]), max(ys + [reference])
        padding = max((yhi - ylo) * .08, .08)
        ylo, yhi = max(0, ylo - padding), yhi + padding
        if ylo == yhi:
            yhi = ylo + 1
        for tick in range(5):
            x = left + plot_w * tick / 4
            y = top + plot_h * tick / 4
            if options.get("show_grid", True):
                canvas.create_line(x, top, x, top + plot_h, fill="#dbe4ec", dash=(2, 4))
                canvas.create_line(left, y, left + plot_w, y, fill="#dbe4ec", dash=(2, 4))
            x_value = 10 ** (xlo + (xhi - xlo) * tick / 4) if use_log else xlo + (xhi - xlo) * tick / 4
            y_value = yhi - (yhi - ylo) * tick / 4
            canvas.create_text(x, top + plot_h + 17, text=fmt(x_value), font=("Microsoft YaHei UI", 8), fill="#52606d")
            canvas.create_text(left - 8, y, text=f"{y_value:.1f}×", anchor="e", font=("Microsoft YaHei UI", 8), fill="#52606d")
        reference_y = top + (yhi - reference) / (yhi - ylo) * plot_h
        canvas.create_line(left, reference_y, left + plot_w, reference_y, fill="#64748b", width=2)
        canvas.create_text(left + 4, reference_y - 5, text="1倍人气基准", anchor="sw", font=("Microsoft YaHei UI", 8), fill="#64748b")
        max_size = max([number(point.get("size")) for point in points] + [1e-9])
        for index, point in enumerate(points):
            tx = transformed_x[index]
            x = left + (tx - xlo) / (xhi - xlo) * plot_w
            y = top + (yhi - number(point.get("y"))) / (yhi - ylo) * plot_h
            radius = 4 + 22 * math.sqrt(max(0, number(point.get("size"))) / max_size)
            highlighted = bool(point.get("highlight"))
            if point.get("anomaly"):
                fill, outline = "#f6ad55", "#dd6b20"
            elif highlighted:
                fill, outline = "#8b1e3f", "#6b102f"
            else:
                fill, outline = "#b7c5cf", "#ffffff"
            canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=fill, outline=outline, width=1)
            canvas._point_points.append({
                "x": x, "y": y, "radius": radius, "label": point.get("label", "点"),
                "x_value": point.get("x"), "y_value": point.get("y"), "x_format": "number",
                "y_format": "decimal", "x_label": chart.get("x_label", "X"), "y_label": chart.get("y_label", "Y"),
                "subtitle": point.get("subtitle", ""), "plot_top": top, "plot_bottom": top + plot_h,
                "plot_left": left, "plot_right": left + plot_w,
            })
            if options.get("show_labels", True) and highlighted:
                direction = -1 if x > left + plot_w * .72 else 1
                label_x = clamp(x + direction * (radius + 44), left + 4, left + plot_w - 4)
                label_y = max(top + 12, min(top + plot_h - 24, y - 22))
                canvas.create_line(x, y, label_x, label_y, fill="#94a3b8")
                anchor = "e" if direction < 0 else "w"
                canvas.create_text(label_x, label_y - 3, text=point.get("label", ""), anchor=anchor, font=("Microsoft YaHei UI", 8, "bold"), fill="#263238")
                canvas.create_text(label_x, label_y + 11, text=point.get("subtitle", ""), anchor=anchor, font=("Microsoft YaHei UI", 8), fill="#718096")
        canvas.create_text(left + plot_w / 2, height - 12, text=chart.get("x_label", "X"), font=("Microsoft YaHei UI", 10, "bold"), fill="#263238")
        canvas.create_text(15, top + plot_h / 2, text=chart.get("y_label", "Y"), angle=90, font=("Microsoft YaHei UI", 10, "bold"), fill="#263238")

    def draw_heatmap(self, canvas, chart, options, palette, width, height):
        matrix = chart["matrix"]; rows = chart["row_labels"]; cols = chart["col_labels"]
        if not matrix:
            return
        kind = chart.get("heatmap_kind", "")
        longest = max((len(str(label)) for label in rows), default=8)
        left = min(int(width * .34), max(150, 48 + longest * 9))
        if kind == "ranked_metrics":
            top, right, bottom = 62, 24, 64
        else:
            top, right, bottom = 142, 24, 32
        cell_w = (width - left - right) / max(1, len(cols)); cell_h = (height - top - bottom) / max(1, len(rows))
        values = [v for row in matrix for v in row if v is not None]
        lo, hi = min(values or [0]), max(values or [1])
        if lo == hi: hi = lo + 1
        diagonal = {tuple(cell) for cell in chart.get("diagonal_cells", [])}
        anomalies = {tuple(cell) for cell in chart.get("anomaly_cells", [])}
        for c, label in enumerate(cols):
            short = label if len(label) < 18 else label[:17] + "…"
            if kind == "ranked_metrics":
                canvas.create_text(left + (c + .5) * cell_w, top + len(rows) * cell_h + 13, text=short, anchor="n", font=("Microsoft YaHei UI", 8, "bold"), fill="#263238", width=max(55, cell_w - 4))
            else:
                header = short.replace(" ", "\n", 1)
                canvas.create_text(left + (c + .5) * cell_w, top - 8, text=header, anchor="s", font=("Microsoft YaHei UI", 7, "bold"), fill="#263238", width=max(28, cell_w - 2))
        for r, (label, values_row) in enumerate(zip(rows, matrix)):
            canvas.create_text(left - 8, top + (r + .5) * cell_h, text=label, anchor="e", font=("Microsoft YaHei UI", 8), fill="#263238")
            for c, value in enumerate(values_row):
                x1 = left + c * cell_w; y1 = top + r * cell_h
                if (r, c) in diagonal:
                    color = "#17363d"
                elif value is None:
                    color = "#eef2f6"
                else:
                    ratio = (number(value) - lo) / (hi - lo)
                    if chart.get("color_direction") == "low":
                        ratio = 1 - ratio
                    color = mix_color("#edf5f6", palette[1 if len(palette) > 1 else 0], ratio)
                canvas.create_rectangle(x1, y1, x1 + cell_w, y1 + cell_h, fill=color, outline="#ffffff")
                if value is None and (r, c) not in diagonal and chart.get("missing_hatch"):
                    canvas.create_line(x1, y1, x1 + cell_w, y1 + cell_h, fill="#cbd5e1")
                    canvas.create_line(x1, y1 + cell_h * .55, x1 + cell_w * .45, y1 + cell_h, fill="#cbd5e1")
                    canvas.create_line(x1 + cell_w * .55, y1, x1 + cell_w, y1 + cell_h * .45, fill="#cbd5e1")
                elif value is not None and options.get("show_labels", True) and cell_w >= 29 and cell_h >= 17:
                    canvas.create_text(x1 + cell_w / 2, y1 + cell_h / 2, text=fmt(value, chart.get("value_format")), font=("Microsoft YaHei UI", 7), fill=contrast_color(color))
                if (r, c) in anomalies:
                    canvas.create_rectangle(x1 + 1, y1 + 1, x1 + cell_w - 1, y1 + cell_h - 1, outline="#dd6b20", width=2)

    def draw_network(self, canvas, chart, options, palette, width, height):
        nodes, edges = chart.get("nodes", []), chart.get("edges", [])
        if not nodes:
            return
        list_width = min(390, max(240, width * .28))
        graph_width = width - list_width
        cx, cy = graph_width / 2, height / 2 + 15; radius = max(100, min(graph_width, height) * .34)
        positions = {}
        for idx, node in enumerate(nodes):
            angle = -math.pi / 2 + 2 * math.pi * idx / len(nodes)
            positions[node["id"]] = (cx + radius * math.cos(angle), cy + radius * math.sin(angle))
        max_edge = max([e["value"] for e in edges] + [1]); max_node = max([n["value"] for n in nodes] + [1])
        for edge in sorted(edges, key=lambda e: e["value"]):
            if edge["source"] not in positions or edge["target"] not in positions:
                continue
            x1, y1 = positions[edge["source"]]; x2, y2 = positions[edge["target"]]
            width_line = 1 + 6 * edge["value"] / max_edge
            color = mix_color("#cbd5e1", palette[0], min(1, edge.get("lift", 1) / 8))
            canvas.create_line(x1, y1, x2, y2, fill=color, width=width_line)
        for idx, node in enumerate(nodes):
            x, y = positions[node["id"]]; size = 6 + 11 * math.sqrt(node["value"] / max_node)
            color = palette[idx % len(palette)]
            canvas.create_oval(x - size, y - size, x + size, y + size, fill=color, outline="#ffffff", width=2)
            if options.get("show_labels", True):
                canvas.create_text(x, y, text=str(idx + 1), font=("Microsoft YaHei UI", 8, "bold"), fill=contrast_color(color))
        if options.get("show_labels", True):
            canvas.create_text(graph_width + 12, 55, text="节点完整名称", anchor="w", font=("Microsoft YaHei UI", 10, "bold"), fill="#263238")
            for idx, node in enumerate(nodes):
                canvas.create_text(graph_width + 12, 78 + idx * 19, text=f"{idx + 1}. {node['label']}", anchor="w", font=("Microsoft YaHei UI", 8), fill="#263238")

    def draw_faceted_network(self, canvas, chart, options, palette, width, height):
        panels = chart.get("panels", [])
        gap, area_top, legend_h = 18, 52, 54
        panel_w = (width - gap * 3) / 2
        panel_h = (height - area_top - legend_h - gap * 3) / 2

        def edge_style(lift):
            lift = number(lift)
            if lift < 1: return "#cbd5e1", 1, (4, 4)
            if lift < 1.5: return "#94a3b8", 2, None
            if lift < 2: return "#2a9d8f", 2, None
            if lift < 3: return "#d4a72c", 3, None
            if lift < 5: return "#e76f51", 4, None
            if lift < 10: return "#8b1e3f", 5, None
            return "#6a4c93", 6, None

        for index in range(4):
            row, col = divmod(index, 2)
            x1 = gap + col * (panel_w + gap)
            y1 = area_top + gap + row * (panel_h + gap)
            x2, y2 = x1 + panel_w, y1 + panel_h
            canvas.create_rectangle(x1, y1, x2, y2, fill="#f4f1ec", outline="#e7e2da", width=1)
            if index >= len(panels):
                continue
            panel = panels[index]
            nodes, edges = panel.get("nodes", []), panel.get("edges", [])
            canvas.create_text(x1 + 16, y1 + 15, text=panel.get("title", ""), anchor="nw", font=("Microsoft YaHei UI", 11, "bold"), fill="#263238")
            if not nodes:
                canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2, text="当前届无公开关系", font=("Microsoft YaHei UI", 10), fill="#718096")
                continue
            graph_cx = (x1 + x2) / 2
            graph_cy = y1 + panel_h * .43
            radius_x = max(40, panel_w * .28)
            radius_y = max(35, panel_h * .25)
            positions = {}
            for node_index, node in enumerate(nodes):
                angle = -math.pi / 2 + 2 * math.pi * node_index / max(1, len(nodes))
                positions[node["id"]] = (graph_cx + radius_x * math.cos(angle), graph_cy + radius_y * math.sin(angle))
            for edge in sorted(edges, key=lambda item: number(item.get("lift"))):
                if edge["source"] not in positions or edge["target"] not in positions:
                    continue
                ex1, ey1 = positions[edge["source"]]; ex2, ey2 = positions[edge["target"]]
                color, line_w, dash = edge_style(edge.get("lift"))
                canvas.create_line(ex1, ey1, ex2, ey2, fill=color, width=line_w, dash=dash)
            for node in nodes:
                nx, ny = positions[node["id"]]
                size = 24 if len(nodes) <= 4 else 21
                canvas.create_oval(nx - size, ny - size, nx + size, ny + size, fill="#fffdf8", outline="#138f8f", width=3)
                label = node.get("label", "")
                canvas.create_text(nx, ny, text=label, width=size * 1.7, justify="center", font=("Microsoft YaHei UI", 7, "bold"), fill="#263238")
            strong = panel.get("strong_edges", [])
            if strong:
                text_lines = [f"{edge['label']} {number(edge.get('lift')):.2f}×·{number(edge.get('value')):,.0f}人" for edge in strong]
                canvas.create_text(x1 + 16, y2 - 13, text="较强边：" + " ｜ ".join(text_lines), anchor="sw", width=panel_w - 32, font=("Microsoft YaHei UI", 7), fill="#718096")
        legend_y = height - 24
        labels = [("<1倍", "#cbd5e1"), ("1–1.5倍", "#94a3b8"), ("1.5–2倍", "#2a9d8f"), ("2–3倍", "#d4a72c"), ("3–5倍", "#e76f51"), ("5–10倍", "#8b1e3f"), ("≥10倍", "#6a4c93")]
        start_x = max(18, (width - len(labels) * 105) / 2)
        canvas.create_text(start_x - 8, legend_y, text="同投集中倍数：", anchor="e", font=("Microsoft YaHei UI", 8, "bold"), fill="#52606d")
        for index, (label, color) in enumerate(labels):
            x = start_x + index * 105
            canvas.create_line(x, legend_y, x + 28, legend_y, fill=color, width=max(1, index))
            canvas.create_text(x + 34, legend_y, text=label, anchor="w", font=("Microsoft YaHei UI", 8), fill="#52606d")

    def draw_vertical_legend(self, canvas, series, palette, x, top, bottom):
        canvas.create_text(x, top, text="系列", anchor="nw", font=("Microsoft YaHei UI", 9, "bold"), fill="#52606d")
        max_items = max(1, int((bottom - top - 22) / 18))
        for index, item in enumerate(series[:max_items]):
            y = top + 22 + index * 18
            color = palette[index % len(palette)]
            canvas.create_line(x, y, x + 16, y, fill=color, width=3)
            label = item["name"] if len(item["name"]) <= 24 else item["name"][:23] + "…"
            canvas.create_text(x + 22, y, text=label, anchor="w", font=("Microsoft YaHei UI", 8), fill="#263238")
        if len(series) > max_items:
            canvas.create_text(x + 22, top + 22 + max_items * 18, text=f"另有 {len(series) - max_items} 个系列，完整名称见结果表", anchor="w", font=("Microsoft YaHei UI", 8), fill="#718096")

    def draw_legend(self, canvas, series, palette, width):
        x = width - 22
        for idx, item in enumerate(reversed(series)):
            label = item["name"]
            tw = 18 + len(label) * 12
            x -= tw
            color = palette[(len(series) - idx - 1) % len(palette)]
            canvas.create_rectangle(x, 18, x + 10, 28, fill=color, outline="")
            canvas.create_text(x + 15, 23, text=label, anchor="w", font=("Microsoft YaHei UI", 8), fill="#263238")


class AnalysisWorkbench:
    def __init__(self, parent: tk.Misc):
        self.window = tk.Toplevel(parent)
        self.window.title("东方投票全届分析工作台｜CN1–11 / JP3–22")
        self.window.geometry("1500x940")
        self.window.minsize(1120, 720)
        self.repo = AnalysisRepository()
        self.renderer = ChartRenderer()
        self.chart: dict | None = None
        self._build_vars()
        self._build_ui()
        self.on_template_changed()

    def _build_vars(self):
        self.template_display = tk.StringVar(value=TEMPLATES[0].display)
        self.template_group = tk.StringVar(value="全部")
        self.current_round = tk.StringVar(value="JP22")
        self.compare_round = tk.StringVar(value="JP21")
        self.top_n = tk.StringVar(value="20")
        self.rank_start = tk.StringVar(value="1")
        self.rank_end = tk.StringVar(value="20")
        self.range_preset = tk.StringVar(value="1–20")
        self.pair_range_mode = tk.StringVar(value="两端都在区间")
        self.min_count = tk.StringVar(value="100")
        self.min_entity_votes = tk.StringVar(value="0")
        self.search = tk.StringVar()
        self.faction = tk.StringVar(value="")
        self.faction_display = tk.StringVar(value="全部")
        self.chart_override = tk.StringVar(value="自动（按模板）")
        self.palette = tk.StringVar(value="东方红蓝")
        self.sort_mode = tk.StringVar(value="数值降序")
        self.change_direction = tk.StringVar(value="全部变化")
        self.language = tk.StringVar(value="中文优先")
        self.question_key = tk.StringVar(value="age")
        self.question_display = tk.StringVar(value=QUESTION_LABELS["age"])
        self.question_raw_by_display = {QUESTION_LABELS["age"]: "age"}
        self.relation_question = tk.StringVar(value="sex")
        self.relation_question_display = tk.StringVar(value=ENTITY_QUESTION_LABELS["sex"])
        self.relation_answer = tk.StringVar(value="女性")
        self.relation_answer_display = tk.StringVar(value=answer_display("女性"))
        self.relation_value_mode = tk.StringVar(value="问卷选项比例")
        self.relation_sort_mode = tk.StringVar(value="按选项人数")
        self.answer_raw_by_display = {answer_display("女性"): "女性"}
        self.relation_question_raw_by_display = {ENTITY_QUESTION_LABELS["sex"]: "sex"}
        self.x_metric = tk.StringVar(value="selection_count")
        self.y_metric = tk.StringVar(value="rank")
        self.x_metric_display = tk.StringVar(value=METRIC_LABELS["selection_count"])
        self.y_metric_display = tk.StringVar(value=METRIC_LABELS["rank"])
        self.custom_title = tk.StringVar()
        self.export_width = tk.StringVar(value="1400")
        self.export_height = tk.StringVar(value="900")
        self.show_labels = tk.BooleanVar(value=True)
        self.show_grid = tk.BooleanVar(value=True)
        self.description = tk.StringVar()
        self.note = tk.StringVar()
        self.interpretation = tk.StringVar()
        self.status = tk.StringVar()

    def _build_ui(self):
        controls = ttk.LabelFrame(self.window, text="分析模板与图表配置")
        controls.pack(fill="x", padx=8, pady=(8, 4))
        for col in range(12):
            controls.columnconfigure(col, weight=1 if col in {1, 5, 9} else 0)
        groups = ["全部"] + list(dict.fromkeys(item.group for item in TEMPLATES))
        self.group_combo = self._combo(controls, 0, 0, "图表分类", self.template_group, groups, 13, self.on_group_changed)
        self.template_combo = self._combo(controls, 0, 2, "文章图表", self.template_display, [t.display for t in TEMPLATES], 38, self.on_template_changed, span=3)
        self.current_round_combo = self._combo(controls, 0, 6, "当前届", self.current_round, self.repo.round_labels, 7, self.on_round_changed)
        self.compare_round_combo = self._combo(controls, 0, 8, "对比届", self.compare_round, self.repo.round_labels, 7, self.on_compare_round_changed)
        ttk.Label(controls, text="自定义标题").grid(row=0, column=10, padx=(10, 3), pady=5, sticky="e")
        ttk.Entry(controls, textvariable=self.custom_title).grid(row=0, column=11, columnspan=1, padx=3, pady=5, sticky="ew")

        self.top_n_spin = self._spin(controls, 1, 0, "显示结果数（Top N）", self.top_n, 3, 100)
        self.rank_start_spin = self._spin(controls, 1, 2, "起始名次", self.rank_start, 1, 2000)
        self.rank_end_spin = self._spin(controls, 1, 4, "结束名次", self.rank_end, 1, 2000)
        self.search_label = ttk.Label(controls, text="实体/阵营搜索")
        self.search_label.grid(row=1, column=6, padx=(10, 3), pady=5, sticky="e")
        self.search_entry = ttk.Entry(controls, textvariable=self.search)
        self.search_entry.grid(row=1, column=7, columnspan=2, padx=3, pady=5, sticky="ew")
        self.question_combo = self._combo(controls, 1, 9, "问卷题目", self.question_display, list(QUESTION_LABELS.values()), 36, self.on_question_changed)

        self.chart_override_combo = self._combo(controls, 2, 0, "图表类型", self.chart_override, list(CHART_OVERRIDES), 17, self.redraw)
        self._combo(controls, 2, 2, "配色", self.palette, list(PALETTES), 12)
        self.sort_combo = self._combo(controls, 2, 4, "排序", self.sort_mode, list(SORT_OPTIONS), 12, self.refresh)
        self.change_direction_combo = self._combo(controls, 2, 6, "变化方向", self.change_direction, list(CHANGE_DIRECTION_OPTIONS), 14, self.refresh)
        # Put the name selector on the next available row; the dynamic change
        # direction selector occupies columns 6–7.
        self.language_combo = self._combo(controls, 2, 8, "名称", self.language, list(LANGUAGE_OPTIONS), 11, self.refresh)
        self.faction_combo = self._combo(
            controls, 3, 0, "原作阵营", self.faction_display,
            ["全部"] + self.repo.faction_options, 26,
            self.on_faction_changed, span=3,
        )
        self.x_combo = self._combo(controls, 3, 8, "横轴指标", self.x_metric_display, [METRIC_LABELS[x] for x in CHARACTER_METRICS], 18, self.on_metric_changed)
        self.y_combo = self._combo(controls, 3, 10, "纵轴指标", self.y_metric_display, [METRIC_LABELS[x] for x in CHARACTER_METRICS], 18, self.on_metric_changed)

        self.export_width_spin = self._spin(controls, 4, 0, "导出宽度", self.export_width, 600, 4000)
        self.export_height_spin = self._spin(controls, 4, 2, "导出高度", self.export_height, 400, 3000)
        ttk.Checkbutton(controls, text="显示数值/名称", variable=self.show_labels, command=self.redraw).grid(row=4, column=4, padx=7, pady=5)
        ttk.Checkbutton(controls, text="显示网格", variable=self.show_grid, command=self.redraw).grid(row=4, column=5, padx=7, pady=5)
        self.min_count_spin = self._spin(controls, 4, 6, "最少共同人数", self.min_count, 0, 10000)
        ttk.Button(controls, text="生成/刷新", command=self.refresh).grid(row=4, column=8, padx=4, pady=5, sticky="ew")
        ttk.Button(controls, text="恢复默认", command=self.reset).grid(row=4, column=9, padx=4, pady=5, sticky="ew")
        ttk.Button(controls, text="导出 SVG", command=self.export_svg).grid(row=4, column=10, padx=4, pady=5, sticky="ew")
        ttk.Button(controls, text="导出数据 CSV", command=self.export_csv).grid(row=4, column=11, padx=4, pady=5, sticky="ew")

        self.range_preset_combo = self._combo(controls, 5, 0, "名次区间", self.range_preset, RANGE_PRESETS, 11, self.on_range_preset)
        self.shift_prev_button = ttk.Button(controls, text="上一段", command=lambda: self.shift_range(-1)); self.shift_prev_button.grid(row=5, column=2, padx=3, pady=5, sticky="ew")
        self.shift_next_button = ttk.Button(controls, text="下一段", command=lambda: self.shift_range(1)); self.shift_next_button.grid(row=5, column=3, padx=3, pady=5, sticky="ew")
        self.pair_range_combo = self._combo(controls, 5, 4, "同投区间", self.pair_range_mode, list(PAIR_RANGE_OPTIONS), 16)
        self.min_entity_votes_spin = self._spin(controls, 5, 6, "最少实体投票人数", self.min_entity_votes, 0, 1000000)
        self.range_hint = ttk.Label(controls, text="区间会同时作用于图表、总览、结果表和导出", foreground="#475569")
        self.range_hint.grid(row=5, column=8, columnspan=4, padx=6, pady=5, sticky="w")

        self.relation_question_combo = self._combo(controls, 6, 0, "实体问卷", self.relation_question_display, list(ENTITY_QUESTION_LABELS.values()), 42, self.on_relation_question_changed, span=2)
        self.relation_answer_combo = self._combo(controls, 6, 2, "问卷选项", self.relation_answer_display, [answer_display("女性")], 26, self.on_relation_answer_changed, span=2)
        self.relation_value_combo = self._combo(controls, 6, 6, "关联纵轴", self.relation_value_mode, list(RELATION_VALUE_OPTIONS), 22, self.refresh)
        self.relation_sort_combo = self._combo(controls, 6, 9, "关联排序", self.relation_sort_mode, list(RELATION_SORT_OPTIONS), 16, self.refresh)
        self.relation_hint = ttk.Label(controls, text="横轴=所选人群人数；纵轴=该人群比例；点大小=该题有效人数", foreground="#475569")
        self.relation_hint.grid(row=7, column=0, columnspan=12, padx=9, pady=3, sticky="w")

        ttk.Label(self.window, textvariable=self.description, foreground="#334155").pack(fill="x", padx=12, pady=(2, 0))
        ttk.Label(self.window, textvariable=self.note, foreground="#9a3412").pack(fill="x", padx=12, pady=(0, 3))
        interpretation_frame = ttk.LabelFrame(self.window, text="数据解读 / 异常说明")
        interpretation_frame.pack(fill="x", padx=8, pady=(0, 3))
        ttk.Label(interpretation_frame, textvariable=self.interpretation, foreground="#334155", wraplength=1450, justify="left").pack(fill="x", padx=8, pady=5)

        notebook = ttk.Notebook(self.window)
        notebook.pack(fill="both", expand=True, padx=8, pady=4)
        chart_frame = ttk.Frame(notebook)
        overview_frame = ttk.Frame(notebook)
        table_frame = ttk.Frame(notebook)
        notebook.add(chart_frame, text="图表预览")
        notebook.add(overview_frame, text="分段总览（非作图）")
        notebook.add(table_frame, text="计算结果表")
        self.canvas = tk.Canvas(chart_frame, background="#fffdf8", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _event: self.redraw())
        overview_toolbar = ttk.Frame(overview_frame)
        overview_toolbar.pack(fill="x", padx=5, pady=5)
        self.overview_caption = ttk.Label(overview_toolbar, text="")
        self.overview_caption.pack(side="left")
        ttk.Button(overview_toolbar, text="导出当前区间 CSV", command=self.export_overview_csv).pack(side="right")
        self.overview = ttk.Treeview(overview_frame, show="headings", columns=("round", "rank", "name", "points", "primary", "secondary", "selection", "rate"))
        overview_y = ttk.Scrollbar(overview_frame, orient="vertical", command=self.overview.yview)
        overview_x = ttk.Scrollbar(overview_frame, orient="horizontal", command=self.overview.xview)
        self.overview.configure(yscrollcommand=overview_y.set, xscrollcommand=overview_x.set)
        self.overview.pack(fill="both", expand=True, padx=(5, 20), pady=(0, 20))
        overview_y.place(relx=1.0, rely=0.0, relheight=1.0, x=-18, y=38, anchor="ne")
        overview_x.place(relx=0.0, rely=1.0, relwidth=1.0, x=5, y=-18, anchor="sw")
        overview_headers = {"round": "届次", "rank": "官方名次", "name": "实体完整名称", "points": "官方分数", "primary": "第一顺位票", "secondary": "第二顺位票", "selection": "实际选择人数", "rate": "选择率"}
        for column, heading in overview_headers.items():
            self.overview.heading(column, text=heading)
            self.overview.column(column, width=280 if column == "name" else 115, anchor="w" if column == "name" else "center")
        self.table = ttk.Treeview(table_frame, show="headings")
        ybar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        xbar = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.table.grid(row=0, column=0, sticky="nsew"); ybar.grid(row=0, column=1, sticky="ns"); xbar.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1); table_frame.columnconfigure(0, weight=1)
        ttk.Label(self.window, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x", padx=8, pady=(0, 7))

    def _combo(self, parent, row, col, label, variable, values, width, callback=None, span=1):
        label_widget = ttk.Label(parent, text=label)
        label_widget.grid(row=row, column=col, padx=(8, 3), pady=5, sticky="e")
        combo = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly", width=width)
        combo.grid(row=row, column=col + 1, columnspan=span, padx=3, pady=5, sticky="ew")
        combo._workbench_label = label_widget
        if callback:
            combo.bind("<<ComboboxSelected>>", lambda _event: callback())
        return combo

    def _spin(self, parent, row, col, label, variable, start, end):
        label_widget = ttk.Label(parent, text=label)
        label_widget.grid(row=row, column=col, padx=(8, 3), pady=5, sticky="e")
        spin = ttk.Spinbox(parent, textvariable=variable, from_=start, to=end, width=8)
        spin.grid(row=row, column=col + 1, padx=3, pady=5, sticky="w")
        spin._workbench_label = label_widget
        return spin

    @staticmethod
    def _set_control_visible(widget, visible: bool):
        if widget is None:
            return
        label = getattr(widget, "_workbench_label", None)
        if visible:
            if label is not None:
                label.grid()
            widget.grid()
        else:
            if label is not None:
                label.grid_remove()
            widget.grid_remove()

    def template_key(self) -> str:
        for item in TEMPLATES:
            if item.display == self.template_display.get():
                return item.key
        return TEMPLATES[0].key

    def on_group_changed(self):
        group = self.template_group.get()
        items = [item for item in TEMPLATES if group == "全部" or item.group == group]
        values = [item.display for item in items]
        self.template_combo["values"] = values
        if self.template_display.get() not in values:
            self.template_display.set(values[0] if values else TEMPLATES[0].display)
        self.on_template_changed()

    def config(self) -> dict:
        return {
            "current_round": self.current_round.get(), "compare_round": self.compare_round.get(),
            "top_n": integer(self.top_n.get(), 20), "rank_start": integer(self.rank_start.get(), 1),
            "rank_end": integer(self.rank_end.get(), 20),
            "min_count": integer(self.min_count.get(), 100), "search": self.search.get(),
            "min_entity_votes": integer(self.min_entity_votes.get(), 0),
            "faction": self.faction.get(),
            "sort": SORT_OPTIONS[self.sort_mode.get()], "language": LANGUAGE_OPTIONS[self.language.get()],
            "change_direction": CHANGE_DIRECTION_OPTIONS[self.change_direction.get()],
            "question_key": self.question_key.get(), "x_metric": self.x_metric.get(), "y_metric": self.y_metric.get(),
            "pair_range_mode": PAIR_RANGE_OPTIONS[self.pair_range_mode.get()],
            "relation_question": self.relation_question.get(), "relation_answer": self.relation_answer.get(),
            "relation_value_mode": RELATION_VALUE_OPTIONS[self.relation_value_mode.get()],
            "relation_sort": RELATION_SORT_OPTIONS[self.relation_sort_mode.get()],
        }

    def render_options(self) -> dict:
        return {
            "title": self.custom_title.get().strip(), "chart_override": CHART_OVERRIDES[self.chart_override.get()],
            "palette": self.palette.get(), "show_labels": self.show_labels.get(), "show_grid": self.show_grid.get(),
        }

    def is_music_template(self) -> bool:
        return TEMPLATE_BY_KEY[self.template_key()].group in {"曲子", "曲子问卷关联"} or self.template_key() == "m06_music_character_cross"

    def is_cp_template(self) -> bool:
        return TEMPLATE_BY_KEY[self.template_key()].group == "CP投票"

    def is_cross_template(self) -> bool:
        return self.template_key() in {"m05_character_music_cross", "m06_music_character_cross", "m09_music_arrangement_cross", "m10_character_arrangement_cross"}

    def is_relation_template(self) -> bool:
        return TEMPLATE_BY_KEY[self.template_key()].group in {"问卷关联", "曲子问卷关联"}

    def relation_category(self) -> str:
        if self.template_key() == "r08_work_question_matrix":
            return "work"
        return "music" if self.is_music_template() else "character"

    def on_template_changed(self):
        spec = TEMPLATE_BY_KEY[self.template_key()]
        # Top N is applied after each template's own sort.  Relation/scatter
        # views select entities, while ranking/table views select result rows;
        # make that distinction visible instead of leaving an unexplained
        # generic "Top N" label.
        relation_entity_builders = {
            "entity_question_scatter", "entity_question_difference", "entity_question_correlation",
            "character_cognition", "work_question_matrix", "entity_question_matrix",
        }
        top_label = "显示实体数（Top N）" if spec.builder in relation_entity_builders or spec.chart_type == "scatter" else "显示结果数（Top N）"
        self.top_n_spin._workbench_label.configure(text=top_label)
        self.description.set(spec.description)
        # Only expose chart forms that match the data returned by this
        # template.  ``auto`` remains the recommended choice and ``table`` is
        # always available as a lossless fallback.
        display_for_type = {value: label for label, value in CHART_OVERRIDES.items()}
        allowed = template_chart_types(spec)
        values = [display_for_type[item] for item in allowed if item in display_for_type]
        self.chart_override_combo["values"] = values
        if self.chart_override.get() not in values:
            self.chart_override.set(values[0] if values else "自动（按模板）")
        if spec.key in {"a03_bubble"}:
            self.rank_start.set("1"); self.rank_end.set("100"); self.top_n.set("100"); self.range_preset.set("自定义")
        if spec.key == "q01_age": self.question_key.set("age")
        elif spec.key == "q02_cognition": self.question_key.set("cognition")
        elif spec.key == "q03_usertype": self.question_key.set("usertype")
        elif spec.key == "q04_new" and self.question_key.get() not in {"th21", "parents"}: self.question_key.set("th21")
        self.question_display.set(questionnaire_label(self.question_key.get()))
        if spec.key == "x_covote":
            self.x_combo["values"] = [METRIC_LABELS[x] for x in COVOTE_METRICS]
            self.y_combo["values"] = [METRIC_LABELS[x] for x in COVOTE_METRICS]
            self.x_metric.set("intersection_count"); self.y_metric.set("lift")
            self.x_metric_display.set(METRIC_LABELS["intersection_count"]); self.y_metric_display.set(METRIC_LABELS["lift"])
        elif self.is_cp_template():
            self.x_combo["values"] = [METRIC_LABELS[x] for x in CP_METRICS]
            self.y_combo["values"] = [METRIC_LABELS[x] for x in CP_METRICS]
            if self.x_metric.get() not in CP_METRICS: self.x_metric.set("rank")
            if self.y_metric.get() not in CP_METRICS: self.y_metric.set("vote_count")
            self.x_metric_display.set(METRIC_LABELS[self.x_metric.get()]); self.y_metric_display.set(METRIC_LABELS[self.y_metric.get()])
        elif spec.key in {"m09_music_arrangement_cross", "m10_character_arrangement_cross"}:
            self.x_combo["values"] = [METRIC_LABELS[x] for x in ARRANGEMENT_X_METRICS]
            if self.x_metric.get() not in ARRANGEMENT_X_METRICS:
                self.x_metric.set("arrangement_cumulative_count")
            y_metrics = CHARACTER_METRICS if spec.key == "m10_character_arrangement_cross" else MUSIC_METRICS
            self.y_combo["values"] = [METRIC_LABELS[x] for x in y_metrics]
            if self.y_metric.get() not in y_metrics:
                self.y_metric.set("selection_count")
            self.x_metric_display.set(METRIC_LABELS[self.x_metric.get()])
            self.y_metric_display.set(METRIC_LABELS[self.y_metric.get()])
        elif spec.key == "m05_character_music_cross":
            self.x_combo["values"] = [METRIC_LABELS[x] for x in CHARACTER_METRICS]
            self.y_combo["values"] = [METRIC_LABELS[x] for x in MUSIC_METRICS]
            if self.x_metric.get() not in CHARACTER_METRICS: self.x_metric.set("selection_rate")
            if self.y_metric.get() not in MUSIC_METRICS: self.y_metric.set("selection_rate")
            self.x_metric_display.set(METRIC_LABELS[self.x_metric.get()]); self.y_metric_display.set(METRIC_LABELS[self.y_metric.get()])
        elif spec.key == "m06_music_character_cross":
            self.x_combo["values"] = [METRIC_LABELS[x] for x in MUSIC_METRICS]
            self.y_combo["values"] = [METRIC_LABELS[x] for x in CHARACTER_METRICS]
            if self.x_metric.get() not in MUSIC_METRICS: self.x_metric.set("selection_rate")
            if self.y_metric.get() not in CHARACTER_METRICS: self.y_metric.set("selection_rate")
            self.x_metric_display.set(METRIC_LABELS[self.x_metric.get()]); self.y_metric_display.set(METRIC_LABELS[self.y_metric.get()])
        elif self.is_music_template():
            self.x_combo["values"] = [METRIC_LABELS[x] for x in MUSIC_METRICS]
            self.y_combo["values"] = [METRIC_LABELS[x] for x in MUSIC_METRICS]
            if self.x_metric.get() not in MUSIC_METRICS: self.x_metric.set("rank")
            if self.y_metric.get() not in MUSIC_METRICS: self.y_metric.set("rank")
            self.x_metric_display.set(METRIC_LABELS[self.x_metric.get()]); self.y_metric_display.set(METRIC_LABELS[self.y_metric.get()])
        else:
            self.x_combo["values"] = [METRIC_LABELS[x] for x in CHARACTER_METRICS]
            self.y_combo["values"] = [METRIC_LABELS[x] for x in CHARACTER_METRICS]
            if self.x_metric.get() not in CHARACTER_METRICS: self.x_metric.set("selection_count")
            if self.y_metric.get() not in CHARACTER_METRICS: self.y_metric.set("primary_rate")
            self.x_metric_display.set(METRIC_LABELS[self.x_metric.get()]); self.y_metric_display.set(METRIC_LABELS[self.y_metric.get()])
        if spec.key in {"c00_rank_trend", "m03_rank_trend"}:
            self.y_metric.set("rank")
            self.y_metric_display.set(METRIC_LABELS["rank"])

        # Contextual controls.  Unsupported controls are removed from the
        # grid so a user cannot accidentally configure a meaningless option.
        key = spec.key
        compare_keys = {
            "c00_round_compare", "c01_rank_change", "c03_primary_rate_change", "c06_primary_change",
            "c07_selection_change", "c07_selection_yoy", "c08_points_change", "c09_selection_rate_change",
            "c12_gender_change", "m02_round_compare", "a04_count_dumbbell", "a04_count_change",
            "a05_largest_change", "a09_phi_change", "a13_quadrant", "q01_age", "q02_cognition",
            "q03_usertype", "q04_new", "q_custom",
        }
        change_keys = {
            "c01_rank_change", "c03_primary_rate_change", "c06_primary_change", "c07_selection_change",
            "c07_selection_yoy", "c08_points_change", "c09_selection_rate_change", "c12_gender_change",
            "a04_count_change", "a05_largest_change", "a09_phi_change",
        }
        relation_keys = {item.key for item in TEMPLATES if item.builder in {"entity_question_scatter", "entity_question_difference", "entity_question_correlation", "character_cognition", "work_question_matrix", "entity_question_matrix"}}
        range_visible = spec.group in {"角色", "角色画像", "曲子", "曲子问卷关联", "问卷关联", "同投", "角色—曲子", "CP投票"} and key not in relation_keys
        pair_visible = spec.group == "同投"
        search_visible = spec.group not in {"问卷"}
        self._set_control_visible(self.compare_round_combo, key in compare_keys or key == "p02_combination_compare")
        self._set_control_visible(self.question_combo, key == "q_custom")
        self._set_control_visible(self.relation_question_combo, key in relation_keys)
        matrix_relation_keys = {"r08_work_question_matrix", "r09_character_question_matrix", "r10_music_question_matrix"}
        self._set_control_visible(self.relation_answer_combo, key in relation_keys and key not in matrix_relation_keys)
        self._set_control_visible(self.relation_value_combo, key in relation_keys and key not in matrix_relation_keys)
        self._set_control_visible(self.relation_sort_combo, key in relation_keys and key not in matrix_relation_keys)
        x_metric_keys = {"x_character", "x_covote", "m05_character_music_cross", "m06_music_character_cross", "m09_music_arrangement_cross", "m10_character_arrangement_cross", "r03_character_question_corr", "r06_music_question_corr"}
        y_metric_keys = {
            "c00_round_compare", "c00_all_trend", "m01_metric", "m02_round_compare", "m03_all_trend",
            "x_character", "x_covote", "m05_character_music_cross", "m06_music_character_cross", "m09_music_arrangement_cross", "m10_character_arrangement_cross",
        }
        if self.is_cp_template():
            x_metric_keys.add("p01_cp_metric")
            y_metric_keys.add("p01_cp_metric")
        self._set_control_visible(self.x_combo, key in x_metric_keys and key != "p01_cp_metric")
        self._set_control_visible(self.y_combo, key in y_metric_keys and key not in {"m07_character_music_covote", "m08_character_carryover", "r07_character_cognition"})
        if key in {"r01_character_question_scatter", "r02_character_question_diff", "r03_character_question_corr", "r07_character_cognition"}:
            # A rank/metric that varies by entity makes the association
            # visible; using one fixed cohort total on the x-axis can make
            # answer changes look like mere vertical jitter.
            self.x_metric.set("rank")
            self.x_metric_display.set(METRIC_LABELS["rank"])
            self.x_combo._workbench_label.configure(text="投票指标（表/相关）")
        elif key in {"m09_music_arrangement_cross", "m10_character_arrangement_cross"}:
            self.x_combo._workbench_label.configure(text="横轴同人曲口径")
            self.y_combo._workbench_label.configure(text="纵轴投票指标")
        elif key not in relation_keys:
            self.x_combo._workbench_label.configure(text="横轴指标")
            self.y_combo._workbench_label.configure(text="纵轴指标")
        if key == "r07_character_cognition":
            self.relation_question.set("cognition")
            self.relation_question_display.set(ENTITY_QUESTION_LABELS["cognition"])
        if key in matrix_relation_keys:
            self.relation_question.set(self.relation_question.get() or "cognition")
        self._set_control_visible(self.min_count_spin, pair_visible)
        # The vote-count threshold applies to character/music cohorts only;
        # works have no corresponding entity vote total in the matrix.
        threshold_visible = key in relation_keys and key != "r08_work_question_matrix"
        self._set_control_visible(self.min_entity_votes_spin, threshold_visible)
        self._set_control_visible(self.pair_range_combo, pair_visible)
        self._set_control_visible(self.sort_combo, key not in {"c00_rank_trend", "c00_all_trend", "m03_rank_trend", "m03_all_trend", "c00_round_compare", "m02_round_compare", "p02_combination_compare", "c10_growth_lag", "c11_structure", "c11_metric_heatmap", "c12_gender_structure", "r01_character_question_scatter", "r04_music_question_scatter", "x_character", "x_covote", "m05_character_music_cross", "m06_music_character_cross", "m09_music_arrangement_cross", "m10_character_arrangement_cross", "a01_direction_matrix", "a01_count_matrix", "a02_network", "a03_bubble", "a10_direction", "a13_quadrant", "q01_age", "q02_cognition", "q03_usertype", "q04_new", "q_custom"})
        self._set_control_visible(self.change_direction_combo, key in change_keys)
        for widget in (self.rank_start_spin, self.rank_end_spin, self.range_preset_combo, self.shift_prev_button, self.shift_next_button):
            self._set_control_visible(widget, range_visible)
        self.search_label.grid() if search_visible else self.search_label.grid_remove()
        self.search_entry.grid() if search_visible else self.search_entry.grid_remove()
        # Faction filtering applies to character, music (through validated
        # character↔music tags), relation and co-vote templates.  Aggregate
        # questionnaire-only charts have no entity list, so the selector is
        # hidden there.
        faction_visible = search_visible
        self._set_control_visible(self.faction_combo, faction_visible)
        valid_factions = ["全部"] + self.repo.faction_options
        if self.faction_display.get() not in valid_factions:
            self.faction_display.set("全部")
            self.faction.set("")
        self.range_hint.grid() if range_visible else self.range_hint.grid_remove()
        self.update_metric_options()
        self.update_question_options()
        self.update_relation_question_options()
        self.update_relation_answers()
        self.custom_title.set("")
        self.refresh()

    def on_metric_changed(self):
        reverse = {label: key for key, label in METRIC_LABELS.items()}
        self.x_metric.set(reverse.get(self.x_metric_display.get(), self.x_metric.get()))
        self.y_metric.set(reverse.get(self.y_metric_display.get(), self.y_metric.get()))
        self.refresh()

    def on_question_changed(self):
        self.question_key.set(self.question_raw_by_display.get(self.question_display.get(), self.question_key.get() or "age"))
        self.refresh()

    def on_round_changed(self):
        self.update_metric_options()
        self.update_question_options()
        self.update_relation_question_options()
        self.update_relation_answers()
        self.refresh()

    def on_faction_changed(self):
        selected = self.faction_display.get().strip()
        self.faction.set("" if selected in {"", "全部"} else selected)
        self.refresh()

    def on_compare_round_changed(self):
        self.update_metric_options()
        self.update_question_options()
        self.refresh()

    def _metric_rows(self, category: str, round_label: str) -> list[dict]:
        if category == "music":
            return self.repo.music_by_round.get(round_label, [])
        if category == "covote":
            return self.repo.pairs_by_round.get(round_label, [])
        if category == "cp":
            return self.repo.cp_by_round.get(round_label, [])
        return self.repo.character_by_round.get(round_label, [])

    def _available_metric_fields(self, fields: list[str], category: str, round_labels: list[str], require_each=False) -> list[str]:
        groups = [self._metric_rows(category, label) for label in round_labels]
        available = []
        for field in fields:
            checks = [any(row.get(field) is not None for row in rows) for rows in groups]
            if (all(checks) if require_each else any(checks)):
                available.append(field)
        return available

    @staticmethod
    def _set_metric_combo_values(combo, raw_var, display_var, fields: list[str], fallback: str):
        combo["values"] = [METRIC_LABELS[field] for field in fields]
        selected = raw_var.get()
        if selected not in fields:
            selected = fallback if fallback in fields else (fields[0] if fields else fallback)
        raw_var.set(selected)
        display_var.set(METRIC_LABELS.get(selected, selected))

    def update_metric_options(self):
        """Expose only metrics that have data for the selected round context."""
        key = self.template_key()
        current = self.current_round.get()
        compare = self.compare_round.get()
        compare_metric_keys = {"c00_round_compare", "m02_round_compare", "p02_combination_compare"}
        all_round_keys = {"c00_all_trend", "m03_all_trend"}

        if key in all_round_keys:
            prefix = current[:2]
            rounds = [label for label in self.repo.round_labels if label.startswith(prefix)]
            require_each = False
        elif key in compare_metric_keys:
            rounds = [current, compare]
            require_each = True
        else:
            rounds = [current]
            require_each = False

        if key == "x_covote":
            fields = self._available_metric_fields(COVOTE_METRICS, "covote", [current])
            self._set_metric_combo_values(self.x_combo, self.x_metric, self.x_metric_display, fields, "intersection_count")
            self._set_metric_combo_values(self.y_combo, self.y_metric, self.y_metric_display, fields, "lift")
            return

        if self.is_cp_template():
            fields = self._available_metric_fields(CP_METRICS, "cp", rounds, require_each=require_each)
            self._set_metric_combo_values(self.x_combo, self.x_metric, self.x_metric_display, fields, "rank")
            self._set_metric_combo_values(self.y_combo, self.y_metric, self.y_metric_display, fields, "vote_count")
            return

        if key in {"m09_music_arrangement_cross", "m10_character_arrangement_cross"}:
            x_fields = self._available_metric_fields(ARRANGEMENT_X_METRICS, "music", [current])
            # CN rounds intentionally expose no JP-windowed arrangement axes.
            self._set_metric_combo_values(self.x_combo, self.x_metric, self.x_metric_display, x_fields, "arrangement_cumulative_count")
            y_candidates = CHARACTER_METRICS if key == "m10_character_arrangement_cross" else MUSIC_METRICS
            y_category = "character" if key == "m10_character_arrangement_cross" else "music"
            y_fields = self._available_metric_fields(y_candidates, y_category, [current])
            fallback = "selection_count" if "selection_count" in y_fields else ("points" if "points" in y_fields else "rank")
            self._set_metric_combo_values(self.y_combo, self.y_metric, self.y_metric_display, y_fields, fallback)
            return

        if key == "m05_character_music_cross":
            x_fields = self._available_metric_fields(CHARACTER_METRICS, "character", [current])
            y_fields = self._available_metric_fields(MUSIC_METRICS, "music", [current])
            self._set_metric_combo_values(self.x_combo, self.x_metric, self.x_metric_display, x_fields, "selection_rate")
            self._set_metric_combo_values(self.y_combo, self.y_metric, self.y_metric_display, y_fields, "selection_rate")
            return

        if key == "m06_music_character_cross":
            x_fields = self._available_metric_fields(MUSIC_METRICS, "music", [current])
            y_fields = self._available_metric_fields(CHARACTER_METRICS, "character", [current])
            self._set_metric_combo_values(self.x_combo, self.x_metric, self.x_metric_display, x_fields, "selection_rate")
            self._set_metric_combo_values(self.y_combo, self.y_metric, self.y_metric_display, y_fields, "selection_rate")
            return

        category = "music" if self.is_music_template() else "character"
        candidates = MUSIC_METRICS if category == "music" else CHARACTER_METRICS
        fields = self._available_metric_fields(candidates, category, rounds, require_each=require_each)
        fallback = "rank" if "rank" in fields else (fields[0] if fields else "rank")
        self._set_metric_combo_values(self.x_combo, self.x_metric, self.x_metric_display, fields, fallback)
        self._set_metric_combo_values(self.y_combo, self.y_metric, self.y_metric_display, fields, fallback)

    def on_relation_question_changed(self):
        self.relation_question.set(self.relation_question_raw_by_display.get(self.relation_question_display.get(), self.relation_question.get() or "sex"))
        self.update_relation_answers()
        self.refresh()

    def on_relation_answer_changed(self):
        self.relation_answer.set(self.answer_raw_by_display.get(self.relation_answer_display.get(), ""))
        self.refresh()

    def update_relation_answers(self):
        category = self.relation_category()
        raw_answers = self.repo.entity_question_answers(self.current_round.get(), category, self.relation_question.get())
        self.answer_raw_by_display = {}
        displays = []
        for raw in raw_answers:
            # Entity questionnaire options include work-era ranges such as
            # ``アマノジャク～紺珠伝（2015年8月）``.  Use the repository's
            # catalogue-backed translator instead of the small fixed gender/
            # age dictionary so these options are Chinese and chronological.
            display = self.repo.question_answer_display(self.relation_question.get(), raw, "cn")
            if display in self.answer_raw_by_display and self.answer_raw_by_display[display] != raw:
                display = f"{display}｜{raw}"
            self.answer_raw_by_display[display] = raw
            displays.append(display)
        if not displays:
            displays = ["（该届无实体问卷）"]
            self.answer_raw_by_display = {displays[0]: ""}
        current_raw = self.relation_answer.get()
        selected = next((display for display, raw in self.answer_raw_by_display.items() if raw == current_raw), displays[0])
        self.relation_answer_combo["values"] = displays
        self.relation_answer_display.set(selected)
        self.relation_answer.set(self.answer_raw_by_display[selected])

    def update_question_options(self):
        """Refresh aggregate question selector from the selected CN/JP rounds."""
        rounds = [self.current_round.get(), self.compare_round.get()]
        keys = self.repo.questionnaire_questions(rounds)
        if not keys:
            keys = list(QUESTION_LABELS)
        self.question_raw_by_display = {}
        displays = []
        for key in keys:
            display = questionnaire_label(key)
            if display in self.question_raw_by_display and self.question_raw_by_display[display] != key:
                display = f"{display}｜{key}"
            self.question_raw_by_display[display] = key
            displays.append(display)
        self.question_combo["values"] = displays
        selected = next((display for display, key in self.question_raw_by_display.items() if key == self.question_key.get()), displays[0])
        self.question_display.set(selected)
        self.question_key.set(self.question_raw_by_display[selected])

    def update_relation_question_options(self):
        category = self.relation_category()
        keys = self.repo.entity_question_questions(self.current_round.get(), category)
        if not keys:
            keys = list(ENTITY_QUESTION_LABELS)
        self.relation_question_raw_by_display = {}
        displays = []
        for key in keys:
            display = questionnaire_label(key, entity=True)
            if display in self.relation_question_raw_by_display and self.relation_question_raw_by_display[display] != key:
                display = f"{display}｜{key}"
            self.relation_question_raw_by_display[display] = key
            displays.append(display)
        self.relation_question_combo["values"] = displays
        selected = next((display for display, key in self.relation_question_raw_by_display.items() if key == self.relation_question.get()), displays[0])
        self.relation_question_display.set(selected)
        self.relation_question.set(self.relation_question_raw_by_display[selected])

    def on_range_preset(self):
        value = self.range_preset.get()
        if value == "全部":
            self.rank_start.set("1"); self.rank_end.set("2000"); self.top_n.set("100")
        elif value != "自定义":
            start, end = value.replace("–", "-").split("-", 1)
            self.rank_start.set(start); self.rank_end.set(end); self.top_n.set(str(int(end) - int(start) + 1))
        self.refresh()

    def shift_range(self, direction: int):
        start = max(1, integer(self.rank_start.get(), 1))
        end = max(start, integer(self.rank_end.get(), start + 19))
        span = end - start + 1
        new_start = max(1, start + direction * span)
        new_end = new_start + span - 1
        self.rank_start.set(str(new_start)); self.rank_end.set(str(new_end))
        label = f"{new_start}–{new_end}"
        self.range_preset.set(label if label in RANGE_PRESETS else "自定义")
        self.refresh()

    def refresh(self):
        try:
            if integer(self.rank_start.get(), 1) > integer(self.rank_end.get(), 20):
                self.rank_start.set(self.rank_end.get())
            self.chart = self.repo.build(self.template_key(), self.config())
            self.note.set(self.chart.get("note", ""))
            self.interpretation.set(self.chart.get("interpretation", ""))
            self.populate_table()
            self.populate_overview()
            self.redraw()
            self.status.set(f"模板：{TEMPLATE_BY_KEY[self.template_key()].title}｜结果 {len(self.chart.get('table_rows', [])):,} 行｜区间 {self.rank_start.get()}–{self.rank_end.get()}｜数据：CN1–11 / JP3–22")
        except Exception as exc:
            messagebox.showerror("生成失败", f"无法生成当前图表：\n{exc}", parent=self.window)

    def redraw(self):
        if self.chart:
            effective = self.renderer.render(self.canvas, self.chart, self.render_options())
            self.status.set(f"图表类型：{effective}｜结果 {len(self.chart.get('table_rows', [])):,} 行｜区间 {self.rank_start.get()}–{self.rank_end.get()}｜可切换“分段总览”查看完整名称")

    def overview_rows(self):
        cfg = self.config()
        if self.is_cp_template():
            # CP/组合模板 must not reuse the character overview fields.
            # Keep the same Treeview width but return the actual combination
            # records so names, ranks, counts and provenance remain visible.
            if self.template_key() == "p02_combination_compare":
                current = self.repo.filtered_combinations(cfg, self.current_round.get())
                previous = self.repo.filtered_combinations(cfg, self.compare_round.get())
                rows = [{**row, "_overview_round": self.current_round.get()} for row in current]
                rows += [{**row, "_overview_round": self.compare_round.get()} for row in previous
                         if row.get("combination_key") not in {x.get("combination_key") for x in current}]
            else:
                rows = self.repo.filtered_cp(cfg)
            return sorted(rows, key=lambda row: (number(row.get("rank"), 999999), str(row.get("combination_label", ""))))
        if self.is_relation_template() or self.template_key() in {"r08_work_question_matrix", "r09_character_question_matrix", "r10_music_question_matrix"}:
            cfg = {**cfg, "rank_start": 1, "rank_end": 1000000}
        rows = self.repo.filtered_music(cfg) if self.is_music_template() else self.repo.filtered_characters(cfg)
        return sorted(rows, key=lambda row: number(row.get("rank")))

    def populate_overview(self):
        self.overview.delete(*self.overview.get_children())
        rows = self.overview_rows()
        if self.is_cp_template():
            headers = ["届次", "官方名次", "组合名称", "投票人数", "第一顺位票", "官方分数", "投票率", "来源"]
            for column, heading in zip(("round", "rank", "name", "points", "primary", "secondary", "selection", "rate"), headers):
                self.overview.heading(column, text=heading)
            for row in rows:
                source = row.get("data_source") or row.get("source_type") or "official_cp"
                source = "官方CP" if source in {"official_cp", "cn_official_cp"} else "同投替代" if source == "co-vote_fallback" else source
                self.overview.insert("", "end", values=(
                    row.get("_overview_round", row.get("round_label", self.current_round.get())),
                    fmt(row.get("rank"), "rank") if row.get("rank") is not None else "—",
                    self.repo.combination_label(row, self.config()),
                    fmt(row.get("vote_count", row.get("comparison_count"))),
                    fmt(row.get("first_choice_count")), fmt(row.get("points")),
                    fmt(row.get("vote_rate", row.get("comparison_rate")), "percent"), source,
                ))
            scope = f"结果区间 {self.rank_start.get()}–{self.rank_end.get()}"
            self.overview_caption.configure(text=f"{self.current_round.get()}｜{scope}｜共 {len(rows)} 个组合（组合名称与来源完整显示）")
            return
        overview_headers = {"round": "届次", "rank": "官方名次", "name": "实体完整名称", "points": "官方分数", "primary": "第一顺位票", "secondary": "第二顺位票", "selection": "实际选择人数", "rate": "选择率"}
        for column, heading in overview_headers.items():
            self.overview.heading(column, text=heading)
        for row in rows:
            name = self.repo.name(row, self.config())
            self.overview.insert("", "end", values=(
                row.get("round_label", self.current_round.get()), fmt(row.get("rank"), "rank"), name,
                fmt(row.get("points")), fmt(row.get("primary_count")), fmt(row.get("secondary_count")),
                fmt(row.get("selection_count")), fmt(row.get("selection_rate"), "percent"),
            ))
        entity_type = "曲子" if self.is_music_template() else "角色"
        scope = "全部实体（问卷关联不按名次截取）" if self.is_relation_template() else f"官方名次 {self.rank_start.get()}–{self.rank_end.get()}"
        self.overview_caption.configure(text=f"{self.current_round.get()}｜{scope}｜共 {len(rows)} 个{entity_type}（完整名称不截断）")

    def populate_table(self):
        if not self.chart:
            return
        headers = self.chart.get("table_headers", [])
        self.table.delete(*self.table.get_children())
        self.table["columns"] = [f"c{i}" for i in range(len(headers))]
        for idx, header in enumerate(headers):
            column = f"c{idx}"
            self.table.heading(column, text=header)
            self.table.column(column, width=220 if idx == 0 else 125, anchor="w" if idx == 0 else "center")
        kind = self.chart.get("value_format", "number")
        for row in self.chart.get("table_rows", []):
            values = [row[0]] + [fmt(value, kind) if isinstance(value, (int, float)) else value for value in row[1:]]
            self.table.insert("", "end", values=values)

    def reset(self):
        self.current_round.set("JP22"); self.compare_round.set("JP21"); self.top_n.set("20")
        self.rank_start.set("1"); self.rank_end.set("20"); self.range_preset.set("1–20")
        self.pair_range_mode.set("两端都在区间"); self.min_count.set("100"); self.min_entity_votes.set("0"); self.search.set("")
        self.faction.set(""); self.faction_display.set("全部")
        self.chart_override.set("自动（按模板）"); self.palette.set("东方红蓝")
        self.sort_mode.set("数值降序"); self.language.set("中文优先")
        self.change_direction.set("全部变化")
        self.x_metric.set("selection_count"); self.y_metric.set("rank")
        self.x_metric_display.set(METRIC_LABELS["selection_count"]); self.y_metric_display.set(METRIC_LABELS["rank"])
        self.export_width.set("1400"); self.export_height.set("900")
        self.show_labels.set(True); self.show_grid.set(True); self.custom_title.set("")
        self.relation_question.set("sex"); self.relation_question_display.set(ENTITY_QUESTION_LABELS["sex"])
        self.relation_answer.set("女性"); self.relation_value_mode.set("问卷选项比例")
        self.relation_sort_mode.set("按选项人数")
        self.on_template_changed()

    def export_overview_csv(self):
        rows = self.overview_rows()
        if not rows:
            messagebox.showinfo("没有数据", "当前届次和名次区间没有可导出的实体数据。", parent=self.window)
            return
        path = filedialog.asksaveasfilename(parent=self.window, title="导出当前名次区间", defaultextension=".csv", filetypes=[("CSV 文件", "*.csv")])
        if not path:
            return
        if self.is_cp_template():
            fields = ["round_label", "rank", "combination_label", "vote_count", "first_choice_count", "points", "vote_rate", "data_source", "source_type"]
            with open(path, "w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
                writer.writeheader(); writer.writerows(rows)
            messagebox.showinfo("导出完成", f"已导出 {len(rows)} 个组合：\n{path}", parent=self.window)
            return
        fields = ["category", "round_label", "rank", "name_cn", "name_jp", "points", "primary_count", "secondary_count", "selection_count", "selection_rate"]
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            writer.writeheader(); writer.writerows(rows)
        messagebox.showinfo("导出完成", f"已导出 {len(rows)} 个角色：\n{path}", parent=self.window)

    def export_csv(self):
        if not self.chart:
            return
        path = filedialog.asksaveasfilename(parent=self.window, title="导出分析数据", defaultextension=".csv", filetypes=[("CSV 文件", "*.csv")])
        if not path:
            return
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh); writer.writerow(self.chart.get("table_headers", [])); writer.writerows(self.chart.get("table_rows", []))
        messagebox.showinfo("导出完成", f"分析数据已保存：\n{path}", parent=self.window)

    def export_svg(self):
        if not self.chart:
            return
        path = filedialog.asksaveasfilename(parent=self.window, title="导出配置后的图表", defaultextension=".svg", filetypes=[("SVG 矢量图", "*.svg")])
        if not path:
            return
        options = self.render_options() | {"width": integer(self.export_width.get(), 1400), "height": integer(self.export_height.get(), 900)}
        Path(path).write_text(chart_to_svg(self.chart, options, self.renderer), encoding="utf-8")
        messagebox.showinfo("导出完成", f"SVG 图表已保存：\n{path}", parent=self.window)


def svg_text(x, y, value, size=12, anchor="start", color="#263238", weight="normal", rotate=None):
    transform = f' transform="rotate({rotate} {x} {y})"' if rotate is not None else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" font-family="Microsoft YaHei, sans-serif" font-size="{size}" font-weight="{weight}" fill="{color}"{transform}>{html.escape(str(value))}</text>'


def chart_to_svg(chart: dict, options: dict, renderer: ChartRenderer) -> str:
    width, height = options["width"], options["height"]
    palette = PALETTES[options.get("palette", "东方红蓝")]
    title = options.get("title") or chart.get("title", "")
    chart_type = renderer.effective_type(chart, options)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', '<rect width="100%" height="100%" fill="#fffdf8"/>', svg_text(24, 32, title, 19, weight="bold")]
    if chart_type in {"bar", "grouped", "stacked"} and chart.get("categories"):
        cats, series = chart["categories"], chart["series"]
        longest=max((len(str(label)) for label in cats),default=8)
        left=min(int(width*.43),max(250,70+min(longest,24)*10)); left=min(left,max(190,width-250)); top,right,bottom=62,90,48; pw,ph=max(120,width-left-right),max(120,height-top-bottom)
        values = [v for s in series for v in s["values"] if v is not None]
        lo, hi = (0, 1) if chart_type == "stacked" else (min(values+[0]), max(values+[0]))
        if lo == hi: hi = lo + 1
        zero = left + (-lo)/(hi-lo)*pw; slot = ph/max(1,len(cats))
        for i,label in enumerate(cats):
            y=top+i*slot
            if options.get('show_grid',True): out.append(f'<line x1="{left:.1f}" y1="{y+slot*.5:.1f}" x2="{left+pw:.1f}" y2="{y+slot*.5:.1f}" stroke="#edf2f7" stroke-dasharray="1,5"/>')
            out.append(svg_text(left-10,y+slot*.58,short_label(label,max(12,int((left-24)/9))),9 if longest>28 else 10,"end"))
            if chart_type=="stacked":
                x=left; total=sum(max(0,s["values"][i] or 0) for s in series) or 1
                for si,s in enumerate(series):
                    val=max(0,s["values"][i] or 0)/total; bw=pw*val; color=palette[si%len(palette)]
                    out.append(f'<rect x="{x:.1f}" y="{y+slot*.18:.1f}" width="{bw:.1f}" height="{slot*.62:.1f}" fill="{color}"/>'); x+=bw
            else:
                bh=slot*.68/max(1,len(series))
                for si,s in enumerate(series):
                    val=s["values"][i]
                    if val is None: continue
                    x=left+(val-lo)/(hi-lo)*pw; color=palette[si%len(palette)] if val>=0 else '#64748b'
                    out.append(f'<rect x="{min(zero,x):.1f}" y="{y+slot*.15+si*bh:.1f}" width="{abs(x-zero):.1f}" height="{bh*.82:.1f}" fill="{color}"/>')
                    if options.get('show_labels',True):
                        edge=left+pw
                        if val>=0:
                            anchor='end' if x>edge-48 else 'start'; tx=x-6 if anchor=='end' else x+6
                        else:
                            anchor='start' if x<left+48 else 'end'; tx=x+6 if anchor=='start' else x-6
                        tx=clamp(tx,left+3,edge-3)
                        out.append(svg_text(tx,y+slot*.15+si*bh+bh*.63,fmt(val,chart.get('value_format')),9,anchor))
        out.append(f'<line x1="{zero:.1f}" y1="{top}" x2="{zero:.1f}" y2="{top+ph}" stroke="#64748b"/>')
    elif chart_type == "line" and chart.get("categories"):
        cats, series=chart['categories'],chart['series']; left,top,right,bottom=85,65,min(360,max(210,int(width*.25))),100; pw,ph=width-left-right,height-top-bottom
        vals=[v for s in series for v in s['values'] if v is not None]
        is_rank=chart.get('rank_axis') or chart.get('value_format')=='rank'
        lo,hi=(min(vals),max(vals)) if is_rank and vals else (min(vals+[0]),max(vals+[0])); hi=hi if hi!=lo else lo+1
        for tick in range(5):
            y=top+ph*tick/4; value=lo+(hi-lo)*tick/4 if is_rank else hi-(hi-lo)*tick/4
            if options.get('show_grid',True): out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left+pw}" y2="{y:.1f}" stroke="#dbe4ec" stroke-opacity="0.58" stroke-dasharray="2,4"/>')
            out.append(svg_text(left-8,y+3,fmt(value,chart.get('value_format')),9,'end','#52606d'))
        for si,s in enumerate(series):
            segments=[]; pts=[]
            for i,v in enumerate(s['values']):
                if v is None:
                    if pts: segments.append(pts); pts=[]
                    continue
                x=left+pw*i/max(1,len(cats)-1); y=top+((v-lo) if is_rank else (hi-v))/(hi-lo)*ph; pts.append(f'{x:.1f},{y:.1f}')
            if pts: segments.append(pts)
            for segment in segments:
                if len(segment)>1: out.append(f'<polyline points="{" ".join(segment)}" fill="none" stroke="{palette[si%len(palette)]}" stroke-width="3"/>')
            for point in [item for segment in segments for item in segment]:
                px,py=point.split(','); out.append(f'<circle cx="{px}" cy="{py}" r="3" fill="{palette[si%len(palette)]}"/>')
        for i,label in enumerate(cats):
            x=left+pw*i/max(1,len(cats)-1)
            if options.get('show_grid',True): out.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top+ph}" stroke="#edf2f7" stroke-dasharray="1,5"/>')
            out.append(svg_text(x,top+ph+20,label[:16],9,'end',rotate=-35))
        out += [svg_text(left+pw/2,height-16,chart.get('x_label','届数'),12,'middle',weight='bold'),svg_text(18,top+ph/2,chart.get('y_label','指标'),12,'middle',weight='bold',rotate=-90)]
        legend_x=left+pw+20; out.append(svg_text(legend_x,top+4,'系列',10,'start','#52606d','bold')); max_items=max(1,int((height-bottom-top-22)/18))
        for si,item in enumerate(series[:max_items]):
            y=top+25+si*18; out.append(f'<line x1="{legend_x}" y1="{y}" x2="{legend_x+18}" y2="{y}" stroke="{palette[si%len(palette)]}" stroke-width="3"/>'); out.append(svg_text(legend_x+24,y+3,item['name'][:28],9))
        if len(series)>max_items: out.append(svg_text(legend_x+24,top+25+max_items*18,f'另有 {len(series)-max_items} 个系列，完整名称见数据表',9,color='#718096'))
    elif chart_type == "dumbbell" and chart.get("categories"):
        cats,series=chart['categories'],chart.get('series',[])[:2]
        longest=max((len(str(label)) for label in cats),default=8); left=min(int(width*.47),max(270,72+min(longest,24)*10)); left=min(left,max(190,width-290)); top,right,bottom=72,105,55; pw,ph=max(120,width-left-right),max(120,height-top-bottom)
        vals=[v for s in series for v in s.get('values',[]) if v is not None]
        if vals:
            lo=0 if min(vals)>=0 else min(vals); hi=max(vals); hi=lo+1 if hi==lo else hi+(hi-lo)*.08; slot=ph/max(1,len(cats)); anomalies=set(chart.get('anomaly_rows',[]))
            for tick in range(6):
                x=left+pw*tick/5; value=lo+(hi-lo)*tick/5
                if options.get('show_grid',True): out.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top+ph}" stroke="#dbe4ec" stroke-dasharray="2,4"/>')
                out.append(svg_text(x,top+ph+20,fmt(value,chart.get('value_format')),9,'middle','#52606d'))
            for i,label in enumerate(cats):
                y=top+(i+.5)*slot
                if options.get('show_grid',True): out.append(f'<line x1="{left:.1f}" y1="{y:.1f}" x2="{left+pw:.1f}" y2="{y:.1f}" stroke="#edf2f7" stroke-opacity="0.72" stroke-dasharray="1,5"/>')
                out.append(svg_text(left-12,y+3,short_label(label,max(12,int((left-26)/9))),9,'end'))
                points=[]
                for si,s in enumerate(series):
                    value=s['values'][i]
                    if value is not None: points.append((left+(value-lo)/(hi-lo)*pw,value,si))
                if len(points)==2: out.append(f'<line x1="{points[0][0]:.1f}" y1="{y:.1f}" x2="{points[1][0]:.1f}" y2="{y:.1f}" stroke="#cbd5e1" stroke-width="3"/>')
                for pi,(x,value,si) in enumerate(points):
                    color='#dd6b20' if i in anomalies and si==len(series)-1 else palette[si%len(palette)]
                    out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{color}" stroke="#fffdf8"/>')
                    if options.get('show_labels',True):
                        other_x=points[1-pi][0] if len(points)==2 else x; close_points=len(points)==2 and abs(x-other_x)<30; anchor=('end' if pi==0 else 'start') if close_points else ('end' if x>other_x else 'start'); offset=-8 if anchor=='end' else 8; tx=clamp(x+offset,left+3,left+pw-3); label_y=y-8 if not close_points or pi==0 else y+13
                        out.append(svg_text(tx,label_y,fmt(value,chart.get('value_format')),9,anchor,color))
                if len(points)==2:
                    delta = points[1][1] - points[0][1]
                    out.append(svg_text(width - 8, y + 3, f"差值 {fmt(delta, chart.get('value_format'))}", 9, 'end', '#475569'))
            legend_x=width-20
            for si in range(len(series)-1,-1,-1):
                label=series[si]['name']; legend_x-=26+len(label)*12; out.append(f'<circle cx="{legend_x:.1f}" cy="24" r="5" fill="{palette[si%len(palette)]}"/>'); out.append(svg_text(legend_x+10,28,label,9))
    elif chart_type == "scatter" and chart.get("points") is not None:
        pts=chart.get('points',[]); left,top,right,bottom=100,65,92,70; pw,ph=width-left-right,height-top-bottom
        xs=[p['x'] for p in pts] or [0,1]; ys=[p['y'] for p in pts] or [0,1]
        x_kind,y_kind=scatter_axis_format(chart,'x'),scatter_axis_format(chart,'y')
        xlo,xhi,x_ticks=scatter_axis_scale(xs,x_kind); ylo,yhi,y_ticks=scatter_axis_scale(ys,y_kind)
        for index,value in enumerate(x_ticks):
            x=left+(value-xlo)/(xhi-xlo)*pw
            if options.get('show_grid',True): out.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top+ph}" stroke="#dbe4ec" stroke-opacity="0.58" stroke-dasharray="2,4"/>')
            anchor='start' if index==0 else ('end' if index==len(x_ticks)-1 else 'middle')
            out.append(svg_text(x,top+ph+20,fmt(value,x_kind),9,anchor,'#52606d'))
        for value in y_ticks:
            y=top+(yhi-value)/(yhi-ylo)*ph
            if options.get('show_grid',True): out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left+pw}" y2="{y:.1f}" stroke="#dbe4ec" stroke-opacity="0.58" stroke-dasharray="2,4"/>')
            out.append(svg_text(left-8,y+3,fmt(value,y_kind),9,'end','#52606d'))
        zx=left+(-xlo)/(xhi-xlo)*pw; zy=top+yhi/(yhi-ylo)*ph
        if xlo <= 0 <= xhi: out.append(f'<line x1="{zx:.1f}" y1="{top}" x2="{zx:.1f}" y2="{top+ph}" stroke="#64748b"/>')
        if ylo <= 0 <= yhi: out.append(f'<line x1="{left}" y1="{zy:.1f}" x2="{left+pw}" y2="{zy:.1f}" stroke="#64748b"/>')
        max_size=max([number(p.get('size')) for p in pts]+[1])
        for i,p in enumerate(pts):
            x=left+(p['x']-xlo)/(xhi-xlo)*pw; y=top+(yhi-p['y'])/(yhi-ylo)*ph; radius=5+8*math.sqrt(max(0,number(p.get('size')))/max_size) if p.get('size') is not None else 5; out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="{palette[i%len(palette)]}"/>')
            if options.get('show_labels',True):
                label_x=x+7 if x<=left+pw*.76 else x-7; anchor='start' if label_x>=x else 'end'; label_x=clamp(label_x,left+3,left+pw-3)
                out.append(svg_text(label_x,y-7,short_label(p.get('label',''),20),9,anchor))
        out += [svg_text(left+pw/2,height-16,chart.get('x_label','X'),12,'middle',weight='bold'),svg_text(18,top+ph/2,chart.get('y_label','Y'),12,'middle',weight='bold',rotate=-90)]
    elif chart_type == "bubble" and chart.get("points") is not None:
        pts=chart.get('points',[]); left,top,right,bottom=95,68,58,72; pw,ph=width-left-right,height-top-bottom
        if pts:
            raw_x=[max(number(p.get('x')),1e-9) for p in pts]; use_log=bool(chart.get('x_log')); txs=[math.log10(value) if use_log else value for value in raw_x]
            xlo,xhi=min(txs),max(txs); xhi=xlo+1 if xhi==xlo else xhi; ref=number(chart.get('y_reference'),1); ys=[number(p.get('y')) for p in pts]; ylo,yhi=min(ys+[ref]),max(ys+[ref]); pad=max((yhi-ylo)*.08,.08); ylo=max(0,ylo-pad); yhi+=pad; yhi=ylo+1 if yhi==ylo else yhi
            for tick in range(5):
                x=left+pw*tick/4; y=top+ph*tick/4; xv=10**(xlo+(xhi-xlo)*tick/4) if use_log else xlo+(xhi-xlo)*tick/4; yv=yhi-(yhi-ylo)*tick/4
                if options.get('show_grid',True): out += [f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top+ph}" stroke="#dbe4ec" stroke-opacity="0.58" stroke-dasharray="2,4"/>',f'<line x1="{left}" y1="{y:.1f}" x2="{left+pw}" y2="{y:.1f}" stroke="#dbe4ec" stroke-opacity="0.58" stroke-dasharray="2,4"/>']
                out += [svg_text(x,top+ph+20,fmt(xv),9,'middle','#52606d'),svg_text(left-8,y+3,f'{yv:.1f}×',9,'end','#52606d')]
            ref_y=top+(yhi-ref)/(yhi-ylo)*ph; out.append(f'<line x1="{left}" y1="{ref_y:.1f}" x2="{left+pw}" y2="{ref_y:.1f}" stroke="#64748b" stroke-width="2"/>'); out.append(svg_text(left+4,ref_y-5,'1倍人气基准',9,'start','#64748b'))
            max_size=max([number(p.get('size')) for p in pts]+[1e-9])
            for i,p in enumerate(pts):
                x=left+(txs[i]-xlo)/(xhi-xlo)*pw; y=top+(yhi-number(p.get('y')))/(yhi-ylo)*ph; radius=4+22*math.sqrt(max(0,number(p.get('size')))/max_size); highlighted=bool(p.get('highlight'))
                fill,outline=('#f6ad55','#dd6b20') if p.get('anomaly') else (('#8b1e3f','#6b102f') if highlighted else ('#b7c5cf','#ffffff'))
                out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="{fill}" stroke="{outline}"/>')
                if options.get('show_labels',True) and highlighted:
                    direction=-1 if x>left+pw*.72 else 1; lx=clamp(x+direction*(radius+48),left+4,left+pw-4); ly=max(top+14,min(top+ph-26,y-22)); anchor='end' if direction<0 else 'start'
                    out.append(f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{lx:.1f}" y2="{ly:.1f}" stroke="#94a3b8"/>'); out += [svg_text(lx,ly-3,p.get('label',''),9,anchor,'#263238','bold'),svg_text(lx,ly+11,p.get('subtitle',''),8,anchor,'#718096')]
            out += [svg_text(left+pw/2,height-16,chart.get('x_label','X'),12,'middle',weight='bold'),svg_text(18,top+ph/2,chart.get('y_label','Y'),12,'middle',weight='bold',rotate=-90)]
    elif chart_type == "heatmap" and chart.get("matrix") is not None:
        matrix=chart['matrix']; rows=chart['row_labels']; cols=chart['col_labels']; kind=chart.get('heatmap_kind',''); longest=max((len(str(label)) for label in rows),default=8); left=min(int(width*.34),max(180,55+longest*10)); top,right,bottom=(65,25,70) if kind=='ranked_metrics' else (145,25,35); cw=(width-left-right)/max(1,len(cols)); ch=(height-top-bottom)/max(1,len(rows)); vals=[v for row in matrix for v in row if v is not None]; lo,hi=min(vals or [0]),max(vals or [1]); hi=hi if hi!=lo else lo+1
        diagonal={tuple(cell) for cell in chart.get('diagonal_cells',[])}; anomalies={tuple(cell) for cell in chart.get('anomaly_cells',[])}
        out.append('<defs><pattern id="missing-hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="8" height="8" fill="#eef2f6"/><line x1="0" y1="0" x2="0" y2="8" stroke="#cbd5e1" stroke-width="2"/></pattern></defs>')
        for c,label in enumerate(cols):
            x=left+(c+.5)*cw
            if kind=='ranked_metrics': out.append(svg_text(x,top+len(rows)*ch+20,label[:18],9,'middle','#263238','bold'))
            else:
                parts=str(label).split(' ',1); out.append(svg_text(x,top-28,parts[0],8,'middle','#718096','bold')); out.append(svg_text(x,top-13,(parts[1] if len(parts)>1 else '')[:7],8,'middle','#263238','bold'))
        for r,(label,row) in enumerate(zip(rows,matrix)):
            out.append(svg_text(left-8,top+(r+.6)*ch,label,9,'end'))
            for c,v in enumerate(row):
                ratio=(number(v)-lo)/(hi-lo) if v is not None else 0; ratio=1-ratio if chart.get('color_direction')=='low' else ratio
                color='#17363d' if (r,c) in diagonal else ('url(#missing-hatch)' if v is None and chart.get('missing_hatch') else ('#eef2f6' if v is None else mix_color('#edf5f6',palette[1 if len(palette)>1 else 0],ratio)))
                out.append(f'<rect x="{left+c*cw:.1f}" y="{top+r*ch:.1f}" width="{cw:.1f}" height="{ch:.1f}" fill="{color}" stroke="#fff"/>')
                if v is not None and options.get('show_labels',True) and cw>28 and ch>16: out.append(svg_text(left+(c+.5)*cw,top+(r+.65)*ch,fmt(v,chart.get('value_format')),7,'middle',contrast_color(color)))
                if (r,c) in anomalies: out.append(f'<rect x="{left+c*cw+1:.1f}" y="{top+r*ch+1:.1f}" width="{cw-2:.1f}" height="{ch-2:.1f}" fill="none" stroke="#dd6b20" stroke-width="2"/>')
    elif chart_type == "network" and chart.get("nodes") is not None:
        nodes,edges=chart.get('nodes',[]),chart.get('edges',[]); listw=min(420,max(250,width*.3)); graphw=width-listw; cx,cy=graphw/2,height/2+15; radius=min(graphw,height)*.34; pos={}
        for i,n in enumerate(nodes):
            a=-math.pi/2+2*math.pi*i/max(1,len(nodes)); pos[n['id']]=(cx+radius*math.cos(a),cy+radius*math.sin(a))
        maxe=max([e['value'] for e in edges]+[1]); maxn=max([n['value'] for n in nodes]+[1])
        for e in edges:
            if e['source'] in pos and e['target'] in pos:
                x1,y1=pos[e['source']];x2,y2=pos[e['target']];out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{mix_color("#cbd5e1",palette[0],min(1,e.get("lift",1)/8))}" stroke-width="{1+6*e["value"]/maxe:.1f}"/>')
        for i,n in enumerate(nodes):
            x,y=pos[n['id']]; size=6+11*math.sqrt(n['value']/maxn); out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{size:.1f}" fill="{palette[i%len(palette)]}" stroke="#fff" stroke-width="2"/>')
            if options.get('show_labels',True): out.append(svg_text(x,y+3,i+1,9,'middle',contrast_color(palette[i%len(palette)]),'bold'))
        if options.get('show_labels',True):
            out.append(svg_text(graphw+12,60,'节点完整名称',11,weight='bold'))
            for i,n in enumerate(nodes): out.append(svg_text(graphw+12,84+i*20,f"{i+1}. {n['label']}",9))
    elif chart_type == "faceted_network" and chart.get("panels") is not None:
        panels=chart.get('panels',[]); gap,area_top,legend_h=20,52,58; panelw=(width-gap*3)/2; panelh=(height-area_top-legend_h-gap*3)/2
        def svg_edge_style(lift):
            lift=number(lift)
            if lift<1: return '#cbd5e1',1,' stroke-dasharray="4 4"'
            if lift<1.5: return '#94a3b8',2,''
            if lift<2: return '#2a9d8f',2,''
            if lift<3: return '#d4a72c',3,''
            if lift<5: return '#e76f51',4,''
            if lift<10: return '#8b1e3f',5,''
            return '#6a4c93',6,''
        for index in range(4):
            row,col=divmod(index,2); x1=gap+col*(panelw+gap); y1=area_top+gap+row*(panelh+gap); x2,y2=x1+panelw,y1+panelh
            out.append(f'<rect x="{x1:.1f}" y="{y1:.1f}" width="{panelw:.1f}" height="{panelh:.1f}" rx="18" fill="#f4f1ec" stroke="#e7e2da"/>')
            if index>=len(panels): continue
            panel=panels[index]; nodes=panel.get('nodes',[]); edges=panel.get('edges',[]); out.append(svg_text(x1+16,y1+23,panel.get('title',''),12,'start','#263238','bold'))
            if not nodes:
                out.append(svg_text((x1+x2)/2,(y1+y2)/2,'当前届无公开关系',11,'middle','#718096')); continue
            cx=(x1+x2)/2; cy=y1+panelh*.43; rx=max(40,panelw*.28); ry=max(35,panelh*.25); positions={}
            for ni,node in enumerate(nodes):
                angle=-math.pi/2+2*math.pi*ni/max(1,len(nodes)); positions[node['id']]=(cx+rx*math.cos(angle),cy+ry*math.sin(angle))
            for edge in sorted(edges,key=lambda item:number(item.get('lift'))):
                if edge['source'] not in positions or edge['target'] not in positions: continue
                ex1,ey1=positions[edge['source']]; ex2,ey2=positions[edge['target']]; color,linew,dash=svg_edge_style(edge.get('lift')); out.append(f'<line x1="{ex1:.1f}" y1="{ey1:.1f}" x2="{ex2:.1f}" y2="{ey2:.1f}" stroke="{color}" stroke-width="{linew}"{dash}/>')
            for node in nodes:
                nx,ny=positions[node['id']]; size=24 if len(nodes)<=4 else 21; out.append(f'<circle cx="{nx:.1f}" cy="{ny:.1f}" r="{size}" fill="#fffdf8" stroke="#138f8f" stroke-width="3"/>'); out.append(svg_text(nx,ny+3,node.get('label','')[:8],7,'middle','#263238','bold'))
            strong=panel.get('strong_edges',[])
            if strong:
                strong_text='较强边：'+' ｜ '.join(f"{edge['label']} {number(edge.get('lift')):.2f}×·{number(edge.get('value')):,.0f}人" for edge in strong)
                out.append(svg_text(x1+16,y2-14,strong_text[:100],8,'start','#718096'))
        legend=[('<1倍','#cbd5e1'),('1–1.5倍','#94a3b8'),('1.5–2倍','#2a9d8f'),('2–3倍','#d4a72c'),('3–5倍','#e76f51'),('5–10倍','#8b1e3f'),('≥10倍','#6a4c93')]; start=max(20,(width-len(legend)*112)/2); ly=height-24; out.append(svg_text(start-10,ly+3,'同投集中倍数：',9,'end','#52606d','bold'))
        for index,(label,color) in enumerate(legend):
            x=start+index*112; out.append(f'<line x1="{x:.1f}" y1="{ly}" x2="{x+30:.1f}" y2="{ly}" stroke="{color}" stroke-width="{max(1,index)}"/>'); out.append(svg_text(x+36,ly+3,label,9,'start','#52606d'))
    else:
        out.append(svg_text(width/2,height/2,'当前配置仅导出数据表',16,'middle','#718096'))
    out.append('</svg>')
    return ''.join(out)


def open_workbench(parent: tk.Misc):
    return AnalysisWorkbench(parent)
