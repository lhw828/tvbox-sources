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
import os, json, sys
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import save_last_good, restore_last_good

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
SUB = os.path.join(ROOT, 'subscriptions')
SRC = os.path.join(ROOT, 'sources')
REP = os.path.join(ROOT, 'reports')
for d in (SUB, SRC, REP):
    os.makedirs(d, exist_ok=True)

def now_cn():
    return datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S CST')


def site_count(r):
    """从 tv_check.detail 解析源内站点数 (形如 'sites(234)' / 'urls(12)')。"""
    import re
    detail = str(r.get('tv_check', {}).get('detail', ''))
    m = re.search(r'(?:sites|urls)\((\d+)\)', detail, re.I)
    return int(m.group(1)) if m else 0


def sort_key(r):
    """纯延迟排序: 延迟小者优先, 同延迟按名称。不再考虑源内站点数。"""
    return (r['latency'], r['name'])


def main():
    d = json.load(open(os.path.join(DATA, 'tv_result.json'), encoding='utf-8'))
    results = d['results']
    ok = [r for r in results if r['tv_ok']]
    dead = [r for r in results if not r['tv_ok']]
    adult = [r for r in ok if r.get('adult')]

    # 失败回退(需求4): 若可用源为空或较上次骤降>50%, 保留上次成功的点播订阅
    SUB_OUTPUTS = ['subscriptions/tvbox.json', 'subscriptions/tvbox_fast.json',
                   'subscriptions/tvbox.txt', 'subscriptions/by_source.json',
                   'sources/dead.json', 'sources/rewritten.json', 'sources/adult.json',
                   'data/tv_result.json']
    prev_ok = os.path.join(DATA, 'last_good', 'data__tv_result.json')
    if len(ok) == 0:
        restored = restore_last_good(SUB_OUTPUTS)
        print(f'  ⚠ 本次无可用源，已保留上次成功的点播订阅 ({len(restored)} 个文件)')
        return
    if os.path.exists(prev_ok):
        try:
            prev_n = json.load(open(prev_ok, encoding='utf-8')).get('tv_ok', 0)
        except Exception:
            prev_n = 0
        if prev_n >= 10 and len(ok) < prev_n * 0.5:
            restored = restore_last_good(SUB_OUTPUTS)
            print(f'  ⚠ 可用源异常骤降({prev_n} → {len(ok)})，已保留上次成功的点播订阅 ({len(restored)} 个文件)')
            return

    # 成人源默认纳入主订阅, 分组名显示为"大象"
    ADULT_GROUP = '大象'
    def group_name(r):
        return ADULT_GROUP if r.get('adult') else r.get('from', '其他')
    normal = list(ok)
    rewritten = [r for r in ok if r['rewrite']]

    # 纯延迟排序: 从快到慢, 不考虑源内站点数
    normal.sort(key=sort_key)
    fast = [r for r in normal if r['latency'] < 1.5]

    # 全局编号(从快到慢 1,2,3...), 名称前加 "01. " 形式。
    # 固定宽度补零, 使部分客户端按字符串排序时编号也不会乱。
    width = max(2, len(str(len(normal))))
    def numbered(r):
        return f"{r.get('_rank', 0):0{width}d}. {r['name']}"

    for i, r in enumerate(normal, 1):
        r['_rank'] = i

    def entry(r):
        return {'name': numbered(r), 'url': r['tv_url']}

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
             '## 编号与排序规则', '',
             '> 主订阅名称前的编号即排名：**单纯按延迟从快到慢**排序，不再参考源内站点数。', '',
             '| 编号 | 源名 | 延迟 |', '|---|---|---|']
    for r in normal:
        lines.append(f'| {numbered(r)} | {r["name"]} | {r["latency"]}s |')
    lines += ['', '## 改写救活的源(原始 → 电视友好地址)', '']
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

    # 构建成功，快照到 last_good 供后续失败时回退
    saved = save_last_good(SUB_OUTPUTS)
    print(f'构建完成 @ {now_cn()}')
    print(f'  主订阅可用: {len(normal)}  快速精选: {len(fast)}')
    print(f'  改写救活: {len(rewritten)}  失效单列: {len(dead)}  成人隔离: {len(adult)}')
    print(f'  已快照 {len(saved)} 个文件到 data/last_good/')

if __name__ == '__main__':
    main()
