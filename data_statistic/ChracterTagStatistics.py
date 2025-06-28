import json
import numpy as np
import re

# 给出排名限定，如果排名 <= rank_boundary 则不计入
rank_boundary = 0

# 打开文件，存储至字典data中
with open('./touhou_vote.json','r',encoding='utf-8') as file:
    data = json.load(file)

# 存储所有tag到列表tag_set中
tag_list = []
for character in data['characters']:
    tag_list += data['characters'][character]['keywords']

# 处理重复元素，得到所有唯一的 tag
all_unique_tags = np.unique(tag_list)

# 数据处理，例：输入'3_jp'，返回session = 3, nationality = 1
def vote_data_processing(votes):
    session = int(re.findall(r'\d+', votes)[0]) - 1
    nationality = ''.join(re.findall(r'[a-zA-Z]', votes))
    if nationality == 'cn':
        nationality = 0
    else:
        nationality = 1
    return session, nationality

# ---
# ## 新增：过滤掉独有 Tag

# 这个部分会遍历所有 tag，统计每个 tag 对应的角色数量，然后只保留那些被多个角色共同拥有的 tag。

# ```python
# 统计每个 tag 被多少个不同的角色拥有
tag_character_counts = {}
for tag in all_unique_tags:
    tag_character_counts[tag] = 0
    for character_name in data['characters']:
        if tag in data['characters'][character_name]['keywords']:
            tag_character_counts[tag] += 1

# 筛选 tags 列表，只保留被至少两个角色拥有的 tag
# 你可以根据需要修改这里的阈值，比如只想分析被10个以上角色共有的tag
min_characters_per_tag = 2 
tags = [tag for tag in all_unique_tags if tag_character_counts[tag] >= min_characters_per_tag]

print(f"原始 tag 数量: {len(all_unique_tags)}")
print(f"过滤后 tag 数量 (至少被 {min_characters_per_tag} 个角色拥有): {len(tags)}")

# ---
# ## 预处理：确定排除的角色与届次

# 为了确保一个角色只要在任一地区排名靠前就被完全排除，我们首先建立一个排除集合。

# ```python
excluded_character_sessions = set()

for character_name, character_data in data['characters'].items():
    for votes_key, session_data in character_data['sessions'].items():
        rank = int(session_data['r'])
        session_num = int(re.findall(r'\d+', votes_key)[0]) # 提取届数（1-indexed）
        
        # 只要任意一边的排名达到排除条件，就将此“角色-届数”组合加入排除列表
        if rank <= rank_boundary:
            excluded_character_sessions.add((character_name, session_num))

# ---
# ## 核心修改：统计总票数和角色数量

# 这里是主要修改的部分。`tags_dict` 将不再直接存储得票率，而是存储**总票数**和**角色计数**，以便后续计算平均值。

# ```python
tags_dict = {}

# 遍历筛选后的 tag 列表
for tag in tags:
    # 初始化每个tag的数据结构
    tags_dict[tag] = {
        'total_votes': np.zeros((2, 20)),
        'character_counts': np.zeros((2, 20))
    }
    
    # 遍历角色
    for character in data['characters']:
        # 如果角色没有该tag，则跳过
        if tag not in data['characters'][character]['keywords']:
            continue
        # 如果有该tag，则统计其票数和角色数量
        else:
            # 用一个集合来记录当前届次中该角色是否已被计入，避免重复计数
            # 比如一个角色在同一届同时有cn和jp的数据，我们只计一次
            counted_sessions_for_character_tag = set() 

            for votes in data['characters'][character]['sessions']:
                session, nationality = vote_data_processing(votes)
                original_session_num = session + 1 # 将0-indexed的session转换回1-indexed

                # 检查当前“角色-届数”组合是否在排除列表中
                if (character, original_session_num) in excluded_character_sessions:
                    continue # 如果在排除列表，则跳过本次投票数据
                else:
                    # 累加票数
                    current_votes = data['characters'][character]['sessions'][votes]['v']
                    total_session_votes = data['indexes']['by_session'][votes]['total_votes']
                    
                    if total_session_votes > 0: # 避免除以零
                        tags_dict[tag]['total_votes'][nationality][session] += (current_votes / total_session_votes)
                    
                    # 累加角色数量，确保每个角色在每届只被计算一次
                    if (session, nationality) not in counted_sessions_for_character_tag:
                        tags_dict[tag]['character_counts'][nationality][session] += 1
                        counted_sessions_for_character_tag.add((session, nationality))

# ---
# ## 数据统计：计算平均得票率并输出

# 现在 `tags_dict` 存储的是总票数和角色数量。在数据统计阶段，我们将进行平均值计算。

# ```python
tag_average_vote_percentage = {}

for tag in tags_dict.keys():
    tag_average_vote_percentage[tag] = np.zeros((2,20)) # 同样是 [中/日][届数]

    # 分区计算平均值
    for i in range(2): # i=0 为中国，i=1 为日本
        for session_idx in range(20): # 遍历所有届数 (0-19)
            total_votes_for_tag = tags_dict[tag]['total_votes'][i][session_idx]
            character_count_for_tag = tags_dict[tag]['character_counts'][i][session_idx]

            if character_count_for_tag > 0:
                # 计算平均得票率：总票数 / 角色数量
                tag_average_vote_percentage[tag][i][session_idx] = total_votes_for_tag / character_count_for_tag
            else:
                tag_average_vote_percentage[tag][i][session_idx] = 0 # 如果没有角色，则平均得票率为0
    
    # 你可以在这里打印每个tag的中国和日本的平均得票率列表
    # print(f"Tag: {tag}")
    # print(f"  中国区平均得票率 (1-11届): {tag_average_vote_percentage[tag][0][0:11]}")
    # print(f"  日本区平均得票率 (3-20届): {tag_average_vote_percentage[tag][1][2:20]}")

# ---
# ## 排序：基于新的平均得票率

# 排序部分需要使用新的 `tag_average_vote_percentage` 数据结构。

# ```python
tag_rank_sessions_china = {}
tag_rank_sessions_japan = {}

for i in range(2):
    if i == 0:
        # 中国：1-11届
        for session in range(1,12): # 1-indexed session
            # 创建临时字典来存储当前届次的tag和其平均得票率
            temp_dict = {}
            for tag in tags: # 注意这里现在遍历的是筛选后的 tags 列表
                # 使用 tag_average_vote_percentage 来获取数据
                temp_dict[tag] = tag_average_vote_percentage[tag][0][session-1]
            
            # 排序
            sorted_dict = sorted(temp_dict.items(), key=lambda x: x[1],reverse=True)
            
            # 写入
            tag_rank_sessions_china[session] = sorted_dict

    else:
        # 日本：3-20届
        for session in range(3,21): # 1-indexed session
            # 创建临时字典
            temp_dict = {}
            for tag in tags: # 注意这里现在遍历的是筛选后的 tags 列表
                # 使用 tag_average_vote_percentage 来获取数据
                temp_dict[tag] = tag_average_vote_percentage[tag][1][session-1]
            
            # 排序
            sorted_dict = sorted(temp_dict.items(), key=lambda x: x[1],reverse=True)
            
            # 写入
            tag_rank_sessions_japan[session] = sorted_dict

# ---
# ## 保存结果

# 这个部分与之前相同，直接将处理好的数据保存为 JSON 文件。

# ```python
# 将 tuple 转成 list，JSON 不支持 tuple
data_to_save_cn = {
    session: list(map(list, tag_list)) 
    for session, tag_list in tag_rank_sessions_china.items()
}

with open("data_statistic/data_cn.json", "w", encoding="utf-8") as f:
    json.dump(data_to_save_cn, f, ensure_ascii=False, indent=4)


# 将 tuple 转成 list，JSON 不支持 tuple
data_to_save_jp = {
    session: list(map(list, tag_list)) 
    for session, tag_list in tag_rank_sessions_japan.items()
}

with open("data_statistic/data_jp.json", "w", encoding="utf-8") as f:
    json.dump(data_to_save_jp, f, ensure_ascii=False, indent=4)