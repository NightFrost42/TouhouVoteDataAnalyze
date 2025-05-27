import pandas as pd
import matplotlib.pyplot as plt

# ===== 用户配置区域 =====
TARGET_CN_NAME = "琪露诺"    # 要分析的中文角色名
CN_SHEET_NAME = "11"         # 中文版分析的Sheet名称
JP_SHEET_NAME = "20"     # 日文版分析的Sheet名称
# =======================

# 1. 读取名称对照表
name_mapping = pd.read_excel('fun.xlsx').set_index('译名')['日文名'].to_dict()

# 2. 验证角色存在性
if TARGET_CN_NAME not in name_mapping:
    raise ValueError(f"角色'{TARGET_CN_NAME}'在对照表中不存在")
target_jp = name_mapping[TARGET_CN_NAME]

# 3. 定义核心查询函数
def analyze_sheet(excel_grouped, excel_raw, sheet_name, target_col, target_name):
    try:
        # 读取数据
        df_group = pd.read_excel(excel_grouped, sheet_name=sheet_name)
        df_raw = pd.read_excel(excel_raw, sheet_name=sheet_name)
    except ValueError:
        raise ValueError(f"Sheet '{sheet_name}'不存在")

    # 验证数据列
    if '票数' not in df_group.columns or target_col not in df_group.columns:
        raise ValueError(f"Sheet '{sheet_name}'缺少必要列")

    # 计算总票数
    total_votes = df_raw['票数'].sum()
    if total_votes == 0:
        raise ValueError(f"Sheet '{sheet_name}'总票数为0")

    # 获取目标数据
    target_data = df_group[df_group[target_col] == target_name]
    if target_data.empty:
        raise ValueError(f"Sheet '{sheet_name}'未找到'{target_name}'")

    return (target_data['票数'].iloc[0] / total_votes) * 100

# 4. 执行分析
try:
    cn_pct = analyze_sheet('TouhouVote_cn_grouped.xlsx', 'TouhouVote_cn.xlsx',
                          CN_SHEET_NAME, '译名', TARGET_CN_NAME)
    jp_pct = analyze_sheet('TouhouVote_jp_grouped.xlsx', 'TouhouVote_jp.xlsx',
                          JP_SHEET_NAME, '日文名', target_jp)
except Exception as e:
    print(f"分析失败: {str(e)}")
    exit()

# 5. 输出结果
diff = round(cn_pct - jp_pct, 2)
print(f"[角色分析报告] {TARGET_CN_NAME} ({target_jp})")
print("═" * 40)
print(f"中文版 Sheet [{CN_SHEET_NAME}]: {cn_pct:.2f}%")
print(f"日文版 Sheet [{JP_SHEET_NAME}]: {jp_pct:.2f}%")
print(f"比例差值: {diff}% (+表示中文更高)")

# 6. 可视化对比
plt.figure(figsize=(10, 5))
ax = plt.subplot()

# 绘制双柱状图
positions = [0.2, 0.6]
colors = ['#2E86C1', '#E74C3C']
bars = ax.bar(positions, [cn_pct, jp_pct], 
             width=0.3, color=colors, 
             edgecolor='black', linewidth=1)

# 图表装饰
ax.set_xticks(positions)
ax.set_xticklabels([f'国区', f'日区'])
plt.ylabel('得票比例 (%)', fontsize=12)
plt.title(f"角色人气对比: {TARGET_CN_NAME} vs {target_jp}", pad=20)
plt.grid(axis='y', alpha=0.3)
plt.rcParams['font.sans-serif'] = ['SimHei']  # 解决中文乱码

# 添加数据标签
for bar, value in zip(bars, [cn_pct, jp_pct]):
    height = bar.get_height()
    ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
            f'{value:.2f}%', ha='center', va='bottom')

# 绘制差值箭头
ymax = max(cn_pct, jp_pct) + 5
ax.annotate('', xy=(0.4, ymax-2), xytext=(0.4, ymax-8),
            arrowprops=dict(arrowstyle="->", lw=1.5))
ax.text(0.4, ymax, f'差值: {diff}%', 
        ha='center', va='bottom', fontsize=12)

plt.tight_layout()
plt.show()