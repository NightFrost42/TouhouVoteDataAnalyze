import json
import numpy as np
import matplotlib.pyplot as plt

# -------------------------------
# （1） 读取并转换 data_cn.json 和 data_jp.json
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
cn_session = 11     # 中国区要对比的届数 (1–11)
jp_session = 20     # 日本区要对比的届数 (3–20)
threshold = 0.001   # 绝对差值阈值 (现在是相对热度差值，范围通常在0-1之间)
top_n_tags = 30     # 新增：只显示差异最大的前 N 个标签，可根据需要调整

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
    diff = cn_rate - jp_rate    # 有向差值
    if abs(diff) >= threshold:
        diff_list.append((tag, cn_rate, jp_rate, diff))

# 按差值绝对值从大到小排序
diff_list.sort(key=lambda x: abs(x[3]), reverse=True)

# 如果指定了 top_n_tags，则只取前 N 个
if top_n_tags > 0:
    diff_list = diff_list[:top_n_tags]

# 如果没有满足条件的 tag，则提示
if not diff_list:
    print(f"在中国区第 {cn_session} 届和日本区第 {jp_session} 届中，没有 tag 的相对热度差异 ≥ {threshold:.3f} 或没有足够多的标签满足显示数量 ({top_n_tags})。")
else:
    # -------------------------------
    # （5） 分解信息，准备绘图
    # -------------------------------
    # 注意：为了水平条形图，这里需要反转列表，让最大的差异在图表上方显示
    tags = [item[0] for item in diff_list][::-1]
    # 不再乘以 100，直接使用 diff 值
    diffs = [item[3] for item in diff_list][::-1] 

    y = np.arange(len(tags)) # Y轴现在是标签的位置

    # 为正负差值分别指定颜色：正(中国区更高)为红色，负(日本区更高)为蓝色
    colors = ['tab:red' if d > 0 else 'tab:blue' for d in diffs] # 这里也使用 diffs

    # -------------------------------
    # （6） 绘制“差值条形图”，使用水平条形图
    # -------------------------------
    plt.figure(figsize=(10, len(tags) * 0.4 + 2)) # 根据标签数量动态调整图表高度
    plt.rcParams['font.sans-serif'] = ['SimHei']  # 中文支持

    # 使用 plt.barh 绘制水平条形图
    bars = plt.barh(y, diffs, color=colors) # 这里也使用 diffs

    # 在每个条形旁边标注数值（保留三位小数，因为是小数比例）
    for bar, d in zip(bars, diffs):
        x_val = bar.get_width() # 获取条形的宽度（即差值）
        y_val = bar.get_y() + bar.get_height() / 2 # 获取条形的中心Y坐标

        # 根据正负差值调整文本位置：正值文本在条形右侧，负值文本在条形左侧
        if x_val >= 0:
            ha, x_offset = 'left', 0.00 # 文本左对齐，稍偏右
        else:
            ha, x_offset = 'right', -0.00 # 文本右对齐，稍偏左
        
        plt.text(
            x_val + x_offset,
            y_val,
            f"{d:.3f}",  # 显示为三位小数
            ha=ha,
            va='center', # 垂直居中
            fontsize=8
        )

    plt.axvline(0, color='black', linewidth=0.8) # 添加 x=0 的参考线 (现在是垂直的)
    plt.ylabel("标签 (Tag)") # Y轴现在是标签
    # 更改 x 轴标签以反映“相对热度差值”
    plt.xlabel("相对热度差值 (中国区 – 日本区)") 
    
    title_suffix = f"（|差| ≥ {threshold:.3f}）" # 更改阈值显示格式
    if top_n_tags > 0:
        title_suffix = f"（差异最大前 {top_n_tags} 个，|差| ≥ {threshold:.3f}）"
    # 更改标题以反映“相对热度差值”
    plt.title(f"中日区 第{cn_session}届 vs 第{jp_session}届 标签相对热度有向差值{title_suffix}")
    
    # 设置 Y 轴刻度标签
    plt.yticks(y, tags)
    plt.grid(axis='x', linestyle='--', alpha=0.6) # 网格线现在是垂直的
    plt.tight_layout() # 自动调整布局，防止标签重叠
    plt.show()