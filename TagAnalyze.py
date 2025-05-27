import os
import hashlib
import pandas as pd
import requests
from bs4 import BeautifulSoup
import jieba
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from sklearn.feature_extraction.text import TfidfVectorizer
from wordcloud import WordCloud
import matplotlib.pyplot as plt
import re  # 用于清理字符串

# === 配置区 ===
excel_path = "TouhouVote_jp_grouped.xlsx"                 # Excel 文件路径，包含一列 "partial_path"
sheet_name = "20"                       # 要读取的 Sheet 名称或索引
base_url = "https://thbwiki.cc/"        # 基础域名，确保以 '/' 结尾
suffixes = ["/二次设定", "/分析考据","/"]       # 每个 partial_path 后要拼接的特定地址列表
remove_keywords = ["的", "我们", "公司", "产品"]
stopwords_path = "stopwords.txt"         # 停用词文件（可选）
font_path = "E:\School\Touhou\\fun\方正书宋简体.ttf"  # 词云字体路径，根据系统调整
cache_dir = "cache_data"                # 本地缓存目录，存放抓取结果

# === 初始化缓存目录 ===
os.makedirs(cache_dir, exist_ok=True)

# === 配置请求重试机制 ===
session = requests.Session()
retries = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"]
)
adapter = HTTPAdapter(max_retries=retries)
session.mount('http://', adapter)
session.mount('https://', adapter)
headers = {"User-Agent": "Mozilla/5.0"}

# === 辅助函数: URL 到缓存文件名 ===
def url_to_filename(url):
    h = hashlib.md5(url.encode('utf-8')).hexdigest()
    return os.path.join(cache_dir, f"{h}.txt")

# === 1. 构建完整 URL 列表 ===
df = pd.read_excel(excel_path, sheet_name=sheet_name)
df = df.dropna(subset=["译名 "])
urls = []
for partial in df["译名 "]:
    text = str(partial)
    # 跳过指定名称
    if text == "蕾拉·普莉兹姆利巴":
        continue
    # 清除中文括号及其中内容
    text = re.sub(r"（.*?）", "", text)
    # 替换“天为”为“帝”
    text = text.replace("天为", "帝")
    # 去除前导斜杠
    p = text.lstrip('/')
    # 拼接后缀
    for suf in suffixes:
        urls.append(base_url + p + suf)

# === 2. 爬取网页文本 ===
def fetch_text(url):
    cache_file = url_to_filename(url)
    if os.path.exists(cache_file):
        with open(cache_file, 'r', encoding='utf-8') as f:
            return f.read()
    try:
        r = session.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        text = soup.get_text(separator=' ', strip=True)
        with open(cache_file, 'w', encoding='utf-8') as f:
            f.write(text)
        return text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return ""

documents = [fetch_text(u) for u in urls]

# === 3. 文本预处理与分词 ===
stopwords = set()
try:
    with open(stopwords_path, 'r', encoding='utf-8') as f:
        stopwords = {w.strip() for w in f if w.strip()}
except FileNotFoundError:
    print("Warning: 停用词文件不存在，仅使用 remove_keywords")
stopwords |= set(remove_keywords)
print(stopwords)

tokenized_docs = []
for doc in documents:
    words = [w for w in jieba.cut(doc) if w.strip() and w not in stopwords]
    tokenized_docs.append(" ".join(words))

# === 4. TF-IDF 分析 ===
vectorizer = TfidfVectorizer()
tfidf_matrix = vectorizer.fit_transform(tokenized_docs)
feature_names = vectorizer.get_feature_names_out()

# 汇总权重
import numpy as np
global_scores = np.asarray(tfidf_matrix.sum(axis=0)).ravel()
# 过滤停用词
weights = {
    feature_names[i]: global_scores[i]
    for i in range(len(feature_names))
    if feature_names[i] not in stopwords
}

# 输出前20关键词
top20 = sorted(weights.items(), key=lambda x: x[1], reverse=True)[:20]
print("Top 20 Keywords:")
for w, s in top20:
    print(f"{w}: {s:.4f}")

# === 5. 生成词云 ===
wc = WordCloud(
    font_path=font_path,
    width=800, height=600,
    background_color="white"
)
wc.generate_from_frequencies(weights)

plt.figure(figsize=(10, 8))
plt.imshow(wc, interpolation='bilinear')
plt.axis('off')
plt.title('TF-IDF Keyword Word Cloud')
plt.tight_layout()
plt.show()
