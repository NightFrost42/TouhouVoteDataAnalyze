import pandas as pd

dic_saw = pd.read_excel('fun.xlsx',usecols=['日文名','译名','首次出现作品'])
dic_saw.dropna(subset=['首次出现作品'], inplace=True)
dic_saw = dic_saw.loc[dic_saw['首次出现作品'] > 5]
dic_saw['首次出现作品'] = dic_saw['首次出现作品'].astype(float)
# dic = dict(zip(dic_saw['日文名'], dic_saw['首次出现作品']))
# print(dic_saw)

dic_jp = dic_saw.loc[dic_saw['首次出现作品'] > 5,['日文名','首次出现作品']]
data_jp = pd.read_excel('TouhouVote_jp.xlsx',sheet_name=None)
processed_sheets = {}
for num, df in data_jp.items():
    merged_df = pd.merge(df, dic_jp,on='日文名',how='left')
    merged_df.dropna(subset=['首次出现作品'], inplace=True)
    processed_sheets[num] = merged_df

with pd.ExcelWriter("TouhouVote_jp_grouped.xlsx", engine="openpyxl") as writer:
    for sheet_name, df in processed_sheets.items():
        df.to_excel(writer, sheet_name=sheet_name, index=False)

dic_cn = dic_saw.loc[dic_saw['首次出现作品'] > 5,['译名','首次出现作品']]
data_jp = pd.read_excel('TouhouVote_cn.xlsx',sheet_name=None)
processed_sheets = {}
for num, df in data_jp.items():
    merged_df = pd.merge(df, dic_cn,on='译名',how='left')
    merged_df.dropna(subset=['首次出现作品'], inplace=True)
    processed_sheets[num] = merged_df

with pd.ExcelWriter("TouhouVote_cn_grouped.xlsx", engine="openpyxl") as writer:
    for sheet_name, df in processed_sheets.items():
        df.to_excel(writer, sheet_name=sheet_name, index=False)