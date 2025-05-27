import pandas as pd
import matplotlib.pyplot as plt
import re

TARGET_NAME = 'チルノ'
EXCEL_FILE= 'TouhouVote_jp_grouped.xlsx'
EXCEL_FILE_RAW = 'TouhouVote_jp.xlsx'
OUTPUT_IMAGE = 'TouhouVote_character.png'

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

# 1. 读取所有 Sheet 并按键名（数字）升序排序
all_sheets = pd.read_excel(EXCEL_FILE, sheet_name=None)
raw_sheets = pd.read_excel(EXCEL_FILE_RAW, sheet_name=None)

# 提取 Sheet 名并转换为整数排序（例如 "1", "2" → 1, 2）
try:
    sorted_sheet_names = sorted(all_sheets.keys(), key=lambda x: extract_number(x))
except ValueError:
    raise ValueError("Sheet 名必须为可转换为整数的字符串（如 '1', '2'）")

# 2. 处理每个 Sheet
results = {}  # 保存结果：{Sheet名: 百分比}

for sheet_name in sorted_sheet_names:
    df = all_sheets[sheet_name]
    try:
        # 检查必要列是否存在
        if "日文名" not in df.columns or "票数" not in df.columns:
            print(f"警告：Sheet '{sheet_name}' 缺少列 '名字' 或 '票数'，已跳过")
            continue
        
        # 计算总票数（忽略票数为0的Sheet）
        total_votes = raw_sheets[sheet_name]["票数"].sum()
        if total_votes == 0:
            print(f"警告：Sheet '{sheet_name}' 总票数为0，已跳过")
            continue
        
        # 查找目标人物的票数（若不存在或票数为0则跳过）
        target_row = df[df["日文名"] == TARGET_NAME]
        if target_row.empty:
            print(f"警告：Sheet '{sheet_name}' 中未找到 '{TARGET_NAME}'，已跳过")
            continue
        target_votes = target_row["票数"].iloc[0]  # 假设每个名字在Sheet内唯一
        if target_votes == 0:
            print(f"警告：Sheet '{sheet_name}' 中 '{TARGET_NAME}' 票数为0，已跳过")
            continue
        
        # 计算百分比
        percentage = (target_votes / total_votes) * 100
        results[sheet_name] = round(percentage, 2)
        
    except Exception as e:
        print(f"处理 Sheet '{sheet_name}' 时出错: {str(e)}")
        continue

# 3. 检查是否有有效数据
if not results:
    raise ValueError("没有有效数据可绘制图表！")

# 4. 转换为 DataFrame（已按 Sheet 名升序排列）
result_df = pd.DataFrame(
    list(results.items()),
    columns=["Sheet名称", "百分比"]
)

# 5. 绘制趋势图
plt.figure(figsize=(10, 6))
plt.plot(result_df["Sheet名称"], result_df["百分比"], marker='o', linestyle='-', color='#2E86C1')
plt.rcParams['font.sans-serif'] = ['SimHei']  # 解决中文乱码
plt.title(f"'{TARGET_NAME}' 在各 Sheet 中的得票占比（按数字顺序）")
plt.xlabel("Sheet 名称（数字序号）")
plt.ylabel("得票占比 (%)")
plt.xticks(rotation=45)
plt.grid(True, linestyle='--', alpha=0.7)

# 添加数据标签
for x, y in zip(result_df["Sheet名称"], result_df["百分比"]):
    plt.text(x, y, f"{y}%", ha='center', va='bottom', fontsize=9)

plt.tight_layout()
# plt.savefig(OUTPUT_IMAGE, dpi=300)s
plt.show()

# print(f"处理完成！图表已保存为 {OUTPUT_IMAGE}")