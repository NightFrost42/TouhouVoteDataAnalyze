
import os
import hashlib
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import jieba
import jieba.analyse
from wordcloud import WordCloud
import matplotlib.pyplot as plt
import re

# === 配置区 ===
excel_path = "TouhouVote_jp_grouped.xlsx"    # Excel 文件路径，包含一列 "译名 "
sheet_name = "20"                          # 要读取的 Sheet 名称或索引
base_url = "https://thbwiki.cc/"           # 基础域名，确保以 '/' 结尾
# suffixes = ["/二次设定", "/分析考据", "/"]  # 每个 partial_path 后要拼接的特定地址列表
suffixes = ["/二次设定", "/"]  # 每个 partial_path 后要拼接的特定地址列表
remove_keywords = ["的", "我们", "公司", "产品"]  # 强制过滤词
stopwords_path = "stopwords.txt"            # 停用词文件（可选）
font_path = r"方正书宋简体.ttf"  # 词云字体路径，根据系统调整
cache_dir = "cache_data"                   # 本地缓存目录
output_dir = "CharacterTagAnalyze-results-textrank"                     # 输出目录，用于保存结果

# === 初始化目录 ===
os.makedirs(cache_dir, exist_ok=True)
os.makedirs(output_dir, exist_ok=True)

# === 请求会话配置 ===
session = requests.Session()
retries = Retry(total=3, backoff_factor=1,
                status_forcelist=[429,500,502,503,504],
                allowed_methods=["GET"])
adapter = HTTPAdapter(max_retries=retries)
session.mount('http://', adapter)
session.mount('https://', adapter)
headers = {"User-Agent": "Mozilla/5.0"}

# === 工具函数 ===
def url_to_filename(url):
    h = hashlib.md5(url.encode('utf-8')).hexdigest()
    return os.path.join(cache_dir, f"{h}.txt")

# 读取停用词
stopwords = set(remove_keywords)
try:
    with open(stopwords_path, 'r', encoding='utf-8') as f:
        stopwords |= {w.strip() for w in f if w.strip()}
except FileNotFoundError:
    print("Warning: 停用词文件不存在，仅使用 remove_keywords")

# === 1. 构建 URL 列表及名称列表 ===
df = pd.read_excel(excel_path, sheet_name=sheet_name)
df = df.dropna(subset=["译名 "])
name_to_docs = {}
for name in df["译名 "]:
    text = str(name)
    if text == "蕾拉·普莉兹姆利巴":
        continue
    text = re.sub(r"（.*?）", "", text)
    text = text.replace("天为", "帝")
    key = text.lstrip('/').strip()
    name_to_docs[key] = []
    for suf in suffixes:
        url = base_url + key + suf
        name_to_docs[key].append(url)

# 构建译名集合，用于过滤关键词
name_set = set(name_to_docs.keys())

# === 2. 获取并缓存网页文本 ===
def fetch_text(url):
    cache_file = url_to_filename(url)
    if os.path.exists(cache_file):
        return open(cache_file, 'r', encoding='utf-8').read()
    try:
        r = session.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        text = BeautifulSoup(r.text, 'html.parser').get_text(separator=' ', strip=True)
        with open(cache_file, 'w', encoding='utf-8') as f:
            f.write(text)
        return text
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return ""

# 合并每个 name 对应 suffix 文档内容
combined_docs = []
names = []
for name, urls in name_to_docs.items():
    texts = [fetch_text(url) for url in urls]
    combined = ' '.join([t for t in texts if t])
    combined_docs.append(combined)
    names.append(name)

# 判断是否为单字母或单数字
def is_single_letter_or_digit(w):
    return bool(re.fullmatch(r"[A-Za-z0-9]", w))

# === 3. 使用 TextRank 提取关键词并绘制词云 ===
for idx, name in enumerate(names):
    doc = combined_docs[idx]
    keywords = jieba.analyse.textrank(
        doc, topK=50, withWeight=True, allowPOS=('ns', 'n', 'vn', 'v'))
    scores = {
        word: weight for word, weight in keywords
        if word not in stopwords and word not in name_set and not is_single_letter_or_digit(word)
    }
    top_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:20]
    df_k = pd.DataFrame(top_items, columns=["keyword", "textrank"])
    df_k.to_csv(os.path.join(output_dir, f"{name}_combined_top20_textrank.csv"),
                index=False, encoding='utf-8-sig')

    wc = WordCloud(font_path=font_path, width=800, height=600,
                   background_color="white")
    wc.generate_from_frequencies(scores)
    wc.to_file(os.path.join(output_dir, f"{name}_combined_wordcloud_textrank.png"))
    print(f"Processed TextRank results for {name}")

print("All TextRank-based analyses complete. Files saved in:", output_dir)
