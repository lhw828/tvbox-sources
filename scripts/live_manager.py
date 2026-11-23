#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TVBox 直播源管理器
==================
独立于点播源脚本，专门处理直播源(IPTV)。

子命令：
  test    直连实测聚合地址(模拟电视无代理) + 频道抽样连通率
  build   基于测试结果生成影视仓可用的独立直播订阅文件
  all     依次执行 test + build

输出：
  data/live_result.json        测试明细
  subscriptions/iptv.json       影视仓直播订阅(lives 格式,独立文件)
  subscriptions/iptv.m3u        标准 m3u(通用播放器)
  reports/live_report.md        可读报告

判定原则：
  - 电视无代理，一律 curl 直连(GitHub 源统一用 cdn.jsdelivr.net 改写)
  - 不仅测聚合地址可达，还抽样测试频道 m3u8 真实连通率
  - 按 连通率 + 延迟 + 频道数 综合排序
"""
import os, sys, json, re, time, tempfile, subprocess, random
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'data')
RAW_LIVE = os.path.join(BASE, 'raw', 'live')
SUBS = os.path.join(BASE, 'subscriptions')
REPORTS = os.path.join(BASE, 'reports')
UA = 'Mozilla/5.0 (Linux; Android 10)'

def now_cn():
    return datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S CST')

# ---------- 直播聚合源清单 ----------
# existing=True 表示原线路里已有的源；补充源为搜集的新源
def load_seeds():
    seeds = [
        # 原有线路里的源
        {'name': '俊佬直播', 'url': 'http://home.jundie.top:81/Cat/tv/live.txt', 'from': '原线路-俊佬', 'existing': True},
        {'name': '老刘备肥猫', 'url': 'http://xn--ihqu10cn4c.xn--z7x900a.live/TV/tvzb.txt', 'from': '原线路-老刘备', 'existing': True},
        {'name': '老刘备SAO0', 'url': 'https://raw.liucn.cc/box/libs/tv/tvlive.txt', 'from': '原线路-老刘备', 'existing': True,
         'local': os.path.join(RAW_LIVE, 'liucn_tvlive.txt')},
        {'name': '老刘备IPV6', 'url': 'https://raw.liucn.cc/box/lib/tv/ipv6.m3u', 'from': '原线路-老刘备', 'existing': True},
        # 搜集的新源(经初筛可用的)
        {'name': '范明明index', 'url': 'https://cdn.jsdelivr.net/gh/fanmingming/live@main/tv/m3u/index.m3u', 'from': '补充-范明明', 'local': os.path.join(RAW_LIVE, 'fanmingming_index.m3u')},
        {'name': 'YanG集合', 'url': 'https://cdn.jsdelivr.net/gh/YanG-1989/m3u@main/Gather.m3u', 'from': '补充-YanG', 'local': os.path.join(RAW_LIVE, 'yang_gather.m3u')},
        {'name': 'Kimentanm', 'url': 'https://cdn.jsdelivr.net/gh/Kimentanm/aptv@master/m3u/iptv.m3u', 'from': '补充-Kimentanm', 'local': os.path.join(RAW_LIVE, 'kimentanm.m3u')},
        {'name': 'YueChan', 'url': 'https://cdn.jsdelivr.net/gh/YueChan/Live@main/IPTV.m3u', 'from': '补充-YueChan', 'local': os.path.join(RAW_LIVE, 'yuechan.m3u')},
        {'name': 'BigBigGrandG', 'url': 'https://cdn.jsdelivr.net/gh/BigBigGrandG/IPTV-URL@release/Gather.m3u', 'from': '补充-BigBigGrandG'},
        {'name': '范明明IPV6镜像', 'url': 'https://cdn.jsdelivr.net/gh/fanmingming/live@main/tv/m3u/ipv6.m3u', 'from': '补充-范明明'},
    ]
    # 并入 juwanhezi.com 聚合站抓取的直播源（由 juhe_scraper.py 生成，只读取链接，不再访问页面）
    juhe_path = os.path.join(DATA, 'juhe_sources.json')
    if os.path.exists(juhe_path):
        try:
            juhe = json.load(open(juhe_path, encoding='utf-8'))
            for i, item in enumerate(juhe.get('live', [])):
                seeds.append({'name': f'[聚盒] {item["name"]}', 'url': item['url'],
                              'from': '聚盒直播', 'existing': False})
            print(f'  + 并入 juwanhezi 直播源 {len(juhe.get("live", []))} 条')
        except Exception as e:
            print(f'  ! juhe_sources.json 读取失败: {e}')
    return seeds

def curl_fetch(url, timeout, outfile=None):
    tf = outfile
    tmp = None
    if not tf:
        f = tempfile.NamedTemporaryFile(delete=False); f.close(); tf = f.name; tmp = tf
    cmd = ['curl', '-s', '-L', '-m', str(timeout), '-o', tf,
           '-w', '%{http_code}|%{time_total}|%{size_download}', '-A', UA, url]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        parts = p.stdout.strip().split('|')
        if len(parts) < 3:
            return {'code': 'ERR', 'latency': 99, 'size': 0, 'text': ''}
        raw = open(tf, 'rb').read() if os.path.exists(tf) else b''
        return {'code': int(parts[0]) if parts[0].isdigit() else parts[0],
                'latency': round(float(parts[1]), 2) if parts[1].replace('.','').isdigit() else 99,
                'size': int(parts[2]) if parts[2].isdigit() else 0,
                'text': raw.decode('utf-8', errors='replace')}
    except Exception as e:
        return {'code': 'ERR', 'latency': 99, 'size': 0, 'text': ''}
    finally:
        if tmp:
            try: os.unlink(tmp)
            except: pass

def parse_channels(text):
    """从 m3u / txt 里解析出 [(name, url)]"""
    ch = []
    lines = [l.strip() for l in text.splitlines()]
    # M3U 格式
    if '#EXTM3U' in text:
        pending = None
        for l in lines:
            if l.startswith('#EXTINF'):
                m = re.search(r',\s*(.+)$', l)
                pending = m.group(1).strip() if m else None
            elif l and not l.startswith('#') and re.match(r'^(https?|rtmp)://', l):
                ch.append((pending or '', l)); pending = None
    # TXT 格式: 频道名,地址
    else:
        for l in lines:
            if ',' in l and not l.endswith('#genre#'):
                name, url = l.split(',', 1)
                if re.match(r'^(https?|rtmp|mitv)://', url.strip()):
                    ch.append((name.strip(), url.strip()))
    return ch

def probe_channel(url, timeout=9):
    """测试单个频道 m3u8 是否真能取回播放列表"""
    f = tempfile.NamedTemporaryFile(delete=False); f.close()
    try:
        cmd = ['curl', '-s', '-L', '-m', str(timeout), '-r', '0-4096', '-o', f.name,
               '-w', '%{http_code}', '-A', UA, url]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 3)
        code = p.stdout.strip()
        raw = open(f.name, 'rb').read()
        head = raw[:400].decode('utf-8', errors='replace')
        ok = (code.startswith('2') or code.startswith('3')) and ('#EXTM3U' in head or len(raw) > 500)
        return ok
    except Exception:
        return False
    finally:
        try: os.unlink(f.name)
        except: pass

def cmd_test(sample=12, workers=12):
    print(f'[{now_cn()}] 开始直播源测试 (频道抽样 {sample} 个/源)...')
    seeds = load_seeds()
    results = []

    def work(seed):
        r = dict(seed)
        # 取内容：优先本地缓存，否则直连抓取
        if seed.get('local') and os.path.exists(seed['local']):
            text = open(seed['local'], encoding='utf-8', errors='replace').read()
            # 即便用本地缓存，也测一次聚合地址连通
            net = curl_fetch(seed['url'], 15)
            r['agg_code'] = net['code']; r['agg_latency'] = net['latency']; r['agg_size'] = net['size']
        else:
            net = curl_fetch(seed['url'], 18)
            text = net['text']
            r['agg_code'] = net['code']; r['agg_latency'] = net['latency']; r['agg_size'] = net['size']
        ch = parse_channels(text)
        r['channel_count'] = len(ch)
        r['has_genre'] = ('#genre#' in text or '#EXTM3U' in text)
        r['is_html'] = '<!DOCTYPE html' in text[:500].upper() or '<html' in text[:500].lower()
        # 只测 http(s) 的 m3u8 频道(rtmp/mitv 无法用 curl 判定)
        testable = [(n, u) for n, u in ch if u.startswith('http') and '.m3u8' in u and '[' not in u]
        r['testable'] = len(testable)
        random.seed(hash(seed['url']) & 0xffff)
        sample_list = random.sample(testable, min(sample, len(testable))) if testable else []
        if sample_list:
            with ThreadPoolExecutor(max_workers=8) as ex:
                futs = {ex.submit(probe_channel, u): (n, u) for n, u in sample_list}
                oks = 0
                for fut in as_completed(futs):
                    if fut.result(): oks += 1
            r['probed'] = len(sample_list); r['probe_ok'] = oks
            r['reach_rate'] = round(oks / len(sample_list) * 100, 1)
        else:
            r['probed'] = 0; r['probe_ok'] = 0; r['reach_rate'] = 0.0
        # 综合可用判定
        r['valid'] = (r['agg_code'] == 200 and r['has_genre'] and not r['is_html']
                      and r['channel_count'] > 5 and r['reach_rate'] >= 30)
        return r

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(work, s) for s in seeds]
        for fut in as_completed(futs):
            results.append(fut.result())

    # 排序: 可用优先, 连通率降序, 延迟升序
    results.sort(key=lambda x: (not x['valid'], -x['reach_rate'], x['agg_latency']))
    out = {'tested_at': now_cn(), 'sample_per_source': sample, 'results': results}
    os.makedirs(DATA, exist_ok=True)
    json.dump(out, open(os.path.join(DATA, 'live_result.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

    print(f'\n{"状态":<4} {"名称":<16} {"HTTP":>5} {"延迟":>7} {"频道":>6} {"抽测连通率":>10} {"来源":<16}')
    print('-' * 78)
    for r in results:
        flag = '✓' if r['valid'] else '✗'
        rate = f"{r['probe_ok']}/{r['probed']}({r['reach_rate']}%)" if r['probed'] else '-'
        tag = '原有' if r.get('existing') else '补充'
        print(f'{flag:<4} {r["name"]:<16} {str(r["agg_code"]):>5} {r["agg_latency"]:>6}s {r["channel_count"]:>6} {rate:>12} {r["from"]:<16}')
    ok = sum(1 for r in results if r['valid'])
    print(f'\n可用 {ok}/{len(results)}')
    return out

def cmd_build():
    r = json.load(open(os.path.join(DATA, 'live_result.json'), encoding='utf-8'))
    results = r['results']
    ok = [x for x in results if x['valid']]
    dead = [x for x in results if not x['valid']]
    existing_ok = [x for x in ok if x.get('existing')]
    replacement = [x for x in ok if not x.get('existing')]

    os.makedirs(SUBS, exist_ok=True)
    os.makedirs(REPORTS, exist_ok=True)

    # 1) 影视仓 lives 订阅(独立文件) - 用补充可用源替换失效的原源
    lives = []
    for x in ok:
        lives.append({
            'name': x['name'],
            'type': 0,
            'url': x['url'],
            'playerType': 1,
            'ua': UA,
            'epg': 'https://epg.112114.xyz/?ch={name}&date={date}',
            'logo': 'https://live.fanmingming.cn/tv/{name}.png',
            'group': x['from'],
        })
    json.dump({'lives': lives}, open(os.path.join(SUBS, 'iptv.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)

    # 2) 标准 m3u
    m3u = ['#EXTM3U x-tvg-url="https://live.fanmingming.cn/e.xml"']
    with open(os.path.join(SUBS, 'iptv.m3u'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(m3u) + '\n')
        for x in ok:
            if x.get('local') and os.path.exists(x['local']):
                text = open(x['local'], encoding='utf-8', errors='replace').read()
                ch = parse_channels(text)
                for name, url in ch:
                    f.write(f'#EXTINF:-1 group-title="{x["name"]}",{name}\n{url}\n')

    # 3) 报告
    lines = [f'# 直播源可用性报告', '', f'> 检测时间：{r["tested_at"]}（直连模拟电视，无代理）',
             f'> 频道抽测：每个源随机抽 {r["sample_per_source"]} 个 m3u8 频道实测连通率', '',
             '## 汇总', '',
             f'| 项目 | 数量 |', f'|---|---|',
             f'| 直播源总数 | {len(results)} |',
             f'| 可用 | {len(ok)} |',
             f'| 失效 | {len(dead)} |',
             f'| 原线路可用 | {len(existing_ok)} |',
             f'| 补充可用(用于替换) | {len(replacement)} |', '',
             '## 可用源（按连通率+速度排序）', '',
             '| 名称 | 连通率 | 延迟 | 频道数 | 来源 | 地址 |',
             '|---|---|---|---|---|---|']
    for x in ok:
        rate = f"{x['reach_rate']}% ({x['probe_ok']}/{x['probed']})" if x['probed'] else '-'
        lines.append(f"| {x['name']} | {rate} | {x['agg_latency']}s | {x['channel_count']} | {x['from']} | `{x['url']}` |")
    lines += ['', '## 失效源', '', '| 名称 | 状态 | 原因 |', '|---|---|---|']
    for x in dead:
        reason = 'HTTP错误/超时' if x['agg_code'] != 200 else ('反爬页面' if x['is_html'] else ('连通率过低' if x['probed'] else '无有效频道'))
        lines.append(f"| {x['name']} | {x['agg_code']} | {reason} |")
    lines += ['', '## 替换说明', '',
              '原线路中失效的直播源（俊佬、肥猫、IPV6）已由补充的可用源替换。',
              '影视仓导入 `subscriptions/iptv.json` 即可，与点播订阅互不影响。', '']
    open(os.path.join(REPORTS, 'live_report.md'), 'w', encoding='utf-8').write('\n'.join(lines))

    # 4) 失效源单列
    json.dump(dead, open(os.path.join(DATA, 'live_dead.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

    print(f'[{now_cn()}] 构建完成')
    print(f'  影视仓直播订阅: subscriptions/iptv.json  ({len(lives)} 个源)')
    print(f'  标准m3u: subscriptions/iptv.m3u')
    print(f'  报告: reports/live_report.md')
    print(f'  其中补充源 {len(replacement)} 个用于替换失效的原源')

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if cmd == 'test':
        cmd_test(sample=int(os.environ.get('SAMPLE', 12)))
    elif cmd == 'build':
        cmd_build()
    elif cmd == 'all':
        cmd_test(sample=int(os.environ.get('SAMPLE', 12)))
        cmd_build()
    else:
        print(__doc__)
