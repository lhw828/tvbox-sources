#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ntv_plugin_fetch.py —— 生成 nTv 应用可用的插件清单 ntv_all.m3u
==============================================================
上游：https://github.com/buhanzhe/ntv-plugin 的 all.m3u
  * 每条 #EXTINF 的地址指向一个 .jar 插件（带 sha256 锁定），
    这是 nTv 应用的插件安装协议，影视仓/FongMi 的 lives[].jar 需要 CatVod Spider，
    两者不兼容，因此本清单仅供 nTv 应用使用，不混入主直播订阅。

改造点：
  * 把上游 TVBox 插件条目的 url 参数改指向本仓库的 subscriptions/tvbox.json，
    让 nTv 用户可直接加载本项目订阅；
  * 其余插件（文件浏览、BL 哔哩哔哩）保留上游固定版本与 sha256。

输出：subscriptions/ntv_all.m3u
失败时保留上次产物，不写空文件。
"""
import os, sys, re, json, base64, tempfile, subprocess
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import now_cn, UA_BROWSER, atomic_write

SRC = ('https://api.github.com/repos/buhanzhe/ntv-plugin/contents/all.m3u?ref=main')
OUT = os.path.join(BASE, 'subscriptions', 'ntv_all.m3u')
OUR_CONFIG = ('https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@main/'
              'subscriptions/tvbox.json')


def download(url):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.dl')
    tmp.close()
    try:
        p = subprocess.run(
            ['curl', '-s', '-L', '-m', '25', '--noproxy', '*',
             '-o', tmp.name, '-w', '%{http_code}', '-A', UA_BROWSER, url],
            capture_output=True, text=True, timeout=30)
        code = p.stdout.strip()
        raw = open(tmp.name, encoding='utf-8', errors='replace').read() if os.path.exists(tmp.name) else ''
        # API 返回 base64 编码的文件内容；兼容直链纯文本
        try:
            data = json.loads(raw)
            text = base64.b64decode(data.get('content', '')).decode('utf-8', errors='replace') if 'content' in data else raw
        except Exception:
            text = raw
        return code, text
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def point_to_our_config(url):
    """替换/追加 url 参数，保留 sha256 与其余参数。"""
    parts = urlsplit(url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    q['url'] = OUR_CONFIG
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(q), parts.fragment))


def to_cdn(url):
    """raw.githubusercontent 的定版地址改写成 jsDelivr，电视端无需代理。"""
    parts = urlsplit(url)
    m = re.match(r'^/([^/]+)/([^/]+)/([0-9a-f]{40})/(.+)$', parts.path)
    if parts.netloc == 'raw.githubusercontent.com' and m:
        user, repo, sha, path = m.groups()
        return urlunsplit(('https', 'cdn.jsdelivr.net',
                           f'/gh/{user}/{repo}@{sha}/{path}',
                           parts.query, parts.fragment))
    return url


def main():
    code, text = download(SRC)
    lines = text.splitlines()
    jars = [l for l in lines if '.jar?' in l or l.rstrip().endswith('.jar')]
    if not code.startswith('2') or len(jars) < 2:
        print(f'[{now_cn()}] 上游 all.m3u 获取失败(HTTP {code}, jar 条目 {len(jars)})，保留原 ntv_all.m3u')
        return

    out = [
        '#EXTM3U',
        '# ⚠ 本清单是 nTv 应用的插件安装源，影视仓/FongMi 不能直接播放，请勿混入直播订阅',
        f'# 生成时间: {now_cn()}',
        '# 来源: https://github.com/buhanzhe/ntv-plugin (插件版本与 sha256 以上游为准)',
        '# jar 地址已改写为 jsDelivr 并锁定上游 commit，电视端无需代理',
        '# TVBox 插件已指向本项目配置: ' + OUR_CONFIG,
        '',
    ]
    name = None
    count = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith('#EXTINF'):
            name = line
            continue
        if '.jar' not in line:
            continue
        line = to_cdn(line)
        if '/plugins/tvbox/dist/tvbox.jar' in line:
            line = point_to_our_config(line)
        if name:
            out.append(name)
            name = None
        out.append(line)
        count += 1

    if count < 2:
        print(f'  ⚠ 生成条目 {count} 个，异常偏少，保留原 ntv_all.m3u')
        return

    atomic_write(OUT, '\n'.join(out) + '\n')
    print(f'[{now_cn()}] ntv_all.m3u 已更新: {count} 个插件条目')


if __name__ == '__main__':
    main()
