#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推送后刷新 jsDelivr 缓存，让订阅链接立即指向最新内容。

背景：jsDelivr 对 GitHub 文件缓存 s-maxage=43200(12h)，每日更新后
电视端最长要等 12 小时才能拿到新订阅。本脚本在 git push 之后调用
公开的 purge API 主动清缓存，CDN 回源即拿到最新文件。

注意：README 中订阅链接混用了 @main 与 @refs/heads/main 两种写法，
它们是两个不同的缓存键，必须都 purge。
"""
import os
import sys
import time

import requests

REPO = os.environ.get('GITHUB_REPOSITORY', 'lhw828/tvbox-sources')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUBS_DIR = os.path.join(ROOT, 'subscriptions')
REFS = ['main', 'refs/heads/main']
PURGE = 'https://purge.jsdelivr.net/gh/{repo}@{ref}/{path}'


def main():
    files = sorted(
        f for f in os.listdir(SUBS_DIR)
        if os.path.isfile(os.path.join(SUBS_DIR, f))
    )
    if not files:
        print('订阅目录为空，跳过 purge')
        return 0

    s = requests.Session()
    s.headers.update({'User-Agent': 'tvbox-sources-purge/1.0'})
    ok = 0
    failed = []
    total = len(REFS) * len(files)

    for ref in REFS:
        for f in files:
            url = PURGE.format(repo=REPO, ref=ref, path='subscriptions/' + f)
            last_err = ''
            for attempt in range(3):
                try:
                    r = s.get(url, timeout=20)
                    data = r.json()
                    throttled = any(
                        p.get('throttled') for p in data.get('paths', {}).values()
                    )
                    if (r.status_code == 200
                            and data.get('status') == 'finished'
                            and not throttled):
                        ok += 1
                        last_err = ''
                        break
                    last_err = 'HTTP {} status={} throttled={}'.format(
                        r.status_code, data.get('status'), throttled)
                except Exception as e:
                    last_err = '{}: {}'.format(type(e).__name__, str(e)[:80])
                time.sleep(0.5 * (attempt + 1))
            else:
                failed.append((ref, f, last_err))
                print('  x purge失败: @{} / {} -> {}'.format(ref, f, last_err))

    print('jsDelivr缓存刷新: {}/{} 成功'.format(ok, total))
    if failed:
        print('失败明细:', failed)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
