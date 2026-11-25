#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ntv_fetch.py —— 从 buhanzhe/NativeWasmTv 内置频道表提取稳定的直连直播源

内置频道表(builtin_channels.txt)含 webview:// 嗅探地址(我们的静态订阅用不了)和
央视固定 CDN 的 m3u8(无签名、无过期、长期稳定)。本脚本只保留后者，生成标准
m3u 到 raw/live/ntv.m3u，供 live_probe_all.py / build_own_live.py 融入。

下载失败或提取到的直连地址过少时保留上次缓存，不写空。
使用 GitHub API 取文件内容（raw.githubusercontent 在部分网络不稳定）。
"""
import os, sys, re, json, base64, subprocess, tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import now_cn, UA_BROWSER

RAW_LIVE = os.path.join(BASE, 'raw', 'live')
SRC_URL = ('https://api.github.com/repos/buhanzhe/NativeWasmTv/contents/'
           'app/src/main/assets/builtin_channels.txt?ref=master')
OUT = os.path.join(RAW_LIVE, 'ntv.m3u')
UA = UA_BROWSER


def extract(text):
    """从内置 M3U 提取直连 http(s) 频道，返回标准 m3u 文本。"""
    lines = text.splitlines()
    out = ['#EXTM3U']
    name = None
    seen = set()
    for line in lines:
        line = line.strip()
        if line.startswith('#EXTINF'):
            # 名称取最后一个逗号后的部分
            m = re.search(r',([^,]+)$', line)
            gm = re.search(r'group-title="([^"]+)"', line)
            group = gm.group(1) if gm else '央视'
            name = (group, m.group(1) if m else '')
        elif line and not line.startswith('#'):
            # 只保留 http(s) 直连; 跳过 webview:// / rtmp / rtsp
            if not re.match(r'^https?://', line):
                continue
            # 跳过带过期签名参数的地址(txSecret/txTime 等)
            if re.search(r'txSecret=|txTime=|sign=|token=', line, re.I):
                continue
            if line in seen:
                continue
            seen.add(line)
            group, nm = name if name else ('央视', '未知')
            out.append(f'#EXTINF:-1 group-title="{group}",{nm}')
            out.append(line)
    return '\n'.join(out) + '\n', len(seen)


def main():
    os.makedirs(RAW_LIVE, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.dl')
    tmp.close()
    try:
        p = subprocess.run(
            ['curl', '-s', '-L', '-m', '30', '--noproxy', '*', '-o', tmp.name,
             '-w', '%{http_code}', '-A', UA, SRC_URL],
            capture_output=True, text=True, timeout=35)
        code = p.stdout.strip()
        raw = open(tmp.name, encoding='utf-8', errors='replace').read() if os.path.exists(tmp.name) else ''
        try:
            data = json.loads(raw)
            text = base64.b64decode(data.get('content', '')).decode('utf-8', errors='replace') if 'content' in data else raw
        except Exception:
            text = raw
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

    if not code.startswith('2') or len(text) < 200:
        print(f'[{now_cn()}] 下载失败(HTTP {code})，保留原 ntv.m3u')
        return

    m3u, n = extract(text)
    if n < 5:
        print(f'[{now_cn()}] 直连频道仅 {n} 个(异常偏少)，保留原 ntv.m3u')
        return

    old_n = 0
    if os.path.exists(OUT):
        old_n = open(OUT, encoding='utf-8', errors='replace').read().count('#EXTINF')
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(m3u)
    print(f'[{now_cn()}] ntv.m3u 已更新: {n} 个直连频道(原 {old_n})')


if __name__ == '__main__':
    main()
