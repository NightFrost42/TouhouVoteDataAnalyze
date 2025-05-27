import os
import hashlib
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import jieba
import jieba.analyse
from collections import Counter, defaultdict
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.decomposition import LatentDirichletAllocation
from sklearn.cluster import KMeans
import numpy as np
import re

# === 配置 ===
excel_path = "TouhouVote_jp_grouped.xlsx"
sheet_name = "20"
base_url = "https://thbwiki.cc/"
suffixes = ["/二次设定", "/分析考据", "/"]
remove_keywords = ["的", "我们", "公司", "产品"]
stopwords_path = "stopwords.txt"
cache_dir = "cache_data"
output_dir = "keyword_clusters"
num_clusters = 5

os.makedirs(cache_dir, exist_ok=True)
os.makedirs(output_dir, exist_ok=True)

# 停用词
stopwords = set(remove_keywords)
try:
    with open(stopwords_path, 'r', encoding='utf-8') as f:
        stopwords |= {line.strip() for line in f if line.strip()}
except:
    pass

# 工具函数
def clean_text(text):
    return re.sub(r"（.*?）", "", text).replace("天为", "帝").strip()

def is_valid_word(w):
    return len(w) > 1 and w not in stopwords and not re.fullmatch(r"[A-Za-z0-9]+", w) and not re.fullmatch(r"\d+", w)

def fetch_text(url):
    cache_file = os.path.join(cache_dir, hashlib.md5(url.encode()).hexdigest() + ".txt")
    if os.path.exists(cache_file):
        return open(cache_file, 'r', encoding='utf-8').read()
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        res.raise_for_status()
        text = BeautifulSoup(res.text, 'html.parser').get_text(separator=' ', strip=True)
        with open(cache_file, 'w', encoding='utf-8') as f:
            f.write(text)
        return text
    except:
        return ""

# 收集所有关键词上下文信息
df = pd.read_excel(excel_path, sheet_name=sheet_name).dropna(subset=["译名 "])
keyword_contexts = []  # (method, keyword, source)
entry_clean_texts = {}  # {entry: cleaned text}

for name in df["译名 "]:
    name = clean_text(str(name))
    if name == "蕾拉·普莉兹姆利巴": continue
    texts = [fetch_text(base_url + name + suf) for suf in suffixes]
    combined = ' '.join(t for t in texts if t)
    tokens = [w for w in jieba.lcut(combined) if is_valid_word(w)]
    full_text = ' '.join(tokens)
    entry_clean_texts[name] = full_text

    tfidf_keywords = jieba.analyse.extract_tags(full_text, topK=20, withWeight=False)
    textrank_keywords = [kw for kw, _ in jieba.analyse.textrank(full_text, topK=20, withWeight=True)]
    freq_keywords = [w for w, _ in Counter(tokens).most_common(20)]
    vectorizer = CountVectorizer()
    dtm = vectorizer.fit_transform([full_text])
    lda = LatentDirichletAllocation(n_components=1, random_state=0)
    lda.fit(dtm)
    lda_keywords = [vectorizer.get_feature_names_out()[i] for i in lda.components_[0].argsort()[-20:]]

    for method, words in zip(["tfidf", "textrank", "freq", "lda"], [tfidf_keywords, textrank_keywords, freq_keywords, lda_keywords]):
        for w in words:
            if is_valid_word(w):
                keyword_contexts.append((method, w, name))

# 构建共现矩阵并聚类
keyword_set = sorted({kw for _, kw, _ in keyword_contexts})
entry_list = sorted(entry_clean_texts.keys())
keyword_index = {kw: i for i, kw in enumerate(keyword_set)}
entry_index = {name: i for i, name in enumerate(entry_list)}

matrix = np.zeros((len(keyword_set), len(entry_list)))
for method, kw, entry in keyword_contexts:
    if kw in keyword_index and entry in entry_index:
        matrix[keyword_index[kw], entry_index[entry]] += 1

kmeans = KMeans(n_clusters=num_clusters, random_state=0).fit(matrix)
kw_labels = kmeans.labels_

# 保存结果
results = pd.DataFrame(keyword_contexts, columns=["method", "keyword", "source"])
results["cluster"] = results["keyword"].map(dict(zip(keyword_set, kw_labels)))

for method in ["tfidf", "textrank", "freq", "lda"]:
    df_m = results[results.method == method][["keyword", "cluster"]].drop_duplicates()
    df_m.to_csv(os.path.join(output_dir, f"keyword_clusters_{method}.csv"), index=False, encoding='utf-8-sig')

print("关键词聚类完成，结果保存在:", output_dir)