import os
import hashlib
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import jieba
from collections import Counter
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
output_dir = "CharacterTagAnalyze-results-freq"

os.makedirs(cache_dir, exist_ok=True)
os.makedirs(output_dir, exist_ok=True)

session = requests.Session()
retries = Retry(total=3, backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET"])
adapter = HTTPAdapter(max_retries=retries)
session.mount('http://', adapter)
session.mount('https://', adapter)
headers = {"User-Agent": "Mozilla/5.0"}

def url_to_filename(url):
    h = hashlib.md5(url.encode('utf-8')).hexdigest()
    return os.path.join(cache_dir, f"{h}.txt")

stopwords = set(remove_keywords)
try:
    with open(stopwords_path, 'r', encoding='utf-8') as f:
        stopwords |= {w.strip() for w in f if w.strip()}
except FileNotFoundError:
    print("Warning: 停用词文件不存在，仅使用 remove_keywords")

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
    name_to_docs[key] = []
    for suf in suffixes:
        name_to_docs[key].append(base_url + key + suf)

name_set = set(name_to_docs.keys())

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

def is_single_letter_or_digit(w):
    return bool(re.fullmatch(r"[A-Za-z0-9]", w))

for name, urls in name_to_docs.items():
    texts = [fetch_text(url) for url in urls]
    combined = ' '.join(t for t in texts if t)
    words = jieba.lcut(combined)
    filtered = [w for w in words if w not in stopwords and w not in name_set and not is_single_letter_or_digit(w) and len(w.strip()) > 1]
    counter = Counter(filtered)
    top_items = counter.most_common(20)

    df_k = pd.DataFrame(top_items, columns=["keyword", "freq"])
    df_k.to_csv(os.path.join(output_dir, f"{name}_combined_top20_freq.csv"), index=False, encoding='utf-8-sig')

    wc = WordCloud(font_path=font_path, width=800, height=600, background_color="white")
    wc.generate_from_frequencies(dict(counter))
    wc.to_file(os.path.join(output_dir, f"{name}_combined_wordcloud_freq.png"))

    print(f"Processed frequency-based results for {name}")

print("All frequency-based analyses complete. Files saved in:", output_dir)