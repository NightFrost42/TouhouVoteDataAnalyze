import pandas as pd
import matplotlib.pyplot as plt
import re

# 参数配置
EXCEL_FILE = "TouhouVote_jp_grouped.xlsx"  # 输入文件路径（包含首次出现作品和票数）
EXCEL_FILE_RAW = 'TouhouVote_jp.xlsx'
OUTPUT_IMAGE = "group_percentages.png"  # 输出图片路径

def extract_number(group_value):
    # 处理 NaN 值
    if pd.isna(group_value):
        return float('inf')
    # 正则提取数字部分（含小数点）
    match = re.match(r'^(\d+)', group_value)
    if match:
        try:
            # 转换为浮点数
            return float(match.group(1))
        except:
            return float('inf')
    else:
        # 没有匹配到数字的情况
        return float('inf')

# 1. 读取所有 Sheet 并按数字升序排序
all_sheets = pd.read_excel(EXCEL_FILE, sheet_name=None)
raw_sheets = pd.read_excel(EXCEL_FILE_RAW, sheet_name=None)


# 提取 Sheet 名并转换为整数排序（例如 "1", "2" → 1, 2）
try:
    sheet_names = sorted(all_sheets.keys(), key=lambda x: extract_number(x))
except ValueError:
    raise ValueError("Sheet 名必须为可转换为整数的字符串（如 '1', '2'）")

# 2. 处理每个 Sheet，计算各组的百分比
results = []  # 保存结果：[{"Sheet": 名称, "首次出现作品": 组名, "百分比": 值}, ...]

for sheet_name in sheet_names:
    df = all_sheets[sheet_name]
    df['首次出现作品'] = df['首次出现作品'].astype(float)

    # 检查必要列是否存在
    if "首次出现作品" not in df.columns or "票数" not in df.columns:
        print(f"警告：Sheet '{sheet_name}' 缺少列 '首次出现作品' 或 '票数'，已跳过")
        continue
    
    # 计算总票数（忽略总票数为0的Sheet）
    total_votes = raw_sheets[sheet_name]["票数"].sum()
    if total_votes == 0:
        print(f"警告：Sheet '{sheet_name}' 总票数为0，已跳过")
        continue
    
    # 按首次出现作品分组统计
    grouped = df.groupby("首次出现作品")["票数"].sum().reset_index()
    grouped["百分比"] = (grouped["票数"] / total_votes * 100).round(2)
    
    # 记录结果
    for _, row in grouped.iterrows():
        results.append({
            "Sheet": sheet_name,
            "首次出现作品": row["首次出现作品"],
            "百分比": row["百分比"]
        })


# 3. 检查数据有效性
if not results:
    raise ValueError("没有有效数据可绘制图表！")
result_df = pd.DataFrame(results)

result_df["首次出现作品"] = pd.to_numeric(result_df["首次出现作品"], errors="coerce")

# 4. 绘制点线图
plt.figure(figsize=(12, 6))

# 获取所有首次出现作品和颜色配置
# 按浮点数值直接排序（处理 NaN）
groups = sorted(
    result_df["首次出现作品"].unique(),
    key=lambda x: float(x)
)
# 定义颜色和标记样式（扩展更多选项）
colors = plt.cm.tab20(range(len(groups)))  # 从 tab10 改为 tab20，支持更多颜色
markers = ['o', 's', '^', 'D', 'v', 'p', '*', 'X', 'h', '+', 'x', '|', '1', '2', '3', '4']  # 扩展更多标记样式

# 遍历每个组别，分别绘制线条
for idx, group in enumerate(groups):
    group_data = result_df[result_df["首次出现作品"] == group]
    group_data = group_data.sort_values("Sheet", key=lambda col: col.apply(extract_number))
    plt.plot(
        group_data["Sheet"],
        group_data["百分比"],
        label=group,
        marker=markers[idx % len(markers)],
        linestyle='-',
        color=colors[idx % len(colors)],
        markersize=8,
        linewidth=2
    )

# 图表美化
plt.title("各组的票数占比趋势（按 Sheet 顺序）", fontsize=14)
plt.xlabel("Sheet 名称（数字序号）", fontsize=12)
plt.ylabel("票数占比 (%)", fontsize=12)
plt.xticks(rotation=45)
plt.grid(True, linestyle='--', alpha=0.6)
plt.legend(loc='upper left', bbox_to_anchor=(1, 1))  # 图例放在右侧
plt.rcParams['font.sans-serif'] = ['SimHei']  # 解决中文乱码
plt.tight_layout()

# 保存图片
plt.savefig(OUTPUT_IMAGE, dpi=300, bbox_inches='tight')
plt.show()

print(f"处理完成！图表已保存为 {OUTPUT_IMAGE}")

