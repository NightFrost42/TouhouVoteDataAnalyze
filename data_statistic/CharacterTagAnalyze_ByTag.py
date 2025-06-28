import json
import matplotlib.pyplot as plt
import numpy as np

TAG = "萝莉" # 你要分析的特定 Tag

with open("data_statistic/data_cn.json", "r", encoding="utf-8") as f:
    loaded_data = json.load(f)

# 将 list[list[key, value]] 转回 list[tuple[key, value]]
# 注意：这里的 value 已经是相对热度了
tag_rank_sessions_china = {
    int(session): [(tag, np.float64(value)) for tag, value in tag_list]
    for session, tag_list in loaded_data.items()
}

with open("data_statistic/data_jp.json", "r", encoding="utf-8") as f:
    loaded_data = json.load(f)

# 将 list[list[key, value]] 转回 list[tuple[key, value]]
# 注意：这里的 value 已经是相对热度了
tag_rank_sessions_japan = {
    int(session): [(tag, np.float64(value)) for tag, value in tag_list]
    for session, tag_list in loaded_data.items()
}

# -------------------------------
# （3） 分别获取中国区 (1–11 届) 和日本区 (3–20 届) 的 sessions 列表
# -------------------------------
cn_sessions = sorted(tag_rank_sessions_china.keys())  # [1, 2, ..., 11]
jp_sessions = sorted(tag_rank_sessions_japan.keys())  # [3, 4, ..., 20]

# -------------------------------
# （4） 定义函数提取每个 session 中的 tag 相对热度
# -------------------------------
def extract_relative_heat_per_session(rank_dict, sessions, tag_name):
    rates = []
    for s in sessions:
        found = False
        # 从字典中获取当前届次的所有标签及其值
        session_data = rank_dict.get(s, [])
        for (t, rate) in session_data:
            if t == tag_name:
                rates.append(float(rate))
                found = True
                break
        if not found:
            rates.append(0.0) # 如果没有找到该 tag，则热度为 0
    return rates

cn_values = extract_relative_heat_per_session(tag_rank_sessions_china, cn_sessions, TAG)
jp_values = extract_relative_heat_per_session(tag_rank_sessions_japan, jp_sessions, TAG)

# -------------------------------
# （5） 创建一张包含两张子图的图表
# -------------------------------
plt.figure(figsize=(14, 5))
plt.rcParams['font.sans-serif'] = ['SimHei']  # 中文支持

# 子图 1：中国区折线图
ax1 = plt.subplot(1, 2, 1)
ax1.plot(cn_sessions, cn_values, marker='o', linestyle='-', color='blue')
ax1.set_xlabel("届数 (Session)")
ax1.set_ylabel("相对热度") # 适配：更改 Y 轴标签
ax1.set_title(f"Tag “{TAG}” 相对热度 中国区 (第1–11届)") # 适配：更改标题
ax1.set_xticks(cn_sessions)
# 可以考虑设置Y轴的范围，因为相对热度应该在0-1之间
ax1.set_ylim(bottom=0) # 确保Y轴从0开始
ax1.grid(True)

# 子图 2：日本区折线图
ax2 = plt.subplot(1, 2, 2)
ax2.plot(jp_sessions, jp_values, marker='s', linestyle='-', color='orange')
ax2.set_xlabel("届数 (Session)")
ax2.set_ylabel("相对热度") # 适配：添加 Y 轴标签，保持一致
ax2.set_title(f"Tag “{TAG}” 相对热度 日本区 (第3–20届)") # 适配：更改标题
ax2.set_xticks(jp_sessions)
# 可以考虑设置Y轴的范围，因为相对热度应该在0-1之间
ax2.set_ylim(bottom=0) # 确保Y轴从0开始
ax2.grid(True)

plt.tight_layout()
plt.show()