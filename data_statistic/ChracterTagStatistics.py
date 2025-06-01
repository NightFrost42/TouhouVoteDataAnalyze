
import json
import numpy as np
import re

# 给出排名限定，如果排名 <= rank_boundary 则不计入
rank_boundary = 10

# 打开文件，存储至字典data中
with open('./touhou_vote.json','r',encoding='utf-8') as file:
    data = json.load(file)

# 存储所有tag到列表tag_set中
tag_list = []
for character in data['characters']:
    tag_list += data['characters'][character]['keywords']

# 处理重复元素
tags = np.unique(tag_list)

# 需求：tag基于投票届数的数据变化表，以及得票率排名

# 统计数据
# 创建数据存储结构dict，格式：dict{key1:tag名字，key2:国家，key3:届数，value:得票率}
# tag名于tags中，届数为1-20届对应0-19，国家分中日，中为0，日为1
tags_dict = {}

# 数据处理，例：输入'3_jp'，返回session = 3, nationality = 1
def vote_data_processing(votes):
    session = int(re.findall(r'\d+', votes)[0]) - 1
    nationality = ''.join(re.findall(r'[a-zA-Z]', votes))
    if nationality == 'cn':
        nationality = 0
    else:
        nationality = 1
    return session, nationality

# 遍历tag
for tag in tags:
    # 初始化
    tags_dict[tag] = np.zeros((2,20))
    
    # 遍历角色
    for character in data['characters']:
        # 如果角色没有该tag
        if tag not in data['characters'][character]['keywords']:
            continue
        # 如果有，则统计
        else:
            for votes in data['characters'][character]['sessions']:
                # 如果角色当期排名高于N，则跳过
                if int(data['characters'][character]['sessions'][votes]['r']) <= rank_boundary:
                    continue
                else:
                    session, nationality = vote_data_processing(votes)
                    tags_dict[tag][nationality][session] += (data['characters'][character]['sessions'][votes]['v'] / data['indexes']['by_session'][votes]['total_votes'])

# ------------------------------------------------------------------------------
# 数据统计

# 中国部分(1-11届)：tags_dict[tag][0][0:11]
# 日本部分(3-20届)：tags_dict[tag][1][2:20]
# 数据为百分比，意义为所有票中有多少比例投了该tag
# 例：print(tags_dict["贫乳"][0][0:11])

for tag in tags_dict.keys():
    # 初始化
    tag_vote_percentage_list = []
    
    # 分区：
    for i in range(2):
        if i == 0:
            # 中
            tag_vote_percentage_list = tags_dict[tag][i][0:11]
        else:
            # 日
            tag_vote_percentage_list = tags_dict[tag][1][2:20]
    
        # TODO：绘图！
        # tag_vote_percentage_list按届数从前往后排序，直接用这个
        # 例：print(tag_vote_percentage_list)
        # print(tag)
        # print(i)
        # print(tag_vote_percentage_list)

# ------------------------------------------------------------------------------
# 排序

# 生成子字典
tag_rank_sessions_china = {}
tag_rank_sessions_japan = {}

for i in range(2):
    if i == 0:
        # 中：1-11
        for session in range(1,12):
            # 创建临时字典
            temp_dict = {}
    
            #读取数据
            for tag in tags:
                temp_dict[tag] = tags_dict[tag][0][session-1]
    
            # 排序
            sorted_dict = sorted(temp_dict.items(), key=lambda x: x[1],reverse=True)
    
            # 写入
            tag_rank_sessions_china[session] = sorted_dict

    else:
        # 日：3-20
        for session in range(3,21):
            # 创建临时字典
            temp_dict = {}
    
            #读取数据
            for tag in tags:
                temp_dict[tag] = tags_dict[tag][1][session-1]
    
            # 排序
            sorted_dict = sorted(temp_dict.items(), key=lambda x: x[1],reverse=True)
    
            # 写入
            tag_rank_sessions_japan[session] = sorted_dict

# tag_rank_sessions_china和tag_rank_sessions_japan分别存储了按届排序的不同tag
# 格式：list[dict{key: tag, value: 具体得票率}]
# 返回为第3届日本tag得票率排序后的，dict{key: tag, value: 得票率}，大->小

# TODO：绘图！
# 例：
#   print(tag_rank_sessions_japan[3])
# print(tag_rank_sessions_japan[3])


# 将 tuple 转成 list，JSON 不支持 tuple
data_to_save = {
    session: list(map(list, tag_list))  # 把每个 (key, value) tuple 转成 [key, value]
    for session, tag_list in tag_rank_sessions_china.items()
}

with open("data_statistic/data_cn.json", "w", encoding="utf-8") as f:
    json.dump(data_to_save, f, ensure_ascii=False, indent=4)


# 将 tuple 转成 list，JSON 不支持 tuple
data_to_save = {
    session: list(map(list, tag_list))  # 把每个 (key, value) tuple 转成 [key, value]
    for session, tag_list in tag_rank_sessions_japan.items()
}

with open("data_statistic/data_jp.json", "w", encoding="utf-8") as f:
    json.dump(data_to_save, f, ensure_ascii=False, indent=4)
# # 国家分中日，中为0，日为1
# NATIONAL = 0
# SESSION = 11
# TOP_N = 15  # 你想展示的前 N 名，可自行修改

# if NATIONAL == 0:
#     data = tag_rank_sessions_china[SESSION-1]
# else:
#     data = tag_rank_sessions_japan[SESSION-1]

# # 对列表进行切片，只保留前 TOP_N 项
# top_n_data = data[:TOP_N]

# # 分别提取字典的 key 和 value 作为横轴和纵轴数据
# tags = []   # 存储所有标签
# values = [] # 存储所有对应的得票率

# for tag_name, vote_rate in top_n_data:
#     tags.append(tag_name)
#     values.append(vote_rate)

# # 创建条形图
# plt.figure(figsize=(8, 5))
# plt.rcParams['font.sans-serif'] = ['SimHei']  # 解决中文乱码
# plt.bar(tags, values)
# plt.xlabel("标签 (tag)")
# plt.ylabel("得票率 (value)")
# title = f"第{SESSION}届{'中国' if NATIONAL == 0 else '日本'}标签得票率排名前{TOP_N}名"
# plt.title(f"{title}得票率条形图")
# plt.xticks(rotation=45)
# plt.tight_layout()

# # 显示图表
# plt.show()