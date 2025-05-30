import pandas as pd

# 读取曲目信息表，并删除“所属角色”为空的行
dic_saw = pd.read_excel('TouhouMusicInfo.xlsx', usecols=['曲目','译名','所属角色'])
dic_saw.dropna(subset=['所属角色'], inplace=True)

# 构造日文映射表
dic_jp = dic_saw[['曲目', '所属角色']].copy()

# 读取日文投票表（多个 sheet），合并并清洗
data_jp = pd.read_excel('TouhouVote_music_jp.xlsx', sheet_name=None)
processed_sheets_jp = {}
for sheet_name, df in data_jp.items():
    merged_df = pd.merge(df, dic_jp, on='曲目', how='left')
    merged_df.dropna(subset=['所属角色'], inplace=True)
    processed_sheets_jp[sheet_name] = merged_df

# 写出合并结果
with pd.ExcelWriter("TouhouVote_music_jp_grouped.xlsx", engine="openpyxl") as writer:
    for sheet_name, df in processed_sheets_jp.items():
        df.to_excel(writer, sheet_name=sheet_name, index=False)

# 构造中文映射表
dic_cn = dic_saw[['译名', '所属角色']].copy()

# 读取中文投票表并合并
data_cn = pd.read_excel('TouhouVote_music_cn.xlsx', sheet_name=None)
processed_sheets_cn = {}
for sheet_name, df in data_cn.items():
    merged_df = pd.merge(df, dic_cn, on='译名', how='left')
    merged_df.dropna(subset=['所属角色'], inplace=True)
    processed_sheets_cn[sheet_name] = merged_df

# 写出中文合并结果
with pd.ExcelWriter("TouhouVote_music_cn_grouped.xlsx", engine="openpyxl") as writer:
    for sheet_name, df in processed_sheets_cn.items():
        df.to_excel(writer, sheet_name=sheet_name, index=False)
