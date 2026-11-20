#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_final.py —— 基于电视可用性结果生成最终交付文件

输出:
  subscriptions/tvbox.json        影视仓/影视 可直接导入的订阅(全部可用,按速度排序)
  subscriptions/tvbox_fast.json   精选: 延迟<1.5s 的快速源
  subscriptions/by_source.json    按上游来源分组
  sources/dead.json               失效源单列
  sources/rewritten.json          被改写的源(记录原始→改写映射)
  sources/adult.json              成人源隔离
  reports/inventory.md            资产清单
"""
import os, json
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
SUB = os.path.join(ROOT, 'subscriptions')
SRC = os.path.join(ROOT, 'sources')
REP = os.path.join(ROOT, 'reports')
for d in (SUB, SRC, REP):
    os.makedirs(d, exist_ok=True)

def now_cn():
    return datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S CST')

def main():
    d = json.load(open(os.path.join(DATA, 'tv_result.json'), encoding='utf-8'))
    results = d['results']
    ok = [r for r in results if r['tv_ok']]
    dead = [r for r in results if not r['tv_ok']]
    adult = [r for r in ok if r.get('adult')]
    # 成人源默认纳入主订阅, 分组名显示为"大象"
    ADULT_GROUP = '大象'
    def group_name(r):
        return ADULT_GROUP if r.get('adult') else r.get('from', '其他')
    normal = list(ok)
    fast = [r for r in normal if r['latency'] < 1.5]
    rewritten = [r for r in ok if r['rewrite']]

    # 按延迟排序; 同延时按 name
    normal.sort(key=lambda x: (x['latency'], x['name']))
    fast.sort(key=lambda x: (x['latency'], x['name']))

    def entry(r):
        e = {'name': r['name'], 'url': r['tv_url']}
        return e

    # 主订阅(影视仓格式)
    json.dump({'urls': [entry(r) for r in normal]},
              open(os.path.join(SUB, 'tvbox.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    json.dump({'urls': [entry(r) for r in fast]},
              open(os.path.join(SUB, 'tvbox_fast.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)

    # 按来源分组 (成人源归入"大象"组)
    groups = {}
    for r in normal:
        groups.setdefault(group_name(r), []).append(entry(r))
    json.dump(groups, open(os.path.join(SUB, 'by_source.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)

    # TXT 纯链接(影视批量导入)
    with open(os.path.join(SUB, 'tvbox.txt'), 'w', encoding='utf-8') as f:
        for r in normal:
            f.write(r['tv_url'] + '\n')

    # 失效源
    json.dump([{'name': r['name'], 'url': r['orig_url'],
                'http': r['tv_check']['code'], 'reason': '直连不可达/上游失效'}
               for r in dead],
              open(os.path.join(SRC, 'dead.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)

    # 改写映射
    json.dump([{'name': r['name'], 'original': r['orig_url'], 'tv_url': r['tv_url'],
                'rule': r['rewrite']} for r in rewritten],
              open(os.path.join(SRC, 'rewritten.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)

    # 成人源(已纳入主订阅, 分组名"大象"; 此处保留单独清单便于查看)
    json.dump({'note': '大象分组: 已纳入主订阅 tvbox.json, 此处单独列出便于查看',
               'count': len(adult),
               'urls': [dict(entry(r), group=ADULT_GROUP) for r in adult]},
              open(os.path.join(SRC, 'adult.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)

    # 清单
    lines = [f'# 源资产清单', '',
             f'- 生成时间: {now_cn()}',
             f'- 数据来源: {d["tested_at"]} ({d["network"]})', '',
             f'| 分类 | 数量 | 文件 |', f'|---|---|---|',
             f'| ✅ 可用(主订阅) | {len(normal)} | `subscriptions/tvbox.json` |',
             f'| ⚡ 精选快速源(<1.5s) | {len(fast)} | `subscriptions/tvbox_fast.json` |',
             f'| 🔧 改写救活 | {len(rewritten)} | `sources/rewritten.json` |',
             f'| ❌ 失效单列 | {len(dead)} | `sources/dead.json` |',
             f'| 🐘 大象分组(已纳入主订阅) | {len(adult)} | `sources/adult.json` |', '',
             '## 改写救活的源(原始 → 电视友好地址)', '']
    for r in rewritten:
        lines.append(f'- **{r["name"][:16]}** ({r["rewrite"]})')
        lines.append(f'  - 原: `{r["orig_url"]}`')
        lines.append(f'  - 新: `{r["tv_url"]}`')
    lines += ['', '## 失效源清单', '']
    for r in dead:
        lines.append(f'- ❌ {r["name"][:20]} — HTTP {r["tv_check"]["code"]} — `{r["orig_url"][:70]}`')
    open(os.path.join(REP, 'inventory.md'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')

    # 同步 README 状态区块
    import re
    rp = os.path.join(ROOT, 'README.md')
    if os.path.exists(rp):
        txt = open(rp, encoding='utf-8').read()
        block = ('<!-- STATUS:START -->\n'
                 f'> 最近一次检测：{d["tested_at"]}（{d["network"]}）\n'
                 f'> 汇总：收录 **{d["total"]}** 个源 ｜ 电视可用 **{len(ok)}** 个 ｜ '
                 f'主订阅 **{len(normal)}** 个 ｜ 改写救活 **{len(rewritten)}** 个 ｜ '
                 f'失效隔离 **{len(dead)}** 个\n'
                 '<!-- STATUS:END -->')
        txt = re.sub(r'<!-- STATUS:START -->.*?<!-- STATUS:END -->', block, txt, flags=re.S)
        open(rp, 'w', encoding='utf-8').write(txt)

    print(f'构建完成 @ {now_cn()}')
    print(f'  主订阅可用: {len(normal)}  快速精选: {len(fast)}')
    print(f'  改写救活: {len(rewritten)}  失效单列: {len(dead)}  成人隔离: {len(adult)}')

if __name__ == '__main__':
    main()
