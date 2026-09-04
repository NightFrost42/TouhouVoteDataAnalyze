"""参考文章分析模板的数据计算层，仅依赖 Python 标准库。"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:  # package import (tests) and direct script import (Windows launcher)
    from .resource_paths import DATA_DIR
    from .data_chunks import read_csv_rows
except ImportError:  # pragma: no cover - exercised by the Windows launcher
    from resource_paths import DATA_DIR
    from data_chunks import read_csv_rows

def round_sort_key(label: str) -> tuple[int, int]:
    text = str(label or "").upper()
    match = re.fullmatch(r"(CN|JP)(\d+)", text)
    return ((0 if match and match.group(1) == "CN" else 1), int(match.group(2)) if match else 0)


def normalize_round_label(value, default="JP22") -> str:
    text = str(value or "").strip().upper()
    if re.fullmatch(r"(?:CN|JP)\d+", text):
        return text
    if re.fullmatch(r"\d+", text):
        return f"JP{text}"
    return default


def number(value, default=0.0) -> float:
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


def normalize_work_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"^ds", "", text)
    return "".join(ch for ch in text if not unicodedata.category(ch).startswith(("P", "S", "Z")))


def work_name_variants(value: str) -> list[str]:
    """Return exact/short keys for work and questionnaire-era labels."""
    raw = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not raw:
        return []
    variants: list[str] = []
    def add(text: str) -> None:
        key = normalize_work_name(text)
        if key and key not in variants:
            variants.append(key)
    add(raw)
    # 入坑时间选项 use ranges such as ``アマノジャク～紺珠伝`` and may
    # append a parenthesised release date.  Each endpoint is useful for the
    # catalogue lookup and for chronological sorting.
    for part in re.split(r"\s*[～〜~]\s*", raw):
        add(re.sub(r"[（(][^）)]*[）)]", "", part).strip())
    for part in re.findall(r"[（(]([^）)]*)[）)]", raw):
        add(part)
    return variants


def pearson(values: list[tuple[float, float]]) -> float | None:
    if len(values) < 3:
        return None
    xs = [x for x, _ in values]; ys = [y for _, y in values]
    mx = sum(xs) / len(xs); my = sum(ys) / len(ys)
    numerator = sum((x - mx) * (y - my) for x, y in values)
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs)); dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return numerator / (dx * dy) if dx and dy else None


def read_numeric_csv(path: Path, numeric_fields: set[str]) -> list[dict]:
    rows = read_csv_rows(path, compressed=path.suffix == ".gz")
    for row in rows:
        for field in numeric_fields:
            if field in row:
                raw = row[field]
                row[field] = number(raw, None) if str(raw).strip() else None
    return rows


CHARACTER_FIELDS = {
    "round", "rank", "equal_rank", "old_2_1_rank", "points", "old_2_1_points",
    "primary_count", "secondary_count", "other_count", "selection_count", "ballots",
    "primary_rate", "secondary_rate", "top2_rate", "selection_rate", "male_rate",
    "female_rate", "other_gender_rate", "under20_rate", "overall_male_rate",
    "overall_female_rate", "overall_other_gender_rate", "rank_change", "equal_rank_change",
    "points_change", "primary_count_change", "secondary_count_change", "selection_count_change",
    "selection_rate_change", "primary_rate_change", "female_rate_change", "selection_yoy",
}

MUSIC_FIELDS = {
    "round", "rank", "equal_rank", "points", "primary_count", "secondary_count",
    "selection_count", "ballots", "primary_rate", "selection_rate", "comment_count",
    "arrangement_count", "arrangement_cumulative_count", "undated_arrangement_count", "arrangement_total_count",
}

COVOTE_FIELDS = {
    "round", "rank_a", "rank_b", "count_a", "count_b", "ballots", "intersection_count",
    "direction_a_to_b", "direction_b_to_a", "share", "baseline_count", "lift",
    "excess_count", "phi", "asymmetry", "anomaly_difference", "directions_found",
}
CP_FIELDS = {
    "round", "member_count", "rank", "vote_count", "first_choice_count", "points", "vote_rate", "ballots"
}
COMBINATION_FIELDS = {
    "round", "rank", "comparison_count", "comparison_rate", "cp_rank", "cp_vote_count", "covote_count"
}

QUESTIONNAIRE_FIELDS = {"round", "count", "rate", "denominator"}
ENTITY_QUESTIONNAIRE_FIELDS = {
    "round", "rank", "count", "rate", "overall_rate", "difference_points", "denominator",
}
LINK_FIELDS = {
    "round", "association_count",
} | {f"{prefix}_{field}" for prefix, fields in (("character", CHARACTER_FIELDS), ("music", MUSIC_FIELDS)) for field in fields if field not in {"round"}}
CROSSVOTE_FIELDS = {
    "round", "character_rank", "character_selection_count", "character_ballots", "music_rank",
    "music_selection_count", "music_ballots", "intersection_count", "conditional_denominator", "conditional_rate",
    "music_overall_rate", "lift",
}

METRIC_LABELS = {
    "rank": "官方名次", "equal_rank": "等权名次", "old_2_1_rank": "2/1规则名次",
    "points": "官方分数", "primary_count": "第一顺位票", "secondary_count": "第二顺位票",
    "other_count": "其余顺位票", "selection_count": "实际选择人数", "primary_rate": "第一顺位率",
    "secondary_rate": "第二顺位率", "top2_rate": "前两顺位集中率", "selection_rate": "选择率",
    "male_rate": "男性比例", "female_rate": "女性比例", "under20_rate": "20岁以下比例",
    "intersection_count": "共同投票人数", "share": "同投占总盘比例", "lift": "同投集中倍数",
    "excess_count": "比人气基准多出人数", "phi": "综合重合分数 φ", "asymmetry": "方向同投率差",
    "old_2_1_points": "2/1规则分数", "other_gender_rate": "其他性别比例",
    "comment_count": "评论数", "arrangement_count": "届间新增同人曲数",
    "arrangement_cumulative_count": "截至投票结束累计同人曲数", "undated_arrangement_count": "未标日期同人曲数",
    "arrangement_total_count": "同人曲累计总数（抓取时点）", "question_rate": "所选问卷选项比例",
    "difference_points": "相对全体差值（百分点）", "correlation": "皮尔逊相关系数",
    "associated_music_count": "关联曲数量", "associated_character_count": "所属角色数量",
    "associated_music_avg": "关联曲平均指标", "associated_character_avg": "所属角色平均指标",
    "conditional_rate": "角色条件下同投率", "music_overall_rate": "曲子总体选择率",
    "character_music_lift": "角色—曲子连带倍数", "carryover_index": "角色连带指数",
    "vote_count": "CP投票/组合人数", "vote_rate": "CP投票比例", "comparison_count": "组合对比人数",
    "comparison_rate": "组合对比比例", "cp_rank": "CP官方名次", "cp_vote_count": "CP官方人数",
    "covote_count": "同投替代人数",
}

PERCENT_FIELDS = {
    "primary_rate", "secondary_rate", "top2_rate", "selection_rate", "male_rate", "female_rate",
    "other_gender_rate", "under20_rate", "share", "direction_a_to_b", "direction_b_to_a",
    "asymmetry", "selection_rate_change", "primary_rate_change", "female_rate_change", "selection_yoy",
}


def metric_axis_format(field: str) -> str:
    """Choose a truthful axis formatter for a metric field."""
    if field in PERCENT_FIELDS or field.endswith("_rate"):
        return "percent"
    if field == "rank" or field.endswith("_rank"):
        return "rank"
    if field.endswith("_count") or field in {"points", "ballots", "vote_count", "first_choice_count", "intersection_count"}:
        return "integer"
    return "number"

QUESTION_LABELS = {
    "age": "年龄分布", "sex": "性别构成", "location": "居住地区",
    "cleared_title": "整数作通关难度", "subnumber": "小数点作游玩情况",
    "books": "官方书籍阅读情况", "purchase_method": "原作购买方式",
    "magazine": "官方连载阅读方式", "charm": "东方的魅力所在",
    "cognition": "入坑时间", "trigger": "最初知道东方的途径",
    "intention": "线下活动参与方式", "event": "感兴趣的活动类型",
    "friends": "身边的东方爱好者人数", "usertype": "参与东方的方式",
    "voted": "历届投票经验", "lastVote": "上一次投票时间",
    "triggerVote": "开始参与投票的途径", "th21": "新作体验版",
    "parents": "是否由家人传教",
}

ENTITY_QUESTION_LABELS = {
    "sex": "性别", "age": "年龄", "cognition": "入坑时间", "voted": "历届投票经验",
    "intention": "线下活动参与",
}


def questionnaire_label(question_key: str, entity: bool = False) -> str:
    """Return a human-readable label without collapsing CN/JP question sets.

    CN modern questionnaires retain their audited source wording in keys with
    a ``cn_`` prefix.  The previous UI only looked up the fixed JP label map,
    making valid CN questions appear unnamed or unavailable.
    """
    key = str(question_key or "").strip()
    labels = ENTITY_QUESTION_LABELS if entity else QUESTION_LABELS
    if key in labels:
        return labels[key]
    if key.startswith("cn_"):
        return key[3:] or key
    return key

WORK_QUESTION_KEYS = {"books", "magazine", "subnumber", "cognition"}
COGNITION_TOKEN_TRANSLATIONS = {"現在": "现在", "現在": "现在", "旧作": "旧作"}
WORK_TOKEN_TRANSLATIONS = {
    "秋霜玉": "秋霜玉", "紅魔郷": "东方红魔乡", "妖々夢": "东方妖妖梦", "永夜抄": "东方永夜抄",
    "萃夢想": "东方萃梦想", "花映塚": "东方花映塚", "文花帖": "东方文花帖", "求聞史紀": "东方求闻史纪",
    "求聞口授": "东方求闻口授", "風神録": "东方风神录", "地霊殿": "东方地灵殿", "星蓮船": "东方星莲船",
    "妖精大戦争": "妖精大战争", "神霊廟": "东方神灵庙", "輝針城": "东方辉针城", "アマノジャク": "弹幕天邪鬼",
    "紺珠伝": "东方绀珠传", "旧約酒場": "旧约酒吧", "天空璋": "东方天空璋", "ナイトメアダイアリー": "秘封噩梦日记",
    "鬼形獣": "东方鬼形兽", "虹龍洞": "东方虹龙洞", "バレットフィリア": "弹幕狂们的黑市", "獣王園": "东方兽王园",
}

ENTITY_ANSWER_LABELS = {
    "男性": "男性", "女性": "女性", "男": "男性", "女": "女性", "その他": "其他性别", "はい": "是", "いいえ": "否", "～9歳": "9岁以下",
    "10～14歳": "10–14岁", "15～19歳": "15–19岁", "20～24歳": "20–24岁",
    "25～29歳": "25–29岁", "30～34歳": "30–34岁", "35～39歳": "35–39岁",
    "40～44歳": "40–44岁", "45～49歳": "45–49岁", "50歳～": "50岁以上",
    "今回がはじめて": "本届第一次投票", "過去1～3回投票したことがある": "过去投过1–3届",
    "過去4～6回投票したことがある": "过去投过4–6届", "過去7～9回投票したことがある": "过去投过7–9届",
    "過去10回以上投票したことがある": "过去投过10届以上", "過去4回以上投票したことがある": "过去投过4届以上", "参加している": "参加线下活动",
    "うちサークル参加": "其中参加社团", "うちコスプレ参加": "其中参加Cosplay",
    # Japanese questionnaire options (JP17–22).  Keep the raw values in the
    # dataset for reproducibility, while exposing Chinese labels in charts,
    # tables and selectors.
    "東方作品を通じた交流": "通过东方作品交流", "キャラクタ": "角色", "ゲーム性": "游戏性", "ストーリー": "故事剧情",
    "Easy未クリア": "Easy未通关", "Easyクリア": "Easy通关", "Normalクリア": "Normal通关", "Hardクリア": "Hard通关", "Lunaticクリア": "Lunatic通关",
    "東方Project原作ゲーム大会（獣王園、非想天則など）": "东方Project原作游戏大会（兽王园、非想天则等）",
    "企業主体イベント（アトレコラボ、大・東方Project展など）": "企业主办活动（atre合作、大·东方Project展等）",
    "同人即売会（博麗神社例大祭など）": "同人贩售会（博丽神社例大祭等）",
    "音楽ライブイベント（アレンジサークル主催など）": "音乐现场活动（改编社团主办等）",
    "オフ会(交流会、合宿など)": "线下聚会（交流会、合宿等）",
    "オンラインイベント（即売会、スライド発表会、歌リレー配信など）": "线上活动（贩售会、幻灯片发表会、接力歌直播等）",
    "クラブイベント（DJイベントなど）": "Club活动（DJ活动等）", "スライド発表会（考察評論、作品紹介など）": "幻灯片发表会（考察评论、作品介绍等）",
    "1人もいない": "1人也没有", "参加していない": "未参加", "公式原作の購入": "购买官方原作", "裏方作業（スタッフ）": "后台工作（工作人员）",
    "企業制作作品の購入": "购买企业制作作品", "同人誌作品の購入": "购买同人志作品", "同人グッズ作品の購入": "购买同人周边作品",
    "同人ソフト作品の購入": "购买同人软件作品", "音楽同人作品の購入": "购买音乐同人作品", "音楽ライブ（併催されるとき）": "音乐现场（联动举办时）",
    "音ゲーなどのコラボ企画": "音游等联动企划", "作品頒布（サークル）": "作品发布（社团）", "コスプレ（見る・撮影する側）": "Cosplay（观看/拍摄）",
    "コスプレ（する側）": "Cosplay（参与）", "サークルや友人との交流": "与社团或朋友交流",
    "日本国外：北アメリカ": "日本以外：北美", "日本国外：東南アジア": "日本以外：东南亚", "日本国外：東アジア": "日本以外：东亚",
    "日本国外：南・中央・西アジア": "日本以外：南亚、中亚、西亚", "日本国外：南アメリカ": "日本以外：南美",
    "日本国外：アフリカ": "日本以外：非洲", "日本国外：オセアニア": "日本以外：大洋洲", "日本国外：ヨーロッパ": "日本以外：欧洲",
    "単行本で購入している": "购买单行本", "東方我楽多叢誌で読んでいる": "阅读《东方我乐多丛志》", "読んでいない": "未阅读",
    "購入していない": "未购买", "連載誌（外來韋編）を購入した": "购买连载杂志（外来韦编）",
    "連載誌（コンプエース）を継続購入している": "持续购买连载杂志（Comp Ace）", "Comic Walkerで読んでいる": "在Comic Walker阅读",
    "カドコミ（旧Comic Walker）で読んでいる": "在Kadokomi（原Comic Walker）阅读", "ニコニコ静画で読んでいる": "在Niconico静画阅读",
    "両方購入している": "两者都购买", "CD-ROMを購入している": "购买CD-ROM版", "ダウンロード版を購入している": "购买下载版",
    "ダブルスポイラー": "Double Spoiler（双重剧透）", "例大祭で体験版ディスクを買ってプレイした": "在例大祭购买体验版光盘并游玩",
    "体験版を遊んでいない": "未游玩体验版", "SteamやDLsiteでダウンロードして体験版をプレイした": "通过Steam或DLsite下载并游玩体验版",
    "2ちゃんねる、ふたば、したらばなど匿名掲示板で話題になっているのをみて知った": "在2ch、Futaba、Shitaraba等匿名论坛看到话题后得知",
    "個人サイト、ブログ、ニュースサイトなどで話題になっているのをみて知った": "在个人网站、博客、新闻网站等看到话题后得知",
    "即売会以外のリアルイベントで知った（アトレコラボイベントや大・東方Project展など）": "在线下贩售会以外的活动中得知（atre合作活动、大·东方Project展等）",
    "面白いゲームを探していたときにみつけた": "寻找有趣游戏时发现",
    "同人誌即売会（コミケなど）、サークル告知などでみかけて知った": "在同人志贩售会（Comiket等）或社团宣传中看到后得知",
    "同人ショップ、一般書店などでみかけて知った": "在同人商店、普通书店等看到后得知",
    "学校、部活、家族などオフラインでのつながりから教えてもらった": "通过学校、社团、家人等线下关系得知",
    "学校、部活などオフラインでのつながりから教えてもらった": "通过学校、社团等线下关系得知",
    "音楽ゲームに東方曲があるのをみて知った": "在音乐游戏中看到东方曲目后得知",
    "雑誌連載、雑誌記事、TV番組などをみて知った": "通过杂志连载、杂志文章、电视节目等得知",
    "pixiv、ニジエ、TINAMIなどイラストSNSで話題になっているのをみて知った": "在pixiv、Nijie、TINAMI等插画SNS看到话题后得知",
    "Twitterで話題になっているのをみて知った": "在Twitter看到话题后得知", "TwitterやTiktokで話題になっているのをみて知った": "在Twitter或TikTok看到话题后得知",
    "Youtubeで話題になっているのをみて知った": "在YouTube看到话题后得知", "Youtubeなどその他の動画サイトで話題になっているのをみて知った": "在YouTube等视频站看到话题后得知",
    "オンラインゲーム、チャット（IRC）などネットでのつながりから教えてもらった": "通过网络游戏、聊天（IRC）等网络关系得知",
    "スマホアプリの二次創作ゲームで知った": "在手机应用的二次创作游戏中得知", "その他の動画サイトで話題になっているのをみて知った": "在其他视频网站看到话题后得知",
    "ニコニコ動画（生放送なども含む）で話題になっているのをみて知った": "在Niconico动画（含直播等）看到话题后得知",
    "よみうりランドのコラボイベント": "读卖乐园合作活动",
    "東方系イベントに参加した": "参加东方相关活动", "東方系イベントを企画、運営(スタッフも含む)をした": "策划/运营东方相关活动（含工作人员）",
    "公式公認スマホゲーム制作に関与した": "参与官方认可手机游戏制作", "公式公認スマホゲームをした": "游玩官方认可手机游戏",
    "公式書籍制作に関与した": "参与官方书籍制作", "公式書籍を読んだ": "阅读官方书籍", "公式原作ゲーム制作に関与した": "参与官方原作游戏制作",
    "公式原作ゲームを遊んだ": "游玩官方原作游戏", "企業制作作品（グッズなど）制作に関与した": "参与企业制作作品（周边等）的制作",
    "企業制作作品（グッズなど）を購入した": "购买企业制作作品（周边等）", "同人映像作品を視聴した": "观看同人影像作品",
    "同人映像作品を制作した": "制作同人影像作品", "同人誌即売会にサークル参加をした": "以社团身份参加同人志贩售会",
    "同人誌作品（ストーリーも含む）を読んだ": "阅读同人志作品（含故事）", "同人誌作品（ストーリーも含む）を制作した": "制作同人志作品（含故事）",
    "同人グッズ作品を購入した": "购买同人周边作品", "同人グッズ作品を制作した": "制作同人周边作品",
    "同人ゲームソフトを遊んだ": "游玩同人游戏软件", "同人ゲームソフトを制作した": "制作同人游戏软件",
    "音ゲーなどのゲームコラボ制作に関与した": "参与音游等游戏联动制作", "音ゲーなどのゲームコラボを遊んだ": "游玩音游等游戏联动",
    "アレンジ楽曲を聞いた": "听过改编曲", "アレンジ楽曲を制作した": "制作改编曲", "イラスト作品を鑑賞した": "欣赏插画作品",
    "イラスト作品を制作した": "制作插画作品", "コスプレの鑑賞や撮影をした": "欣赏或拍摄Cosplay", "コスプレをした": "进行Cosplay",
}


def entity_answer_label(value: str) -> str:
    cleaned = str(value or "").strip()
    if cleaned in ENTITY_ANSWER_LABELS:
        return ENTITY_ANSWER_LABELS[cleaned]
    # Common numeric options occur in JP detail tables but vary by round.
    match = re.fullmatch(r"(\d+)歳", cleaned)
    if match:
        return f"{match.group(1)}岁"
    match = re.fullmatch(r"(\d+)歳～", cleaned)
    if match:
        return f"{match.group(1)}岁以上"
    match = re.fullmatch(r"(\d+)人〜(\d+)人", cleaned)
    if match:
        return f"{match.group(1)}–{match.group(2)}人"
    return cleaned


@dataclass(frozen=True)
class TemplateSpec:
    key: str
    group: str
    title: str
    builder: str
    chart_type: str
    description: str

    @property
    def display(self) -> str:
        return f"{self.group}｜{self.title}"


# The renderer deliberately exposes only chart forms that preserve the
# semantics of a template.  A user can always switch to a data table, but a
# one-series ranking cannot accidentally be changed into a misleading
# grouped/stacked chart.
def template_chart_types(spec: TemplateSpec) -> tuple[str, ...]:
    key = spec.key
    if key in {"c00_round_compare", "m02_round_compare", "a04_count_dumbbell", "a10_direction",
               "q01_age", "q02_cognition", "q03_usertype", "q04_new", "q_custom", "p02_combination_compare"}:
        return ("auto", "dumbbell", "table")
    if key in {"c00_rank_trend", "c00_all_trend", "m03_rank_trend", "m03_all_trend"}:
        return ("auto", "line", "table")
    if key in {"c11_structure", "c12_gender_structure"}:
        return ("auto", "stacked", "table")
    if key in {"c02_equal_rank"}:
        return ("auto", "grouped", "table")
    # Any template whose declared semantic form is a two-dimensional scatter
    # must stay a scatter (or lossless table).  Key-by-key lists previously
    # missed new cross-analysis templates and allowed the GUI to retain a bar
    # override from the preceding template.
    if spec.chart_type == "scatter":
        return ("auto", "scatter", "table")
    if key in {"c11_metric_heatmap", "a01_direction_matrix", "a01_count_matrix"}:
        return ("auto", "heatmap", "table")
    if key in {"r08_work_question_matrix"}:
        return ("auto", "heatmap", "table")
    if key in {"r09_character_question_matrix", "r10_music_question_matrix"}:
        return ("auto", "heatmap", "table")
    if key in {"a02_network"}:
        return ("auto", "network", "table")
    if key in {"a03_bubble"}:
        return ("auto", "bubble", "table")
    return ("auto", "bar", "table")


TEMPLATES = [
    TemplateSpec("c00_round_compare", "角色", "任意两届独立系列对比", "round_comparison", "dumbbell", "同一角色用两个点连接比较当前届与对比届；可选择任意 CN1–11 或 JP3–22。"),
    TemplateSpec("c00_rank_trend", "角色", "届数 × 名次变化图", "rank_trend", "line", "横轴为同地区全部届次，纵轴为官方名次；#1 固定在最上方。"),
    TemplateSpec("c00_all_trend", "角色", "同地区全部届次趋势", "all_round_trend", "line", "以当前届所在地区为范围，查看所选名次区间角色的全部届次趋势。"),
    TemplateSpec("c01_rank_change", "角色", "排名上升/下降幅度", "rank_change", "bar", "当前届相对对比届的官方名次变化，正数表示上升。"),
    TemplateSpec("c02_selection_top", "角色", "实际选择人数 TOP", "character_metric", "bar", "去除顺位加权后的实际选择人数。"),
    TemplateSpec("c02_equal_rank", "角色", "官方排名与等权排名", "score_rule", "grouped", "比较官方、等权与旧2/1规则名次。"),
    TemplateSpec("c03_primary_rate", "角色", "第一顺位本命率", "character_metric", "bar", "第一顺位票÷实际选择人数。"),
    TemplateSpec("c03_primary_rate_change", "角色", "第一顺位率跨届变化", "character_change", "bar", "当前届减去对比届。"),
    TemplateSpec("c04_secondary_rate", "角色", "第二顺位率", "character_metric", "bar", "第二顺位票÷实际选择人数。"),
    TemplateSpec("c05_top2_rate", "角色", "前两顺位集中率", "character_metric", "bar", "（第一+第二顺位票）÷实际选择人数。"),
    TemplateSpec("c06_primary_change", "角色", "第一顺位票绝对变化", "character_change", "bar", "第一顺位票的跨届绝对增减。"),
    TemplateSpec("c07_selection_change", "角色", "实际选择人数绝对变化", "character_change", "bar", "实际选择人数跨届增减。"),
    TemplateSpec("c07_selection_yoy", "角色", "实际选择人数同比", "character_change", "bar", "实际选择人数相对上届的百分比变化。"),
    TemplateSpec("c08_points_change", "角色", "官方分数绝对变化", "character_change", "bar", "两届计分制度不同时仅作官方分数展示。"),
    TemplateSpec("c09_selection_rate_change", "角色", "角色选择率变化", "character_change", "bar", "角色实际选择人数÷当届有效票数的变化。"),
    TemplateSpec("c10_growth_lag", "角色", "人数增加但选择率下降", "growth_lag", "scatter", "横轴人数变化，纵轴选择率变化。"),
    TemplateSpec("c11_structure", "角色", "第一/第二/其余顺位结构", "vote_structure", "stacked", "按届次实际公开字段显示第一、第二及其余顺位；旧届未细分第二顺位时自动显示第一/非第一两段结构。"),
    TemplateSpec("c11_metric_heatmap", "角色", "TOP角色多维指标热力图", "character_heatmap", "heatmap", "每个指标在当前筛选角色中单独排名。"),
    TemplateSpec("c12_gender_structure", "角色画像", "支持者性别构成", "gender_structure", "stacked", "男性、女性及其他性别比例。"),
    TemplateSpec("c12_gender_lean", "角色画像", "相对全体的性别倾向", "gender_lean", "bar", "正数更偏女性，负数更偏男性。"),
    TemplateSpec("c12_gender_change", "角色画像", "性别比例跨届变化", "gender_change", "bar", "女性比例当前届减去对比届。"),
    TemplateSpec("r01_character_question_scatter", "问卷关联", "角色投票结果 × 问卷选项", "entity_question_scatter", "scatter", "把角色投票指标与该角色支持者的问卷选项比例/倾向放在同一散点图中。"),
    TemplateSpec("r02_character_question_diff", "问卷关联", "角色问卷倾向排行", "entity_question_difference", "bar", "按所选问卷选项相对全体的百分点差排序。"),
    TemplateSpec("r03_character_question_corr", "问卷关联", "角色投票指标与问卷各项相关系数", "entity_question_correlation", "bar", "对所选题目的每个选项分别计算角色投票指标与选项比例的皮尔逊相关系数。"),
    TemplateSpec("m01_metric", "曲子", "当前届曲子指标排行", "music_metric", "bar", "可用中文指标选择官方名次、分数、实际选择人数、第一顺位率等。"),
    TemplateSpec("m02_round_compare", "曲子", "任意两届曲子独立系列对比", "music_round_comparison", "dumbbell", "同一曲子用两个点连接比较当前届与对比届；不会把两届混成一根条。"),
    TemplateSpec("m03_rank_trend", "曲子", "届数 × 名次变化图", "music_rank_trend", "line", "横轴为同地区全部届次，纵轴为曲子官方名次；#1 固定在最上方。"),
    TemplateSpec("m03_all_trend", "曲子", "同地区曲子全部届次趋势", "music_all_round_trend", "line", "查看当前届所在地区的曲子历届趋势。"),
    TemplateSpec("m04_primary_rate", "曲子", "曲子第一顺位率", "music_primary_rate", "bar", "第一顺位票占实际选择人数的比例。"),
    TemplateSpec("m05_character_music_cross", "角色—曲子", "角色人气 × 关联曲人气", "character_music_cross", "scatter", "用根目录曲子打标关系，把角色投票指标与其关联曲平均指标放在同一张散点图；点大小表示关联曲数量。"),
    TemplateSpec("m06_music_character_cross", "角色—曲子", "曲子人气 × 所属角色人气", "music_character_cross", "scatter", "把曲子投票指标与其所属角色平均指标放在同一张散点图；点大小表示所属角色数量。"),
    TemplateSpec("m07_character_music_covote", "角色—曲子", "角色—曲子同投人数与同投率", "character_music_covote", "scatter", "官方角色详情中的条件统计：同投人数与 P(曲子|角色) 同时展示；目前本地完整覆盖 JP17–22。"),
    TemplateSpec("m08_character_carryover", "角色—曲子", "角色连带效应", "character_carryover", "scatter", "用角色人气与其打标关联曲平均人气、关联曲数量衡量连带效应；这是关联分析，不是因果证明。"),
    TemplateSpec("m09_music_arrangement_cross", "曲子", "曲子投票 × 同人曲数量", "music_arrangement_cross", "scatter", "横轴可切换届间新增数、截至投票结束累计数或抓取时点累计总数，纵轴为曲子投票指标；未匹配曲目留空。"),
    TemplateSpec("m10_character_arrangement_cross", "角色—曲子", "角色投票 × 关联原曲同人曲数量", "character_arrangement_cross", "scatter", "按角色—原曲打标关系去重汇总，横轴可切换届间新增数、截至投票结束累计数或抓取时点累计总数，纵轴为角色投票指标。"),
    TemplateSpec("r04_music_question_scatter", "曲子问卷关联", "曲子投票结果 × 问卷选项", "entity_question_scatter", "scatter", "把曲子投票指标与听众问卷选项比例/倾向放在同一散点图中。"),
    TemplateSpec("r05_music_question_diff", "曲子问卷关联", "曲子问卷倾向排行", "entity_question_difference", "bar", "按所选问卷选项相对全体的百分点差对曲子排序。"),
    TemplateSpec("r06_music_question_corr", "曲子问卷关联", "曲子投票指标与问卷各项相关系数", "entity_question_correlation", "bar", "对所选题目的每个选项分别计算曲子投票指标与选项比例的皮尔逊相关系数。"),
    TemplateSpec("r07_character_cognition", "问卷关联", "角色投票 × 入坑时间", "character_cognition", "scatter", "固定使用‘入坑时间’题目，把角色投票指标与不同入坑时间选项比例/相对全体差值关联。"),
    TemplateSpec("r08_work_question_matrix", "问卷关联", "作品 × 问卷选项矩阵", "work_question_matrix", "heatmap", "作品不是按名次区间截取；每行是一个公开作品，每列是问卷选项比例，适合观察作品受众画像。"),
    TemplateSpec("r09_character_question_matrix", "问卷关联", "角色 × 问卷选项矩阵", "entity_question_matrix", "heatmap", "每行是一名角色，每列是年龄、入坑时间等所选问题的一个选项；颜色表示该角色支持者中的比例。"),
    TemplateSpec("r10_music_question_matrix", "曲子问卷关联", "曲子 × 问卷选项矩阵", "entity_question_matrix", "heatmap", "每行是一首曲子，每列是年龄、入坑时间等所选问题的一个选项；颜色表示该曲听众中的比例。"),
    TemplateSpec("a01_direction_matrix", "同投", "TOP角色方向同投率矩阵", "covote_matrix_rate", "heatmap", "每一行以该角色选择人数为分母。"),
    TemplateSpec("a01_count_matrix", "同投", "TOP角色共同人数矩阵", "covote_matrix_count", "heatmap", "矩阵展示两名角色的共同投票人数。"),
    TemplateSpec("a02_network", "同投", "团体/阵营关联网络", "covote_network", "network", "节点为角色，边宽按同投人数。搜索可限制阵营角色。"),
    TemplateSpec("a17_concentration_clusters", "同投", "跨部门同投集中聚类", "concentration_clusters", "network", "仅对角色×曲子跨类别同投关系按集中倍数聚类；当前覆盖 CN10–11 与 JP17–22。"),
    TemplateSpec("a18_music_concentration_clusters", "同投", "音乐内部同投集中聚类", "concentration_clusters", "network", "对同一音乐部门内的曲子×曲子关系聚类；当前完整矩阵覆盖 CN10–11。"),
    TemplateSpec("a03_bubble", "同投", "共同人数 × 集中倍数气泡图", "covote_bubble", "bubble", "横轴共同人数使用对数尺度，纵轴为集中倍数，气泡大小表示正向 φ。"),
    TemplateSpec("a03_count_top", "同投", "共同投票人数 TOP", "covote_metric", "bar", "同一张选票同时选择A与B的人数。"),
    TemplateSpec("a04_count_dumbbell", "同投", "两届同投人数哑铃图", "covote_dumbbell", "dumbbell", "同一行用两个点表示当前届和对比届共同人数，灰线只连接同一角色对。"),
    TemplateSpec("a04_count_change", "同投", "共同人数跨届变化", "covote_change", "bar", "两届均有公开记录的同投人数变化。"),
    TemplateSpec("a05_largest_change", "同投", "共同人数变化幅度最大", "covote_change_abs", "bar", "按跨届变化绝对值排序。"),
    TemplateSpec("a06_lift", "同投", "同投集中倍数", "covote_metric", "bar", "实际共同人数÷仅按双方人气得到的期望人数。"),
    TemplateSpec("a07_excess", "同投", "比人气基准多出人数", "covote_metric", "bar", "实际共同人数减去人气随机交叉基准。"),
    TemplateSpec("a08_phi", "同投", "综合重合分数 φ", "covote_metric", "bar", "把同投、仅投A、仅投B、均未投四类状态纳入。"),
    TemplateSpec("a09_phi_change", "同投", "综合重合分数跨届变化", "covote_phi_change", "bar", "φ当前届减去对比届。"),
    TemplateSpec("a10_direction", "同投", "A→B与B→A方向同投率", "covote_direction", "dumbbell", "同一关系用两个点比较 A→B 与 B→A；两者使用各自方向的分母。"),
    TemplateSpec("a11_asymmetry", "同投", "方向同投率差", "covote_metric_abs", "bar", "A→B与B→A的比例差。"),
    TemplateSpec("a12_cumulative", "同投", "角色关系超额累计", "covote_cumulative", "bar", "每名角色参与关系的正向超额人数累计。"),
    TemplateSpec("a13_quadrant", "同投", "两届整体变化四象限", "covote_quadrant", "scatter", "横轴同投占比变化，纵轴集中倍数变化。"),
    TemplateSpec("a14_count_top10", "同投", "同投人数 TOP10", "covote_metric", "bar", "文章末尾摘要榜，可由Top N配置改变。"),
    TemplateSpec("a15_lift_top10", "同投", "集中倍数 TOP10", "covote_metric", "bar", "默认要求共同人数达到阈值。"),
    TemplateSpec("a16_anomalies", "同投", "官方异常数据", "covote_anomaly", "bar", "双向公布的共同人数不一致；TOP100应为38组。"),
    TemplateSpec("p01_cp_metric", "CP投票", "CP投票结果排行", "cp_metric", "bar", "官方CP/组合投票结果；展示官方名次、投票人数或比例。"),
    TemplateSpec("p02_combination_compare", "CP投票", "所有组合跨届对比", "combination_compare", "dumbbell", "有官方CP时使用CP投票；没有CP项目时自动使用同投，并在结果表标明来源。"),
    TemplateSpec("q01_age", "问卷", "年龄结构比例哑铃图", "questionnaire_age", "dumbbell", "按文章口径合并年龄段，以两个点比较任意两届比例。"),
    TemplateSpec("q02_cognition", "问卷", "入坑时间比例哑铃图", "questionnaire", "dumbbell", "每一行是一个入坑时间选项，横轴是该选项所占比例。"),
    TemplateSpec("q03_usertype", "问卷", "参与东方方式比例哑铃图", "questionnaire", "dumbbell", "多选题各项比例不要求合计100%，每届使用独立圆点。"),
    TemplateSpec("q04_new", "问卷", "新作体验版与家人传教比例", "questionnaire", "dumbbell", "第21回起出现的问卷题，可在问卷题目配置中切换；不存在的届次保留为空。"),
    TemplateSpec("q_custom", "问卷", "自选问题 × 选项比例图", "questionnaire", "dumbbell", "从全部公开问卷问题中选择；行是答案选项，横轴是比例。"),
    TemplateSpec("x_character", "自定义", "角色指标散点图", "custom_character", "scatter", "自由选择角色横轴和纵轴指标。"),
    TemplateSpec("x_covote", "自定义", "同投指标散点图", "custom_covote", "scatter", "自由选择同投横轴和纵轴指标。"),
]

TEMPLATE_BY_KEY = {item.key: item for item in TEMPLATES}


class AnalysisRepository:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        character_path = data_dir / "analysis_character_metrics_all.csv"
        music_path = data_dir / "analysis_music_metrics_all.csv"
        pair_path = data_dir / "analysis_covote_pairs_all.csv"
        cp_path = data_dir / "analysis_cp_metrics_all.csv"
        combination_path = data_dir / "analysis_vote_combinations_all.csv"
        questionnaire_path = data_dir / "analysis_questionnaire_all.csv"
        entity_questionnaire_path = data_dir / "analysis_entity_questionnaire_all.csv.gz"
        cn_advanced_pairs_path = data_dir / "analysis_cn_advanced_pairs_all.csv.gz"
        link_path = data_dir / "analysis_character_music_links_all.csv"
        character_music_covote_path = data_dir / "analysis_character_music_covote_all.csv"
        self.characters = read_numeric_csv(character_path, CHARACTER_FIELDS)
        self.music = read_numeric_csv(music_path, MUSIC_FIELDS)
        self.pairs = read_numeric_csv(pair_path, COVOTE_FIELDS)
        self.cp_metrics = read_numeric_csv(cp_path, CP_FIELDS) if cp_path.exists() else []
        self.combinations = read_numeric_csv(combination_path, COMBINATION_FIELDS) if combination_path.exists() else []
        self.questionnaire = read_numeric_csv(questionnaire_path, QUESTIONNAIRE_FIELDS)
        self.entity_questionnaire = read_numeric_csv(entity_questionnaire_path, ENTITY_QUESTIONNAIRE_FIELDS)
        # CN5–11 official questionnaire pair cells are kept separately from
        # character co-vote pairs.  The UI currently exposes them as a raw
        # analysis table/API field; keeping an empty list when the optional
        # file is absent preserves compatibility with older data bundles.
        self.cn_advanced_pairs = read_numeric_csv(cn_advanced_pairs_path, set()) if cn_advanced_pairs_path.exists() else []
        catalog_path = data_dir / "analysis_work_catalog.csv"
        self.work_catalog = read_numeric_csv(catalog_path, {"release_order"}) if catalog_path.exists() else []
        self.work_catalog_by_key = {}
        for item in self.work_catalog:
            for raw in (item.get("name_jp", ""), item.get("name_cn", "")):
                key = normalize_work_name(raw)
                if key:
                    previous = self.work_catalog_by_key.get(key)
                    # The catalogue can contain a dated combined entry and a
                    # later undated fallback row with the same display name.
                    # Keep the entry with the earliest known release order so
                    # chronological questionnaire sorting remains stable.
                    if previous is None or number(item.get("release_order"), 99999999) < number(previous.get("release_order"), 99999999):
                        self.work_catalog_by_key[key] = item
        # Original-setting faction crosswalk.  The table is generated from
        # the checked-in THBWiki character index plus a conservative mapping
        # of formal groups; it is intentionally separate from community tags.
        faction_path = data_dir / "analysis_character_factions.csv"
        self.character_factions = read_numeric_csv(faction_path, set()) if faction_path.exists() else []
        self.character_factions_by_key = {}
        self.faction_options = []
        for item in self.character_factions:
            labels = [label.strip() for label in str(item.get("factions", "")).split(";") if label.strip()]
            item["faction_labels"] = labels
            for raw in (item.get("canonical_name", ""), item.get("name_cn", ""), item.get("name_jp", "")):
                key = normalize_name(raw)
                if key:
                    self.character_factions_by_key[key] = item
            for label in labels:
                if label not in self.faction_options:
                    self.faction_options.append(label)
        # Keep the four article groups first, then ordinary formal groups,
        # then work-cohort/unknown labels in deterministic order.
        preferred = ["红魔馆", "地灵殿", "秘封俱乐部", "神灵庙", "博丽神社", "白玉楼", "永远亭", "守矢神社", "命莲寺", "妖怪之山", "天界", "地狱", "畜生界", "月之都", "魔界", "妖精", "外界"]
        self.faction_options = [label for label in preferred if label in self.faction_options] + sorted(
            [label for label in self.faction_options if label not in preferred],
            key=lambda value: (0 if value.startswith("作品首登：") else 1, value),
        )
        self.links = read_numeric_csv(link_path, LINK_FIELDS) if link_path.exists() else []
        self.character_music_covote = read_numeric_csv(character_music_covote_path, CROSSVOTE_FIELDS) if character_music_covote_path.exists() else []
        self.character_by_round = defaultdict(list)
        self.music_by_round = defaultdict(list)
        self.pairs_by_round = defaultdict(list)
        self.cp_by_round = defaultdict(list)
        self.combinations_by_round = defaultdict(list)
        self.links_by_round = defaultdict(list)
        self.character_music_covote_by_round = defaultdict(list)
        for row in self.characters:
            label = normalize_round_label(row.get("round_label") or row.get("round"))
            row["round_label"] = label
            self.character_by_round[label].append(row)
        for row in self.music:
            label = normalize_round_label(row.get("round_label") or row.get("round"))
            row["round_label"] = label
            self.music_by_round[label].append(row)
        for row in self.pairs:
            label = normalize_round_label(row.get("round_label") or row.get("round"))
            row["round_label"] = label
            self.pairs_by_round[label].append(row)
        for row in self.cp_metrics:
            label = normalize_round_label(row.get("round_label") or row.get("round"))
            row["round_label"] = label
            self.cp_by_round[label].append(row)
        for row in self.combinations:
            label = normalize_round_label(row.get("round_label") or row.get("round"))
            row["round_label"] = label
            self.combinations_by_round[label].append(row)
        for row in self.links:
            label = normalize_round_label(row.get("round_label") or row.get("round"))
            row["round_label"] = label
            self.links_by_round[label].append(row)
        for row in self.character_music_covote:
            label = normalize_round_label(row.get("round_label") or row.get("round"))
            row["round_label"] = label
            self.character_music_covote_by_round[label].append(row)
        self.round_labels = sorted(self.character_by_round, key=round_sort_key)
        self.covote_round_labels = sorted(self.pairs_by_round, key=round_sort_key)
        self.cp_round_labels = sorted(self.cp_by_round, key=round_sort_key)
        self.questionnaire_round_labels = sorted(
            {
                normalize_round_label(row.get("round_label") or row.get("round")) for row in self.questionnaire
            }
            | {
                normalize_round_label(row.get("round_label") or row.get("round"))
                for row in self.entity_questionnaire
                if row.get("region") == "cn"
            },
            key=round_sort_key,
        )
        self.entity_questionnaire_by_round_category = defaultdict(list)
        for row in self.entity_questionnaire:
            label = normalize_round_label(row.get("round_label") or row.get("round"))
            row["round_label"] = label
            self.entity_questionnaire_by_round_category[(label, row.get("category", ""))].append(row)

    def name(self, row: dict, config: dict, pair_side: str = "") -> str:
        suffix = f"_{pair_side}" if pair_side else ""
        jp = row.get(f"name{suffix}_jp") if not pair_side else row.get(f"name_{pair_side}")
        cn = row.get(f"name{suffix}_cn") if not pair_side else row.get(f"name_{pair_side}_cn")
        if not pair_side:
            jp = row.get("name_jp", "")
            cn = row.get("name_cn", "")
        language = config.get("language", "cn")
        if language == "jp":
            return jp or cn or "?"
        if language == "both" and cn and jp and cn != jp:
            return f"{cn} / {jp}"
        return cn or jp or "?"

    def pair_label(self, row: dict, config: dict) -> str:
        return f"{self.name(row, config, 'a')} × {self.name(row, config, 'b')}"

    def entity_key(self, row: dict) -> str:
        return row.get("canonical_name") or normalize_name(row.get("name_cn") or row.get("name_jp", ""))

    def work_info(self, name: str, entity_id: str | int = "") -> dict:
        """Return catalogue metadata for a Japanese/Chinese work label."""
        variants = work_name_variants(name)
        for key in variants:
            if key in self.work_catalog_by_key:
                return self.work_catalog_by_key[key]
        # Cognition ranges abbreviate titles (``アマノジャク`` or
        # ``紺珠伝``).  Resolve a unique suffix/prefix match against the
        # catalogue without treating generic words such as “现在” as works.
        for key in variants:
            candidates = [item for catalog_key, item in self.work_catalog_by_key.items()
                          if len(key) >= 3 and (catalog_key.endswith(key) or key.endswith(catalog_key))]
            if candidates:
                candidates.sort(key=lambda item: (number(item.get("release_order"), 99999999), str(item.get("name_jp", ""))))
                return candidates[0]
        return {}

    def work_name(self, name: str, entity_id: str | int = "", language: str = "cn") -> str:
        info = self.work_info(name, entity_id)
        jp = info.get("name_jp") or str(name or "")
        cn = info.get("name_cn") or jp
        if language == "jp":
            return jp or cn or "?"
        if language == "both" and cn and jp and cn != jp:
            return f"{cn} / {jp}"
        return cn or jp or "?"

    def work_release_order(self, name: str, entity_id: str | int = "") -> float:
        info = self.work_info(name, entity_id)
        return number(info.get("release_order"), 999999) if info else 999999

    def work_release_code(self, name: str, entity_id: str | int = "") -> str:
        info = self.work_info(name, entity_id)
        return str(info.get("release_code") or "") if info else ""

    def work_release_date(self, name: str, entity_id: str | int = "") -> str:
        info = self.work_info(name, entity_id)
        return str(info.get("release_date") or "") if info else ""

    def question_answer_display(self, question_key: str, value: str, language: str = "cn") -> str:
        """Translate questionnaire answers, including work-era options."""
        raw = str(value or "").strip()
        if not raw:
            return raw
        if question_key == "cognition":
            # Preserve the source date annotation while translating both ends
            # of the era range, e.g. ``アマノジャク～紺珠伝（2015年8月）``.
            suffix = ""
            match = re.search(r"([（(][^）)]*[）)])\s*$", raw)
            if match:
                suffix = f"（{match.group(1)[1:-1]}）"
                raw = raw[:match.start()].strip()
            parts = re.split(r"\s*[～〜~]\s*", raw)
            translated = []
            for part in parts:
                token = COGNITION_TOKEN_TRANSLATIONS.get(part.strip(), "") or WORK_TOKEN_TRANSLATIONS.get(part.strip(), "")
                info = self.work_info(part.strip())
                translated.append(token or (self.work_name(part.strip(), language=language) if info else part.strip()))
            return "～".join(translated) + suffix
        if question_key in WORK_QUESTION_KEYS:
            info = self.work_info(raw)
            if info:
                return self.work_name(raw, language=language)
        display = entity_answer_label(raw)
        return re.sub(r"(?<=\d)-(?=\d)", "–", display)

    def question_answer_sort_key(self, question_key: str, value: str) -> tuple:
        """Sort work-valued questionnaire options chronologically."""
        raw = str(value or "").strip()
        if question_key == "age":
            if raw.startswith("～") or any(token in raw for token in ("未满", "不到", "以下")):
                return (0, raw)
            match = re.search(r"(\d+)", raw)
            return (int(match.group(1)) if match else 99999999, raw)
        if question_key == "cognition":
            date_match = re.search(r"(\d{4})年?(\d{1,2})?月?", raw)
            date_key = int(date_match.group(1)) * 100 + int(date_match.group(2) or 1) if date_match else 99999999
            orders = []
            for part in re.split(r"\s*[～〜~]\s*", re.sub(r"[（(][^）)]*[）)]", "", raw)):
                info = self.work_info(part.strip())
                if info:
                    orders.append(number(info.get("release_order"), 99999999))
            # The parenthesised date is the end of the period and is the
            # source's intended chronology.  Prefer it over a catalogue's
            # combined/undated fallback entries.
            return (date_key if date_key != 99999999 else (min(orders) if orders else date_key), raw)
        if question_key in WORK_QUESTION_KEYS:
            return (self.work_release_order(raw), raw)
        return (99999999, raw)

    def entity_question_answers(self, round_label: str, category: str, question_key: str) -> list[str]:
        rows = self.entity_questionnaire_by_round_category[(normalize_round_label(round_label), category)]
        answers = list(dict.fromkeys(row.get("answer_label", "") for row in rows
                                    if row.get("question_key") == question_key and row.get("answer_label", "")))
        return sorted(answers, key=lambda value: self.question_answer_sort_key(question_key, value))

    def entity_question_questions(self, round_label: str, category: str) -> list[str]:
        """List the actual entity-question keys published for a round/category."""
        rows = self.entity_questionnaire_by_round_category.get((normalize_round_label(round_label), category), [])
        keys = list(dict.fromkeys(row.get("question_key", "") for row in rows if row.get("question_key", "")))
        # Keep the common demographic questions in a stable order, then show
        # every CN-specific source question instead of hiding it behind the
        # fixed JP-only selector.
        preferred = {"sex": 0, "age": 1, "cognition": 2, "voted": 3, "intention": 4}
        return sorted(keys, key=lambda value: (preferred.get(value, 10), questionnaire_label(value, entity=True), value))

    def questionnaire_questions(self, round_labels: list[str] | None = None) -> list[str]:
        """List aggregate questionnaire keys available in the selected rounds."""
        selected = {normalize_round_label(value) for value in (round_labels or self.questionnaire_round_labels)}
        keys = list(dict.fromkeys(
            row.get("question_key", "") for row in self.questionnaire
            if normalize_round_label(row.get("round_label") or row.get("round")) in selected and row.get("question_key", "")
        ))
        preferred = {key: index for index, key in enumerate(QUESTION_LABELS)}
        return sorted(keys, key=lambda value: (preferred.get(value, 100), questionnaire_label(value), value))

    def faction_labels_for_row(self, row: dict) -> set[str]:
        """Return strict original-setting group labels for a character row."""
        labels: set[str] = set()
        for raw in (
            row.get("canonical_name", ""), row.get("name_cn", ""), row.get("name_jp", ""),
            row.get("character_canonical", ""), row.get("character_name_cn", ""), row.get("character_name_jp", ""),
        ):
            item = self.character_factions_by_key.get(normalize_name(raw))
            if item:
                labels.update(item.get("faction_labels", []))
        return labels

    def _selected_faction(self, config: dict) -> str:
        value = str(config.get("faction", "") or "").strip()
        return "" if value in {"", "全部"} else value

    def music_keys_for_faction(self, round_label: str, faction: str) -> set[str]:
        """Resolve songs linked to characters in one original-setting group."""
        if not faction:
            return set()
        keys: set[str] = set()
        for link in self.links_by_round.get(normalize_round_label(round_label), []):
            if faction in self.faction_labels_for_row(link):
                key = link.get("music_canonical", "")
                if key:
                    keys.add(key)
        return keys

    def filtered_characters(self, config: dict, round_no=None) -> list[dict]:
        rnd = normalize_round_label(round_no or config.get("current_round", "JP22"))
        rank_start = max(1, integer(config.get("rank_start", 1), 1))
        rank_limit = max(rank_start, integer(config.get("rank_end", config.get("rank_limit", 100)), 100))
        query = str(config.get("search", "")).strip().casefold()
        faction = self._selected_faction(config)
        rows = []
        for row in self.character_by_round[rnd]:
            rank = integer(row.get("rank"), 999999)
            if rank < rank_start or rank > rank_limit:
                continue
            row_factions = self.faction_labels_for_row(row)
            if faction and faction not in row_factions:
                continue
            hay = f"{row.get('name_jp','')} {row.get('name_cn','')} {' '.join(row_factions)}".casefold()
            if query and query not in hay:
                continue
            rows.append(row)
        return rows

    def filtered_music(self, config: dict, round_no=None) -> list[dict]:
        rnd = normalize_round_label(round_no or config.get("current_round", "JP22"))
        rank_start = max(1, integer(config.get("rank_start", 1), 1))
        rank_limit = max(rank_start, integer(config.get("rank_end", 100), 100))
        query = str(config.get("search", "")).strip().casefold()
        faction = self._selected_faction(config)
        faction_music = self.music_keys_for_faction(rnd, faction) if faction else set()
        rows = []
        for row in self.music_by_round[rnd]:
            rank = integer(row.get("rank"), 999999)
            if rank < rank_start or rank > rank_limit:
                continue
            if faction and row.get("canonical_name", "") not in faction_music:
                continue
            hay = f"{row.get('name_jp','')} {row.get('name_cn','')}".casefold()
            if query and query not in hay:
                continue
            rows.append(row)
        return rows

    @staticmethod
    def _filter_min_entity_votes(rows: list[dict], config: dict) -> tuple[list[dict], int, bool]:
        """Apply the optional questionnaire cohort vote-count threshold.

        ``selection_count`` is the number of people who actually selected the
        entity in the ballot, not the questionnaire answer count.  Missing
        values are left out only when a positive threshold is requested; with
        the default zero threshold all rows retain the historical behaviour.
        """
        minimum = max(0, integer(config.get("min_entity_votes", 0), 0))
        if minimum <= 0:
            return rows, 0, False
        kept: list[dict] = []
        removed = 0
        missing = False
        for row in rows:
            value = number(row.get("selection_count"), None)
            if value is None:
                missing = True
                removed += 1
                continue
            if value >= minimum:
                kept.append(row)
            else:
                removed += 1
        return kept, removed, missing

    def filtered_pairs(self, config: dict, round_no=None, apply_minimum: bool = True) -> list[dict]:
        rnd = normalize_round_label(round_no or config.get("current_round", "JP22"))
        rank_start = max(1, integer(config.get("rank_start", 1), 1))
        rank_limit = max(rank_start, integer(config.get("rank_end", config.get("rank_limit", 100)), 100))
        minimum = integer(config.get("min_count", 100), 100) if apply_minimum else 0
        range_mode = config.get("pair_range_mode", "both")
        query = str(config.get("search", "")).strip().casefold()
        faction = self._selected_faction(config)
        rows = []
        for row in self.pairs_by_round[rnd]:
            a_in = rank_start <= integer(row.get("rank_a"), 999999) <= rank_limit
            b_in = rank_start <= integer(row.get("rank_b"), 999999) <= rank_limit
            if (range_mode == "either" and not (a_in or b_in)) or (range_mode != "either" and not (a_in and b_in)):
                continue
            if number(row.get("intersection_count")) < minimum:
                continue
            if faction:
                a_factions = self.faction_labels_for_row({"name_cn": row.get("name_a_cn", ""), "name_jp": row.get("name_a", ""), "canonical_name": row.get("canonical_a", "")})
                b_factions = self.faction_labels_for_row({"name_cn": row.get("name_b_cn", ""), "name_jp": row.get("name_b", ""), "canonical_name": row.get("canonical_b", "")})
                if faction not in a_factions or faction not in b_factions:
                    continue
            hay = f"{row.get('name_a','')} {row.get('name_b','')} {row.get('name_a_cn','')} {row.get('name_b_cn','')}".casefold()
            if query and query not in hay:
                continue
            rows.append(row)
        return rows

    def filtered_cp(self, config: dict, round_no=None) -> list[dict]:
        """Filter official CP/组合 rows using the same rank/search controls."""
        rnd = normalize_round_label(round_no or config.get("current_round", "JP22"))
        rank_start = max(1, integer(config.get("rank_start", 1), 1))
        rank_limit = max(rank_start, integer(config.get("rank_end", config.get("rank_limit", 100)), 100))
        query = str(config.get("search", "")).strip().casefold()
        rows = []
        for row in self.cp_by_round.get(rnd, []):
            rank = integer(row.get("rank"), 999999)
            if rank < rank_start or rank > rank_limit:
                continue
            hay = " ".join(str(row.get(field, "")) for field in ("combination_label", "name_a", "name_b", "name_c")).casefold()
            if query and query not in hay:
                continue
            rows.append(row)
        return rows

    def filtered_combinations(self, config: dict, round_no=None) -> list[dict]:
        rnd = normalize_round_label(round_no or config.get("current_round", "JP22"))
        rank_start = max(1, integer(config.get("rank_start", 1), 1))
        rank_limit = max(rank_start, integer(config.get("rank_end", config.get("rank_limit", 100)), 100))
        query = str(config.get("search", "")).strip().casefold()
        rows = []
        for row in self.combinations_by_round.get(rnd, []):
            # Official CP rows have an official rank. Co-vote fallback rows do
            # not; they remain eligible for the same result window instead of
            # being silently removed as if they had an unknown rank.
            rank = integer(row.get("rank"), None)
            if rank is not None and not rank_start <= rank <= rank_limit:
                continue
            hay = str(row.get("combination_label", "")).casefold()
            if query and query not in hay:
                continue
            rows.append(row)
        return rows

    def build(self, template_key: str, config: dict) -> dict:
        spec = TEMPLATE_BY_KEY[template_key]
        method: Callable[[TemplateSpec, dict], dict] = getattr(self, f"build_{spec.builder}")
        chart = method(spec, config)
        chart.setdefault("title", spec.title)
        chart.setdefault("chart_type", spec.chart_type)
        chart.setdefault("description", spec.description)
        chart.setdefault("note", "")
        chart.setdefault("allowed_chart_types", template_chart_types(spec))
        current = normalize_round_label(config.get("current_round", "JP22"))
        selected_faction = self._selected_faction(config)
        if selected_faction:
            chart["note"] = (chart.get("note", "") + f" 原作阵营筛选：{selected_faction}；角色可同时属于多个原作群体。" ).strip()
        if not chart.get("table_rows"):
            chart["note"] = (chart.get("note", "") + f" 当前选择的 {current} 没有这一指标的可用公开数据。请更换届次或指标。").strip()
        chart["interpretation"] = self.interpret_chart(spec, chart, config)
        chart["template"] = spec.key
        return chart

    def interpret_chart(self, spec: TemplateSpec, chart: dict, config: dict) -> str:
        """Return a short, data-aware reading guide shown beside every chart."""
        key = spec.key
        text: list[str] = []
        if key in {"c01_rank_change", "c03_primary_rate_change", "c06_primary_change", "c07_selection_change", "c07_selection_yoy", "c08_points_change", "c09_selection_rate_change", "c12_gender_change", "a04_count_change", "a05_largest_change", "a09_phi_change"}:
            text.append("变化图：正数表示当前届相对对比届增加/名次上升（名次数字变小才是上升）；负数表示下降。它不是因果效应。")
        elif key in {"a16_anomalies"}:
            text.append("异常行表示官网 A→B 与 B→A 公布的共同人数不一致，是源数据发布冲突，不等同于关系特别强；需要回溯原始页面。")
        elif key in {"a01_direction_matrix", "a01_count_matrix", "c11_metric_heatmap", "r08_work_question_matrix", "r09_character_question_matrix", "r10_music_question_matrix"}:
            text.append("矩阵按行/列分别展示；斜线或空白表示未公开，不是0。热力颜色只在当前矩阵语境内比较，不能把不同列直接当成同一尺度。")
        elif key == "a03_bubble":
            text.append("气泡图横轴是共同人数、纵轴是集中倍数；1倍为按双方人气得到的随机基准。小共同人数的高倍数可能不稳定，要同时看人数、倍数和 φ。")
        elif key in {"q01_age", "q02_cognition", "q03_usertype", "q04_new", "q_custom"}:
            text.append("问卷图的比例以该题有效回答者为分母；多选题各项不必合计100%，不同届的有效人数也可能不同。未公开题目留空，不代表无人选择。")
        elif key in {"r01_character_question_scatter", "r04_music_question_scatter", "r07_character_cognition", "r02_character_question_diff", "r05_music_question_diff", "r03_character_question_corr", "r06_music_question_corr"}:
            text.append("问卷关联只说明投票指标与受访者构成的统计关联；相关系数不代表因果，名次数字越小越受欢迎，解读方向时要反向理解。")
            if key in {"r01_character_question_scatter", "r04_music_question_scatter", "r07_character_cognition"}:
                text.append("散点图的横轴是选择该问卷选项的实际人数，纵轴是该实体人群中的比例；比例高不等于人数最多，比较时应同时看横轴、纵轴和结果表中的有效样本数。")
        elif key in {"p01_cp_metric", "p02_combination_compare"}:
            text.append("CP官方榜与同投替代采用不同统计口径；结果表中的来源列会明确标记。缺少官方CP的届次只用同投人数填补，不表示该届发布过CP榜。")
        elif key in {"a17_concentration_clusters", "a18_music_concentration_clusters"}:
            scope = "角色×音乐跨部门" if key == "a17_concentration_clusters" else "音乐×音乐内部"
            text.append(f"这是{scope}聚类，不是官方榜：先按共同人数和集中倍数筛边，再以单链接连通分量成簇；集中度得分是组件内超出随机期望的共同人数之和。两个范围分开计算，不混成一个网络。")
        elif key == "m07_character_music_covote":
            text.append("同投人数是官方角色详情中的条件交叉计数；同投率=P(曲子|角色)。这里只列官方公开的条件排行，未公开组合不能解释为0。")
        elif key in {"m05_character_music_cross", "m06_music_character_cross", "m08_character_carryover", "m09_music_arrangement_cross", "m10_character_arrangement_cross"}:
            text.append("角色—曲子关系来自本地打标；关联强不证明角色人气导致曲子人气。没有打标或没有指标的关系会被留空。")
        else:
            text.append("请结合图下注释和结果表阅读；空白表示源数据未公开，极端值应先检查样本量和计分制度。")
        rows = chart.get("table_rows") or []
        if rows:
            text.append(f"当前显示 {len(rows):,} 行结果；完整名称和原始数值可在“计算结果表”或 CSV 中查看。")
        if chart.get("coverage"):
            text.append(f"该专项数据覆盖：{chart['coverage']}。")
        return " ".join(text)

    def _limit_sort(self, rows: list[dict], config: dict, key: str = "value", absolute: bool = False) -> list[dict]:
        sort_mode = config.get("sort", "desc")
        direction = config.get("change_direction", "all")
        # Change-oriented templates can be narrowed before ranking.  Keeping
        # zero out of either directional view makes the result a true
        # increase/decrease list rather than a second arbitrary top-N slice.
        if direction == "positive":
            rows = [row for row in rows if number(row.get(key)) > 0]
        elif direction == "negative":
            rows = [row for row in rows if number(row.get(key)) < 0]
        if sort_mode == "asc":
            ordered = sorted(rows, key=lambda r: number(r.get(key)))
        elif sort_mode == "abs" or (absolute and direction == "all") or (absolute and direction in {"positive", "negative"} and sort_mode == "desc"):
            ordered = sorted(rows, key=lambda r: abs(number(r.get(key))), reverse=True)
        else:
            ordered = sorted(rows, key=lambda r: number(r.get(key)), reverse=True)
        return ordered[: integer(config.get("top_n", 20), 20)]

    def _categorical(self, title: str, rows: list[dict], series: list[tuple[str, str]], value_format="number", chart_type="bar", note="") -> dict:
        return {
            "title": title, "chart_type": chart_type, "categories": [r["label"] for r in rows],
            "series": [{"name": name, "values": [number(r.get(field), None) for r in rows]} for name, field in series],
            "value_format": value_format, "table_headers": ["名称"] + [name for name, _ in series],
            "table_rows": [[r["label"]] + [r.get(field, "") for _, field in series] for r in rows], "note": note,
        }

    def _pair_join(self, config: dict) -> list[tuple[dict, dict]]:
        current = self.filtered_pairs(config)
        compare = self.filtered_pairs(config, config.get("compare_round", "JP21"))
        prev = {(r.get("canonical_a") or normalize_name(r["name_a"]), r.get("canonical_b") or normalize_name(r["name_b"])): r for r in compare}
        output = []
        for row in current:
            other = prev.get((row.get("canonical_a") or normalize_name(row["name_a"]), row.get("canonical_b") or normalize_name(row["name_b"])))
            if other:
                output.append((row, other))
        return output

    def build_rank_change(self, spec, config):
        current = self.filtered_characters(config)
        previous = {self.entity_key(r): r for r in self.filtered_characters(config, config.get("compare_round", "JP21"))}
        rows = []
        for row in current:
            prev = previous.get(self.entity_key(row))
            if prev:
                rows.append({"label": self.name(row, config), "value": number(prev["rank"]) - number(row["rank"])})
        rows = self._limit_sort(rows, config, absolute=True)
        return self._categorical(spec.title, rows, [("名次变化", "value")], chart_type="bar", note="正数表示名次上升，负数表示下降。")

    def build_round_comparison(self, spec, config):
        field = config.get("y_metric", "rank")
        if field not in CHARACTER_FIELDS:
            field = "rank"
        current_label = normalize_round_label(config.get("current_round", "JP22"))
        compare_label = normalize_round_label(config.get("compare_round", "JP21"))
        current_rows = sorted(self.filtered_characters(config), key=lambda r: number(r.get("rank")))
        previous = {self.entity_key(r): r for r in self.filtered_characters(config, compare_label)}
        rows = []
        for row in current_rows:
            other = previous.get(self.entity_key(row))
            if other and row.get(field) is not None and other.get(field) is not None:
                rows.append({"label": self.name(row, config), "compare": other[field], "current": row[field]})
        rows = rows[: integer(config.get("top_n", 20), 20)]
        fmt = "percent" if field in PERCENT_FIELDS else "rank" if "rank" in field else "number"
        note = "每一届为独立系列，不会合并到同一根条。"
        if current_label[:2] != compare_label[:2] or field in {"points", "old_2_1_points"}:
            note += " 两地区或不同计分制度的分数不可视为同一尺度；优先比较名次、人数或比例。"
        return self._categorical(
            spec.title, rows, [(compare_label, "compare"), (current_label, "current")],
            value_format=fmt, chart_type="dumbbell", note=note,
        )

    def build_rank_trend(self, spec, config):
        chart = self.build_all_round_trend(spec, {**config, "y_metric": "rank"})
        chart["title"] = "角色届数 × 官方名次变化"
        chart["x_label"] = "届数"
        chart["y_label"] = "官方名次（#1 在上）"
        chart["rank_axis"] = True
        return chart

    def build_all_round_trend(self, spec, config):
        field = config.get("y_metric", "rank")
        if field not in CHARACTER_FIELDS:
            field = "rank"
        current_label = normalize_round_label(config.get("current_round", "JP22"))
        prefix = current_label[:2]
        rounds = [label for label in self.round_labels if label.startswith(prefix)]
        entities = sorted(self.filtered_characters(config), key=lambda row: number(row.get("rank")))[: integer(config.get("top_n", 20), 20)]
        keys = [self.entity_key(row) for row in entities]
        labels = [self.name(row, config) for row in entities]
        lookup = {
            (row["round_label"], self.entity_key(row)): row
            for label in rounds for row in self.character_by_round[label]
        }
        series = []
        for key, label in zip(keys, labels):
            values = []
            for round_name in rounds:
                row = lookup.get((round_name, key))
                values.append(number(row.get(field), None) if row and row.get(field) is not None else None)
            series.append({"name": label, "values": values})
        fmt = "percent" if field in PERCENT_FIELDS else "rank" if "rank" in field else "number"
        table = [[round_name] + [s["values"][idx] for s in series] for idx, round_name in enumerate(rounds)]
        note = f"显示 {prefix} 的全部可用届次；折线中的缺口表示该角色当届未上榜或指标未公开。"
        if field in {"points", "old_2_1_points"}:
            note += " 各届计分制度可能变化，分数趋势需谨慎解释。"
        return {
            "title": f"{METRIC_LABELS.get(field, field)}｜同地区全部届次趋势", "chart_type": "line",
            "categories": rounds, "series": series, "value_format": fmt,
            "table_headers": ["届次"] + labels, "table_rows": table, "note": note,
            "x_label": "届数", "y_label": METRIC_LABELS.get(field, field), "rank_axis": fmt == "rank",
        }

    def music_metric_for_config(self, config: dict) -> tuple[str, str]:
        field = config.get("y_metric", "rank")
        if field not in MUSIC_FIELDS:
            field = "rank"
        fmt = "percent" if field in PERCENT_FIELDS else "rank" if "rank" in field else "number"
        return field, fmt

    def build_music_metric(self, spec, config):
        field, fmt = self.music_metric_for_config(config)
        rows = [{"label": self.name(row, config), "value": row.get(field)} for row in self.filtered_music(config) if row.get(field) is not None]
        if "rank" in field and config.get("sort", "desc") == "desc":
            rows = sorted(rows, key=lambda row: number(row.get("value")))[: integer(config.get("top_n", 20), 20)]
        else:
            rows = self._limit_sort(rows, config)
        return self._categorical(spec.title, rows, [(METRIC_LABELS.get(field, field), "value")], value_format=fmt, note="曲子榜覆盖 CN1–11、JP3–22；跨制度分数需谨慎比较。")

    def build_music_primary_rate(self, spec, config):
        rows = [{"label": self.name(row, config), "value": row.get("primary_rate")} for row in self.filtered_music(config) if row.get("primary_rate") is not None]
        rows = self._limit_sort(rows, config)
        return self._categorical(spec.title, rows, [(METRIC_LABELS["primary_rate"], "value")], value_format="percent")

    def build_music_arrangement_cross(self, spec, config):
        """Scatter plot of vote popularity against THBWiki arrangement count."""
        arrangement_fields = {"arrangement_count", "arrangement_cumulative_count", "arrangement_total_count"}
        x_field = config.get("x_metric", "arrangement_cumulative_count")
        if x_field not in arrangement_fields:
            x_field = "arrangement_cumulative_count"
        y_field = config.get("y_metric", "selection_count")
        if y_field not in MUSIC_FIELDS or y_field in arrangement_fields | {"undated_arrangement_count"}:
            y_field = "selection_count"
        music_rows = self.filtered_music(config)
        if y_field == "selection_count" and not any(number(m.get("selection_count"), None) is not None for m in music_rows):
            y_field = "points"
        rows = []
        for music in music_rows:
            x = number(music.get(x_field), None)
            y = number(music.get(y_field), None)
            # Early JP windows published points but not the later
            # participant/selection count.  Keep the cross-analysis useful by
            # falling back to the officially available points metric rather
            # than returning an empty chart.
            effective_y_field = y_field
            if y is None and y_field == "selection_count":
                y = number(music.get("points"), None)
                effective_y_field = "points" if y is not None else y_field
            if x is None or y is None:
                continue
            selection_n = number(music.get("selection_count"), None)
            rows.append({"label": self.name(music, config), "x": x, "y": y,
                         "rank": music.get("rank"),
                         "size": max(selection_n, 0) if selection_n is not None else None,
                         "subtitle": f"{METRIC_LABELS[x_field]} {x:,.0f} 首｜{METRIC_LABELS.get(effective_y_field, effective_y_field)} {y:,.0f}"})
        rows.sort(key=lambda item: item["x"], reverse=True)
        rows = rows[: max(1, integer(config.get("top_n", 20), 20))]
        region_note = "CN1 为中文区首届基线，仅有抓取时点总数；CN2–11 与 JP3–22 的投票结束日历分别计算。" if str(config.get("current_round", "JP22")).upper().startswith("CN") else "JP3–22 使用日区投票结束日历；中文区 CN1–11 使用独立中文区日历。"
        chart = self._scatter(spec.title, rows, METRIC_LABELS[x_field], METRIC_LABELS.get(y_field, y_field),
                              "percent_y" if y_field.endswith("rate") else "auto",
                              f"届间新增数与截至投票结束累计数按当前地区的独立投票窗口表计算；抓取时点累计总数来自同目录总表。{region_note} 历史累计只计发布日期不晚于该届投票结束的曲目，未标日期曲目不纳入。抓取时点总数包含投票结束后的新增，不能解释为当届存量。未匹配曲目不填0；早期届次没有实际选择人数时自动使用官方分数。")
        chart["table_headers"] = ["曲子", "官方名次", METRIC_LABELS[x_field], METRIC_LABELS.get(y_field, y_field), "实际选择人数"]
        chart["table_rows"] = [[item["label"], item.get("rank"), item["x"], item["y"], item.get("size")] for item in rows]
        chart["x_format"] = "integer"
        chart["y_format"] = "percent" if y_field.endswith("rate") else ("rank" if "rank" in y_field else "integer")
        chart["cross_kind"] = "music_arrangement"
        return chart

    def build_character_arrangement_cross(self, spec, config):
        """Cross character vote metrics with the arrangement supply of themes."""
        round_label = normalize_round_label(config.get("current_round", "JP22"))
        arrangement_fields = {"arrangement_count", "arrangement_cumulative_count", "arrangement_total_count"}
        x_field = config.get("x_metric", "arrangement_cumulative_count")
        if x_field not in arrangement_fields:
            x_field = "arrangement_cumulative_count"
        y_field = config.get("y_metric", "selection_count")
        if y_field not in CHARACTER_FIELDS:
            y_field = "selection_count"
        links_by_character = defaultdict(dict)
        for link in self._cross_link_rows(round_label):
            arrangement = number(link.get(f"music_{x_field}"), None)
            music_key = link.get("music_canonical", "")
            if arrangement is None or not music_key:
                continue
            links_by_character[link.get("character_canonical", "")][music_key] = link
        points = []
        for character in self.filtered_characters(config):
            metric = number(character.get(y_field), None)
            links = list(links_by_character.get(self.entity_key(character), {}).values())
            if metric is None or not links:
                continue
            arrangement_total = sum(number(link.get(f"music_{x_field}"), 0) for link in links)
            window_total = sum(number(link.get("music_arrangement_count"), 0) for link in links)
            historical_total = sum(number(link.get("music_arrangement_cumulative_count"), 0) for link in links)
            crawl_total = sum(number(link.get("music_arrangement_total_count"), 0) for link in links)
            undated_total = sum(number(link.get("music_undated_arrangement_count"), 0) for link in links)
            label = self.name(character, config)
            points.append({"label": label, "x": arrangement_total, "y": metric, "rank": character.get("rank"),
                           "size": len(links), "window_total": window_total, "historical_total": historical_total,
                           "crawl_total": crawl_total, "undated": undated_total,
                           "subtitle": f"{len(links)} 首关联原曲｜{METRIC_LABELS[x_field]} {arrangement_total:,.0f} 首"})
        points.sort(key=lambda item: item["x"], reverse=True)
        points = points[: max(1, integer(config.get("top_n", 20), 20))]
        region_note = "CN1 为中文区首届基线，届间新增/截至结束累计为空；CN2–11 使用中文区独立投票窗口。" if round_label.startswith("CN") else "JP3–22 使用日区投票窗口；JP3 为首届基线。"
        chart = self._scatter(spec.title, points, f"关联原曲{METRIC_LABELS[x_field]}", METRIC_LABELS.get(y_field, y_field),
                              "percent_y" if y_field.endswith("rate") else "auto",
                              f"{region_note} 每个角色的关联原曲按 canonical key 去重后汇总所选口径。历史累计只计投票结束前有发布日期的曲目；抓取时点总数包含后来新增。点大小表示有数量数据的关联原曲数，未匹配不作0处理。")
        chart["table_headers"] = ["角色", "官方名次", f"关联原曲{METRIC_LABELS[x_field]}", METRIC_LABELS.get(y_field, y_field), "关联原曲数", "届间新增合计", "截至投票结束累计合计", "抓取时点累计合计", "未标日期同人曲数"]
        chart["table_rows"] = [[item["label"], item.get("rank"), item["x"], item["y"], item.get("size"), item.get("window_total"), item.get("historical_total"), item.get("crawl_total"), item.get("undated")] for item in points]
        chart["x_format"] = "integer"
        chart["y_format"] = "percent" if y_field.endswith("rate") else ("rank" if "rank" in y_field else "integer")
        chart["cross_kind"] = "character_arrangement"
        return chart

    def build_music_round_comparison(self, spec, config):
        field, fmt = self.music_metric_for_config(config)
        current_label = normalize_round_label(config.get("current_round", "JP22"))
        compare_label = normalize_round_label(config.get("compare_round", "JP21"))
        previous = {self.entity_key(row): row for row in self.filtered_music(config, compare_label)}
        rows = []
        for row in sorted(self.filtered_music(config), key=lambda item: number(item.get("rank"))):
            other = previous.get(self.entity_key(row))
            if other and row.get(field) is not None and other.get(field) is not None:
                rows.append({"label": self.name(row, config), "compare": other[field], "current": row[field]})
        rows = rows[: integer(config.get("top_n", 20), 20)]
        note = "每一届为独立系列。"
        if current_label[:2] != compare_label[:2] or field == "points":
            note += " 两地区或不同计分制度的分数不可直接视为同一尺度。"
        return self._categorical(spec.title, rows, [(compare_label, "compare"), (current_label, "current")], value_format=fmt, chart_type="dumbbell", note=note)

    def build_music_rank_trend(self, spec, config):
        chart = self.build_music_all_round_trend(spec, {**config, "y_metric": "rank"})
        chart["title"] = "曲子届数 × 官方名次变化"
        chart["x_label"] = "届数"
        chart["y_label"] = "官方名次（#1 在上）"
        chart["rank_axis"] = True
        return chart

    def build_music_all_round_trend(self, spec, config):
        field, fmt = self.music_metric_for_config(config)
        current_label = normalize_round_label(config.get("current_round", "JP22"))
        prefix = current_label[:2]
        rounds = [label for label in self.round_labels if label.startswith(prefix)]
        entities = sorted(self.filtered_music(config), key=lambda row: number(row.get("rank")))[: integer(config.get("top_n", 20), 20)]
        keys = [self.entity_key(row) for row in entities]; labels = [self.name(row, config) for row in entities]
        # A rebuilt dataset normally contains one canonical song per round.
        # Keep a defensive list reduction here as well so older bundled CSVs
        # (or a user-edited catalogue) cannot make the last duplicate silently
        # overwrite the first and create apparent trend breaks.  The best
        # official rank is the stable representative for a duplicate group;
        # selection count is used as a tie-breaker when rank is unavailable.
        lookup_groups = defaultdict(list)
        for label in rounds:
            for row in self.music_by_round[label]:
                lookup_groups[(row["round_label"], self.entity_key(row))].append(row)
        lookup = {
            key: min(values, key=lambda row: (number(row.get("rank"), 999999), -number(row.get("selection_count"), 0)))
            for key, values in lookup_groups.items()
        }
        series = []
        for key, label in zip(keys, labels):
            values = []
            for round_name in rounds:
                row = lookup.get((round_name, key))
                values.append(number(row.get(field), None) if row and row.get(field) is not None else None)
            series.append({"name": label, "values": values})
        table = [[round_name] + [item["values"][idx] for item in series] for idx, round_name in enumerate(rounds)]
        note = f"显示 {prefix} 曲子榜的全部可用届次；空缺表示未上榜或指标未公开。"
        if field == "points": note += " 各届计分制度可能变化。"
        return {
            "title": f"曲子{METRIC_LABELS.get(field, field)}全部届次趋势", "chart_type": "line",
            "categories": rounds, "series": series, "value_format": fmt,
            "table_headers": ["届次"] + labels, "table_rows": table, "note": note,
            "x_label": "届数", "y_label": METRIC_LABELS.get(field, field), "rank_axis": fmt == "rank",
        }

    def cp_metric_for_config(self, config: dict) -> tuple[str, str]:
        field = config.get("y_metric", "vote_count")
        if field not in CP_FIELDS:
            field = "vote_count"
        fmt = "percent" if field in {"vote_rate"} else "rank" if field == "rank" else "number"
        return field, fmt

    def combination_label(self, row: dict, config: dict) -> str:
        return str(row.get("combination_label") or " × ".join(part for part in (row.get("name_a"), row.get("name_b"), row.get("name_c")) if part) or "?")

    def build_cp_metric(self, spec, config):
        field, fmt = self.cp_metric_for_config(config)
        rows = [{"label": self.combination_label(row, config), "value": row.get(field), "source": row.get("source_type", "")} for row in self.filtered_cp(config) if row.get(field) is not None]
        if field == "rank":
            rows = sorted(rows, key=lambda row: number(row.get("value")))[: integer(config.get("top_n", 20), 20)]
        else:
            rows = self._limit_sort(rows, config)
        chart = self._categorical(spec.title, rows, [(METRIC_LABELS.get(field, field), "value")], value_format=fmt, note="官方CP/组合榜；CN10/11来自完整现代 GraphQL。")
        chart["table_headers"] = ["组合", METRIC_LABELS.get(field, field), "来源"]
        chart["table_rows"] = [[row["label"], row["value"], "官方CP"] for row in rows]
        return chart

    def build_combination_compare(self, spec, config):
        current_label = normalize_round_label(config.get("current_round", "JP22"))
        compare_label = normalize_round_label(config.get("compare_round", "JP21"))
        current = self.filtered_combinations(config, current_label)
        previous = {row.get("combination_key", ""): row for row in self.filtered_combinations(config, compare_label)}
        current_by_key = {row.get("combination_key", ""): row for row in current}
        rows = []
        # Use the union of keys. A missing endpoint is meaningful (the pair
        # was not published/available in that round) and must render as an
        # empty value rather than as zero or a fabricated fallback.
        for key in sorted(set(current_by_key) | set(previous)):
            row = current_by_key.get(key) or previous.get(key)
            other = previous.get(key)
            current_row = current_by_key.get(key)
            rows.append({"label": self.combination_label(row, config),
                         "compare": other.get("comparison_count") if other else None,
                         "current": current_row.get("comparison_count") if current_row else None,
                         "compare_source": other.get("data_source", "") if other else "",
                         "current_source": current_row.get("data_source", "") if current_row else ""})
        rows.sort(key=lambda item: number(item.get("current"), number(item.get("compare"), 0)), reverse=True)
        rows = rows[: max(1, integer(config.get("top_n", 20), 20))]
        chart = self._categorical(spec.title, rows, [(compare_label, "compare"), (current_label, "current")], value_format="number", chart_type="dumbbell", note="官方CP优先；缺少CP的届次以同投人数替代。结果表保留两端数据来源。")
        chart["table_headers"] = ["组合", compare_label, current_label, "对比届来源", "当前届来源", "差值"]
        def source_label(source):
            return "官方CP" if source == "official_cp" else "同投替代" if source == "co-vote_fallback" else "无公开数据"
        chart["table_rows"] = [[row["label"], row["compare"], row["current"], source_label(row["compare_source"]), source_label(row["current_source"]),
                                number(row["current"]) - number(row["compare"]) if row["current"] is not None and row["compare"] is not None else None] for row in rows]
        return chart

    def _cross_link_rows(self, round_label: str) -> list[dict]:
        """Return validated role↔music links for one round.

        Links are generated from the user's ``local_music_merged.csv`` tags.
        Keeping this as a separate dataset means the plotting layer never has
        to guess a relationship from a title string.
        """
        return [row for row in self.links_by_round[normalize_round_label(round_label)]
                if row.get("character_canonical") and row.get("music_canonical")]

    @staticmethod
    def _mean(values: list[float]) -> float | None:
        clean = [number(value, None) for value in values if value not in (None, "")]
        clean = [value for value in clean if value is not None]
        return sum(clean) / len(clean) if clean else None

    def build_character_music_cross(self, spec, config):
        round_label = normalize_round_label(config.get("current_round", "JP22"))
        x_field = config.get("x_metric", "selection_rate")
        y_field = config.get("y_metric", "selection_rate")
        if x_field not in CHARACTER_FIELDS:
            x_field = "selection_rate"
        if y_field not in MUSIC_FIELDS:
            y_field = "selection_rate"
        characters = {self.entity_key(row): row for row in self.filtered_characters(config)}
        links_by_character = defaultdict(list)
        for link in self._cross_link_rows(round_label):
            links_by_character[link.get("character_canonical", "")].append(link)
        points, table = [], []
        for key, character in characters.items():
            links = links_by_character.get(key, [])
            link_field = f"music_{y_field}"
            values = [link.get(link_field) for link in links]
            avg = self._mean(values)
            if character.get(x_field) is None or avg is None:
                continue
            count = len([value for value in values if value not in (None, "")])
            label = self.name(character, config)
            points.append({"label": label, "x": number(character[x_field]), "y": avg, "size": count,
                           "subtitle": f"{count} 首关联曲"})
            table.append([label, character.get("rank"), character.get(x_field), avg, count])
        points.sort(key=lambda point: point["x"], reverse=True)
        points = points[: max(integer(config.get("top_n", 20), 20), 20)]
        shown = {point["label"] for point in points}
        table = [row for row in table if row[0] in shown]
        chart = self._scatter(spec.title, points, METRIC_LABELS.get(x_field, x_field),
                              f"关联曲平均{METRIC_LABELS.get(y_field, y_field)}", "auto",
                              "每个点是一名角色；点大小表示打标关联曲数量。仅纳入当前届存在角色和曲子公开指标的关系。")
        chart["table_headers"] = ["角色", "角色官方名次", METRIC_LABELS.get(x_field, x_field),
                                   f"关联曲平均{METRIC_LABELS.get(y_field, y_field)}", "关联曲数量"]
        chart["table_rows"] = table
        chart["x_format"] = metric_axis_format(x_field)
        chart["y_format"] = "number"  # y is an average across linked songs
        chart["cross_kind"] = "character_music"
        return chart

    def build_music_character_cross(self, spec, config):
        round_label = normalize_round_label(config.get("current_round", "JP22"))
        x_field = config.get("x_metric", "selection_rate")
        y_field = config.get("y_metric", "selection_rate")
        if x_field not in MUSIC_FIELDS:
            x_field = "selection_rate"
        if y_field not in CHARACTER_FIELDS:
            y_field = "selection_rate"
        music_rows = {self.entity_key(row): row for row in self.filtered_music(config)}
        links_by_music = defaultdict(list)
        for link in self._cross_link_rows(round_label):
            links_by_music[link.get("music_canonical", "")].append(link)
        points, table = [], []
        for key, music in music_rows.items():
            links = links_by_music.get(key, [])
            link_field = f"character_{y_field}"
            values = [link.get(link_field) for link in links]
            avg = self._mean(values)
            if music.get(x_field) is None or avg is None:
                continue
            count = len([value for value in values if value not in (None, "")])
            label = self.name(music, config)
            points.append({"label": label, "x": number(music[x_field]), "y": avg, "size": count,
                           "subtitle": f"{count} 个所属角色"})
            table.append([label, music.get("rank"), music.get(x_field), avg, count])
        points.sort(key=lambda point: point["x"], reverse=True)
        points = points[: max(integer(config.get("top_n", 20), 20), 20)]
        shown = {point["label"] for point in points}
        table = [row for row in table if row[0] in shown]
        chart = self._scatter(spec.title, points, METRIC_LABELS.get(x_field, x_field),
                              f"所属角色平均{METRIC_LABELS.get(y_field, y_field)}", "auto",
                              "每个点是一首曲子；点大小表示打标所属角色数量。仅纳入当前届存在曲子和角色公开指标的关系。")
        chart["table_headers"] = ["曲子", "曲子官方名次", METRIC_LABELS.get(x_field, x_field),
                                   f"所属角色平均{METRIC_LABELS.get(y_field, y_field)}", "所属角色数量"]
        chart["table_rows"] = table
        chart["x_format"] = metric_axis_format(x_field)
        chart["y_format"] = "number"  # y is an average across linked characters
        chart["cross_kind"] = "music_character"
        return chart

    def build_character_music_covote(self, spec, config):
        """Plot the official conditional character→music intersections.

        The source publishes only the top conditional music choices for each
        character.  We keep the source's coverage boundary visible and never
        fill unreported pairs with zero.
        """
        round_label = normalize_round_label(config.get("current_round", "JP22"))
        rank_start = max(1, integer(config.get("rank_start", 1), 1))
        rank_end = max(rank_start, integer(config.get("rank_end", 100), 100))
        query = str(config.get("search", "")).strip().casefold()
        rows = []
        for row in self.character_music_covote_by_round.get(round_label, []):
            rank = integer(row.get("character_rank"), 999999)
            if not rank_start <= rank <= rank_end:
                continue
            label = f"{row.get('character_name_cn') or row.get('character_name_jp')} × {row.get('music_name_cn') or row.get('music_name_jp')}"
            if query and query not in f"{label} {row.get('character_name_jp','')} {row.get('music_name_jp','')}".casefold():
                continue
            if row.get("intersection_count") is None and row.get("conditional_rate") is None:
                continue
            rows.append(row)
        rows.sort(key=lambda row: number(row.get("intersection_count"), 0), reverse=True)
        rows = rows[: max(1, integer(config.get("top_n", 20), 20))]
        points, table = [], []
        for row in rows:
            count = number(row.get("intersection_count"), None)
            rate = number(row.get("conditional_rate"), None)
            if count is None or rate is None:
                continue
            label = f"{row.get('character_name_cn') or row.get('character_name_jp')} × {row.get('music_name_cn') or row.get('music_name_jp')}"
            points.append({"label": label, "x": count, "y": rate, "size": max(number(row.get("lift"), 0), 0),
                           "subtitle": f"{count:,.0f}人｜{rate * 100:.2f}%"})
            table.append([row.get("character_name_cn") or row.get("character_name_jp"),
                          row.get("music_name_cn") or row.get("music_name_jp"), count, rate,
                          row.get("music_overall_rate"), row.get("lift")])
        chart = self._scatter(spec.title, points, "同投人数", "角色条件下同投率", "percent_y",
                              "同投人数为官方角色详情中的条件交叉计数；同投率=P(曲子|角色)。仅显示官方公开的条件排行，未公开的角色—曲子组合不是0。")
        chart["x_format"] = "integer"
        chart["y_format"] = "percent"
        chart["table_headers"] = ["角色", "曲子", "同投人数", "角色条件下同投率", "曲子总体选择率", "连带倍数"]
        chart["table_rows"] = table
        chart["cross_kind"] = "character_music_covote"
        chart["coverage"] = "JP17–22"
        return chart

    def build_character_carryover(self, spec, config):
        """Summarise tag-based role→music carryover without causal claims."""
        round_label = normalize_round_label(config.get("current_round", "JP22"))
        characters = {self.entity_key(row): row for row in self.filtered_characters(config)}
        grouped = defaultdict(list)
        for link in self._cross_link_rows(round_label):
            if link.get("music_selection_rate") is not None:
                grouped[link.get("character_canonical", "")].append(number(link.get("music_selection_rate")))
        points, table = [], []
        for key, character in characters.items():
            values = grouped.get(key, [])
            avg = self._mean(values)
            own = number(character.get("selection_rate"), None)
            if avg is None or own in (None, 0):
                continue
            count = len(values)
            index = avg / own
            label = self.name(character, config)
            points.append({"label": label, "x": own, "y": avg, "size": count,
                           "subtitle": f"{count}首｜连带倍数 {index:.2f}×"})
            table.append([label, character.get("rank"), own, avg, count, index])
        points.sort(key=lambda point: point["y"], reverse=True)
        points = points[: max(1, integer(config.get("top_n", 20), 20))]
        shown = {point["label"] for point in points}
        table = [row for row in table if row[0] in shown]
        chart = self._scatter(spec.title, points, "角色选择率", "关联曲平均选择率", "percent_y",
                              "关联曲来自根目录的打标表；连带倍数=关联曲平均选择率÷角色选择率。它描述关联强弱，不证明角色人气造成曲子人气。")
        chart["x_format"] = "percent"
        chart["y_format"] = "percent"
        chart["table_headers"] = ["角色", "官方名次", "角色选择率", "关联曲平均选择率", "关联曲数量", "角色连带指数"]
        chart["table_rows"] = table
        chart["cross_kind"] = "character_carryover"
        return chart

    def _relation_category(self, spec) -> str:
        return "music" if spec.key.startswith(("r04_", "r05_", "r06_")) else "character"

    def _relation_context(self, spec, config):
        category = self._relation_category(spec)
        round_label = normalize_round_label(config.get("current_round", "JP22"))
        # Questionnaire relationships are entity-level analyses.  A rank
        # window such as 21–40 is not a meaningful definition of an audience
        # group, so relation templates always use all entities and leave rank
        # filtering to the optional search field.
        entity_config = {**config, "rank_start": 1, "rank_end": 1000000}
        metric_rows = self.filtered_music(entity_config) if category == "music" else self.filtered_characters(entity_config)
        metric_rows, _filtered_count, _missing_votes = self._filter_min_entity_votes(metric_rows, config)
        metric_by_key = {self.entity_key(row): row for row in metric_rows}
        question = config.get("relation_question", "sex")
        answer = config.get("relation_answer", "女性")
        question_rows = [
            row for row in self.entity_questionnaire_by_round_category[(round_label, category)]
            if row.get("question_key") == question and (not answer or row.get("answer_label") == answer)
        ]
        return category, round_label, metric_by_key, question_rows, question, answer

    def build_character_cognition(self, spec, config):
        answers = self.entity_question_answers(config.get("current_round", "JP22"), "character", "cognition")
        selected = config.get("relation_answer")
        if selected not in answers:
            selected = next((item for item in answers if item), "")
        return self.build_entity_question_scatter(spec, {**config, "relation_question": "cognition", "relation_answer": selected})

    def build_work_question_matrix(self, spec, config):
        round_label = normalize_round_label(config.get("current_round", "JP22"))
        question = config.get("relation_question", "cognition")
        rows = [row for row in self.entity_questionnaire_by_round_category.get((round_label, "work"), [])
                if row.get("question_key") == question and row.get("rate") is not None]
        if not rows:
            return self._heatmap(spec.title, [], [], [], "percent", "当前届没有公开的作品—问卷交叉数据；缺失不是0。")
        answers = sorted(
            dict.fromkeys(row.get("answer_label", "") for row in rows),
            key=lambda value: self.question_answer_sort_key(question, value),
        )
        entity_keys = list(dict.fromkeys((row.get("entity_name", ""), row.get("entity_id", "")) for row in rows))
        # Work matrices are release-oriented: a popular title's current rank
        # must not move it above an older/newer work.  The catalogue order is
        # stable across rounds; unknown titles are kept at the end.
        entity_keys.sort(key=lambda item: (self.work_release_order(item[0], item[1]), integer(item[1], 999999), item[0]))
        entity_keys = entity_keys[: max(1, integer(config.get("top_n", 20), 20))]
        entities = [self.work_name(name, entity_id, config.get("language", "cn")) for name, entity_id in entity_keys]
        lookup = {(row.get("entity_name", ""), row.get("entity_id", ""), row.get("answer_label", "")): number(row.get("rate"), None) for row in rows}
        matrix = [[lookup.get((name, entity_id, answer)) for answer in answers] for name, entity_id in entity_keys]
        labels = [self.question_answer_display(question, answer, config.get("language", "cn")) for answer in answers]
        chart = self._heatmap(f"作品 × {questionnaire_label(question, entity=True)}｜选项比例", entities, labels, matrix, "percent",
                              "每行是一部作品、每列是问卷选项比例；作品按发布时间目录顺序排列，不按人气名次或字母排序。空白格表示该题/作品没有公开数据，不是0。")
        chart["heatmap_kind"] = "work_question_matrix"
        chart["missing_hatch"] = True
        release_dates = [self.work_release_date(name, entity_id) or "未知" for name, entity_id in entity_keys]
        chart["table_headers"] = ["作品", "发布时间"] + labels
        chart["table_rows"] = [[entity, release_date] + values for entity, release_date, values in zip(entities, release_dates, matrix)]
        chart["work_question"] = question
        return chart

    def build_entity_question_matrix(self, spec, config):
        category = "music" if spec.key == "r10_music_question_matrix" else "character"
        round_label = normalize_round_label(config.get("current_round", "JP22"))
        question = config.get("relation_question", "age")
        rows = [row for row in self.entity_questionnaire_by_round_category.get((round_label, category), [])
                if row.get("question_key") == question and row.get("rate") is not None and row.get("answer_label")]
        if not rows:
            return self._heatmap(spec.title, [], [], [], "percent", "当前届没有公开的实体—问卷交叉数据；缺失不是0。")
        answers = sorted(
            dict.fromkeys(row.get("answer_label", "") for row in rows),
            key=lambda value: self.question_answer_sort_key(question, value),
        )
        metric_rows = self.music_by_round.get(round_label, []) if category == "music" else self.character_by_round.get(round_label, [])
        metric_rows, filtered_count, missing_votes = self._filter_min_entity_votes(metric_rows, config)
        metric_by_key = {self.entity_key(row): row for row in metric_rows}
        keys = list(dict.fromkeys(row.get("canonical_name", "") for row in rows if row.get("canonical_name")))
        keys.sort(key=lambda key: number(metric_by_key.get(key, {}).get("rank"), 999999))
        keys = keys[: max(1, integer(config.get("top_n", 20), 20))]
        names = [self.name(metric_by_key[key], config) if key in metric_by_key else key for key in keys]
        lookup = {(row.get("canonical_name", ""), row.get("answer_label", "")): number(row.get("rate"), None) for row in rows}
        matrix = [[lookup.get((key, answer)) for answer in answers] for key in keys]
        labels = [self.question_answer_display(question, answer, config.get("language", "cn")) for answer in answers]
        threshold = max(0, integer(config.get("min_entity_votes", 0), 0))
        filter_note = ""
        if threshold > 0:
            filter_note = f" 已按实体实际选择人数≥{threshold}过滤，排除{filtered_count}个实体。"
            if missing_votes:
                filter_note += " 缺失实体选择人数的实体会被排除。"
        chart = self._heatmap(f"{'曲子' if category == 'music' else '角色'} × {questionnaire_label(question, entity=True)}｜比例矩阵", names, labels, matrix, "percent",
                              "每行是一个实体，每列是所选问卷问题的一个选项。颜色表示该实体支持者/听众中的比例；各行有效人数可能不同，空白不是0。" + filter_note)
        chart.update({"heatmap_kind": "entity_question_matrix", "missing_hatch": True,
                      "table_headers": ["名称"] + labels,
                      "table_rows": [[name] + values for name, values in zip(names, matrix)]})
        return chart

    def build_entity_question_scatter(self, spec, config):
        category, round_label, metric_by_key, question_rows, question, answer = self._relation_context(spec, config)
        metric = config.get("x_metric", "rank")
        valid_fields = MUSIC_FIELDS if category == "music" else CHARACTER_FIELDS
        if metric not in valid_fields:
            metric = "rank"
        mode = config.get("relation_value_mode", "rate")
        points = []
        table = []
        for qrow in question_rows:
            mrow = metric_by_key.get(qrow.get("canonical_name", ""))
            if not mrow or mrow.get(metric) is None or qrow.get("rate") is None:
                continue
            if mode == "difference":
                # CN10/11 advanced rows currently publish the conditional
                # rate and cohort denominator, but not a precomputed overall
                # rate/difference. Do not coerce the missing value to 0: that
                # was the source of the screenshot's artificial 0–1 band.
                if qrow.get("difference_points") is None:
                    continue
                y = number(qrow.get("difference_points"), None)
            else:
                y = number(qrow.get("rate"), None)
            if y is None:
                continue
            # Use the number of respondents represented by this answer as the
            # horizontal variable.  The previous implementation used the
            # entity's total vote count, which is constant when the answer
            # selector changes and makes the relationship look like vertical
            # jitter only.
            x_value = number(qrow.get("count"), None)
            if x_value is None:
                continue
            label = self.name(mrow, config)
            points.append({"label": label, "x": x_value, "y": y,
                           "rate": number(qrow.get("rate"), 0),
                           "difference": number(qrow.get("difference_points"), 0),
                           "size": max(number(qrow.get("denominator"), 0), 0),
                           "subtitle": f"{x_value:,.0f}人｜{number(qrow.get('rate')) * 100:.2f}%"})
            table.append([label, mrow.get("rank"), mrow.get(metric), qrow.get("count"), qrow.get("rate"), qrow.get("overall_rate"), qrow.get("difference_points"), qrow.get("denominator")])
        relation_sort = config.get("relation_sort", "count")
        if relation_sort == "rate":
            points = sorted(points, key=lambda point: point.get("rate", 0), reverse=True)
        elif relation_sort == "difference":
            points = sorted(points, key=lambda point: abs(point.get("difference", 0)), reverse=True)
        else:
            points = sorted(points, key=lambda point: point["x"], reverse=True)
        points = points[: integer(config.get("top_n", 20), 20)]
        allowed = {point["label"] for point in points}; table = [row for row in table if row[0] in allowed]
        y_label = METRIC_LABELS["difference_points"] if mode == "difference" else METRIC_LABELS["question_rate"]
        value_format = "percent_y" if mode != "difference" else "auto"
        note = f"{round_label}｜{questionnaire_label(question, entity=True)}：{entity_answer_label(answer)}；实体问卷关联按地区/届次使用实际公开题目与选项，CN2–11 与 JP17–22 的题目集合不同。"
        threshold = max(0, integer(config.get("min_entity_votes", 0), 0))
        if threshold > 0:
            note += f" 已过滤实体实际选择人数低于{threshold}的角色/曲子（缺失人数也不纳入）。"
        if "rank" in metric: note += " 名次数值越小代表越受欢迎，因此相关方向与‘人气高低’相反。"
        note += " 横轴为所选问卷选项对应的受访人数，纵轴为该选项比例，点大小为该题有效问卷人数；投票指标保留在结果表中。"
        x_reference = sorted((point["x"] for point in points))[len(points) // 2] if points else None
        y_reference = sorted((point["y"] for point in points))[len(points) // 2] if points else None
        # Do not show the official rank twice when rank is also the selected
        # voting metric.  For other metrics retain both rank and metric value
        # so the table makes the comparison basis explicit.
        metric_label = METRIC_LABELS.get(metric, metric)
        if metric == "rank":
            table_headers = ["名称", "名次", "该选项人数", "该实体比例", "全体比例", "相差百分点", "问卷有效人数"]
            table = [[row[0], row[1], *row[3:]] for row in table]
        else:
            table_headers = ["名称", "官方名次", f"投票指标：{metric_label}", "该选项人数", "该实体比例", "全体比例", "相差百分点", "问卷有效人数"]
        return {"title": spec.title, "chart_type": "scatter", "points": points, "x_label": "问卷选项对应人数", "y_label": y_label, "value_format": value_format, "x_format": "integer", "y_format": "percent" if mode != "difference" else "number", "x_reference": x_reference, "y_reference": y_reference, "reference_label": "当前结果中位数", "table_headers": table_headers, "table_rows": table, "note": note}

    def build_entity_question_difference(self, spec, config):
        category, round_label, metric_by_key, question_rows, question, answer = self._relation_context(spec, config)
        rows = []
        for qrow in question_rows:
            mrow = metric_by_key.get(qrow.get("canonical_name", ""))
            if mrow and qrow.get("difference_points") is not None:
                rows.append({"label": self.name(mrow, config), "value": qrow["difference_points"]})
        rows = self._limit_sort(rows, config, absolute=True)
        note = f"{round_label}｜{questionnaire_label(question, entity=True)}：{entity_answer_label(answer)}；正数表示高于全体比例，单位为百分点。"
        threshold = max(0, integer(config.get("min_entity_votes", 0), 0))
        if threshold > 0:
            note += f" 已过滤实体实际选择人数低于{threshold}的角色/曲子（缺失人数也不纳入）。"
        return self._categorical(spec.title, rows, [(METRIC_LABELS["difference_points"], "value")], value_format="decimal", note=note)

    def build_entity_question_correlation(self, spec, config):
        category, round_label, metric_by_key, question_rows, question, _answer = self._relation_context(spec, {**config, "relation_answer": ""})
        metric = config.get("x_metric", "rank")
        valid_fields = MUSIC_FIELDS if category == "music" else CHARACTER_FIELDS
        if metric not in valid_fields:
            metric = "rank"
        grouped = defaultdict(list)
        for qrow in question_rows:
            mrow = metric_by_key.get(qrow.get("canonical_name", ""))
            if mrow and mrow.get(metric) is not None and qrow.get("rate") is not None:
                grouped[qrow.get("answer_label", "")].append((number(mrow[metric]), number(qrow["rate"])))
        rows = []
        for answer, values in grouped.items():
            value = pearson(values)
            if value is not None:
                rows.append({"label": entity_answer_label(answer), "value": value, "n": len(values)})
        rows = sorted(rows, key=lambda row: abs(row["value"]), reverse=True)
        note = f"{round_label}｜{questionnaire_label(question, entity=True)}；N 为参与相关计算的实体数。相关不代表因果。"
        threshold = max(0, integer(config.get("min_entity_votes", 0), 0))
        if threshold > 0:
            note += f" 相关计算前已过滤实体实际选择人数低于{threshold}的角色/曲子（缺失人数也不纳入）。"
        if "rank" in metric: note += " 名次数值越小代表越受欢迎，解读相关系数方向时需反向理解。"
        chart = self._categorical(spec.title, rows, [(METRIC_LABELS["correlation"], "value")], value_format="decimal", note=note)
        chart["table_headers"] = ["问卷选项", METRIC_LABELS["correlation"], "实体数 N"]
        chart["table_rows"] = [[row["label"], row["value"], row["n"]] for row in rows]
        return chart

    def character_metric_for_template(self, key: str, config: dict) -> tuple[str, str]:
        mapping = {
            "c02_selection_top": ("selection_count", "number"), "c03_primary_rate": ("primary_rate", "percent"),
            "c04_secondary_rate": ("secondary_rate", "percent"), "c05_top2_rate": ("top2_rate", "percent"),
        }
        return mapping.get(key, (config.get("y_metric", "selection_count"), "number"))

    def build_character_metric(self, spec, config):
        field, value_format = self.character_metric_for_template(spec.key, config)
        rows = [{"label": self.name(row, config), "value": row.get(field)} for row in self.filtered_characters(config) if row.get(field) is not None]
        rows = self._limit_sort(rows, config)
        return self._categorical(spec.title, rows, [(METRIC_LABELS.get(field, field), "value")], value_format=value_format)

    def build_score_rule(self, spec, config):
        # The old 2:1 score was not published for every round (notably JP22).
        # Keep the official/equal-rank comparison usable whenever those two
        # values exist, and add the legacy series whenever it is available for
        # at least one displayed row.  Missing historical data must not make
        # the whole template appear unsupported.
        rows = [r for r in self.filtered_characters(config)
                if r.get("rank") is not None and r.get("equal_rank") is not None]
        rows = sorted(rows, key=lambda r: number(r.get("rank")))[: integer(config.get("top_n", 20), 20)]
        formatted = [{"label": self.name(r, config), "official": r.get("rank"), "equal": r.get("equal_rank"), "old": r.get("old_2_1_rank")} for r in rows]
        series = [("官方规则", "official"), ("等权票数", "equal")]
        note = "数值越小名次越高；按当前届实际公开的排名规则显示。"
        if formatted and any(r.get("old") is not None for r in formatted):
            series.append(("旧2/1", "old"))
            if any(r.get("old") is None for r in formatted):
                note += " 旧2/1规则仅对部分角色公开，缺失行留空。"
        else:
            note += " 当前届未完整公开旧2/1规则名次，已隐藏该系列。"
        return self._categorical(spec.title, formatted, series, chart_type="grouped", note=note)

    def build_character_change(self, spec, config):
        field_map = {
            "c03_primary_rate_change": ("primary_rate", "percent"), "c06_primary_change": ("primary_count", "number"),
            "c07_selection_change": ("selection_count", "number"), "c07_selection_yoy": ("selection_count", "percent_yoy"),
            "c08_points_change": ("points", "number"), "c09_selection_rate_change": ("selection_rate", "percent"),
        }
        field, value_format = field_map[spec.key]
        previous = {self.entity_key(r): r for r in self.filtered_characters(config, config.get("compare_round", "JP21"))}
        rows = []
        for row in self.filtered_characters(config):
            prev = previous.get(self.entity_key(row))
            if not prev or row.get(field) is None or prev.get(field) is None:
                continue
            if value_format == "percent_yoy":
                value = number(row[field]) / number(prev[field]) - 1 if number(prev[field]) else 0
                fmt = "percent"
            else:
                value = number(row[field]) - number(prev[field])
                fmt = value_format
            rows.append({"label": self.name(row, config), "value": value})
        rows = self._limit_sort(rows, config, absolute=True)
        note = "两届计分规则不同，官方分数变化不能视为统一尺度。" if spec.key == "c08_points_change" else "当前届减去对比届。"
        return self._categorical(spec.title, rows, [("变化", "value")], value_format=fmt if rows else "number", note=note)

    def build_growth_lag(self, spec, config):
        previous = {self.entity_key(r): r for r in self.filtered_characters(config, config.get("compare_round", "JP21"))}
        points = []
        for row in self.filtered_characters(config):
            prev = previous.get(self.entity_key(row))
            if not prev:
                continue
            x = number(row["selection_count"]) - number(prev["selection_count"])
            y = number(row["selection_rate"]) - number(prev["selection_rate"])
            if x > 0 and y < 0:
                points.append({"label": self.name(row, config), "x": x, "y": y})
        points = sorted(points, key=lambda p: p["x"], reverse=True)[: integer(config.get("top_n", 20), 20)]
        chart = self._scatter(spec.title, points, "实际选择人数变化", "选择率变化", "percent_y", "人数增加但没有跑赢总票池增长。")
        chart["x_format"] = "integer"
        chart["y_format"] = "percent"
        return chart

    def build_vote_structure(self, spec, config):
        # JP3–20 (and the older CN rounds) publish first-choice and
        # non-first-choice totals, but not a separately identified second
        # choice.  JP21+ has the genuine three-way breakdown.  Require only
        # the fields needed by the available representation and never turn a
        # missing second-choice value into a fabricated zero.
        rows = [r for r in self.filtered_characters(config)
                if r.get("selection_count") is not None and r.get("primary_count") is not None]
        rows = sorted(rows, key=lambda r: number(r["rank"]))[: integer(config.get("top_n", 20), 20)]
        if not rows:
            return self._categorical(spec.title, [], [("第一顺位", "primary")], value_format="percent", chart_type="stacked", note="当前筛选没有同时公开实际选择人数和第一顺位票。")

        has_secondary = all(r.get("secondary_count") is not None for r in rows)
        has_other = all(r.get("other_count") is not None for r in rows)
        # A few source tables omit an explicit remainder even though total
        # selections and first/second counts are present; derive it only from
        # those published counts.  For old rounds without second-choice data,
        # the remainder is total minus first choice and is labelled as such.
        if has_secondary and not has_other:
            for row in rows:
                row["_structure_other"] = number(row.get("selection_count")) - number(row.get("primary_count")) - number(row.get("secondary_count"))
            other_field = "_structure_other"
            has_other = True
            other_derived = True
        elif not has_secondary and has_other:
            other_field = "other_count"
            other_derived = False
        elif not has_secondary and not has_other:
            for row in rows:
                row["_structure_other"] = number(row.get("selection_count")) - number(row.get("primary_count"))
            other_field = "_structure_other"
            has_other = True
            other_derived = True
        else:
            other_field = "other_count"
            other_derived = False

        formatted = []
        for row in rows:
            total = number(row.get("selection_count")) or 1
            item = {"label": self.name(row, config), "primary": number(row.get("primary_count")) / total,
                    "other": number(row.get(other_field)) / total}
            if has_secondary:
                item["secondary"] = number(row.get("secondary_count")) / total
            formatted.append(item)
        if has_secondary:
            series = [("第一顺位", "primary"), ("第二顺位", "secondary"), ("其余顺位", "other")]
            note = "三段结构按实际选择人数归一化。"
            if other_derived:
                note += " 其余顺位为实际选择人数减去第一、第二顺位票的推导值。"
        else:
            series = [("第一顺位", "primary"), ("非第一顺位（未细分第二顺位）", "other")]
            note = "当前届未公开单独的第二顺位票，图中以第一顺位与非第一顺位两段展示；非第一顺位不是第二顺位的替代零值。"
            if other_derived:
                note += " 非第一顺位由实际选择人数减去第一顺位票推导。"
        chart = self._categorical(spec.title, formatted, series, value_format="percent", chart_type="stacked", note=note)
        if not has_secondary:
            chart["title"] = "第一/非第一顺位结构（该届未细分第二顺位）"
        chart["structure_detail"] = "three_way" if has_secondary else "first_vs_non_first"
        return chart

    def build_character_heatmap(self, spec, config):
        rows = sorted(self.filtered_characters(config), key=lambda r: number(r["rank"]))[: integer(config.get("top_n", 20), 20)]
        preferred = ["points", "selection_count", "primary_count", "primary_rate", "secondary_rate", "top2_rate", "selection_rate"]
        # A metric remains useful when only part of a historical table
        # publishes it.  Keep the column and mark unavailable cells as blank
        # instead of dropping the entire metric because one entity is missing.
        fields = [field for field in preferred if any(row.get(field) is not None for row in rows)]
        ranked = {field: {} for field in fields}
        for field in fields:
            order = [row for row in rows if row.get(field) is not None]
            order = sorted(order, key=lambda r: number(r.get(field), -1), reverse=True)
            for idx, row in enumerate(order, 1):
                ranked[field][id(row)] = idx
        matrix = [[ranked[field].get(id(row)) for field in fields] for row in rows]
        labels = [self.name(row, config) for row in rows]
        columns = [METRIC_LABELS[field] for field in fields]
        chart = self._heatmap(spec.title, labels, columns, matrix, "rank", "每列单独排名；颜色越深、数字越小，表示该角色在该项指标中越突出。")
        chart.update({"heatmap_kind": "ranked_metrics", "color_direction": "low", "missing_hatch": True})
        chart["note"] = (chart.get("note", "") + " 未公开的实体指标保留为空白格，不参与该列排名。")
        return chart

    def build_gender_structure(self, spec, config):
        rows = [r for r in self.filtered_characters(config)
                if r.get("male_rate") is not None and r.get("female_rate") is not None]
        rows = sorted(rows, key=lambda r: number(r["rank"]))[: integer(config.get("top_n", 20), 20)]
        formatted = [{"label": self.name(r, config), "male": r.get("male_rate"), "female": r.get("female_rate"), "other": r.get("other_gender_rate")} for r in rows]
        has_other = bool(formatted) and all(r.get("other") is not None for r in formatted)
        series = [("男性", "male"), ("女性", "female")]
        note = "按当前届实际公开的性别比例展示。"
        if has_other:
            series.append(("其他", "other"))
        else:
            note += " 当前届未完整公开‘其他性别’比例，已隐藏该系列。"
        return self._categorical(spec.title, formatted, series, value_format="percent", chart_type="stacked", note=note)

    def build_gender_lean(self, spec, config):
        rows = []
        for row in self.filtered_characters(config):
            if row.get("female_rate") is not None and row.get("overall_female_rate") is not None:
                rows.append({"label": self.name(row, config), "value": number(row["female_rate"]) - number(row["overall_female_rate"])})
        rows = self._limit_sort(rows, config, absolute=True)
        return self._categorical(spec.title, rows, [("女性比例－全体女性比例", "value")], value_format="percent", note="正数更偏女性；负数相对更偏男性。")

    def build_gender_change(self, spec, config):
        previous = {self.entity_key(r): r for r in self.filtered_characters(config, config.get("compare_round", "JP21"))}
        rows = []
        for row in self.filtered_characters(config):
            prev = previous.get(self.entity_key(row))
            if prev and row.get("female_rate") is not None and prev.get("female_rate") is not None:
                rows.append({"label": self.name(row, config), "value": number(row["female_rate"]) - number(prev["female_rate"])})
        rows = self._limit_sort(rows, config, absolute=True)
        return self._categorical(spec.title, rows, [("女性比例变化", "value")], value_format="percent")

    def _matrix_entities(self, config: dict) -> list[dict]:
        return sorted(self.filtered_characters(config), key=lambda r: number(r["rank"]))[: min(integer(config.get("top_n", 20), 20), 30)]

    def _build_covote_matrix(self, spec, config, field: str):
        entities = self._matrix_entities(config)
        names = [normalize_name(r["name_jp"]) for r in entities]
        labels = [f"#{integer(r.get('rank'))} {self.name(r, config)}" for r in entities]
        pair_map = {}
        for pair in self.filtered_pairs(config, apply_minimum=False):
            pair_map[tuple(sorted((normalize_name(pair["name_a"]), normalize_name(pair["name_b"]))))] = pair
        matrix = []
        anomaly_cells = []
        for row_index, row_name in enumerate(names):
            values = []
            for col_index, col_name in enumerate(names):
                if row_name == col_name:
                    values.append(None)
                    continue
                key = tuple(sorted((row_name, col_name)))
                pair = pair_map.get(key)
                if not pair:
                    values.append(None)
                elif field == "intersection_count":
                    values.append(number(pair[field]))
                elif row_name == normalize_name(pair["name_a"]):
                    values.append(number(pair["direction_a_to_b"]))
                else:
                    values.append(number(pair["direction_b_to_a"]))
                if pair and (str(pair.get("anomaly", "")).lower() == "true" or number(pair.get("anomaly_difference")) > 0):
                    anomaly_cells.append([row_index, col_index])
            matrix.append(values)
        fmt = "percent" if field != "intersection_count" else "number"
        chart = self._heatmap(spec.title, labels, labels, matrix, fmt, "斜线格表示官网未公开（不是0）；深色对角线不参与统计；橙色边框标记双向人数冲突。")
        chart.update({
            "heatmap_kind": "direction_matrix" if field != "intersection_count" else "count_matrix",
            "diagonal_cells": [[idx, idx] for idx in range(len(labels))],
            "anomaly_cells": anomaly_cells,
            "missing_hatch": True,
        })
        return chart

    def build_covote_matrix_rate(self, spec, config):
        return self._build_covote_matrix(spec, config, "direction_rate")

    def build_covote_matrix_count(self, spec, config):
        return self._build_covote_matrix(spec, config, "intersection_count")

    def build_covote_network(self, spec, config):
        entities = self._matrix_entities(config)
        allowed = {normalize_name(r["name_jp"]): r for r in entities}
        nodes = [{"id": normalize_name(r["name_jp"]), "label": self.name(r, config), "value": number(r["selection_count"]), "rank": number(r["rank"])} for r in entities]
        edges = []
        for pair in self.filtered_pairs(config):
            a, b = normalize_name(pair["name_a"]), normalize_name(pair["name_b"])
            if a in allowed and b in allowed:
                edges.append({"source": a, "target": b, "value": number(pair["intersection_count"]), "lift": number(pair["lift"]), "label": self.pair_label(pair, config)})
        edges = sorted(edges, key=lambda e: e["value"], reverse=True)[: max(integer(config.get("top_n", 20), 20) * 3, 20)]
        table = [[e["label"], e["value"], e["lift"]] for e in edges]
        return {"title": spec.title, "chart_type": "network", "nodes": nodes, "edges": edges, "table_headers": ["关系", "共同人数", "集中倍数"], "table_rows": table, "value_format": "number", "note": "节点为角色；边宽表示共同人数，颜色深浅表示集中倍数。"}

    def build_concentration_clusters(self, spec, config):
        """Cluster heterogeneous co-vote edges using an auditable rule.

        For an edge (A, B), ``lift = observed_intersection / expected`` is
        already computed in the source table. We retain edges with at least
        ``min_count`` respondents and lift >= 1.20, then compute connected
        components (single-link clustering). Components are ranked by the
        sum of positive excess counts, with node/edge counts exposed in the
        result table. This avoids pretending that a CP label is a cluster and
        keeps role×music provenance explicit.
        """
        round_label = normalize_round_label(config.get("current_round", "JP22"))
        min_count = max(1, integer(config.get("min_count", 100), 100))
        lift_threshold = number(config.get("lift_threshold", 1.20), 1.20)
        edges = []
        music_internal = spec.key == "a18_music_concentration_clusters"
        # Cross-department character→music rows use P(music|character) divided
        # by the corresponding music-department marginal. This normalization
        # is valid even when the two departments have different ballot totals.
        for row in ([] if music_internal else self.character_music_covote_by_round.get(round_label, [])):
            count = number(row.get("intersection_count"), None)
            lift = number(row.get("lift"), None)
            if count is None or lift is None or count < min_count or lift < lift_threshold:
                continue
            a = str(row.get("character_name_cn") or row.get("character_name_jp") or "").strip()
            b = str(row.get("music_name_cn") or row.get("music_name_jp") or "").strip()
            if not a or not b:
                continue
            # Derive the random-baseline expectation from the published lift
            # itself (E = observed / lift). Character/music detail pages may
            # use different valid-voter denominators, so multiplying the two
            # marginal counts by an assumed common ballot total would be
            # incorrect.
            expected = count / lift if lift > 0 else count
            edges.append({"a": f"角色:{a}", "b": f"曲子:{b}", "label": f"{a} × {b}", "count": count, "lift": lift,
                          "excess": max(0.0, count - expected)})
        # CN10/11 also expose complete music×music conditional matrices, but
        # keep these in their own template rather than mixing departments.
        for row in (self.pairs_by_round.get(round_label, []) if music_internal else []):
            if row.get("source_type") != "cn10_11_official_music_covote_matrix":
                continue
            count = number(row.get("intersection_count"), None)
            lift = number(row.get("lift"), None)
            if count is None or lift is None or count < min_count or lift < lift_threshold:
                continue
            a = str(row.get("name_a_cn") or row.get("name_a") or "").strip()
            b = str(row.get("name_b_cn") or row.get("name_b") or "").strip()
            if not a or not b:
                continue
            expected = count / lift if lift > 0 else count
            edges.append({"a": f"曲子:{a}", "b": f"曲子:{b}", "label": f"{a} × {b}", "count": count, "lift": lift,
                          "excess": max(0.0, count - expected)})
        if not edges:
            coverage = "音乐内部完整矩阵当前覆盖 CN10–11。" if music_internal else "角色×音乐交叉统计当前覆盖 CN10–11、JP17–22。"
            return {"title": spec.title, "chart_type": "network", "nodes": [], "edges": [],
                    "table_headers": ["聚类", "节点数", "关系数", "集中度得分"], "table_rows": [],
                    "value_format": "number", "note": f"{round_label} 没有达到共同人数≥{min_count} 且集中倍数≥{lift_threshold:.2f} 的公开同投关系。{coverage}"}
        parent = {}
        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]; x = parent[x]
            return x
        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb: parent[rb] = ra
        for edge in edges:
            union(edge["a"], edge["b"])
        groups = defaultdict(lambda: {"nodes": set(), "edges": [], "score": 0.0})
        for edge in edges:
            group = groups[find(edge["a"])]
            group["nodes"].update((edge["a"], edge["b"]))
            group["edges"].append(edge); group["score"] += edge["excess"]
        ordered = sorted(groups.values(), key=lambda g: (g["score"], len(g["edges"])), reverse=True)[:max(1, integer(config.get("top_n", 20), 20))]
        nodes = []
        out_edges = []
        table = []
        for index, group in enumerate(ordered, 1):
            cluster = f"C{index}"
            for node in group["nodes"]:
                nodes.append({"id": f"{cluster}:{node}", "label": node, "value": 1, "cluster": cluster})
            for edge in group["edges"]:
                out_edges.append({"source": f"{cluster}:{edge['a']}", "target": f"{cluster}:{edge['b']}", "value": edge["count"], "lift": edge["lift"], "label": edge["label"]})
            table.append([cluster, len(group["nodes"]), len(group["edges"]), group["score"]])
        scope = "音乐内部" if music_internal else "角色×音乐跨部门"
        note = (f"{round_label}｜{scope}集中聚类算法：保留共同人数≥{min_count}且 lift≥{lift_threshold:.2f} 的边；"
                "以边为相似关系做单链接连通分量，聚类得分=组件内 max(0,共同人数−期望人数) 之和。"
                "lift=实际共同人数/期望共同人数，期望人数由公开的 observed/lift 反推；组件不是官方CP榜，节点前缀‘角色/曲子’表示所属类别。"
                + ("" if music_internal else " 跨部门 lift 使用 P(音乐|角色且参与音乐部门)/P(音乐)，不假设两个部门的有效票总数相同。"))
        return {"title": spec.title, "chart_type": "network", "nodes": nodes, "edges": out_edges,
                "table_headers": ["聚类", "节点数", "关系数", "集中度得分"], "table_rows": table,
                "value_format": "number", "note": note}

    def build_covote_faceted_network(self, spec, config):
        round_label = normalize_round_label(config.get("current_round", "JP22"))
        characters = self.filtered_characters(config)
        selected_faction = self._selected_faction(config)
        formal_four = ["红魔馆", "地灵殿", "秘封俱乐部", "神灵庙"]
        panel_factions = [selected_faction] if selected_faction else formal_four
        group_names = {
            faction: [row.get("name_cn", "") for row in characters if faction in self.faction_labels_for_row(row)]
            for faction in panel_factions
        }
        pair_rows = self.filtered_pairs(config)
        panels = []
        all_table = []
        for panel_title, requested_names in group_names.items():
            by_cn = {normalize_name(row.get("name_cn", "")): row for row in characters}
            members = [by_cn[normalize_name(name)] for name in requested_names if normalize_name(name) in by_cn]
            allowed = {normalize_name(row.get("name_jp", "")): row for row in members}
            nodes = [
                {"id": key, "label": self.name(row, config), "value": number(row.get("selection_count")), "rank": number(row.get("rank"))}
                for key, row in allowed.items()
            ]
            edges = []
            for pair in pair_rows:
                a, b = normalize_name(pair.get("name_a", "")), normalize_name(pair.get("name_b", ""))
                if a not in allowed or b not in allowed:
                    continue
                edge = {
                    "source": a, "target": b, "value": number(pair.get("intersection_count")),
                    "lift": number(pair.get("lift")), "label": self.pair_label(pair, config),
                }
                edges.append(edge)
                all_table.append([panel_title, edge["label"], edge["value"], edge["lift"]])
            edges.sort(key=lambda edge: edge["lift"], reverse=True)
            panels.append({"title": panel_title, "nodes": nodes, "edges": edges, "strong_edges": edges[:3]})
        title = f"{round_label}｜{selected_faction + '阵营' if selected_faction else '四个代表角色群'}的内部同投网络"
        return {
            "title": title, "chart_type": "faceted_network",
            "panels": panels, "value_format": "number",
            "table_headers": ["阵营", "关系", "共同人数", "集中倍数"], "table_rows": all_table,
            "note": "每个阵营单独成图；默认展示红魔馆、地灵殿、秘封俱乐部、神灵庙，选择“原作阵营”后可切换到其他正式群体或作品首登 cohort。线条颜色和粗细按集中倍数分档。",
        }

    def build_covote_bubble(self, spec, config):
        pairs = [row for row in self.filtered_pairs(config) if row.get("lift") is not None and number(row.get("intersection_count")) > 0]
        limit = max(1, integer(config.get("top_n", 20), 20))
        selected = sorted(pairs, key=lambda row: number(row.get("intersection_count")), reverse=True)[:limit]
        high_lift = {id(row) for row in sorted(selected, key=lambda row: number(row.get("lift")), reverse=True)[: min(6, len(selected))]}
        high_count = {id(row) for row in selected[: min(4, len(selected))]}
        points = []
        for row in selected:
            count = number(row.get("intersection_count"))
            lift = number(row.get("lift"))
            points.append({
                "label": self.pair_label(row, config), "x": count, "y": lift,
                "size": max(0.0, number(row.get("phi"))),
                "highlight": id(row) in high_lift or id(row) in high_count,
                "anomaly": str(row.get("anomaly", "")).lower() == "true" or number(row.get("anomaly_difference")) > 0,
                "subtitle": f"{count:,.0f}人｜{lift:.2f}×",
            })
        return {
            "title": spec.title, "chart_type": "bubble", "points": points,
            "x_label": METRIC_LABELS["intersection_count"], "y_label": METRIC_LABELS["lift"],
            "x_log": True, "y_reference": 1.0, "value_format": "decimal",
            "table_headers": ["关系", "共同人数", "集中倍数", "φ", "异常"],
            "table_rows": [[point["label"], point["x"], point["y"], point["size"], "是" if point["anomaly"] else "否"] for point in points],
            "note": "越靠右共同人数越多，越靠上同投越集中；横轴为对数尺度，圆越大表示正向 φ 越高。",
        }

    def build_covote_dumbbell(self, spec, config):
        current_label = normalize_round_label(config.get("current_round", "JP22"))
        compare_label = normalize_round_label(config.get("compare_round", "JP21"))
        joined = self._pair_join(config)
        joined.sort(key=lambda pair: number(pair[0].get("intersection_count")), reverse=True)
        joined = joined[: max(1, integer(config.get("top_n", 20), 20))]
        rows = []
        anomaly_rows = []
        for index, (current, previous) in enumerate(joined):
            rows.append({
                "label": self.pair_label(current, config),
                "compare": previous.get("intersection_count"), "current": current.get("intersection_count"),
            })
            if any(str(item.get("anomaly", "")).lower() == "true" or number(item.get("anomaly_difference")) > 0 for item in (current, previous)):
                anomaly_rows.append(index)
        chart = self._categorical(
            spec.title, rows, [(compare_label, "compare"), (current_label, "current")],
            value_format="number", chart_type="dumbbell", note="仅比较两届均公开的同一角色关系；一行两个点，不会合并成同一根条。",
        )
        chart["anomaly_rows"] = anomaly_rows
        return chart

    def covote_metric_for_template(self, key: str, config: dict) -> tuple[str, str]:
        mapping = {
            "a03_count_top": ("intersection_count", "number"), "a14_count_top10": ("intersection_count", "number"),
            "a06_lift": ("lift", "decimal"), "a15_lift_top10": ("lift", "decimal"),
            "a07_excess": ("excess_count", "number"), "a08_phi": ("phi", "decimal"),
            "a11_asymmetry": ("asymmetry", "percent"),
        }
        return mapping.get(key, (config.get("y_metric", "intersection_count"), "number"))

    def build_covote_metric(self, spec, config):
        field, fmt = self.covote_metric_for_template(spec.key, config)
        rows = [{"label": self.pair_label(r, config), "value": r.get(field)} for r in self.filtered_pairs(config) if r.get(field) is not None]
        rows = self._limit_sort(rows, config)
        return self._categorical(spec.title, rows, [(METRIC_LABELS.get(field, field), "value")], value_format=fmt)

    def build_covote_metric_abs(self, spec, config):
        field, fmt = self.covote_metric_for_template(spec.key, config)
        rows = [{"label": self.pair_label(r, config), "value": abs(number(r.get(field)))} for r in self.filtered_pairs(config) if r.get(field) is not None]
        rows = self._limit_sort(rows, config)
        return self._categorical(spec.title, rows, [("方向比例差绝对值", "value")], value_format=fmt)

    def _covote_change_chart(self, spec, config, field: str, absolute=False):
        rows = []
        for current, previous in self._pair_join(config):
            rows.append({"label": self.pair_label(current, config), "value": number(current[field]) - number(previous[field])})
        rows = self._limit_sort(rows, config, absolute=True)
        fmt = "percent" if field == "share" else "decimal" if field in {"lift", "phi"} else "number"
        return self._categorical(spec.title, rows, [("变化", "value")], value_format=fmt, note="仅纳入两届均公开的关系。")

    def build_covote_change(self, spec, config):
        return self._covote_change_chart(spec, config, "intersection_count")

    def build_covote_change_abs(self, spec, config):
        return self._covote_change_chart(spec, config, "intersection_count", True)

    def build_covote_phi_change(self, spec, config):
        return self._covote_change_chart(spec, config, "phi")

    def build_covote_direction(self, spec, config):
        pairs = sorted(self.filtered_pairs(config), key=lambda r: abs(number(r["asymmetry"])), reverse=True)[: integer(config.get("top_n", 20), 20)]
        rows = [{"label": self.pair_label(r, config), "ab": r["direction_a_to_b"], "ba": r["direction_b_to_a"]} for r in pairs]
        return self._categorical(spec.title, rows, [("A→B", "ab"), ("B→A", "ba")], value_format="percent", chart_type="dumbbell")

    def build_covote_cumulative(self, spec, config):
        totals = defaultdict(float)
        names = {}
        for pair in self.filtered_pairs(config):
            if number(pair["excess_count"]) <= 0:
                continue
            for side in ("a", "b"):
                key = normalize_name(pair[f"name_{side}"])
                totals[key] += number(pair["excess_count"])
                names[key] = self.name(pair, config, side)
        rows = [{"label": names[key], "value": value} for key, value in totals.items()]
        rows = self._limit_sort(rows, config)
        return self._categorical(spec.title, rows, [("正向超额累计", "value")], value_format="number")

    def build_covote_quadrant(self, spec, config):
        points = []
        for current, previous in self._pair_join(config):
            points.append({"label": self.pair_label(current, config), "x": number(current["share"]) - number(previous["share"]), "y": number(current["lift"]) - number(previous["lift"])})
        points = sorted(points, key=lambda p: abs(p["x"]) + abs(p["y"]), reverse=True)[: max(integer(config.get("top_n", 20), 20), 20)]
        return self._scatter(spec.title, points, "同投占总盘比例变化", "集中倍数变化", "percent_x", "右上为规模与集中度都提高；左下为两者都下降。")

    def build_covote_anomaly(self, spec, config):
        rows = [{"label": self.pair_label(r, config), "value": r["anomaly_difference"]} for r in self.filtered_pairs(config, apply_minimum=False) if r.get("anomaly") == "true"]
        rows = self._limit_sort(rows, {**config, "top_n": max(integer(config.get("top_n", 20), 20), 50)})
        return self._categorical(spec.title, rows, [("双向人数差", "value")], value_format="number", note=f"当前筛选共 {len(rows)} 组；JP21 TOP100完整口径应为38组。")

    def _age_bin(self, label: str) -> tuple[int, str]:
        if label.startswith("～") or any(token in label for token in ("未满", "不到", "9岁以下", "10岁以下")):
            return (0, "9岁以下")
        match = re.search(r"(\d+)", label)
        if not match:
            return (999, label)
        age = int(match.group(1))
        if "以上" in label:
            return (60, "60岁以上")
        start = (age // 5) * 5
        if age < 10:
            return (0, "9岁以下")
        return (start, f"{start}–{start + 4}岁")

    def build_questionnaire_age(self, spec, config):
        current = normalize_round_label(config.get("current_round", "JP22"))
        compare = normalize_round_label(config.get("compare_round", "JP21"))
        by_option = defaultdict(dict)
        order = []
        for row in self.questionnaire:
            label_round = normalize_round_label(row.get("round_label") or row.get("round"))
            if row.get("question_key") != "age" or label_round not in {current, compare}:
                continue
            # Do not force CN and JP source ranges into artificial five-year
            # bins. A CN option such as 18–21 cannot be losslessly assigned
            # to either JP's 15–19 or 20–24 range. Equivalent labels are
            # translated and joined; genuinely different bins remain rows.
            label = self.question_answer_display("age", row.get("label", ""))
            if label not in order:
                order.append(label)
            by_option[label][label_round] = number(row.get("rate"), None)
        rows = [{"label": label, "current": by_option[label].get(current), "compare": by_option[label].get(compare)} for label in order]
        return self._categorical(
            "问题：年龄分布｜选项比例", rows, [(compare, "compare"), (current, "current")],
            value_format="percent", chart_type="dumbbell", note="问卷公开范围为 CN1–11 静态/现代汇总与 JP17–22；保留各地区、各届官网实际年龄选项。无法无损对齐的年龄段分行显示，空白不是0。",
        )

    def build_questionnaire(self, spec, config):
        if spec.key == "q02_cognition":
            question_key = "cognition"
        elif spec.key == "q03_usertype":
            question_key = "usertype"
        elif spec.key == "q04_new":
            question_key = config.get("question_key") if config.get("question_key") in {"th21", "parents"} else "th21"
        else:
            question_key = config.get("question_key", "age")
        if question_key == "age":
            return self.build_questionnaire_age(spec, config)
        current = normalize_round_label(config.get("current_round", "JP22"))
        compare = normalize_round_label(config.get("compare_round", "JP21"))
        selected_rows = []
        groups_by_label = defaultdict(set)
        for row in self.questionnaire:
            label_round = normalize_round_label(row.get("round_label") or row.get("round"))
            if row.get("question_key") != question_key or label_round not in {current, compare}:
                continue
            parts = str(row.get("node_path", "")).split("/")
            group = ""
            if "values" in parts:
                values_index = parts.index("values")
                group = "/".join(parts[1:values_index])
            selected_rows.append((row, label_round, group))
            groups_by_label[row.get("label", "")].add(group)
        if question_key in WORK_QUESTION_KEYS:
            # Work-valued options follow the shared release catalogue.  Other
            # options are retained after the known works and are never
            # mistaken for a title.
            selected_rows = sorted(
                enumerate(selected_rows),
                key=lambda item: (
                    self.question_answer_sort_key(question_key, item[1][0].get("label", "")),
                    item[0],
                ),
            )
            selected_rows = [item[1] for item in selected_rows]
        duplicate_labels = {label for label, groups in groups_by_label.items() if len(groups) > 1}
        by_option = defaultdict(dict)
        order = []
        displays = {}
        display_raws: dict[str, set[str]] = defaultdict(set)
        for row, label_round, group in selected_rows:
            label = row.get("label", "")
            option_key = (group, label) if label in duplicate_labels else ("", label)
            if option_key not in order:
                order.append(option_key)
            if option_key not in displays:
                display = self.question_answer_display(question_key, label)
                if option_key[0]:
                    group_label = "-".join(str(int(part) + 1) if part.isdigit() else part for part in option_key[0].split("/"))
                    display = f"第{group_label}组｜{display}"
                displays[option_key] = display
            # CN modern questionnaires use compact option text such as “男/女”,
            # while JP uses “男性/女性”.  They are deliberately kept as
            # separate source options; record raw variants so the combined
            # two-round view cannot render two indistinguishable labels.
            display_raws[displays[option_key]].add(str(label))
            by_option[option_key][label_round] = number(row.get("rate"))
        rows = [
            {"label": (f"{displays[key]}（原文：{key[1]}）" if len(display_raws[displays[key]]) > 1 else displays[key]),
             "compare": by_option[key].get(compare), "current": by_option[key].get(current)}
            for key in order
        ]
        title = questionnaire_label(question_key)
        grouping_note = " 重复选项按源数据分组编号区分。" if duplicate_labels else ""
        if any(len(values) > 1 for values in display_raws.values()):
            grouping_note += " 中日问卷即使译名相同也保留为独立选项，并在标签中标注原文。"
        return self._categorical(
            f"问题：{title}｜选项比例", rows, [(compare, "compare"), (current, "current")],
            value_format="percent", chart_type="dumbbell",
            note="问卷公开范围为 CN1–11 静态/现代汇总与 JP17–22；某届没有该题时留空（不当作0），多选题各项不要求合计100%。" + grouping_note,
        )

    def build_custom_character(self, spec, config):
        x_field = config.get("x_metric", "selection_count")
        y_field = config.get("y_metric", "primary_rate")
        if x_field not in CHARACTER_FIELDS:
            x_field = "selection_count"
        if y_field not in CHARACTER_FIELDS:
            y_field = "primary_rate"
        points = []
        for row in self.filtered_characters(config):
            if row.get(x_field) is not None and row.get(y_field) is not None:
                points.append({"label": self.name(row, config), "x": number(row[x_field]), "y": number(row[y_field])})
        points = points[: max(integer(config.get("top_n", 20), 20), 20)]
        chart = self._scatter(spec.title, points, METRIC_LABELS.get(x_field, x_field), METRIC_LABELS.get(y_field, y_field), "auto", "自定义指标；请留意不同计分制度的可比性。")
        chart["x_format"], chart["y_format"] = metric_axis_format(x_field), metric_axis_format(y_field)
        return chart

    def build_custom_covote(self, spec, config):
        x_field = config.get("x_metric", "intersection_count")
        y_field = config.get("y_metric", "lift")
        if x_field not in COVOTE_FIELDS:
            x_field = "intersection_count"
        if y_field not in COVOTE_FIELDS:
            y_field = "lift"
        points = []
        for row in self.filtered_pairs(config):
            if row.get(x_field) is not None and row.get(y_field) is not None:
                points.append({"label": self.pair_label(row, config), "x": number(row[x_field]), "y": number(row[y_field])})
        points = sorted(points, key=lambda p: p["x"], reverse=True)[: max(integer(config.get("top_n", 20), 20), 20)]
        chart = self._scatter(spec.title, points, METRIC_LABELS.get(x_field, x_field), METRIC_LABELS.get(y_field, y_field), "auto", "自定义同投指标。")
        chart["x_format"], chart["y_format"] = metric_axis_format(x_field), metric_axis_format(y_field)
        return chart

    def _scatter(self, title, points, x_label, y_label, value_format="auto", note=""):
        return {"title": title, "chart_type": "scatter", "points": points, "x_label": x_label, "y_label": y_label, "value_format": value_format, "table_headers": ["名称", x_label, y_label], "table_rows": [[p["label"], p["x"], p["y"]] for p in points], "note": note}

    def _heatmap(self, title, row_labels, col_labels, matrix, value_format, note=""):
        return {"title": title, "chart_type": "heatmap", "row_labels": row_labels, "col_labels": col_labels, "matrix": matrix, "value_format": value_format, "table_headers": ["名称"] + col_labels, "table_rows": [[label] + values for label, values in zip(row_labels, matrix)], "note": note}
