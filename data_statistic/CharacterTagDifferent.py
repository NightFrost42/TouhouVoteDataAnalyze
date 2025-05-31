import json
import numpy as np
import matplotlib.pyplot as plt

# -------------------------------
# （1） 读取并转换 data_cn.json 和 data_jp.json
#     请确认文件路径是否正确，例如：
#     如果在当前目录下，就写 "data_cn.json"、"data_jp.json"；
#     如果在子文件夹 data_statistic 下，则写 "data_statistic/data_cn.json" 等
# -------------------------------
with open("data_statistic/data_cn.json", "r", encoding="utf-8") as f:
    loaded_cn = json.load(f)
tag_rank_sessions_china = {
    int(session): {tag: float(value) for tag, value in tag_list}
    for session, tag_list in loaded_cn.items()
}

with open("data_statistic/data_jp.json", "r", encoding="utf-8") as f:
    loaded_jp = json.load(f)
tag_rank_sessions_japan = {
    int(session): {tag: float(value) for tag, value in tag_list}
    for session, tag_list in loaded_jp.items()
}

# -------------------------------
# （2） 指定要对比的中国区和日本区届数及阈值
# -------------------------------
cn_session = 11    # 中国区要对比的届数 (1–11)
jp_session = 20   # 日本区要对比的届数 (3–20)
threshold = 0.01  # 绝对差值阈值 (vote rate，以小数形式，例如 0.01 表示 1%)

# -------------------------------
# （3） 获取对应届的 tag->rate 映射
# -------------------------------
cn_rates = tag_rank_sessions_china.get(cn_session, {})
jp_rates = tag_rank_sessions_japan.get(jp_session, {})

# -------------------------------
# （4） 找出满足阈值差异的所有 tag，并计算“有向差值”（小数）
# -------------------------------
diff_list = []
all_tags = set(cn_rates.keys()).union(jp_rates.keys())

for tag in all_tags:
    cn_rate = cn_rates.get(tag, 0.0)
    jp_rate = jp_rates.get(tag, 0.0)
    diff = cn_rate - jp_rate  # 有向差值
    if abs(diff) >= threshold:
        diff_list.append((tag, cn_rate, jp_rate, diff))

# 按差值绝对值从大到小排序（可选）
diff_list.sort(key=lambda x: abs(x[3]), reverse=True)

# 如果没有满足条件的 tag，则提示
if not diff_list:
    print(f"在中国区第 {cn_session} 届和日本区第 {jp_session} 届中，没有 tag 的得票率差异 ≥ {threshold}")
else:
    # -------------------------------
    # （5） 分解信息，将差值转换为百分比，并准备绘图
    # -------------------------------
    tags = [item[0] for item in diff_list]
    # 将小数形式的差值乘以 100，得到百分比
    diffs_pct = [item[3] * 100 for item in diff_list]

    x = np.arange(len(tags))

    # 为正负差值分别指定颜色：正(中国区更高)为红色，负(日本区更高)为蓝色
    colors = ['tab:red' if d > 0 else 'tab:blue' for d in diffs_pct]

    # -------------------------------
    # （6） 绘制“差值百分比条形图”，并调大横向尺寸
    # -------------------------------
    plt.figure(figsize=(14, 6))  # 宽度设置为14，足够横向展开，避免标签重叠
    plt.rcParams['font.sans-serif'] = ['SimHei']  # 中文支持

    bars = plt.bar(x, diffs_pct, color=colors)

    # 在每个条形上方或下方标注百分比数值（保留两位小数）
    for bar, d in zip(bars, diffs_pct):
        height = bar.get_height()
        # 如果是正值，文字放在条形上方；如果是负值，文字放在条形下方
        if height >= 0:
            va, y_offset = 'bottom', 0.1
        else:
            va, y_offset = 'top', -0.1
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            height + y_offset,
            f"{d:.2f}%",  # 显示百分号
            ha='center',
            va=va,
            fontsize=8
        )

    plt.axhline(0, color='black', linewidth=0.8)  # 添加 y=0 的参考线
    plt.xlabel("标签 (Tag)")
    plt.ylabel("得票率差值 (中国区率 – 日本区率) [%]")
    plt.title(f"中日区 第{cn_session}届 vs 第{jp_session}届 得票率有向差值（|差| ≥ {threshold*100:.0f}%）")
    plt.xticks(x, tags, rotation=45, ha='right')
    plt.grid(axis='y', linestyle='--', alpha=0.6)
    plt.tight_layout()
    plt.show()
