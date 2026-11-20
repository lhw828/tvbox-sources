#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
频道级全量探测
==============
扫描 raw/live/ 下所有聚合文件的全部频道线路，逐条 curl 实测连通性，
输出 data/live_channel_probe.json，供 build_own_live.py 排序使用。

注意：curl 无法探测 mitv://(小米电视专用)、rtmp:// 及部分防盗链 m3u8，
这些会被标记为 ok=False，但构建时仍会保留（按协议类型给可信度权重）。
"""
import os, re, json, tempfile, subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_LIVE = os.path.join(BASE, 'raw', 'live')
DATA = os.path.join(BASE, 'data')
UA = 'Mozilla/5.0 (Linux; Android 10)'

SOURCE_FILES = [
    ('老刘备', 'liucn_tvlive.txt'),
    ('Kimentanm', 'kimentanm.m3u'),
    ('范明明', 'fanmingming_index.m3u'),
    ('YanG', 'yang_gather.m3u'),
]

def parse(text):
    ch = []; pending = None
    if '#EXTM3U' in text:
        for l in [x.strip() for x in text.splitlines()]:
            if l.startswith('#EXTINF'):
                m = re.search(r',\s*(.+)$', l); pending = m.group(1).strip() if m else None
            elif l and not l.startswith('#') and re.match(r'^(https?|rtmp)://', l):
                ch.append((pending or '', l)); pending = None
    else:
        for l in [x.strip() for x in text.splitlines()]:
            if ',' in l and not l.endswith('#genre#'):
                n, u = l.split(',', 1)
                if re.match(r'^(https?|rtmp|mitv)://', u.strip()):
                    ch.append((n.strip(), u.strip()))
    return ch

def norm(name):
    n = re.sub(r'\s+', '', name.strip().upper()).replace('中央', 'CCTV')
    m = re.match(r'CCTV-?(\d+)', n)
    return 'CCTV' + m.group(1) if m else n

def probe(item):
    ch, v = item; u = v['url']
    f = tempfile.NamedTemporaryFile(delete=False); f.close()
    try:
        p = subprocess.run(['curl', '-s', '-L', '-m', '8', '-o', f.name,
                            '-w', '%{http_code}|%{time_total}', '-A', UA, u],
                           capture_output=True, text=True, timeout=12)
        parts = p.stdout.strip().split('|')
        code = int(parts[0]) if parts[0].isdigit() else 0
        lat = float(parts[1]) if len(parts) > 1 and parts[1].replace('.', '').isdigit() else 9
        raw = open(f.name, 'rb').read()
        head = raw[:400].decode('utf-8', errors='replace')
        ok = (200 <= code < 400) and ('#EXTM3U' in head or len(raw) > 800)
        return ch, v, ok, round(lat, 2), code
    except Exception:
        return ch, v, False, 9, 0
    finally:
        try: os.unlink(f.name)
        except Exception: pass

def run():
    allch = defaultdict(list)
    for src, fn in SOURCE_FILES:
        fp = os.path.join(RAW_LIVE, fn)
        if not os.path.exists(fp): continue
        for n, u in parse(open(fp, encoding='utf-8', errors='replace').read()):
            if u.startswith('http') and '.m3u8' in u and '[' not in u:
                allch[norm(n)].append({'src': src, 'name': n, 'url': u})
    items = [(ch, v) for ch, vs in allch.items() for v in vs]
    print(f'待测线路: {len(items)}')

    results = []
    with ThreadPoolExecutor(max_workers=24) as ex:
        futs = [ex.submit(probe, it) for it in items]
        for i, fut in enumerate(as_completed(futs)):
            results.append(fut.result())
            if (i + 1) % 100 == 0: print(f'  进度 {i+1}/{len(items)}')

    ok_n = sum(1 for r in results if r[2]); ok_ch = set(r[0] for r in results if r[2])
    print(f'可播线路: {ok_n}/{len(results)} ({ok_n/len(results)*100:.1f}%) | 覆盖频道: {len(ok_ch)}')

    detail = [{'channel': ch, 'src': v['src'], 'name': v['name'], 'url': v['url'],
               'ok': ok, 'latency': lat, 'code': code} for ch, v, ok, lat, code in results]
    os.makedirs(DATA, exist_ok=True)
    json.dump(detail, open(os.path.join(DATA, 'live_channel_probe.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    print('已保存 data/live_channel_probe.json')

if __name__ == '__main__':
    run()
