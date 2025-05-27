import os
import hashlib
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import jieba
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.decomposition import LatentDirichletAllocation
from wordcloud import WordCloud
import matplotlib.pyplot as plt
import re

# === 配置区 ===
excel_path = "TouhouVote_jp_grouped.xlsx"
sheet_name = "20"
base_url = "https://thbwiki.cc/"
# suffixes = ["/二次设定", "/分析考据", "/"]
suffixes = ["/二次设定", "/"]
remove_keywords = ["的", "我们", "公司", "产品"]
stopwords_path = "stopwords.txt"
font_path = r"方正书宋简体.ttf"
cache_dir = "cache_data"
output_dir = "CharacterTagAnalyze-results-LDA"
num_topics = 20                 # LDA 主题数
num_words = 30                # 每个主题关键词数

# 初始化目录
os.makedirs(cache_dir, exist_ok=True)
os.makedirs(output_dir, exist_ok=True)

# 请求会话配置
session = requests.Session()
retries = Retry(total=3, backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET"])
adapter = HTTPAdapter(max_retries=retries)
session.mount('http://', adapter)
session.mount('https://', adapter)
headers = {"User-Agent": "Mozilla/5.0"}

# 工具函数
def url_to_filename(url):
    h = hashlib.md5(url.encode('utf-8')).hexdigest()
    return os.path.join(cache_dir, f"{h}.txt")

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

# 加载停用词
stopwords = set(remove_keywords)
try:
    with open(stopwords_path, 'r', encoding='utf-8') as f:
        stopwords |= {w.strip() for w in f if w.strip()}
except FileNotFoundError:
    print("Warning: 停用词文件不存在，仅使用 remove_keywords")

# 词过滤函数
def is_single_letter_or_digit(w):
    return bool(re.fullmatch(r"[A-Za-z0-9]", w))

def is_number(w):
    return bool(re.fullmatch(r"\d+", w))

# 构建 URL 列表和译名集合
df = pd.read_excel(excel_path, sheet_name=sheet_name)
df = df.dropna(subset=["译名 "])
name_to_docs = {}
for name in df["译名 "]:
    text = str(name)
    if text == "蕾拉·普莉兹姆利巴":
        continue
    text = re.sub(r"（.*?）", "", text)
    text = text.replace("天为", "帝")
    key = text.strip()
    name_to_docs[key] = [base_url + key + suf for suf in suffixes]

name_set = set(name_to_docs.keys())

# 合并文档并预处理分词
combined_preprocessed = []
names = []
for name, urls in name_to_docs.items():
    texts = [fetch_text(url) for url in urls]
    combined = ' '.join([t for t in texts if t])
    tokens = []
    for w in jieba.lcut(combined):
        w = w.strip()
        if not w:
            continue
        if w in stopwords:
            continue
        if w in name_set:
            continue
        if is_single_letter_or_digit(w) or is_number(w):
            continue
        if len(w) <= 1:
            continue
        tokens.append(w)
    combined_preprocessed.append(' '.join(tokens))
    names.append(name)

# LDA 分析
vectorizer = CountVectorizer(token_pattern=r"(?u)\b\w+\b")
dtm = vectorizer.fit_transform(combined_preprocessed)
lda = LatentDirichletAllocation(n_components=num_topics, random_state=0)
lda.fit(dtm)
feature_names = vectorizer.get_feature_names_out()

# 输出主题关键词和词云
for topic_idx, topic in enumerate(lda.components_):
    top_indices = topic.argsort()[:-num_words-1:-1]
    top_features = [(feature_names[i], topic[i]) for i in top_indices]
    # 保存主题关键词
    df_t = pd.DataFrame(top_features, columns=["word", "weight"])
    df_t.to_csv(os.path.join(output_dir, f"LDA_topic_{topic_idx}.csv"),
                index=False, encoding='utf-8-sig')
    # 生成词云
    weights = {word: weight for word, weight in top_features}
    wc = WordCloud(font_path=font_path, width=800, height=600,
                   background_color="white")
    wc.generate_from_frequencies(weights)
    wc.to_file(os.path.join(output_dir, f"LDA_topic_{topic_idx}_wordcloud.png"))
    print(f"Saved LDA topic {topic_idx}")

print("LDA analysis complete. Files in", output_dir)