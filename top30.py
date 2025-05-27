import pandas as pd
import matplotlib.pyplot as plt

# 参数配置
EXCEL_FILE = "TouhouVote_jp_grouped.xlsx"  # 输入文件路径（多 Sheet）
EXCEL_FILE_RAW = 'TouhouVote_jp.xlsx'
# OUTPUT_IMAGE = "top7_percentage.png"  # 输出图片路径

# 1. 读取所有 Sheet 并按数字升序排序
all_sheets = pd.read_excel(EXCEL_FILE, sheet_name=None)
raw_sheets = pd.read_excel(EXCEL_FILE_RAW, sheet_name=None)

# 提取 Sheet 名并转换为整数排序（例如 "1", "2" → 1, 2）
try:
    sheet_names = sorted(all_sheets.keys(), key=lambda x: int(x))
except ValueError:
    raise ValueError("Sheet 名必须为可转换为整数的字符串（如 '1', '2'）")

# 2. 处理每个 Sheet，计算前30名占比
results = []  # 保存结果：[{"Sheet": 名称, "前30名占比": 百分比}, ...]

for sheet_name in sheet_names:
    df = all_sheets[sheet_name]
    try:
        # 检查必要列是否存在
        if "票数" not in df.columns:
            print(f"警告：Sheet '{sheet_name}' 缺少列 '票数'，已跳过")
            continue
        
        # 计算总票数（忽略总票数为0的Sheet）
        total_votes = raw_sheets[sheet_name]["票数"].sum()
        if total_votes == 0:
            print(f"警告：Sheet '{sheet_name}' 总票数为0，已跳过")
            continue
        
        # 按票数降序排序，取前30名
        df_sorted = df.sort_values("票数", ascending=False)
        top7_votes = df_sorted["票数"].head(30).sum()
        
        # 计算前30名占比
        percentage = (top7_votes / total_votes) * 100
        results.append({
            "Sheet": sheet_name,
            "前30名占比": round(percentage, 2)
        })
        
    except Exception as e:
        print(f"处理 Sheet '{sheet_name}' 时出错: {str(e)}")
        continue

# 3. 转换为 DataFrame 并检查数据
if not results:
    raise ValueError("没有有效数据可绘制图表！")
result_df = pd.DataFrame(results)

# 4. 绘制趋势图
plt.figure(figsize=(12, 6))
plt.plot(result_df["Sheet"], result_df["前30名占比"], marker='o', linestyle='-', color='#E74C3C')
plt.title("各 Sheet 前30名票数占比趋势", fontsize=14)
plt.xlabel("Sheet 名称（数字序号）", fontsize=12)
plt.ylabel("前30名票数占比 (%)", fontsize=12)
plt.xticks(rotation=45)
plt.grid(True, linestyle='--', alpha=0.6)
plt.rcParams['font.sans-serif'] = ['SimHei']  # 解决中文乱码
plt.ylim(0, 105)  # 固定纵轴范围

# 添加数据标签
for x, y in zip(result_df["Sheet"], result_df["前30名占比"]):
    plt.text(x, y, f"{y}%", ha='center', va='bottom', fontsize=9)

plt.tight_layout()
# plt.savefig(OUTPUT_IMAGE, dpi=300, bbox_inches='tight')
plt.show()

# print(f"处理完成！图表已保存为 {OUTPUT_IMAGE}")