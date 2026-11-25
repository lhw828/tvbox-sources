#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_unstable_live.py —— 短效/易过期直播源单独构建器
====================================================
输入: raw/live_unstable/ 下的 m3u/txt
  - ysp.m3u          央视频匿名签发地址（短效签名，需重新签发）
  - juhe_*.txt       聚盒聚合站每日抓取的直播链接（易变动）
  - ntv_webview.txt  nTv 的 webview:// 频道（需 WebView 嗅探，影视仓不可播）

输出:
  subscriptions/live_unstable.m3u   短效源 m3u（仅直连可播地址）
  subscriptions/live_unstable.txt   短效源 txt（影视仓列表订阅格式）
  subscriptions/live_unstable.json  影视仓 lives 订阅（指向上面的 txt）
  subscriptions/ntv_webview.txt     webview:// 频道清单（仅 nTv 应用可用，单独存放）
  data/live_unstable_channels.json  明细

设计要点：
  * 不做频道探测（短效源每天都可能变，探测既慢又无意义）；
  * webview:// 不是可播放地址，从可播订阅中剔除，单独成文件；
  * 构建失败/源全空时保留上次产物，不写空订阅。
"""
import os, re, glob, json, sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, 'raw', 'live_unstable')
DATA = os.path.join(BASE, 'data')
SUBS = os.path.join(BASE, 'subscriptions')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (now_cn, normalize_channel_name, scrub_url_type,
                    scrub_name_type, atomic_write, atomic_write_json,
                    save_last_good, restore_last_good)

OUTPUTS = [
    'subscriptions/live_unstable.m3u',
    'subscriptions/live_unstable.txt',
    'subscriptions/live_unstable.json',
    'subscriptions/ntv_webview.txt',
    'data/live_unstable_channels.json',
]
CDN_TXT = ('https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@main/'
           'subscriptions/live_unstable.txt')


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', str(s))]


def parse_file(path):
    """返回 (频道名, 地址, 分组) 列表；webview:// 原样单独返回。"""
    text = open(path, encoding='utf-8', errors='replace').read()
    name = None
    group = '短效'
    out = []
    webview = []
    is_m3u = '#EXTM3U' in text
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if is_m3u:
            if line.startswith('#EXTINF'):
                m = re.search(r',\s*(.+)$', line)
                name = m.group(1).strip() if m else ''
                gm = re.search(r'group-title="([^"]*)"', line)
                group = gm.group(1) if gm else '短效'
                continue
            if line.startswith('#') or not re.match(r'^(https?|rtmp|mitv|webview)://', line):
                continue
            url = line
            nm = name or '未知'
        else:
            if line.endswith('#genre#'):
                group = line.split(',')[0].replace('#genre#', '').strip() or '短效'
                continue
            if ',' not in line:
                continue
            nm, url = [x.strip() for x in line.split(',', 1)]
            if not re.match(r'^(https?|rtmp|mitv|webview)://', url):
                continue
        if url.startswith('webview://'):
            webview.append((nm, url, group))
        else:
            out.append((nm, url, group))
        name = None
    return out, webview


def build():
    os.makedirs(SUBS, exist_ok=True)
    os.makedirs(DATA, exist_ok=True)

    channels = defaultdict(list)
    webview_rows = []
    seen_urls = set()
    src_files = sorted(glob.glob(os.path.join(RAW, '*.m3u')) +
                       glob.glob(os.path.join(RAW, '*.txt')))
    for fp in src_files:
        src = os.path.basename(fp)
        rows, wv = parse_file(fp)
        for nm, url, group in rows:
            # 聚合站之间大量重复地址，去重可显著缩小订阅体积
            if url in seen_urls:
                continue
            seen_urls.add(url)
            key = normalize_channel_name(nm)
            channels[key].append({'name': nm, 'url': url, 'group': group, 'src': src})
        for nm, url, group in wv:
            webview_rows.append((nm, url, group, src))

    total_lines = sum(len(v) for v in channels.values())
    if total_lines < 5 and len(webview_rows) < 5:
        print(f'  ⚠ 短效源内容过少(可播 {total_lines} 行 / webview {len(webview_rows)} 行)，保留上次产物')
        restore_last_good(OUTPUTS)
        return

    stamp = now_cn()
    keys = sorted(channels, key=natural_key)

    # 1) m3u: 每频道取第一条（源内已按优先级排列），保留多线路到 txt
    m3u = ['#EXTM3U',
           '# ⚠ 短效直播源：签名/聚合地址可能随时过期，建议仅作备用，失效后手动刷新',
           f'# 生成时间: {stamp}',
           f'# 可播频道: {len(keys)} | 线路 {total_lines} | webview(不可直接在影视仓播) {len(webview_rows)}', '']
    for key in keys:
        ch = channels[key][0]
        m3u.append(f'#EXTINF:-1 group-title="{ch["group"]}",{scrub_name_type(ch["name"])}')
        m3u.append(scrub_url_type(ch['url']))

    # 2) txt: 按来源分组，每频道全部线路（首行最优）
    by_src = defaultdict(list)
    for key in keys:
        for line in channels[key]:
            by_src[line['src']].append((key, line))
    txt = ['# ⚠ 短效源，可能过期；完整稳定源请用 subscriptions/iptv_own.json',
           f'# 生成时间: {stamp}', '']
    for src in sorted(by_src):
        txt.append(f'{src},#genre#')
        for key, line in sorted(by_src[src], key=lambda x: natural_key(x[0])):
            txt.append(f'{scrub_name_type(line["name"])},{scrub_url_type(line["url"])}')

    # 3) 影视仓 lives 订阅
    lives = [{
        'name': '短效备用源', 'type': 0, 'group': '短效备用',
        'url': CDN_TXT, 'playerType': 1,
        'epg': 'https://epg.112114.xyz/?ch={name}&date={date}',
        'logo': 'https://live.fanmingming.cn/tv/{name}.png',
    }]

    # 4) webview 清单（仅 nTv/WebView 类应用可用，不混入可播订阅）
    wv_txt = ['# webview:// 频道需 nTv 等带 WebView 嗅探的应用，影视仓/FongMi 无法直接播放',
              f'# 生成时间: {stamp}', f'# 频道数: {len(webview_rows)}', '']
    wv_groups = []
    for nm, url, group, src in webview_rows:
        if not wv_groups or wv_groups[-1] != group:
            wv_groups.append(group)
            wv_txt.append(f'{group},#genre#')
        wv_txt.append(f'{nm},{url}')

    # 5) 明细（只存摘要，避免聚合源上万行把仓库撑大）
    detail = {'built_at': stamp, 'channels': len(keys), 'lines': total_lines,
              'webview': len(webview_rows),
              'sources': [os.path.basename(f) for f in src_files],
              'sample': keys[:50]}

    atomic_write(os.path.join(SUBS, 'live_unstable.m3u'), '\n'.join(m3u) + '\n')
    atomic_write(os.path.join(SUBS, 'live_unstable.txt'), '\n'.join(txt) + '\n')
    atomic_write_json(os.path.join(SUBS, 'live_unstable.json'), {'lives': lives})
    atomic_write(os.path.join(SUBS, 'ntv_webview.txt'), '\n'.join(wv_txt) + '\n')
    atomic_write_json(os.path.join(DATA, 'live_unstable_channels.json'), detail)
    save_last_good(OUTPUTS)

    print(f'[{stamp}] 短效源构建完成: 可播频道 {len(keys)} / 线路 {total_lines} / webview {len(webview_rows)}')
    print('  输出: subscriptions/live_unstable.{m3u,txt,json}, ntv_webview.txt')


if __name__ == '__main__':
    build()
