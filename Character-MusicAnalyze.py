import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
import matplotlib.pyplot as plt
import seaborn as sns
import matplotlib as mpl
import sys
from scipy.stats import spearmanr

# --- 用户可设置的常数 ---\
PROPORTION_THRESHOLD_CROSS_REGION = 0.5  # 同理
OUTLIER_THRESHOLD_INTERNAL = 2.5


# --- 文件路径和列名定义 ---
# 角色数据文件
FILE_CHAR_CN_RAW = 'TouhouVote_cn.xlsx'
FILE_CHAR_CN_GROUPED = 'TouhouVote_cn_grouped.xlsx'
FILE_CHAR_JP_RAW = 'TouhouVote_jp.xlsx'
FILE_CHAR_JP_GROUPED = 'TouhouVote_jp_grouped.xlsx'

# 歌曲数据文件
FILE_MUSIC_CN_RAW = 'TouhouVote_music_cn.xlsx'
FILE_MUSIC_CN_GROUPED = 'TouhouVote_music_cn_grouped.xlsx'
FILE_MUSIC_JP_RAW = 'TouhouVote_music_jp.xlsx'
FILE_MUSIC_JP_GROUPED = 'TouhouVote_music_jp_grouped.xlsx'

# 角色名称转换文件
FILE_FUN_MAP = 'fun.xlsx'

# 列名定义
COL_CHAR_CN_NAME = '译名'      # 国区角色名列
COL_CHAR_JP_NAME = '日文名'    # 日区角色名列
COL_VOTES = '票数'             # 角色原始票数 (通用)

COL_MUSIC_CN_VOTES = '票数'    # 国区歌曲数据的票数列名
COL_MUSIC_JP_VOTES = '得票数'  # 日区歌曲数据的票数列名

COL_MUSIC_NAME_CN = '译名'     # 国区歌曲名列
COL_MUSIC_NAME_JP = '译名'     # 日区歌曲名列
COL_MUSIC_CHAR_ASSOCIATION = '所属角色' # 歌曲所属角色列

# fun.xlsx 文件中的列名
COL_FUN_JP_NAME = '日文名'
COL_FUN_CN_NAME = '译名'

# --- 修复中文显示问题 ---
if sys.platform.startswith('win'):
    mpl.rcParams['font.sans-serif'] = ['SimHei']
elif sys.platform.startswith('darwin'):
    mpl.rcParams['font.sans-serif'] = ['Heiti TC']
else:
    mpl.rcParams['font.sans-serif'] = ['WenQuanYi Zen Hei']
mpl.rcParams['axes.unicode_minus'] = False


# --- 辅助函数：加载数据 ---
def load_data(file_path):
    xls = pd.ExcelFile(file_path)
    df = pd.read_excel(xls, sheet_name=xls.sheet_names[-1])
    return df

# --- 载入所有数据 ---
print("正在加载数据...")
df_char_cn_raw = load_data(FILE_CHAR_CN_RAW)
df_char_jp_raw = load_data(FILE_CHAR_JP_RAW)
df_char_cn_grouped = load_data(FILE_CHAR_CN_GROUPED)
df_char_jp_grouped = load_data(FILE_CHAR_JP_GROUPED)
df_music_cn_raw = load_data(FILE_MUSIC_CN_RAW)
df_music_jp_raw = load_data(FILE_MUSIC_JP_RAW)
df_music_cn_grouped = load_data(FILE_MUSIC_CN_GROUPED)
df_music_jp_grouped = load_data(FILE_MUSIC_JP_GROUPED)

df_fun_map = load_data(FILE_FUN_MAP)
char_name_map = dict(zip(df_fun_map[COL_FUN_JP_NAME], df_fun_map[COL_FUN_CN_NAME]))
print("数据加载完成。")

# --- 计算总票数 (从原始数据) ---
total_votes_char_cn = df_char_cn_raw[COL_VOTES].sum()
total_votes_char_jp = df_char_jp_raw[COL_VOTES].sum()
total_votes_music_cn = df_music_cn_raw[COL_MUSIC_CN_VOTES].sum()
total_votes_music_jp = df_music_jp_raw[COL_MUSIC_JP_VOTES].sum()

print(f"\n国区角色总票数: {total_votes_char_cn}")
print(f"日区角色总票数: {total_votes_char_jp}")
print(f"国区歌曲总票数: {total_votes_music_cn}")
print(f"日区歌曲总票数: {total_votes_music_jp}")

# --- 计算得票率 (基于清洗后的数据和总票数) ---
df_char_cn_grouped['得票率'] = df_char_cn_grouped[COL_VOTES] / total_votes_char_cn
df_char_jp_grouped['得票率'] = df_char_jp_grouped[COL_VOTES] / total_votes_char_jp
df_music_cn_grouped['得票率'] = df_music_cn_grouped[COL_MUSIC_CN_VOTES] / total_votes_music_cn
df_music_jp_grouped['得票率'] = df_music_jp_grouped[COL_MUSIC_JP_VOTES] / total_votes_music_jp

# --- 标准化得票率 (Z-score) ---
scaler = StandardScaler()

df_char_cn_grouped['标准化得票率'] = scaler.fit_transform(df_char_cn_grouped[['得票率']])
df_char_jp_grouped['标准化得票率'] = scaler.fit_transform(df_char_jp_grouped[['得票率']])
df_music_cn_grouped['标准化得票率'] = scaler.fit_transform(df_music_cn_grouped[['得票率']])
df_music_jp_grouped['标准化得票率'] = scaler.fit_transform(df_music_jp_grouped[['得票率']])

print("\n得票率和标准化处理完成。")

# --- 计算每个角色的平均歌曲人气 (区域内分析) ---
def calculate_character_avg_music_popularity_for_region(
        df_char_grouped, df_music_grouped,
        region_name, char_name_col_char_df):
    """
    计算每个角色在指定区域的：
      - 原始得票率平均（平均歌曲得票率 raw）
      - 标准化得票率平均（平均歌曲标准化得票率 std）
      - 关联歌曲数量
    并与角色自身的得票率等信息合并后返回 DataFrame。
    """
    print(f"\n正在为 {region_name} 区计算角色平均歌曲人气…")

    # 1) 准备一个容器：角色 -> list of {'std': ..., 'raw': ...}
    character_song_data = {}

    for _, row in df_music_grouped.iterrows():
        std_rate = row['标准化得票率']
        raw_rate = row['得票率']
        assoc = row[COL_MUSIC_CHAR_ASSOCIATION]
        if pd.isna(assoc):
            continue

        for char_orig in assoc.split('|'):
            char_orig = char_orig.strip()
            # 统一角色名字
            if region_name == '国区':
                char_unified = char_orig
            else:
                char_unified = char_name_map.get(char_orig, char_orig)

            character_song_data.setdefault(char_unified, []).append({
                'std': std_rate,
                'raw': raw_rate
            })

    # 2) 构造汇总结果列表
    results = []
    for char, recs in character_song_data.items():
        stds = [r['std'] for r in recs]
        raws = [r['raw'] for r in recs]
        results.append({
            '角色名称_统一': char,
            '平均歌曲标准化得票率': np.mean(stds),
            '平均歌曲得票率':        np.mean(raws),
            '关联歌曲数量':         len(stds)
        })

    df_result_music_avg = pd.DataFrame(results)

    # 3) 把角色自身数据准备好，用于 merge
    df_char = df_char_grouped.copy()
    if region_name == '国区':
        df_char['角色名称_统一'] = df_char[char_name_col_char_df]
    else:
        df_char['角色名称_统一'] = df_char[char_name_col_char_df].map(char_name_map)\
                                                         .fillna(df_char[char_name_col_char_df])

    # 4) 合并：角色自身得票率 + 平均歌曲人气
    merged = pd.merge(
        df_char,
        df_result_music_avg,
        on='角色名称_统一',
        how='left'
    )

    # 5) 对缺失值填 0
    merged['平均歌曲标准化得票率'] = merged['平均歌曲标准化得票率'].fillna(0)
    merged['平均歌曲得票率']        = merged['平均歌曲得票率']       .fillna(0)
    merged['关联歌曲数量']         = merged['关联歌曲数量']         .fillna(0).astype(int)

    print(f"{region_name} 区角色平均歌曲人气计算完成。")
    return merged

df_analysis_cn = calculate_character_avg_music_popularity_for_region(df_char_cn_grouped, df_music_cn_grouped, '国区', COL_CHAR_CN_NAME)
df_analysis_jp = calculate_character_avg_music_popularity_for_region(df_char_jp_grouped, df_music_jp_grouped, '日区', COL_CHAR_JP_NAME)


# --- 相关性分析 (分别进行) ---
print("\n--- 分区域斯皮尔曼相关性分析 ---")

cn_data_for_correlation = df_analysis_cn[['标准化得票率', '平均歌曲标准化得票率']].dropna()
correlation_cn, pvalue_cn = np.nan, np.nan
if not cn_data_for_correlation.empty and len(cn_data_for_correlation) > 1:
    correlation_cn, pvalue_cn = spearmanr(cn_data_for_correlation['标准化得票率'], cn_data_for_correlation['平均歌曲标准化得票率'])
    print(f"国区角色人气与平均歌曲人气之间的斯皮尔曼相关系数: {correlation_cn:.4f} (p-value: {pvalue_cn:.4f})")
    if pvalue_cn < 0.05:
        print("  -> 国区相关性在统计上是显著的 (p < 0.05)。")
    else:
        print("  -> 国区相关性在统计上不显著 (p >= 0.05)。")
else:
    print("国区数据不足以计算相关性。")

jp_data_for_correlation = df_analysis_jp[['标准化得票率', '平均歌曲标准化得票率']].dropna()
correlation_jp, pvalue_jp = np.nan, np.nan
if not jp_data_for_correlation.empty and len(jp_data_for_correlation) > 1:
    correlation_jp, pvalue_jp = spearmanr(jp_data_for_correlation['标准化得票率'], jp_data_for_correlation['平均歌曲标准化得票率'])
    print(f"日区角色人气与平均歌曲人气之间的斯皮尔曼相关系数: {correlation_jp:.4f} (p-value: {pvalue_jp:.4f})")
    if pvalue_jp < 0.05:
        print("  -> 日区相关性在统计上是显著的 (p < 0.05)。")
    else:
        print("  -> 日区相关性在统计上不显著 (p >= 0.05)。")
else:
    print("日区数据不足以计算相关性。")


# --- 查找并输出特异点 (基于区域内分析) ---
print("\n--- 区域内特异点角色识别 ---")

# # --- 在计算前，先初始化一个字典来存放各区的 outliers ---
# outliers_dict = {}

# for region, df_analysis in [('国区', df_analysis_cn), ('日区', df_analysis_jp)]:
#     # 计算比例
#     df_analysis['ratio_internal'] = df_analysis['得票率'] / df_analysis['平均歌曲得票率']
#     # 筛出超出阈值的点
#     outliers = df_analysis[abs(df_analysis['ratio_internal'] - 1) > PROPORTION_THRESHOLD_INTERNAL].copy()
#     # 保存到字典
#     outliers_dict[region] = outliers

#     # 打印输出保持原样
#     if not outliers.empty:
#         print(f"\n**{region} 特异点角色（|ratio - 1|>{PROPORTION_THRESHOLD_INTERNAL}）：**")
#         for _, row in outliers.iterrows():
#             name = row['角色名称_统一']
#             r = row['ratio_internal']
#             print(f"- **{name}**: 比例偏离={r:.2f}（角色得票率={row['得票率']:.4%}, 平均歌曲得票率={row['平均歌曲得票率']:.4%}）")
#     else:
#         print(f"{region} 未发现显著比例偏离的特异点。")

# # --- 后面你就可以这样访问各区的超标点数据了 ---
# cn_outliers = outliers_dict['国区']
# jp_outliers = outliers_dict['日区']

# 使用提取到开头的常数
outliers_cn_internal = df_analysis_cn[
    (abs(df_analysis_cn['标准化得票率']) > OUTLIER_THRESHOLD_INTERNAL) ^
    (abs(df_analysis_cn['平均歌曲标准化得票率']) > OUTLIER_THRESHOLD_INTERNAL)
].sort_values(by=['标准化得票率', '平均歌曲标准化得票率'], ascending=False)

if not outliers_cn_internal.empty:
    print("\n**国区特异点角色：**")
    for idx, row in outliers_cn_internal.iterrows():
        char_name = row['角色名称_统一']
        char_pop = row['标准化得票率']
        music_pop = row['平均歌曲标准化得票率']
        print(f"- **{char_name}**: 角色人气={char_pop:.2f}, 平均歌曲人气={music_pop:.2f}")
        if abs(char_pop) > OUTLIER_THRESHOLD_INTERNAL and abs(music_pop) > OUTLIER_THRESHOLD_INTERNAL:
            print(f"  * 该角色自身人气和关联歌曲人气都非常突出（或非常低）。")
        elif abs(char_pop) > OUTLIER_THRESHOLD_INTERNAL:
            print(f"  * 该角色自身人气非常高（或非常低），但关联歌曲人气相对不那么极端。")
        else:
            print(f"  * 该角色关联歌曲人气非常高（或非常低），但角色自身人气相对不那么极端。")
else:
    print("国区未发现显著特异点。")


outliers_jp_internal = df_analysis_jp[
    (abs(df_analysis_jp['标准化得票率']) > OUTLIER_THRESHOLD_INTERNAL) ^
    (abs(df_analysis_jp['平均歌曲标准化得票率']) > OUTLIER_THRESHOLD_INTERNAL)
].sort_values(by=['标准化得票率', '平均歌曲标准化得票率'], ascending=False)

if not outliers_jp_internal.empty:
    print("\n**日区特异点角色：**")
    for idx, row in outliers_jp_internal.iterrows():
        char_name = row['角色名称_统一']
        char_pop = row['标准化得票率']
        music_pop = row['平均歌曲标准化得票率']
        print(f"- **{char_name}**: 角色人气={char_pop:.2f}, 平均歌曲人气={music_pop:.2f}")
        if abs(char_pop) > OUTLIER_THRESHOLD_INTERNAL and abs(music_pop) > OUTLIER_THRESHOLD_INTERNAL:
            print(f"  * 该角色自身人气和关联歌曲人气都非常突出（或非常低）。")
        elif abs(char_pop) > OUTLIER_THRESHOLD_INTERNAL:
            print(f"  * 该角色自身人气非常高（或非常低），但关联歌曲人气相对不那么极端。")
        else:
            print(f"  * 该角色关联歌曲人气非常高（或非常低），但角色自身人气相对不那么极端。")
else:
    print("日区未发现显著特异点。")


# --- 结果展示和可视化 (子图同时绘制) ---
# print("\n--- 可视化散点图 (国区与日区) ---")

# fig, axes = plt.subplots(1, 2, figsize=(15, 7))

# sns.scatterplot(x='标准化得票率', y='平均歌曲标准化得票率', data=df_analysis_cn, ax=axes[0])
# axes[0].set_title('国区：角色人气 vs. 平均歌曲人气')
# axes[0].set_xlabel('角色标准化得票率')
# axes[0].set_ylabel('平均歌曲标准化得票率')
# axes[0].grid(True)
# axes[0].text(0.05, 0.95, f'Spearman r = {correlation_cn:.2f}\np-value = {pvalue_cn:.3f}',
#              transform=axes[0].transAxes, fontsize=12, verticalalignment='top', bbox=dict(boxstyle='round,pad=0.5', fc='wheat', alpha=0.5))

# sns.scatterplot(x='标准化得票率', y='平均歌曲标准化得票率', data=df_analysis_jp, ax=axes[1])
# axes[1].set_title('日区：角色人气 vs. 平均歌曲人气')
# axes[1].set_xlabel('角色标准化得票率')
# axes[1].set_ylabel('平均歌曲标准化得票率')
# axes[1].grid(True)
# axes[1].text(0.05, 0.95, f'Spearman r = {correlation_jp:.2f}\np-value = {pvalue_jp:.3f}',
#              transform=axes[1].transAxes, fontsize=12, verticalalignment='top', bbox=dict(boxstyle='round,pad=0.5', fc='wheat', alpha=0.5))

# plt.tight_layout()
# plt.show()

# --- 新增分析模块：因歌曲差异导致的角色人气差异 ---
print("\n--- 分析：因歌曲差异导致的角色人气差异 ---")

def process_music_data_for_cross_region_analysis(df_music_grouped, region_name, music_name_col, char_name_col_char_df):
    processed_music_data = []
    for index, row in df_music_grouped.iterrows():
        song_name = row[music_name_col]
        song_standardized_popularity = row['标准化得票率']
        associated_chars_str = row[COL_MUSIC_CHAR_ASSOCIATION]

        if pd.isna(associated_chars_str):
            continue

        associated_chars = [c.strip() for c in associated_chars_str.split('|')]

        for char_original in associated_chars:
            char_unified = char_name_map.get(char_original, char_original)
            
            processed_music_data.append({
                '歌曲名称_统一': song_name,
                '角色名称_统一': char_unified,
                '歌曲标准化得票率': song_standardized_popularity,
                '区域': region_name
            })
    return pd.DataFrame(processed_music_data)

df_processed_music_cn_cross = process_music_data_for_cross_region_analysis(df_music_cn_grouped, '国区', COL_MUSIC_NAME_CN, COL_CHAR_CN_NAME)
df_processed_music_jp_cross = process_music_data_for_cross_region_analysis(df_music_jp_grouped, '日区', COL_MUSIC_NAME_JP, COL_CHAR_JP_NAME)

df_all_music_processed_cross = pd.concat([df_processed_music_cn_cross, df_processed_music_jp_cross], ignore_index=True)

df_music_pivot_cross = df_all_music_processed_cross.pivot_table(
    index=['歌曲名称_统一', '角色名称_统一'],
    columns='区域',
    values='歌曲标准化得票率'
).reset_index()

df_music_pivot_cross['国区'] = df_music_pivot_cross['国区'].fillna(0)
df_music_pivot_cross['日区'] = df_music_pivot_cross['日区'].fillna(0)

df_music_pivot_cross['单首歌曲人气差异'] = df_music_pivot_cross['国区'] - df_music_pivot_cross['日区']

character_avg_song_diff = df_music_pivot_cross.groupby('角色名称_统一')['单首歌曲人气差异'].mean().reset_index()
character_avg_song_diff = character_avg_song_diff.rename(columns={'单首歌曲人气差异': '关联歌曲平均人气差异'})

df_char_cn_grouped['角色名称_统一'] = df_char_cn_grouped[COL_CHAR_CN_NAME]
df_char_jp_grouped['角色名称_统一'] = df_char_jp_grouped[COL_CHAR_JP_NAME].map(char_name_map).fillna(df_char_jp_grouped[COL_CHAR_JP_NAME])

df_all_char_popularity_cross = pd.concat([
    df_char_cn_grouped[['角色名称_统一', '标准化得票率']].assign(区域='国区'),
    df_char_jp_grouped[['角色名称_统一', '标准化得票率']].assign(区域='日区')
], ignore_index=True)

df_char_pivot_cross = df_all_char_popularity_cross.pivot_table(
    index='角色名称_统一',
    columns='区域',
    values='标准化得票率'
).reset_index()

df_char_pivot_cross['国区'] = df_char_pivot_cross['国区'].fillna(0)
df_char_pivot_cross['日区'] = df_char_pivot_cross['日区'].fillna(0)

df_char_pivot_cross['角色自身人气差异'] = df_char_pivot_cross['国区'] - df_char_pivot_cross['日区']

df_final_diff_analysis = pd.merge(
    df_char_pivot_cross[['角色名称_统一', '角色自身人气差异']],
    character_avg_song_diff,
    on='角色名称_统一',
    how='left'
)
df_final_diff_analysis['关联歌曲平均人气差异'] = df_final_diff_analysis['关联歌曲平均人气差异'].fillna(0)

# # 使用提取到开头的常数
# impact_characters = df_final_diff_analysis[
#     (abs(df_final_diff_analysis['角色自身人气差异']) > IMPACT_THRESHOLD_CROSS_REGION) &
#     (abs(df_final_diff_analysis['关联歌曲平均人气差异']) > IMPACT_THRESHOLD_CROSS_REGION)
# ].sort_values(by='角色自身人气差异', ascending=False)

# if not impact_characters.empty:
#     print("\n**受歌曲人气差异显著影响的角色：**")
#     for idx, row in impact_characters.iterrows():
#         char_name = row['角色名称_统一']
#         char_diff = row['角色自身人气差异']
#         music_diff = row['关联歌曲平均人气差异']
        
#         print(f"- **{char_name}**: 角色人气={char_diff:.2f}, 关联歌曲平均人气={music_diff:.2f}")
        
#         if char_diff > 0 and music_diff > 0:
#             print("  * 该角色在国区比日区更受欢迎，其关联歌曲在国区也平均更受欢迎。")
#         elif char_diff < 0 and music_diff < 0:
#             print("  * 该角色在日区比国区更受欢迎，其关联歌曲在日区也平均更受欢迎。")
#         elif char_diff > 0 and music_diff < 0:
#             print("  * 该角色在国区更受欢迎，但其关联歌曲在日区平均更受欢迎，可能存在反向影响。")
#         elif char_diff < 0 and music_diff > 0:
#             print("  * 该角色在日区更受欢迎，但其关联歌曲在国区平均更受欢迎，可能存在反向影响。")
# else:
#     print("未发现因歌曲差异而导致角色人气有显著差异的特异点。")

# 1) 首先，从国区/日区分析结果里选出原始得票率和平均歌曲原始得票率，并重命名
df_cn = df_analysis_cn[[
    '角色名称_统一',
    '得票率',             # 角色原始得票率
    '平均歌曲得票率'      # 歌曲原始得票率平均
]].rename(columns={
    '得票率': '国区_raw_rate',
    '平均歌曲得票率': '国区_avg_song_rate'
})

df_jp = df_analysis_jp[[
    '角色名称_统一',
    '得票率',
    '平均歌曲得票率'
]].rename(columns={
    '得票率': '日区_raw_rate',
    '平均歌曲得票率': '日区_avg_song_rate'
})

# 2) 合并两者
df_final_diff_analysis = pd.merge(
    df_cn,
    df_jp,
    on='角色名称_统一',
    how='outer'
).fillna(0)

# 先在 df_final_diff_analysis 中计算 raw_rate_CN、raw_rate_JP、avg_song_rate_CN、avg_song_rate_JP
# 然后：
df_final_diff_analysis['char_ratio']  = df_final_diff_analysis['国区_raw_rate']  / df_final_diff_analysis['日区_raw_rate']
df_final_diff_analysis['music_ratio'] = df_final_diff_analysis['国区_avg_song_rate'] / df_final_diff_analysis['日区_avg_song_rate']

# impact = df_final_diff_analysis[
#     (abs(df_final_diff_analysis['char_ratio'] - 1) > PROPORTION_THRESHOLD_CROSS_REGION) &
#     (abs(df_final_diff_analysis['music_ratio'] - 1) > PROPORTION_THRESHOLD_CROSS_REGION)
# ]

impact = df_final_diff_analysis[
    abs(df_final_diff_analysis['char_ratio']/df_final_diff_analysis['music_ratio'] - 1) > PROPORTION_THRESHOLD_CROSS_REGION
]
if not impact.empty:
    print("\n**受歌曲人气差异显著影响的角色（比例偏离）：**")
    for _, row in impact.iterrows():
        name = row['角色名称_统一']
        cr = row['char_ratio'] if row['char_ratio'] > 1 else 1 / row['char_ratio']
        mr = row['music_ratio'] if row['music_ratio'] > 1 else 1 / row['music_ratio']
        print(f"- **{name}**: 角色偏离={cr:.2f}, 歌曲偏离={mr:.2f}")
else:
    print("未发现因歌曲差异而导致角色人气有显著比例偏离的特异点。")

# plt.figure(figsize=(10, 7))
# sns.scatterplot(x='角色自身人气差异', y='关联歌曲平均人气差异', data=df_final_diff_analysis)
# plt.title('角色自身人气差异 vs. 关联歌曲平均人气差异')
# plt.xlabel('角色自身中日人气差异 (国区 - 日区)')
# plt.ylabel('关联歌曲平均中日人气差异 (国区 - 日区)')
# plt.grid(True)
# plt.axhline(0, color='grey', linestyle='--', linewidth=0.8)
# plt.axvline(0, color='grey', linestyle='--', linewidth=0.8)

# if not impact_characters.empty:
#     for idx, row in impact_characters.iterrows():
#         plt.text(row['角色自身人气差异'], row['关联歌曲平均人气差异'], row['角色名称_统一'],
#                  ha='center', va='bottom', fontsize=9, color='red')

# plt.show()


# ---
## 新增模块：仅输出国区与日区独有曲目

print("\n--- 独有歌曲列表 ---")

# 提取国区和日区的歌曲名称（使用清洗后的数据）
cn_music_names = set(df_music_cn_grouped[COL_MUSIC_NAME_CN].dropna().unique())
jp_music_names = set(df_music_jp_grouped[COL_MUSIC_NAME_JP].dropna().unique())

# 国区独有歌曲
cn_only_music = cn_music_names.difference(jp_music_names)
print(f"\n**国区独有歌曲 ({len(cn_only_music)} 首):**")
if len(cn_only_music) > 0:
    for i, song in enumerate(sorted(list(cn_only_music))): # 排序后输出，方便查看
        print(f"- {song}")
else:
    print("无国区独有歌曲。")

# 日区独有歌曲
jp_only_music = jp_music_names.difference(cn_music_names)
print(f"\n**日区独有歌曲 ({len(jp_only_music)} 首):**")
if len(jp_only_music) > 0:
    for i, song in enumerate(sorted(list(jp_only_music))): # 排序后输出，方便查看
        print(f"- {song}")
else:
    print("无日区独有歌曲。")

print("\n独有歌曲输出完成。")

# 统一在一个 Figure 中绘制三个子图：国区、人区、和跨区域差异
fig, axes = plt.subplots(1, 3, figsize=(20, 6))

# 子图 1：国区 角色 vs 平均歌曲人气
sns.scatterplot(
    x='标准化得票率', y='平均歌曲标准化得票率',
    data=df_analysis_cn, ax=axes[0]
)
axes[0].set_title('国区：角色人气 vs. 平均歌曲人气')
axes[0].set_xlabel('角色标准化得票率')
axes[0].set_ylabel('平均歌曲标准化得票率')
axes[0].grid(True)
axes[0].text(
    0.05, 0.95,
    f'Spearman r = {correlation_cn:.2f}\np-value = {pvalue_cn:.3f}',
    transform=axes[0].transAxes,
    fontsize=12, verticalalignment='top',
    bbox=dict(boxstyle='round,pad=0.5', fc='wheat', alpha=0.5)
)

# 在国区图上标注超标点
for _, row in outliers_cn_internal.iterrows():
    axes[0].text(row['标准化得票率'], row['平均歌曲标准化得票率'],
            row['角色名称_统一'],
            fontsize=9, ha='right', va='bottom')

# 子图 2：日区 角色 vs 平均歌曲人气
sns.scatterplot(
    x='标准化得票率', y='平均歌曲标准化得票率',
    data=df_analysis_jp, ax=axes[1]
)
axes[1].set_title('日区：角色人气 vs. 平均歌曲人气')
axes[1].set_xlabel('角色标准化得票率')
axes[1].set_ylabel('平均歌曲标准化得票率')
axes[1].grid(True)
axes[1].text(
    0.05, 0.95,
    f'Spearman r = {correlation_jp:.2f}\np-value = {pvalue_jp:.3f}',
    transform=axes[1].transAxes,
    fontsize=12, verticalalignment='top',
    bbox=dict(boxstyle='round,pad=0.5', fc='wheat', alpha=0.5)
)

for _, row in outliers_jp_internal.iterrows():
    axes[1].text(row['标准化得票率'], row['平均歌曲标准化得票率'],
            row['角色名称_统一'],
            fontsize=9, ha='right', va='bottom')


# 子图 3：跨区域 差异分析
sns.scatterplot(
    x='char_ratio', y='music_ratio',
    data=df_final_diff_analysis, ax=axes[2]
)
axes[2].set_title('跨区域：自身人气差异 vs. 歌曲人气差异')
axes[2].set_xlabel('角色自身中日人气差异 (国区 - 日区)')
axes[2].set_ylabel('关联歌曲平均中日人气差异 (国区 - 日区)')
axes[2].grid(True)
axes[2].axhline(0, color='grey', linestyle='--', linewidth=0.8)
axes[2].axvline(0, color='grey', linestyle='--', linewidth=0.8)

# 标记显著影响的角色
for idx, row in impact.iterrows():
    axes[2].text(
        row['char_ratio'],
        row['music_ratio'],
        row['角色名称_统一'],
        ha='center', va='bottom', fontsize=9, color='red'
    )

plt.tight_layout()
plt.show()
