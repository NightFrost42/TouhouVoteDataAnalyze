import pandas as pd
import json
import re

# File paths
jp_grouped = 'TouhouVote_jp_grouped.xlsx'
jp_full = 'TouhouVote_jp.xlsx'
cn_grouped = 'TouhouVote_cn_grouped.xlsx'
cn_full = 'TouhouVote_cn.xlsx'
music_jp_grouped = 'TouhouVote_music_jp_grouped.xlsx'
music_jp_full = 'TouhouVote_music_jp.xlsx'
music_cn_grouped = 'TouhouVote_music_cn_grouped.xlsx'
music_cn_full = 'TouhouVote_music_cn.xlsx'
gender_file = 'TouhouVoteGenderInfo.xlsx'
tag_file = 'Character_tag.xlsx'

# Initialize data structure
data = {
    "meta": {"missing_gender": ["3_jp", "4_jp"], "jp_sessions": [], "cn_sessions": []},
    "characters": {},
    "songs": {},
    "gender": {},
    "indexes": {"by_work": {}, "by_session": {}}
}

# Helpers
def parse_session(sheet_name, suffix):
    m = re.match(r"^(\d+)", sheet_name)
    return f"{m.group(1)}_{suffix}" if m else sheet_name + f"_{suffix}"

def to_int(val):
    try:
        if pd.isna(val): return None
        return int(val)
    except:
        return None

def to_float(val):
    try:
        if pd.isna(val): return None
        return float(val)
    except:
        return None

# Clean string values
def clean_str(val):
    if val is None or (isinstance(val, float) and pd.isna(val)): return None
    if isinstance(val, float) and val.is_integer(): return str(int(val))
    return str(val).strip()

# --- JP Character Sessions ---
wb = pd.ExcelFile(jp_grouped)
for sheet in wb.sheet_names:
    sess = parse_session(sheet, 'jp')
    data['meta']['jp_sessions'].append(sess)
    df = wb.parse(sheet)
    df.columns = df.columns.str.strip()
    data['indexes']['by_session'][sess] = {'chars': [], 'songs': [], 'extra_works': []}
    for _, r in df.iterrows():
        tr = r.get('译名')
        if pd.isna(tr): continue
        tr = str(tr).strip()
        jp_name = None if pd.isna(r.get('日文名')) else str(r.get('日文名')).strip()
        cid = re.sub(r"\W+", "", tr).lower()
        fa = clean_str(r.get('首次出现作品'))
        if tr not in data['characters']:
            data['characters'][tr] = {'id': cid, 'jp_name': jp_name, 'first_appear': fa, 'keywords': [], 'sessions': {}}
            if fa: data['indexes']['by_work'].setdefault(fa, []).append(tr)
        stats = {
            'r': to_int(r.get('名次')),
            'prev_r': to_int(r.get('上回名次')),
            'prev2_r': to_int(r.get('上上回名次')),
            'v': to_int(r.get('票数')),
            'bnum': to_int(r.get('本名票数')),
            'comments': to_int(r.get('评论数')),
            'support': to_int(r.get('应援作品数'))
        }
        data['characters'][tr]['sessions'][sess] = stats
        data['indexes']['by_session'][sess]['chars'].append(tr)
    extra = re.findall(r"\(([^)]+)\)", sheet)
    if extra: data['indexes']['by_session'][sess]['extra_works'] = extra[0].split('、')

# --- JP Total Votes ---
wb = pd.ExcelFile(jp_full)
for sheet in wb.sheet_names:
    sess = parse_session(sheet, 'jp')
    if sess not in data['meta']['jp_sessions']: continue
    df = wb.parse(sheet); df.columns = df.columns.str.strip()
    tot = df['票数'].apply(to_int).dropna().sum()
    data['indexes']['by_session'][sess]['total_votes'] = int(tot) if tot is not None else None

# --- CN Character Sessions ---
wb = pd.ExcelFile(cn_grouped)
for sheet in wb.sheet_names:
    sess = parse_session(sheet, 'cn')
    data['meta']['cn_sessions'].append(sess)
    df = wb.parse(sheet); df.columns = df.columns.str.strip()
    data['indexes']['by_session'][sess] = {'chars': [], 'songs': []}
    for _, r in df.iterrows():
        tr = r.get('译名');
        if pd.isna(tr): continue
        tr = str(tr).strip()
        if tr not in data['characters']:
            fa = clean_str(r.get('首次出现作品'))
            data['characters'][tr] = {'id': re.sub(r"\W+", "", tr).lower(), 'jp_name': None, 'first_appear': fa, 'keywords': [], 'sessions': {}}
            if fa: data['indexes']['by_work'].setdefault(fa, []).append(tr)
        stats = {
            'r': to_int(r.get('名次')),
            'v': to_int(r.get('票数')),
            'bnum': to_int(r.get('本命数')),
            'brate': to_float(r.get('本命率')),
            'bw': to_float(r.get('本命加权')),
            'v_pct': to_float(r.get('票数占比')),
            'b_pct': to_float(r.get('本命占比')),
            'male_pct': to_float(r.get('男性比例')),
            'female_pct': to_float(r.get('女性比例'))
        }
        data['characters'][tr]['sessions'][sess] = stats
        data['indexes']['by_session'][sess]['chars'].append(tr)

# --- CN Total Votes ---
wb = pd.ExcelFile(cn_full)
for sheet in wb.sheet_names:
    sess = parse_session(sheet, 'cn')
    if sess not in data['meta']['cn_sessions']: continue
    df = wb.parse(sheet); df.columns = df.columns.str.strip()
    tot = df['票数'].apply(to_int).dropna().sum()
    data['indexes']['by_session'][sess]['total_votes'] = int(tot) if tot is not None else None

# --- JP Music Sessions ---
wb = pd.ExcelFile(music_jp_grouped)
for sheet in wb.sheet_names:
    sess = parse_session(sheet, 'jp')
    idx = data['indexes']['by_session'].setdefault(sess, {'chars': [], 'songs': []})
    df = wb.parse(sheet); df.columns = df.columns.str.strip()
    for _, r in df.iterrows():
        st = r.get('译名');
        if pd.isna(st): continue
        st = str(st).strip(); song_jp = None if pd.isna(r.get('曲目')) else str(r.get('曲目')).strip()
        chars = [] if pd.isna(r.get('所属角色')) else [c.strip() for c in str(r.get('所属角色')).split('|')]
        if st not in data['songs']:
            data['songs'][st] = {'t': song_jp, 'tr_t': st, 'chars': [], 'sessions': {}}
        for c in chars:
            if c not in data['songs'][st]['chars']: data['songs'][st]['chars'].append(c)
        stats = {
            'r': to_int(r.get('排名')),
            'prev_r': to_int(r.get('上回名次')),
            'prev2_r': to_int(r.get('上上回名次')),
            'v': to_int(r.get('得票数')),
            'main_v': to_int(r.get('本名票数')),
            'comments': to_int(r.get('评论数'))
        }
        data['songs'][st]['sessions'][sess] = stats
        idx['songs'].append(st)

# --- JP Music Total Votes ---
wb = pd.ExcelFile(music_jp_full)
for sheet in wb.sheet_names:
    sess = parse_session(sheet, 'jp')
    if sess not in data['indexes']['by_session']: continue
    df = wb.parse(sheet); df.columns = df.columns.str.strip()
    tot = df['得票数'].apply(to_int).dropna().sum()
    data['indexes']['by_session'][sess]['total_song_votes'] = int(tot) if tot is not None else None

# --- CN Music Sessions ---
wb = pd.ExcelFile(music_cn_grouped)
for sheet in wb.sheet_names:
    sess = parse_session(sheet, 'cn')
    idx = data['indexes']['by_session'].setdefault(sess, {'chars': [], 'songs': []})
    df = wb.parse(sheet); df.columns = df.columns.str.strip()
    for _, r in df.iterrows():
        st = r.get('译名');
        if pd.isna(st): continue
        st = str(st).strip()
        if st not in data['songs']: data['songs'][st] = {'t': None, 'tr_t': st, 'chars': [], 'sessions': {}}
        stats = {
            'r': to_int(r.get('名次')),
            'v': to_int(r.get('票数')),
            'bnum': to_int(r.get('本命数')),
            'brate': to_float(r.get('本命率')),
            'bw': to_float(r.get('本命加权')),
            'v_pct': to_float(r.get('票数占比')),
            'b_pct': to_float(r.get('本命占比')),
            'male': to_int(r.get('男性')),
            'male_pct': to_float(r.get('男性比')),
            'male_total_pct': to_float(r.get('占总数')),
            'female': to_int(r.get('女性')),
            'female_pct': to_float(r.get('女性比')),
            'female_total_pct': to_float(r.get('占总数.1')),
            'bias_orig': to_int(r.get('偏原作')),
            'bias_2nd': to_int(r.get('偏二次')),
            'no_bias': to_int(r.get('无偏爱')),
            'no_interest': to_int(r.get('都没兴趣'))
        }
        roles = [] if pd.isna(r.get('所属角色')) else [c.strip() for c in str(r.get('所属角色')).split('|')]
        for c in roles:
            if c not in data['songs'][st]['chars']: data['songs'][st]['chars'].append(c)
        data['songs'][st]['sessions'][sess] = stats
        idx['songs'].append(st)

# --- CN Music Total Votes ---
wb = pd.ExcelFile(music_cn_full)
for sheet in wb.sheet_names:
    sess = parse_session(sheet, 'cn')
    if sess not in data['indexes']['by_session']: continue
    df = wb.parse(sheet); df.columns = df.columns.str.strip()
    tot = df['票数'].apply(to_int).dropna().sum()
    data['indexes']['by_session'][sess]['total_song_votes'] = int(tot) if tot is not None else None

# --- Process Gender Info ---
wb = pd.ExcelFile(gender_file)
for sheet in wb.sheet_names:
    sess = parse_session(sheet, 'jp')
    df = wb.parse(sheet); df.columns = df.columns.str.strip()
    m_v = df[df['性别'] == '男性']['票数'].apply(to_int).sum(min_count=0)
    f_v = df[df['性别'] == '女性']['票数'].apply(to_int).sum(min_count=0)
    o_v = df[df['性别'] == '其他']['票数'].apply(to_int).sum(min_count=0)
    data['gender'][sess] = {
        'm': int(m_v) if pd.notna(m_v) and m_v > 0 else None,
        'f': int(f_v) if pd.notna(f_v) and f_v > 0 else None,
        'o': int(o_v) if pd.notna(o_v) and o_v > 0 else None
    }

# --- Process Character Tags ---
wb = pd.ExcelFile(tag_file)
# Assume single sheet
df_tag = wb.parse(wb.sheet_names[0])
df_tag.columns = df_tag.columns.str.strip()
for _, r in df_tag.iterrows():
    tr = r.get('译名')
    if pd.isna(tr): continue
    tr = str(tr).strip()
    kw_str = r.get('keywords')
    if pd.isna(kw_str): continue
    keywords = [kw.strip() for kw in str(kw_str).split('、') if kw.strip()]
    if tr in data['characters']:
        data['characters'][tr]['keywords'] = keywords
    else:
        # create entry if not existing
        data['characters'][tr] = {'id': re.sub(r"\W+", "", tr).lower(), 'jp_name': None, 'first_appear': None, 'keywords': keywords, 'sessions': {}}

# Sort sessions
data['meta']['jp_sessions'].sort(key=lambda x: int(x.split('_')[0]))
data['meta']['cn_sessions'].sort(key=lambda x: int(x.split('_')[0]))

# Output JSON
touhou_json = 'touhou_vote.json'
with open(touhou_json, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f"Generated {touhou_json}")
