#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tv_rewriter.py —— 生成"电视友好地址"并做直连复测

电视网络特征(实测 2026-11-20, 直连无代理):
  - cdn.jsdelivr.net       直连 200  ✓ 最稳
  - raw.liucn.cc / 国内源   直连 200  ✓
  - raw.githubusercontent   直连 200  但电视端不稳定, 统一改写为 jsdelivr
  - gh-proxy.com / moeyy.xyz 直连超时 ✗ 电视不可用, 必须改写
  - github.com/blob         404(网页非raw), 必须改写

改写规则: 任意 GitHub 仓库路径 -> https://cdn.jsdelivr.net/gh/{user}/{repo}@{branch}/{path}
直接执行 curl 直连复测, 输出 data/tv_result.json
"""
import os, sys, json, re, subprocess, hashlib, tempfile
from urllib.parse import urlparse, unquote, quote, urlsplit, urlunsplit
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CURL = 'curl'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import deep_validate_config, safety_valve

def now_cn():
    return datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S CST')

# --- GitHub URL -> jsdelivr -------------------------------------------------
def to_jsdelivr(url):
    """返回改写后的电视友好地址; 非GitHub源返回原地址"""
    if not url:
        return url, ''
    u = url.strip()
    # 1) 已经带代理前缀: https://<proxy>/https://raw... 或 .../raw.githubusercontent...
    #    覆盖 gh-proxy.com / github.moeyy.xyz / ghproxy.net / fastgit.cc / ghfast.top 等
    m = re.search(r'(https?://(?:gh-proxy\.com|github\.moeyy\.xyz|ghproxy\.net|fastgit\.cc|'
                  r'ghfast\.top|gh\.fastgit\.cc|github\.bgithub\.xyz|raw\.fastgit\.cc)/)?'
                  r'(https?://)?(raw\.githubusercontent\.com|github\.com)/(.+)', u)
    if m:
        rest = m.group(4)  # user/repo/...
        return _gh_to_cdn(rest, 'raw.githubusercontent.com'), 'github(代理/raw)→jsdelivr'

    # 1b) 代理前缀 + blob 路径: ...github.com/user/repo/blob/branch/path
    m = re.search(r'https?://(?:ghproxy\.net|fastgit\.cc|ghfast\.top|gh-proxy\.com)/'
                  r'(?:https?://)?github\.com/(.+)', u)
    if m:
        return _gh_to_cdn(m.group(1), 'github'), 'github(代理/blob)→jsdelivr'

    # 2) raw.bgithub.xyz / raw.gitmirror 等镜像
    m = re.match(r'https?://raw\.bgithub\.xyz/(.*)', u)
    if m:
        return _gh_to_cdn(m.group(1), 'bgithub'), 'bgithub镜像→jsdelivr'

    # 3) 直接 raw.githubusercontent.com
    m = re.match(r'https?://raw\.githubusercontent\.com/(.*)', u)
    if m:
        return _gh_to_cdn(m.group(1), 'raw'), 'raw.githubusercontent→jsdelivr'

    # 4) github.com/user/repo/(blob|raw)/branch/path
    m = re.match(r'https?://github\.com/(.*)', u)
    if m:
        return _gh_to_cdn(m.group(1), 'github'), 'github.com→jsdelivr'

    # 5) 已是 jsdelivr
    if 'cdn.jsdelivr.net/gh/' in u:
        u2 = _fix_jsdelivr_branch(u)
        return u2, ('修正@分支路径' if u2 != u else '')

    # 6) 中文路径百分号编码 (电视端 curl/播放器对中文路径支持差)
    u2 = encode_cn_path(u)
    return u2, ('中文路径编码' if u2 != u else '')


def _fix_jsdelivr_branch(u):
    """修正 cdn.jsdelivr.net/gh/user/repo@blob/main/x -> @main/x"""
    m = re.match(r'(https://cdn\.jsdelivr\.net/gh/[^/]+/[^@]+)@blob/(.*)', u)
    if m:
        return m.group(1) + '@' + m.group(2)
    return u


def encode_cn_path(u):
    """仅对 URL path 中的非 ASCII 字符做百分号编码, 保留 scheme/host/query"""
    try:
        s = urlsplit(u)
        if not s.netloc:
            return u
        # 若 netloc 含中文, 先 punycode
        netloc = s.netloc
        if any(ord(c) > 127 for c in netloc):
            host = netloc.split('@')[-1].split(':')[0]
            try:
                netloc = netloc.replace(host, host.encode('idna').decode('ascii'))
            except Exception:
                pass
        path = quote(s.path, safe='/')
        query = quote(s.query, safe='=&%?+')
        return urlunsplit((s.scheme, netloc, path, query, s.fragment))
    except Exception:
        return u

def _gh_to_cdn(rest, src):
    rest = rest.lstrip('/')
    # 处理 refs/heads/ 前缀
    rest = re.sub(r'^refs/heads/', '', rest)
    parts = rest.split('/')
    if src == 'github' and len(parts) >= 4 and parts[2] in ('blob', 'raw'):
        user, repo, _, branch = parts[0], parts[1], parts[2], parts[3]
        path = '/'.join(parts[4:])
    else:
        if len(parts) < 3:
            return 'https://cdn.jsdelivr.net/gh/' + rest
        user, repo, branch = parts[0], parts[1], parts[2]
        path = '/'.join(parts[3:])
    branch = unquote(branch)
    # 去掉可能的 refs/heads/ 残留
    branch = re.sub(r'^refs/heads/', '', branch)
    # jsdelivr 的 @ 引用 branch/tag/commit
    suffix = ('/' + path) if path else ''
    return f'https://cdn.jsdelivr.net/gh/{user}/{repo}@{branch}{suffix}'

# --- curl 直连探测 ----------------------------------------------------------
def curl_check(url, timeout=12):
    # 用真实临时文件承接 body (Windows 下 /dev/null 会导致 curl RC23 / size=0)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.dl')
    tmp.close()
    cmd = [CURL, '-s', '-L', '-m', str(timeout), '-o', tmp.name,
           '-w', '%{http_code}|%{time_total}|%{size_download}|%{url_effective}',
           '-A', 'Mozilla/5.0 (Linux; Android 10)', url]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 3)
        out = p.stdout.strip()
        parts = out.split('|')
        result = {'ok': False, 'code': 0, 'latency': 99, 'size': 0}
        if len(parts) >= 3:
            code = int(parts[0]) if parts[0].isdigit() else 0
            t = float(parts[1]) if parts[1].replace('.','').isdigit() else 99
            size = int(parts[2]) if parts[2].isdigit() else 0
            final = parts[3] if len(parts) > 3 else url
            # 思路4-深度验活: 200 且非空后, 按内容结构校验(非仅 HTTP 200)
            ok = code == 200 and size > 50
            detail = ''
            if ok:
                try:
                    body = open(tmp.name, 'rb').read(200000).decode('utf-8', 'ignore')
                    valid, detail = deep_validate_config(body, expect='config')
                    ok = valid
                except Exception:
                    pass
            result = {'ok': ok, 'code': code, 'latency': round(t, 2),
                      'size': size, 'final': final, 'detail': detail}
        return result
    except Exception as e:
        return {'ok': False, 'code': 0, 'latency': 99, 'size': 0, 'err': str(e)[:60]}
    finally:
        try: os.unlink(tmp.name)
        except Exception: pass

def check_one(src):
    tv_url, rewrite_note = to_jsdelivr(src['url'])
    orig = curl_check(src['url'])
    # 只有改写过才复测改写地址
    new = curl_check(tv_url) if rewrite_note else orig
    return {
        'id': src['id'], 'name': src['name'], 'orig_url': src['url'],
        'tv_url': tv_url, 'rewrite': rewrite_note,
        'adult': src.get('adult', False), 'from': src.get('from', ''),
        'orig_check': orig, 'tv_check': new,
        'tv_ok': new['ok'], 'latency': new['latency'], 'size': new['size'],
    }

def main():
    srcs = json.load(open(os.path.join(DATA, 'all_sources.json'), encoding='utf-8'))['sources']
    print(f'[{now_cn()}] 直连复测 {len(srcs)} 个源 (模拟电视无代理网络)...')
    results = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(check_one, s): s for s in srcs}
        for i, f in enumerate(as_completed(futs), 1):
            results.append(f.result())
            if i % 15 == 0:
                print(f'  进度 {i}/{len(srcs)}')

    # 思路2-测速安全阀: 可用率过低判为网络/环境误判, 保留全部避免空订阅
    valve_on, effective_ok = safety_valve(results, ok_key='tv_ok', min_rate=0.10, min_total=5)
    if valve_on:
        print(f'  ⚠ 触发安全阀: 可用率过低, 判定为环境误判, 本次保留全部 {len(effective_ok)} 个源')
        for r in results:
            r['tv_ok'] = True
        ok = effective_ok
    else:
        ok = effective_ok
    rewritten = [r for r in results if r['rewrite'] and r['tv_ok']]
    print(f'\n完成: 电视可用 {len(ok)}/{len(results)} | 其中改写后救活 {len(rewritten)} 个 | 安全阀={"开" if valve_on else "关"}')

    out = {'tested_at': now_cn(), 'network': '直连(模拟电视,无代理)',
           'total': len(results), 'tv_ok': len(ok),
           'rewritten_alive': len(rewritten), 'safety_valve': valve_on,
           'results': results}
    with open(os.path.join(DATA, 'tv_result.json'), 'w', encoding='utf-8') as fp:
        json.dump(out, fp, ensure_ascii=False, indent=2)

    # 报告
    ok_sorted = sorted(ok, key=lambda x: x['latency'])
    lines = [f'# 电视端可用性报告（直连·无代理）', '',
             f'- 测试时间: {out["tested_at"]}',
             f'- 电视可用: **{len(ok)}** / {len(results)}',
             f'- 其中通过 jsdelivr 改写救活: **{len(rewritten)}**', '',
             '## ✅ 电视可用源（按响应速度排序）', '',
             '| # | 名称 | 电视地址 | 改写 | 延迟 | 站点来源 |',
             '|---|---|---|---|---|---|']
    for i, r in enumerate(ok_sorted, 1):
        u = r['tv_url']
        disp = u[:52] + '…' if len(u) > 55 else u
        lines.append(f'| {i} | {r["name"][:16]} | `{disp}` | {"是" if r["rewrite"] else "-"} | {r["latency"]}s | {r["from"][:10]} |')
    dead = [r for r in results if not r['tv_ok']]
    lines += ['', '## ❌ 电视不可用 / 失效源', '', '| 名称 | 原因 | 原始地址 |', '|---|---|---|']
    for r in dead:
        reason = '改jsdelivr后仍失败' if r['rewrite'] else f'HTTP {r["tv_check"]["code"]}'
        lines.append(f'| {r["name"][:16]} | {reason} | `{r["orig_url"][:50]}` |')
    with open(os.path.join(ROOT, 'reports', 'tv_report.md'), 'w', encoding='utf-8') as fp:
        fp.write('\n'.join(lines) + '\n')
    print('报告: reports/tv_report.md')

if __name__ == '__main__':
    main()
