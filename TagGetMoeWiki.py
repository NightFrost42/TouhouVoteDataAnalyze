import os
import re
import pandas as pd
from bs4 import BeautifulSoup
from urllib.parse import quote
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 配置输入输出文件及缓存目录
input_file = 'fun.xlsx'
output_file = '萌点提取结果.xlsx'
cache_dir = 'cache'
if not os.path.exists(cache_dir):
    os.makedirs(cache_dir)

# 读取 Excel 数据
_df = pd.read_excel(input_file)
# 检查必需列
for col in ['译名', '首次出现作品']:
    if col not in _df.columns:
        raise KeyError(f"输入文件缺少 '{col}' 列，请检查表头。")
# 过滤“首次出现作品”<6或空值
filtered_df = _df.dropna(subset=['首次出现作品'])
filtered_df = filtered_df[filtered_df['首次出现作品'] >= 6]

# 使用 undetected_chromedriver 启动有头浏览器，便于手动通过 Cloudflare 验证
options = uc.ChromeOptions()
options.headless = False  # 打开可视化窗口进行验证
options.add_argument('--disable-gpu')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
# 请根据本地 Chrome 版本设置 version_main
local_chrome_major = 137

driver = uc.Chrome(options=options, version_main=local_chrome_major)
wait = WebDriverWait(driver, 60)

base_url = 'https://moegirl.icu/'
results = []

# 首次访问主站点，触发 Cloudflare 验证
print("正在打开主页以触发 Cloudflare 验证...")
driver.get(base_url)
# 等待验证码或页面加载，大约需手动完成验证
print("请在打开的浏览器窗口中完成 Cloudflare 验证，验证完毕后在此终端按回车继续...")
input()

for raw_name in filtered_df['译名'].dropna():
    clean_name = re.sub(r'（.*?）', '', str(raw_name))
    clean_name = clean_name.replace('天为', '帝')
    if clean_name == '小恶魔':
        clean_name += '(东方Project)#'
    encoded = quote(clean_name)
    url = base_url + encoded
    print(f"Processing: {url}")

    cache_file = os.path.join(cache_dir, f"{encoded}.html")
    if os.path.exists(cache_file):
        print("  Loading from cache")
        with open(cache_file, 'r', encoding='utf-8') as f:
            html = f.read()
    else:
        try:
            driver.get(url)
            # 假定验证后无需再次验证
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div.infotemplatebox')))
            html = driver.page_source
            with open(cache_file, 'w', encoding='utf-8') as f:
                f.write(html)
        except Exception as e:
            print(f"  访问失败: {e}")
            continue

    soup = BeautifulSoup(html, 'html.parser')
    divs = soup.select('div[itemscope].infotemplatebox') or [d for d in soup.find_all('div') if d.has_attr('itemscope')]
    if not divs:
        print(f"  未找到任何 itemscope div: {clean_name}")
        continue

    for div in divs:
        for table in div.find_all('table'):
            for row in table.find_all('tr'):
                th = row.find('th')
                if th and th.get_text(strip=True) == '萌点':
                    values = [td.get_text(strip=True) for td in row.find_all('td')]
                    results.append({'译名': clean_name, '萌点内容': '；'.join(values)})

# 关闭浏览器
driver.quit()

# 保存到 Excel
if results:
    pd.DataFrame(results).to_excel(output_file, index=False)
    print(f"已保存结果到 {output_file}")
else:
    print("未提取到任何萌点内容。")
