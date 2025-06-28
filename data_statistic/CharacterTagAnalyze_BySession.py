import json
import matplotlib.pyplot as plt
import numpy as np

# 国家分中日，中为0，日为1
NATIONAL = 1
SESSION = 20
TOP_N = 15  # 你想展示的前 N 名，可自行修改

with open("data_statistic/data_cn.json", "r", encoding="utf-8") as f:
    loaded_data = json.load(f)

# 将 list[list[key, value]] 转回 list[tuple[key, value]]
tag_rank_sessions_china = {
    int(session): [(tag, np.float64(value)) for tag, value in tag_list]
    for session, tag_list in loaded_data.items()
}

# print(tag_rank_sessions_china)

with open("data_statistic/data_jp.json", "r", encoding="utf-8") as f:
    loaded_data = json.load(f)

# 将 list[list[key, value]] 转回 list[tuple[key, value]]
tag_rank_sessions_japan = {
    int(session): [(tag, np.float64(value)) for tag, value in tag_list]
    for session, tag_list in loaded_data.items()
}

# print(tag_rank_sessions_china)

if NATIONAL == 0:
    data = tag_rank_sessions_china[SESSION-1]
else:
    data = tag_rank_sessions_japan[SESSION-1]

# 对列表进行切片，只保留前 TOP_N 项
top_n_data = data[:TOP_N]

# 分别提取字典的 key 和 value 作为横轴和纵轴数据
tags = []   # 存储所有标签
values = [] # 存储所有对应的得票率

for tag_name, vote_rate in top_n_data:
    tags.append(tag_name)
    values.append(vote_rate)

# 创建条形图
plt.figure(figsize=(8, 5))
plt.rcParams['font.sans-serif'] = ['SimHei']  # 解决中文乱码
plt.bar(tags, values)
plt.xlabel("标签 (tag)")
plt.ylabel("得票率 (value)")
title = f"第{SESSION}届{'中国' if NATIONAL == 0 else '日本'}标签得票率排名前{TOP_N}名"
plt.title(f"{title}得票率条形图")
plt.xticks(rotation=45)
plt.tight_layout()

# 显示图表
plt.show()