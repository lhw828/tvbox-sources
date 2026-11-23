#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
juhe_scraper.py —— 抓取 juwanhezi.com 聚合站的点播/直播源列表

借鉴 riowang88/tvbox-source-aggregator 的 source-scraper.ts：
  - 页面是 WordPress 结构，源条目标签形如：
      <label ... class="col-sm-2 col-form-label">名称</label>
      <input ... value="https://...json">
    名称用 col-form-label 提取，URL 用 value="http..." 提取，按出现顺序一一配对。
  - 旧版 POST AJAX 翻页（action=load&page=source&paged=N）若失效，自动回退 GET 页面。
  - 新版页面不分页时，GET 首页即全部内容。
  - 兜底：若配对提取为空，扫描页面里所有 *.json/*.txt 链接。

对外接口：
  scrape_jsonlist(kind) -> list[{name, url}]   kind: 'one' 单仓 / 'many' 多仓
  scrape_live()         -> list[{name, url}]   直播页
  main()  -> 写入 data/juhe_sources.json 供 manager.py / live_manager.py 消费
"""
import os, sys, re, json, argparse, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'data')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import now_cn, atomic_write_json, UA_BROWSER, UA_TV

JSONLIST = 'https://juwanhezi.com/jsonlist?type={kind}'
LIVE = 'https://juwanhezi.com/live'
AJAX_LOAD = 'https://juwanhezi.com/ajax/load'   # 分页接口: globals.ajax_url('/ajax/') + data.action('load')
MAX_PAGES = 15

import requests
try:
    import urllib3
    urllib3.disable_warnings()
except Exception:
    pass


def _get(url, timeout=20, retries=3):
    """优先直连；带重试；返回 (ok, text, status)"""
    last = 'ERR'
    for attempt in range(retries):
        for ua in (UA_TV, UA_BROWSER):
            try:
                s = requests.Session()
                s.headers.update({'User-Agent': ua, 'Accept': '*/*'})
                r = s.get(url, timeout=timeout, verify=False, allow_redirects=True)
                r.encoding = r.apparent_encoding or 'utf-8'
                if r.status_code == 200 and r.text:
                    return True, r.text, 200
            except Exception as e:
                last = str(e)[:80]
        if attempt < retries - 1:
            time.sleep(0.5 * (attempt + 1))   # 重试间隔递增，缓解限流
    return False, '', last


def _post_page(page_type, paged, timeout=20, retries=3):
    """POST /ajax/load 拉取分页 HTML。page_type: one/many/live，带重试。"""
    for attempt in range(retries):
        try:
            s = requests.Session()
            s.headers.update({
                'User-Agent': UA_BROWSER,
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': 'https://juwanhezi.com/',
            })
            r = s.post(AJAX_LOAD, timeout=timeout, verify=False,
                       data={'page': 'source', 'type': page_type, 'action': 'load', 'paged': paged})
            r.encoding = r.apparent_encoding or 'utf-8'
            if r.status_code == 200:
                return True, r.text
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(0.5 * (attempt + 1))
    return False, ''


def parse_pairs(html):
    """从页面 HTML 提取 (名称, URL) 配对。按出现顺序严格一一对应，不去重名称。"""
    names = [re.sub(r'\s+', ' ', m).strip()
             for m in re.findall(r'col-form-label["\'][^>]*>([^<]+)<', html)]
    urls = [m.strip() for m in re.findall(r'value=["\'](https?://[^"\']+)["\']', html)]
    out = []
    n = min(len(names), len(urls))
    for i in range(n):
        if names[i] and urls[i]:
            out.append({'name': names[i], 'url': urls[i]})
    return out


def parse_fallback(html):
    """兜底：扫描所有 json/txt/m3u 链接作为无名称源。"""
    urls = re.findall(r'https?://[^\s"\'<>]+?\.(?:json|txt|m3u)(?:\?[^\s"\'<>]*)?', html, re.I)
    seen = set(); out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append({'name': u.split('/')[-1][:24], 'url': u})
    return out


def scrape(kind):
    """抓取某类型的全部源：首页 + /ajax/load 分页，直到返回空页。"""
    url = LIVE if kind == 'live' else JSONLIST.format(kind=kind)
    page_type = kind  # one/many/live 作为 ajax 的 type 参数
    ok, html, status = _get(url)
    if not ok:
        print(f'  ✗ {kind} 页面抓取失败: {status}')
        return []
    all_pairs = []
    first = parse_pairs(html) or parse_fallback(html)
    all_pairs.extend(first)
    print(f'  {kind} 第1页: {len(first)} 条')
    # 拉分页
    for paged in range(2, MAX_PAGES + 1):
        pok, phtml = _post_page(page_type, paged)
        if not pok or not phtml.strip():
            break
        page_pairs = parse_pairs(phtml)
        if not page_pairs:
            break
        all_pairs.extend(page_pairs)
        print(f'  {kind} 第{paged}页: {len(page_pairs)} 条')
        time.sleep(0.5)   # 分页间小间隔，避免限流
    # 去重（按 URL，保序）
    seen = set(); uniq = []
    for p in all_pairs:
        if p['url'] not in seen:
            seen.add(p['url']); uniq.append(p)
    dup = len(all_pairs) - len(uniq)
    print(f'  ✓ {kind}: 共 {len(uniq)} 条唯一源' + (f' (去重 {dup})' if dup else ''))
    return uniq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(DATA, 'juhe_sources.json'))
    args = ap.parse_args()
    print(f'[{now_cn()}] 抓取 juwanhezi.com 聚合站源列表...')
    result = {
        'fetched_at': now_cn(),
        'source': 'https://juwanhezi.com',
        'single': scrape('one'),   # 单仓点播
        'many': scrape('many'),    # 多仓点播
        'live': scrape('live'),    # 直播
    }
    os.makedirs(DATA, exist_ok=True)

    # 失败保护: 任一类别抓取为空则沿用上次成功数据, 避免写出空列表
    old = {}
    if os.path.exists(args.out):
        try:
            old = json.load(open(args.out, encoding='utf-8'))
        except Exception:
            pass
    for key in ('single', 'many', 'live'):
        if not result[key] and old.get(key):
            result[key] = old[key]
            result[f'{key}_fallback'] = f'沿用上次成功数据({old.get("fetched_at", "?")})，本次抓取失败/限流'
            print(f'  ⚠ {key} 本次为空，沿用上次成功的 {len(old[key])} 条')

    atomic_write_json(args.out, result)
    print(f'写入 {args.out}: 单仓 {len(result["single"])} / 多仓 {len(result["many"])} / 直播 {len(result["live"])}')
    return result


if __name__ == '__main__':
    main()
