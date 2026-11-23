#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自建直播源构建器
================
把多个来源的频道整合、重新分组、按可用性证据排序，生成"自己的"直播源。

输入：
  raw/live/*.m3u|txt          各来源聚合文件
  data/live_channel_probe.json  频道级实测连通结果(由 live_manager.py test 生成)

输出：
  subscriptions/iptv_own.json   影视仓 lives 订阅(自建,按分组)
  subscriptions/iptv_own.m3u    标准 m3u(自建)
  data/iptv_own_channels.json   自建频道明细(含多线路与可用性)
  reports/live_own_report.md    自建源报告

分组规则(统一映射各来源的原始分组)：
  央视 / 卫视 / 地方 / 国际 / 4K8K / 春晚轮播 / 影视轮播 / 游戏赛事 / 咪咕 / 其他

排序：
  同一频道内多条线路: 实测可播优先 -> 延迟升序 -> 来源可信度
"""
import os, json, re, sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_LIVE = os.path.join(BASE, 'raw', 'live')
DATA = os.path.join(BASE, 'data')
SUBS = os.path.join(BASE, 'subscriptions')
REPORTS = os.path.join(BASE, 'reports')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (normalize_channel_name, scrub_url_type, scrub_name_type,
                    save_last_good, restore_last_good, has_content)

SOURCE_FILES = [
    ('老刘备', 'liucn_tvlive.txt'),
    ('Kimentanm', 'kimentanm.m3u'),
    ('范明明', 'fanmingming_index.m3u'),
    ('YanG', 'yang_gather.m3u'),
]
# 来源可信度(越小越优先)
SRC_RANK = {'范明明': 1, 'Kimentanm': 2, '老刘备': 3, 'YanG': 4}


def load_source_files():
    """基础源 + juwanhezi 抓取的直播源（由 juhe_live_fetch.py 生成的清单）"""
    files = list(SOURCE_FILES)
    mf = os.path.join(DATA, 'juhe_live_files.json')
    if os.path.exists(mf):
        try:
            for name, fn in json.load(open(mf, encoding='utf-8')).get('files', []):
                if os.path.exists(os.path.join(RAW_LIVE, fn)):
                    files.append((name, fn))
        except Exception:
            pass
    return files

def now_cn():
    return datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S CST')

def parse_with_group(text):
    ch = []; pending = None; cur = '其他'
    lines = [l.strip() for l in text.splitlines()]
    if '#EXTM3U' in text:
        for l in lines:
            if l.startswith('#EXTINF'):
                m = re.search(r',\s*(.+)$', l); pending = m.group(1).strip() if m else None
                gm = re.search(r'group-title="([^"]*)"', l)
                if gm: cur = gm.group(1)
            elif l and not l.startswith('#') and re.match(r'^(https?|rtmp|mitv|rtp)://', l):
                ch.append((pending or '', l, cur)); pending = None
    else:
        for l in lines:
            if l.endswith('#genre#'):
                cur = l.split(',')[0]; continue
            if ',' in l:
                n, u = l.split(',', 1)
                if re.match(r'^(https?|rtmp|mitv|rtp)://', u.strip()):
                    ch.append((n.strip(), u.strip(), cur))
    return ch

def norm_name(name):
    # 思路1: 共享的频道名规范化（繁简 + 去 HD/4K/1080p 后缀 + 压空白 + CCTV 归一）
    return normalize_channel_name(name)


def natural_key(s):
    """自然数排序键: CCTV1 < CCTV2 < ... < CCTV10 < CCTV13（避免字典序 CCTV1<CCTV10<CCTV2）。"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', str(s))]

def classify(name, raw_group):
    """统一分组映射"""
    n = name.upper(); g = raw_group.upper()
    if '春晚' in n or '历年春晚' in g: return '春晚轮播'
    if 'CGTN' in n or re.search(r'CNN|BBC|RT |RT$|NHK|KBS|国际|INTERNATIONAL|CNA|DW|FRANCE|VOA', n): return '国际频道'
    if '4K' in n or '8K' in n or '4K8K' in g: return '4K8K'
    if re.match(r'^CCTV\d', n) or '央视' in g or n.startswith('CCTV'): return '央视'
    if '卫视' in n or '卫视' in g: return '卫视'
    if '咪咕' in g or '咪咕' in n: return '咪咕'
    if '游戏' in g or '赛事' in g or '电竞' in n: return '游戏赛事'
    if '影视' in g or '轮播' in g or '剧场' in n or '影院' in n: return '影视轮播'
    # 地方频道(带地名+新闻/综合/都市等)
    if re.search(r'新闻综合|新闻综合|公共|都市|民生|生活|科教|少儿|经济|文化|综合频道|新闻频道', n): return '地方'
    if 'IPV6' in g: return '地方'
    return '其他'

# 分组展示顺序
GROUP_ORDER = ['央视', '卫视', '4K8K', '国际频道', '地方', '咪咕', '影视轮播', '游戏赛事', '春晚轮播', '其他']
# 分组 -> 英文文件名(避免CDN中文路径问题)
GROUP_FILE = {
    '央视': 'cctv', '卫视': 'satellite', '4K8K': '4k8k', '国际频道': 'international',
    '地方': 'local', '咪咕': 'migu', '影视轮播': 'movie', '游戏赛事': 'game',
    '春晚轮播': 'gala', '其他': 'other',
}

def build():
    # 读取实测结果
    probe = {}
    pp = os.path.join(DATA, 'live_channel_probe.json')
    if os.path.exists(pp):
        for x in json.load(open(pp, encoding='utf-8')):
            probe[x['url']] = {'ok': x['ok'], 'latency': x['latency'], 'code': x['code']}

    # 汇总所有频道 -> {norm_name: {name, group, lines:[...]}}
    channels = {}
    for src, fn in load_source_files():
        fp = os.path.join(RAW_LIVE, fn)
        if not os.path.exists(fp): continue
        for name, url, rawg in parse_with_group(open(fp, encoding='utf-8', errors='replace').read()):
            key = norm_name(name)
            grp = classify(name, rawg)
            t = probe.get(url, {})
            line = {
                'url': url,
                'src': src,
                'raw_name': name,
                'raw_group': rawg,
                'probed': url in probe,
                'ok': t.get('ok', False),
                'latency': t.get('latency', 99),
                'code': t.get('code', 0),
            }
            if key not in channels:
                channels[key] = {'name': name, 'group': grp, 'lines': []}
            channels[key]['lines'].append(line)

    # 线路质量评分(越小越优先)
    def line_score(L):
        url = L['url']
        # 1) 实测可播 -> 最优先
        if L['ok']:
            return (0, L['latency'], 0)
        # 2) 含可疑鉴权参数(mac/Authinfo/token/livodToken) -> 别人设备绑定,电视用不了,降到最后
        suspicious = re.search(r'(mac=|Authinfo=|livodToken=|gMac=|token=)', url, re.I)
        if suspicious:
            return (3, 0, SRC_RANK.get(L['src'], 9))
        # 3) 协议类型: mitv/rtmp 电视专用内核可播(高于未验证的公网m3u8)
        if url.startswith(('mitv://', 'rtmp://')):
            return (1, 0, SRC_RANK.get(L['src'], 9))
        # 4) 运营商IPTV IP段(39.134/111.2/101.35 等直连) - 电视上通常可用
        if re.match(r'https?://(39\.134|111\.2\.185|101\.35|125\.|183\.)', url):
            return (1, L['latency'], SRC_RANK.get(L['src'], 9))
        # 5) 其余未验证的 m3u8
        return (2, L['latency'], SRC_RANK.get(L['src'], 9))

    for key, ch in channels.items():
        ch['lines'].sort(key=line_score)

    # 统计
    total_channels = len(channels)
    total_lines = sum(len(c['lines']) for c in channels.values())
    verified_channels = sum(1 for c in channels.values() if any(l['ok'] for l in c['lines']))
    verified_lines = sum(1 for c in channels.values() for l in c['lines'] if l['ok'])
    group_count = defaultdict(int)
    for c in channels.values(): group_count[c['group']] += 1

    # 失败回退(需求4): 若本次频道数异常塌陷(空或较上次骤降>50%), 保留上次成功的全部直播产物
    LIVE_OUTPUTS = ['subscriptions/iptv_own.json', 'subscriptions/iptv_own.m3u',
                    'data/iptv_own_channels.json', 'reports/live_own_report.md']
    LIVE_OUTPUTS += [f'subscriptions/live_{v}.txt' for v in GROUP_FILE.values()]
    prev = os.path.join(DATA, 'last_good', 'data__iptv_own_channels.json')
    if total_channels < 50 and os.path.exists(prev):
        try:
            prev_n = json.load(open(prev, encoding='utf-8')).get('total_channels', 0)
        except Exception:
            prev_n = 0
        if prev_n >= 100 and total_channels < prev_n * 0.5:
            restored = restore_last_good(LIVE_OUTPUTS)
            print(f'  ⚠ 频道数异常塌陷({prev_n} → {total_channels})，已保留上次成功的直播订阅 ({len(restored)} 个文件)')
            return

    os.makedirs(SUBS, exist_ok=True); os.makedirs(REPORTS, exist_ok=True)

    # 1) 自建频道明细
    json.dump({'built_at': now_cn(), 'total_channels': total_channels,
               'verified_channels': verified_channels, 'channels': channels},
              open(os.path.join(DATA, 'iptv_own_channels.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)

    # 2) 影视仓 lives 订阅(自建) - 每个分组一个 live 条目(用原始列表文件)
    #    由于影视仓 lives 每条指向一个聚合地址，我们同时生成一个"自建聚合txt"方案：
    #    把筛选后的频道按分组写成 txt，供影视仓订阅。
    lives = []
    # 为影视仓提供分组订阅: 每个分组生成一个指向本仓库 txt 的 live 条目
    for g in GROUP_ORDER:
        if group_count.get(g, 0) == 0: continue
        lives.append({
            'name': f'自建-{g}', 'type': 0, 'group': g,
            'url': f'https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@main/subscriptions/live_{GROUP_FILE[g]}.txt',
            'playerType': 1, 'epg': 'https://epg.112114.xyz/?ch={name}&date={date}',
            'logo': 'https://live.fanmingming.cn/tv/{name}.png',
        })
    json.dump({'lives': lives}, open(os.path.join(SUBS, 'iptv_own.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)

    # 3) 每个分组生成 txt(频道名,地址 - 主流线路优先),以及 m3u
    all_m3u = ['#EXTM3U x-tvg-url="https://live.fanmingming.cn/e.xml"']
    for g in GROUP_ORDER:
        members = [(k, c) for k, c in channels.items() if c['group'] == g]
        if not members: continue
        members.sort(key=lambda x: natural_key(x[0]))
        txt_lines = [f'{g},#genre#']
        for key, c in members:
            # 每个频道取全部线路(按可用性排序),第一行是最优线路
            for i, line in enumerate(c['lines']):
                display = scrub_name_type(c['name']) if i == 0 else f'{scrub_name_type(c["name"])}「{line["src"]}」'
                # 思路3: URL 中的 type 编码, 防 TVBox lives.contains("type") 误判为 FongMi 格式
                txt_lines.append(f'{display},{scrub_url_type(line["url"])}')
        open(os.path.join(SUBS, f'live_{GROUP_FILE[g]}.txt'), 'w', encoding='utf-8').write('\n'.join(txt_lines) + '\n')
        # m3u: 每个频道仅取最优线路,避免重复
        for key, c in members:
            best = c['lines'][0]
            all_m3u.append(f'#EXTINF:-1 group-title="{g}",{scrub_name_type(c["name"])}')
            all_m3u.append(scrub_url_type(best['url']))
    open(os.path.join(SUBS, 'iptv_own.m3u'), 'w', encoding='utf-8').write('\n'.join(all_m3u) + '\n')

    # 4) 报告
    lines = [
        '# 自建直播源', '',
        f'> 构建时间：{now_cn()}',
        '> 说明：整合多个公开来源的频道，统一分组、按实测可用性排序，形成独立可用的自建源。',
        '> 电视无代理，GitHub 类地址已统一用 cdn.jsdelivr.net 改写。', '',
        '## 数据概况', '',
        '| 项目 | 数量 |', '|---|---|',
        f'| 收录频道 | {total_channels} |',
        f'| 总线路数 | {total_lines} |',
        f'| 实测可播频道 | {verified_channels} |',
        f'| 实测可播线路 | {verified_lines} |', '',
        '> 注意：`mitv://` 为小米电视专用协议、`rtmp://` 需专用内核，curl 无法探测，',
        '> 但在这台小米电视上可正常播放，故予以保留并标注。', '',
        '## 分组统计', '',
        '| 分组 | 频道数 |', '|---|---|',
    ]
    for g in GROUP_ORDER:
        if group_count.get(g, 0): lines.append(f'| {g} | {group_count[g]} |')
    lines += ['', '## 使用方法', '',
              '影视仓/影视 → 设置 → 订阅管理 → 列表订阅，填入：', '',
              '```',
              'https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@main/subscriptions/iptv_own.json',
              '```', '',
              '或直接用 m3u（通用播放器）：', '',
              '```',
              'https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@main/subscriptions/iptv_own.m3u',
              '```', '',
              '本源与点播订阅相互独立，互不影响。', '']
    open(os.path.join(REPORTS, 'live_own_report.md'), 'w', encoding='utf-8').write('\n'.join(lines))

    # 构建成功，快照到 last_good 供后续失败时回退
    saved = save_last_good(LIVE_OUTPUTS)
    print(f'[{now_cn()}] 自建源构建完成')
    print(f'  频道 {total_channels} | 线路 {total_lines} | 实测可播频道 {verified_channels}')
    print(f'  分组: {dict(group_count)}')
    print(f'  输出: subscriptions/iptv_own.json, iptv_own.m3u, live_<分组>.txt')
    print(f'  已快照 {len(saved)} 个文件到 data/last_good/')
    return channels

if __name__ == '__main__':
    build()
