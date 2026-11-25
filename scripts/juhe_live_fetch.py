#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
juhe_live_fetch.py —— 把 juwanhezi 聚合站抓取到的直播链接下载到 raw/live_unstable/

输入：data/juhe_sources.json 的 live 列表（由 juhe_scraper.py 生成，不再访问页面）
输出：
  raw/live_unstable/juhe_XX.txt   每个直播源内容
  data/juhe_live_files.json  清单 [[显示名, 文件名], ...] 供 build_unstable_live.py 读取

注意：聚盒链接每日可能变动，属于"不稳定源"，不进入每日稳定源扫描。
仅手动运行 scripts/update_unstable_live.sh 时抓取。

单点失败不影响其它源；下载内容过短(疑似失效)则跳过。
"""
import os, sys, re, json, hashlib, subprocess, tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import now_cn, atomic_write_json, UA_BROWSER

DATA = os.path.join(BASE, 'data')
RAW_LIVE = os.path.join(BASE, 'raw', 'live_unstable')
UA = UA_BROWSER


def fetch_one(item, idx):
    """下载单个直播源到 raw/live_unstable，返回 (显示名, 文件名) 或 None。"""
    url = item['url']
    name = f"[聚盒] {item['name']}"
    fn = f"juhe_{idx:02d}_{hashlib.md5(url.encode()).hexdigest()[:6]}.txt"
    path = os.path.join(RAW_LIVE, fn)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.dl'); tmp.close()
    cmd = ['curl', '-s', '-L', '-m', '25', '--noproxy', '*', '-o', tmp.name,
           '-w', '%{http_code}', '-A', UA, url]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        code = p.stdout.strip()
        raw = open(tmp.name, 'rb').read() if os.path.exists(tmp.name) else b''
        text = raw.decode('utf-8', errors='replace')
        # 有效性：2xx/3xx 且内容像 m3u/txt（有频道行）
        like = ('#EXTM3U' in text or '#genre#' in text or re.search(r'^.+,https?://', text, re.M))
        if (code.startswith('2') or code.startswith('3')) and len(raw) > 200 and like:
            os.makedirs(RAW_LIVE, exist_ok=True)
            open(path, 'w', encoding='utf-8').write(text)
            print(f'  ✓ {name[:20]:<22} {len(raw):>7}B -> {fn}')
            return [name, fn]
        else:
            print(f'  ✗ {name[:20]:<22} HTTP {code} {len(raw)}B (内容不符)')
            return None
    except Exception as e:
        print(f'  ✗ {name[:20]:<22} {str(e)[:40]}')
        return None
    finally:
        try: os.unlink(tmp.name)
        except Exception: pass


def main():
    juhe_path = os.path.join(DATA, 'juhe_sources.json')
    if not os.path.exists(juhe_path):
        print('缺少 data/juhe_sources.json，请先运行 juhe_scraper.py'); return
    juhe = json.load(open(juhe_path, encoding='utf-8'))
    lives = juhe.get('live', [])
    print(f'[{now_cn()}] 下载 juwanhezi 直播源 {len(lives)} 条 -> raw/live_unstable/ ...')
    os.makedirs(RAW_LIVE, exist_ok=True)

    manifest = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(fetch_one, item, i): i for i, item in enumerate(lives)}
        for fut in as_completed(futs):
            r = fut.result()
            if r:
                manifest.append(r)
    manifest.sort(key=lambda x: x[1])
    atomic_write_json(os.path.join(DATA, 'juhe_live_files.json'),
                      {'fetched_at': now_cn(), 'files': manifest})
    print(f'完成：成功下载 {len(manifest)}/{len(lives)} 个直播源')


if __name__ == '__main__':
    main()
