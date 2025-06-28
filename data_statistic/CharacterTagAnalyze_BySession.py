import json
import matplotlib.pyplot as plt
import numpy as np

# 国家分中日，中为0，日为1
NATIONAL = 0 # 0 为中国，1 为日本
SESSION = 11 # 你想展示的届数
TOP_N = 15   # 你想展示的前 N 名，可自行修改

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

# 根据选择的国家和届数获取数据
if NATIONAL == 0:
    # 确保 SESSION 存在于中国区数据中
    if SESSION not in tag_rank_sessions_china:
        print(f"错误: 中国区第 {SESSION} 届数据不存在。请选择 1 到 11 之间的届数。")
        exit() # 或者可以采取其他错误处理方式
    data = tag_rank_sessions_china[SESSION] # SESSION 已经是 1-indexed，直接使用
    country_name = "中国"
else:
    # 确保 SESSION 存在于日本区数据中
    if SESSION not in tag_rank_sessions_japan:
        print(f"错误: 日本区第 {SESSION} 届数据不存在。请选择 3 到 20 之间的届数。")
        exit() # 或者可以采取其他错误处理方式
    data = tag_rank_sessions_japan[SESSION] # SESSION 已经是 1-indexed，直接使用
    country_name = "日本"

# 对列表进行切片，只保留前 TOP_N 项
top_n_data = data[:TOP_N]

# 分别提取字典的 key 和 value 作为横轴和纵轴数据
tags = []   # 存储所有标签
values = [] # 存储所有对应的相对热度

for tag_name, relative_heat in top_n_data:
    tags.append(tag_name)
    values.append(relative_heat)

# 创建条形图
plt.figure(figsize=(10, 6)) # 稍微调大图表尺寸，容纳更多标签
plt.rcParams['font.sans-serif'] = ['SimHei']  # 解决中文乱码

# 绘制条形图
bars = plt.bar(tags, values, color='skyblue')

# 在每个条形上方标注数值（保留三位小数）
for bar in bars:
    yval = bar.get_height()
    plt.text(bar.get_x() + bar.get_width()/2, yval + 0.005, # 稍微抬高文本
             f"{yval:.3f}", ha='center', va='bottom', fontsize=8)


plt.xlabel("标签 (Tag)")
plt.ylabel("相对热度") # 适配：更改 Y 轴标签
title_text = f"第{SESSION}届 {country_name} 标签相对热度排名前{TOP_N}名" # 适配：更改标题
plt.title(title_text)
plt.xticks(rotation=45, ha='right') # 旋转标签并右对齐，防止重叠
plt.ylim(bottom=0) # 确保Y轴从0开始，因为相对热度不会小于0
plt.grid(axis='y', linestyle='--', alpha=0.7) # 添加水平网格线

plt.tight_layout() # 自动调整布局，防止标签重叠
plt.show()