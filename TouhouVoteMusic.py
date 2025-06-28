import pandas as pd
import re

def normalize_for_match(s: str) -> str:
    """
    1. 先用手工映射把已知的异名统一
    2. 再删除半角~或全角～及其之后，以及所有中英文括号里的内容
    3. 去除首尾空白
    """
    if not isinstance(s, str):
        return s
    # 2) 删掉波浪线及之后
    s = re.sub(r'[～~].*', '', s)
    # 3) 删掉括号及其中内容（中英文括号）
    s = re.sub(r'[（(].*?[)）]', '', s)
    # 4) 去除空白
    s = s.strip()
    # 1) 先人工映射
    if s in manual_match_map:
        s = manual_match_map[s]
    return s

# 1. 在脚本开头，定义所有已知的译名变体到主标题的映射
manual_match_map = {
    '今宵是飘逸的利己主义者': '今宵是飘逸的自我主义者',
    '今宵是飘逸的自我主义者': '今宵是飘逸的自我主义者',
    '恋色Magic': '恋色Master spark',
    '恋色Magic（恋色Master spark）': '恋色Master spark',
    '恋色Master spark（恋色Magic）': '恋色Master spark',
    '仲夏的妖精梦': '盛夏的妖精梦',
    '盛夏的妖精梦': '盛夏的妖精梦',
    # …如果还有其他已知变体，都加在这里…
}

# 1. 读映射表，生成“标准译名”和“干净名”
dic_saw = pd.read_excel('TouhouMusicInfo.xlsx', usecols=['曲目', '译名', '所属角色'])
dic_saw.dropna(subset=['所属角色'], inplace=True)
dic_saw = dic_saw.rename(columns={'译名': '标准译名'})
dic_saw['干净名'] = dic_saw['标准译名'].map(normalize_for_match)

# 日区映射：按曲目合并
dic_jp = dic_saw[['曲目', '所属角色', '标准译名']].copy()

# 国区映射：按干净名合并
dic_cn = dic_saw[['曲目', '所属角色', '标准译名', '干净名']].copy()

# 2. 处理日区投票表（不变列结构，只替换译名）
data_jp = pd.read_excel('TouhouVote_music_jp.xlsx', sheet_name=None)
processed_jp = {}
for sheet, df in data_jp.items():
    merged = pd.merge(df, dic_jp, on='曲目', how='left', validate='many_to_one')
    merged.dropna(subset=['所属角色', '标准译名'], inplace=True)
    # 【改动】在这里：对标准译名再归一化，去掉括号和子标题
    merged['译名'] = merged['标准译名'].map(normalize_for_match)
    processed_jp[sheet] = merged[df.columns.tolist() + ['所属角色']]

with pd.ExcelWriter("TouhouVote_music_jp_grouped.xlsx", engine="openpyxl") as w:
    for sheet, df in processed_jp.items():
        df.to_excel(w, sheet, index=False)

# 3. 处理国区投票表
data_cn = pd.read_excel('TouhouVote_music_cn.xlsx', sheet_name=None)
processed_cn = {}
for sheet, df in data_cn.items():
    df['干净名'] = df['译名'].map(normalize_for_match)
    merged = pd.merge(df, dic_cn, on='干净名', how='left', validate='many_to_one')
    merged.dropna(subset=['曲目', '所属角色', '标准译名'], inplace=True)
    # 【改动】同样再归一化一下，防止标准译名里还有括号
    merged['译名'] = merged['标准译名'].map(normalize_for_match)
    cols = [c for c in df.columns if c != '干净名'] + ['所属角色']
    processed_cn[sheet] = merged[cols]

with pd.ExcelWriter("TouhouVote_music_cn_grouped.xlsx", engine="openpyxl") as w:
    for sheet, df in processed_cn.items():
        df.to_excel(w, sheet, index=False)
