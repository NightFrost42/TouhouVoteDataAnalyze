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

# --- 过滤掉独有 Tag ---
tag_character_counts = {}
for tag in all_unique_tags:
    tag_character_counts[tag] = 0
    for character_name in data['characters']:
        if tag in data['characters'][character_name]['keywords']:
            tag_character_counts[tag] += 1

min_characters_per_tag = 2 
tags = [tag for tag in all_unique_tags if tag_character_counts[tag] >= min_characters_per_tag]

print(f"原始 tag 数量: {len(all_unique_tags)}")
print(f"过滤后 tag 数量 (至少被 {min_characters_per_tag} 个角色拥有): {len(tags)}")

# --- 预处理：确定排除的角色与届次 ---
excluded_character_sessions = set()

for character_name, character_data in data['characters'].items():
    for votes_key, session_data in character_data['sessions'].items():
        rank = int(session_data['r'])
        session_num = int(re.findall(r'\d+', votes_key)[0]) # 提取届数（1-indexed）
        
        if rank <= rank_boundary:
            excluded_character_sessions.add((character_name, session_num))

# --- 新增部分：预计算每个角色在每届的得票率 (在排除高人气角色后) ---
# 这个字典存储每个角色在每届的得票率（占总票数），用于计算分母
# 格式: {character_name: {session_key: vote_percentage}}
character_session_vote_percentages = {}

for character_name, character_data in data['characters'].items():
    character_session_vote_percentages[character_name] = {}
    for votes_key, session_data in character_data['sessions'].items():
        session_num = int(re.findall(r'\d+', votes_key)[0])
        # 如果该角色在该届被排除，则跳过
        if (character_name, session_num) in excluded_character_sessions:
            continue
        
        current_votes = session_data['v']
        total_session_votes = data['indexes']['by_session'][votes_key]['total_votes']
        
        if total_session_votes > 0:
            character_session_vote_percentages[character_name][votes_key] = current_votes / total_session_votes
        else:
            character_session_vote_percentages[character_name][votes_key] = 0.0

# --- 关键修改：计算每个届次和国家区的“合格角色”总得票率之和 ---
# total_eligible_session_vote_percentage[nationality][session_idx] 
# 存储该届该国家区所有未被排除角色的得票率总和
total_eligible_session_vote_percentage = np.zeros((2, 20))

for character_name, session_votes_map in character_session_vote_percentages.items():
    for votes_key, vote_percentage in session_votes_map.items():
        session_idx, nationality = vote_data_processing(votes_key)
        total_eligible_session_vote_percentage[nationality][session_idx] += vote_percentage

# --- 核心修改：统计带 Tag 角色的总得票率和 ---
# tags_dict{
#   tag名字: {
#     'tag_char_vote_sum': np.zeros((2,20)),  # 存储带有该标签的角色的总得票率和（占届总票数）
#   }
# }
tags_dict = {}

for tag in tags: # 遍历筛选后的 tags 列表
    tags_dict[tag] = {
        'tag_char_vote_sum': np.zeros((2, 20)),
    }
    
    for character in data['characters']:
        for votes_key in data['characters'][character]['sessions']:
            session_idx, nationality = vote_data_processing(votes_key)
            original_session_num = session_idx + 1

            # 如果该角色在该届被排除，则跳过
            if (character, original_session_num) in excluded_character_sessions:
                continue
            
            # 获取该角色在该届的得票率（已经预计算并排除了高人气角色）
            char_vote_percentage_in_session = character_session_vote_percentages[character].get(votes_key, 0.0)

            # 累加所有拥有该tag的角色的总得票率和（占届总票数）
            if tag in data['characters'][character]['keywords']:
                tags_dict[tag]['tag_char_vote_sum'][nationality][session_idx] += char_vote_percentage_in_session


# --- 数据统计：计算相对比例差异 ---
# 这里 tag_relative_proportion 将存储最终的相对比例差异
tag_relative_proportion = {}

for tag in tags_dict.keys():
    tag_relative_proportion[tag] = np.zeros((2,20)) 

    for i in range(2): # i=0 为中国，i=1 为日本
        for session_idx in range(20): # 遍历所有届数 (0-19)
            tag_char_vote_sum = tags_dict[tag]['tag_char_vote_sum'][i][session_idx]
            
            # 分母现在是所有合格角色的总得票率
            eligible_total_vote_percentage = total_eligible_session_vote_percentage[i][session_idx]

            if eligible_total_vote_percentage > 0:
                # 相对比例差异：该Tag的累积得票率 / 合格角色的累积总得票率
                tag_relative_proportion[tag][i][session_idx] = tag_char_vote_sum / eligible_total_vote_percentage
            else:
                tag_relative_proportion[tag][i][session_idx] = 0 # 如果没有合格角色，则为0
    
    # print(f"Tag: {tag}")
    # print(f"  中国区相对比例 (1-11届): {tag_relative_proportion[tag][0][0:11]}")
    # print(f"  日本区相对比例 (3-20届): {tag_relative_proportion[tag][1][2:20]}")


# --- 排序：基于新的相对比例差异 ---
tag_rank_sessions_china = {}
tag_rank_sessions_japan = {}

for i in range(2):
    if i == 0:
        # 中国：1-11届
        for session in range(1,12): # 1-indexed session
            temp_dict = {}
            for tag in tags: # 遍历筛选后的 tags 列表
                temp_dict[tag] = tag_relative_proportion[tag][0][session-1]
            
            sorted_dict = sorted(temp_dict.items(), key=lambda x: x[1],reverse=True)
            tag_rank_sessions_china[session] = sorted_dict

    else:
        # 日本：3-20届
        for session in range(3,21): # 1-indexed session
            temp_dict = {}
            for tag in tags: # 遍历筛选后的 tags 列表
                temp_dict[tag] = tag_relative_proportion[tag][1][session-1]
            
            sorted_dict = sorted(temp_dict.items(), key=lambda x: x[1],reverse=True)
            tag_rank_sessions_japan[session] = sorted_dict

# --- 保存结果 ---
data_to_save_cn = {
    session: list(map(list, tag_list)) 
    for session, tag_list in tag_rank_sessions_china.items()
}

with open("data_statistic/data_cn.json", "w", encoding="utf-8") as f:
    json.dump(data_to_save_cn, f, ensure_ascii=False, indent=4)

data_to_save_jp = {
    session: list(map(list, tag_list)) 
    for session, tag_list in tag_rank_sessions_japan.items()
}

with open("data_statistic/data_jp.json", "w", encoding="utf-8") as f:
    json.dump(data_to_save_jp, f, ensure_ascii=False, indent=4)