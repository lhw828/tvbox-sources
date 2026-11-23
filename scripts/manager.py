#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TVBox 影视订阅源整合管理器

子命令:
  collect   收集所有上游订阅列表, 展开并去重, 生成 data/all_sources.json
  test      并发测试所有源可用性, 生成 data/test_result.json + reports/latest.md
  build     按可用性排序, 生成影视仓/影视可直接导入的订阅文件

设计目标: 后续只需 `python scripts/manager.py collect && ... test && ... build` 一条链更新
"""
import os, sys, json, re, time, hashlib, argparse
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests

# 关闭 SSL 警告
try:
    import urllib3
    urllib3.disable_warnings()
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CONFIG = os.path.join(ROOT, 'config')
RAW = os.path.join(ROOT, 'raw')
SOURCES = os.path.join(ROOT, 'sources')
REPORTS = os.path.join(ROOT, 'reports')

for d in (DATA, CONFIG, RAW, SOURCES, REPORTS, os.path.join(REPORTS, 'history')):
    os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------------------------
# 上游种子: 用户提供的 7 个入口
# ---------------------------------------------------------------------------
SEEDS = [
    {"id": "duocang",    "name": "多仓(小羊)",   "url": "https://cdn.jsdelivr.net/gh/yangxiaoge/tvbox_cust@master/tvbox/多仓.json", "kind": "list"},
    {"id": "gao0707",    "name": "高天流云0707", "url": "https://cdn.jsdelivr.net/gh/gaotianliuyun/gao@master/0707.json",         "kind": "list"},
    {"id": "feimao",     "name": "肥猫",          "url": "https://肥猫.com",                                                      "kind": "single"},
    {"id": "ok321",      "name": "ok321",         "url": "http://ok321.top/ok",                                                  "kind": "single"},
    {"id": "jundie",     "name": "俊佬top98",     "url": "http://home.jundie.top:81/top98.json",                                "kind": "single"},
    {"id": "liucn",      "name": "老刘备m",       "url": "https://raw.liucn.cc/box/m.json",                                     "kind": "single"},
    {"id": "duocang18",  "name": "多仓adult",     "url": "https://cdn.jsdelivr.net/gh/yangxiaoge/tvbox_cust@master/tvbox/多仓adult.json", "kind": "list", "adult": True},
]

# 网络配置
PROXY = os.environ.get('TVBOX_PROXY', 'http://127.0.0.1:2080')
TIMEOUT = 12
WORKERS = 16
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36',
    'Accept': '*/*',
}


def now_cn():
    return datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S CST')


def make_session(use_proxy=False):
    s = requests.Session()
    s.headers.update(HEADERS)
    if use_proxy and PROXY:
        s.proxies = {'http': PROXY, 'https': PROXY}
    return s


def fetch(url, use_proxy=False, timeout=TIMEOUT):
    """返回 (ok, text, status, elapsed, final_url)"""
    t0 = time.time()
    try:
        s = make_session(use_proxy)
        r = s.get(url, timeout=timeout, verify=False, allow_redirects=True,
                  headers={'Accept-Encoding': 'gzip, deflate'})
        r.encoding = r.apparent_encoding or 'utf-8'
        text = r.text
        # 部分影视仓配置站对浏览器 UA 返回 HTML 落地页, 仅 okhttp(电视内核) UA 返回真 JSON。
        # 仅当拿到 HTML 落地页时才换 UA 重试, 不影响其余正常源。
        if r.status_code == 200 and text.lstrip()[:1] == '<' and '<html' in text[:500].lower():
            r = s.get(url, timeout=timeout, verify=False, allow_redirects=True,
                      headers={'Accept-Encoding': 'gzip, deflate', 'User-Agent': 'okhttp/3.12.0'})
            r.encoding = r.apparent_encoding or 'utf-8'
            text = r.text
        return (r.status_code == 200, text, r.status_code,
                round(time.time() - t0, 2), r.url)
    except Exception as e:
        return (False, '', type(e).__name__ + ': ' + str(e)[:80],
                round(time.time() - t0, 2), url)


def parse_json_loose(text):
    """容忍 // 注释和 BOM"""
    if not text:
        return None
    text = text.lstrip('\ufeff')
    # 去掉整行 // 注释
    text = re.sub(r'^\s*//.*$', '', text, flags=re.M)
    try:
        return json.loads(text)
    except Exception:
        # 尝试截取第一个 { 到最后一个 }
        a, b = text.find('{'), text.rfind('}')
        if a >= 0 and b > a:
            try:
                return json.loads(text[a:b + 1])
            except Exception:
                return None
    return None


def norm_url(u, base=None):
    """规范化 URL: 相对路径拼接, punycode 域名, 去空白"""
    if not u:
        return ''
    u = str(u).strip()
    if u.startswith('./') or u.startswith('../') or (base and not re.match(r'^\w+://', u)):
        u = urljoin(base, u) if base else u
    # 中文域名转 punycode
    try:
        p = urlparse(u)
        if p.netloc and any(ord(c) > 127 for c in p.netloc):
            host = p.netloc.encode('idna').decode('ascii')
            u = u.replace(p.netloc, host, 1)
    except Exception:
        pass
    return u


def source_id(url):
    return hashlib.md5(url.encode('utf-8')).hexdigest()[:10]


# ===========================================================================
# collect
# ===========================================================================
def cmd_collect(args):
    print(f'[{now_cn()}] 开始收集上游源...')
    all_sources = {}   # url -> meta
    seed_status = []

    # 合并额外种子(网上搜集的公开仓库, 从 extra_seeds.json 读取)
    seeds = list(SEEDS)
    extra_path = os.path.join(DATA, 'extra_seeds.json')
    if os.path.exists(extra_path):
        try:
            extra = json.load(open(extra_path, encoding='utf-8'))
            seeds.extend(extra)
            print(f'  + 载入 {len(extra)} 个额外种子 (extra_seeds.json)')
        except Exception as e:
            print(f'  ! extra_seeds.json 读取失败: {e}')

    # 合并 juwanhezi.com 聚合站抓取的单仓/多仓源（由 juhe_scraper.py 生成）
    juhe_path = os.path.join(DATA, 'juhe_sources.json')
    if os.path.exists(juhe_path):
        try:
            juhe = json.load(open(juhe_path, encoding='utf-8'))
            for i, item in enumerate(juhe.get('single', [])):
                seeds.append({"id": f"juhe_one_{i}", "name": f"[聚盒] {item['name']}",
                              "url": item['url'], "kind": "single"})
            for i, item in enumerate(juhe.get('many', [])):
                seeds.append({"id": f"juhe_many_{i}", "name": f"[聚盒多仓] {item['name']}",
                              "url": item['url'], "kind": "list"})
            print(f'  + 载入 juwanhezi 聚合源: 单仓 {len(juhe.get("single",[]))} / 多仓 {len(juhe.get("many",[]))}')
        except Exception as e:
            print(f'  ! juhe_sources.json 读取失败: {e}')

    seen_urls = set()  # 防循环 / 去重

    def expand(seed, depth=0):
        """递归展开种子；多仓(urls/storeHouse)最多展开 3 层。"""
        url = seed['url']
        if not url or url in seen_urls:
            return
        seen_urls.add(url)
        print(f'  {"  "*depth}- 抓取种子: {seed["name"]} ({url[:60]})')
        ok, text, status, elapsed, final = fetch(url, use_proxy=True, timeout=20)
        rec = {"id": seed['id'], "name": seed['name'], "url": url,
               "kind": seed['kind'], "adult": seed.get('adult', False),
               "fetch_ok": ok, "fetch_status": str(status)[:40], "fetched_at": now_cn(),
               "depth": depth}
        seed_status.append(rec)

        if not ok:
            # 直连再试一次
            ok2, text2, st2, _, final2 = fetch(url, use_proxy=False, timeout=20)
            if ok2:
                ok, text, status, final = ok2, text2, st2, final2
                rec.update(fetch_ok=True, fetch_status='直连成功')
            else:
                print(f'  {"  "*depth}  ✗ 种子不可达: {status} / {st2}')
                return

        safe = re.sub(r'[^\w\u4e00-\u9fa5]', '_', seed['id'])[:40]
        with open(os.path.join(RAW, f'seed_{safe}.txt'), 'w', encoding='utf-8') as f:
            f.write(text[:500000])

        data = parse_json_loose(text)
        # 多仓判定: urls 或 storeHouse; 且未到最大深度
        # 防病态上游: 源可能返回纯数字/数组/字符串等非 dict JSON, 直接 .get 会崩溃
        children = []
        if isinstance(data, dict):
            if isinstance(data.get('urls'), list):
                children = data['urls']
            elif isinstance(data.get('storeHouse'), list):
                children = data['storeHouse']
        if children and depth < 3:
            n = 0
            for item in children:
                if not isinstance(item, dict):
                    continue
                u = norm_url(item.get('url', item.get('sourceUrl', '')), base=url)
                if not u:
                    continue
                name = str(item.get('name', item.get('sourceName', ''))).strip() or '未命名'
                # 收录子项为单源（子项多仓会在 test 阶段以 urls 内容识别，不在 collect 递归）
                if u not in all_sources:
                    all_sources[u] = {
                        "id": source_id(u), "name": name, "url": u,
                        "from": seed['name'], "adult": seed.get('adult', False),
                        "note": str(item.get('detail', item.get('remark', '')))[:120]
                    }
                    n += 1
            if n:
                print(f'  {"  "*depth}  ✓ 展开 {n} 个子源')
        else:
            all_sources[url] = {
                "id": source_id(url), "name": seed['name'], "url": url,
                "from": seed.get('from', '用户提供'), "adult": seed.get('adult', False),
                "kind": "single", "note": '完整配置(含sites)'
            }
            print(f'  {"  "*depth}  ✓ 单配置源已收录')

    for seed in seeds:
        expand(seed)

    items = list(all_sources.values())
    out = {"collected_at": now_cn(), "total": len(items),
           "seeds": seed_status, "sources": items}
    path = os.path.join(DATA, 'all_sources.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f'\n收集完成: 共 {len(items)} 个唯一源 -> {path}')


# ===========================================================================
# test
# ===========================================================================
def test_one(src, use_proxy=False):
    ok, text, status, elapsed, final = fetch(src['url'], use_proxy=use_proxy, timeout=TIMEOUT)
    result = dict(src)
    result.update(
        tested_at=now_cn(),
        proxy=use_proxy,
        http_status=str(status)[:30],
        latency=elapsed,
        reachable=bool(ok),
        final_url=final,
    )
    if ok:
        data = parse_json_loose(text)
        if isinstance(data, dict):
            if isinstance(data.get('urls'), list):
                result['content'] = 'subscription'
                result['site_count'] = len(data['urls'])
            elif isinstance(data.get('sites'), list):
                result['content'] = 'config'
                result['site_count'] = len(data['sites'])
            else:
                result['content'] = 'json'
                result['site_count'] = 0
        elif data:
            # 合法 JSON 但非对象(纯数字/数组/字符串), 不是有效订阅配置
            result['content'] = 'json(非对象)'
            result['site_count'] = 0
        else:
            txt = text.strip()
            if txt.startswith('<'):
                result['content'] = 'html(疑似过期/落地页)'
                result['site_count'] = 0
                result['reachable'] = False  # HTML 落地页视为不可用
            else:
                result['content'] = 'text'
                result['site_count'] = 0
        result['size'] = len(text)
    else:
        result['content'] = 'unreachable'
        result['site_count'] = 0
        result['size'] = 0
    return result


def cmd_test(args):
    path = os.path.join(DATA, 'all_sources.json')
    if not os.path.exists(path):
        print('请先运行 collect'); return
    srcs = json.load(open(path, encoding='utf-8'))['sources']
    if args.limit:
        srcs = srcs[:args.limit]
    print(f'[{now_cn()}] 开始并发测试 {len(srcs)} 个源 (workers={args.workers}, 直连优先, 失败重试代理)...')

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(test_one, s, False): s for s in srcs}
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            if not r['reachable']:
                # 代理重试
                rf = test_one(futures[fut], True)
                rf['retried_proxy'] = True
                r = rf
            results.append(r)
            if i % 10 == 0:
                print(f'  进度 {i}/{len(srcs)}')

    ok_n = sum(1 for r in results if r['reachable'])
    print(f'\n测试完成: 可用 {ok_n} / {len(results)}')

    out = {"tested_at": now_cn(), "total": len(results),
           "reachable": ok_n, "results": results}
    with open(os.path.join(DATA, 'test_result.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # 历史快照
    stamp = datetime.now().strftime('%Y%m%d_%H%M')
    with open(os.path.join(REPORTS, 'history', f'result_{stamp}.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    gen_report(out)
    print(f'报告已生成: reports/latest.md')


def gen_report(out):
    results = out['results']
    ok = sorted([r for r in results if r['reachable']], key=lambda x: x['latency'])
    dead = [r for r in results if not r['reachable']]
    lines = [f'# 源可用性测试报告', '',
             f'- 测试时间: {out["tested_at"]}',
             f'- 总数: {out["total"]} | 可用: {out["reachable"]} | 失效: {len(dead)}', '',
             '## ✅ 可用源 (按响应速度排序)', '',
             '| 排名 | 名称 | 类型 | 站点数 | 延迟 | 来源 |',
             '|---|---|---|---|---|---|']
    for i, r in enumerate(ok, 1):
        lines.append(f'| {i} | {r["name"][:24]} | {r.get("content","?")} | {r.get("site_count",0)} | {r["latency"]}s | {r.get("from","")} |')
    lines += ['', '## ❌ 失效源', '', '| 名称 | URL | 状态 |', '|---|---|---|']
    for r in dead:
        lines.append(f'| {r["name"][:24]} | `{r["url"][:60]}` | {r["http_status"]} |')
    with open(os.path.join(REPORTS, 'latest.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


# ===========================================================================
# build
# ===========================================================================
def cmd_build(args):
    path = os.path.join(DATA, 'test_result.json')
    if not os.path.exists(path):
        print('请先运行 test'); return
    results = json.load(open(path, encoding='utf-8'))['results']

    ok = sorted([r for r in results if r['reachable']], key=lambda x: (x['latency'], -x.get('site_count', 0)))
    dead = [r for r in results if not r['reachable']]
    adult = [r for r in results if r.get('adult')]

    # 主订阅(影视仓格式 urls)
    main = {"urls": [{"name": r['name'], "url": r['url']} for r in ok if not r.get('adult')]}
    with open(os.path.join(CONFIG, 'subscriptions.json'), 'w', encoding='utf-8') as f:
        json.dump(main, f, ensure_ascii=False, indent=2)

    # 全部(含失效,标注状态)
    allout = [{"name": r['name'], "url": r['url'], "status": 'ok' if r['reachable'] else 'dead',
               "latency": r['latency'], "content": r.get('content', ''), "from": r.get('from', '')}
              for r in results]
    with open(os.path.join(CONFIG, 'all_sources.json'), 'w', encoding='utf-8') as f:
        json.dump(allout, f, ensure_ascii=False, indent=2)

    # 失效单独存放
    with open(os.path.join(SOURCES, 'dead.json'), 'w', encoding='utf-8') as f:
        json.dump([{"name": r['name'], "url": r['url'], "reason": r['http_status']} for r in dead],
                  f, ensure_ascii=False, indent=2)

    # 成人源单独隔离
    with open(os.path.join(SOURCES, 'adult.json'), 'w', encoding='utf-8') as f:
        json.dump({"warning": "成人内容源, 未纳入主订阅, 请按需自行添加",
                   "urls": [{"name": r['name'], "url": r['url']} for r in adult]},
                  f, ensure_ascii=False, indent=2)

    # TXT 纯链接版(方便影视"影视"类软件批量导入)
    with open(os.path.join(CONFIG, 'subscriptions.txt'), 'w', encoding='utf-8') as f:
        for r in ok:
            if not r.get('adult'):
                f.write(r['url'] + '\n')

    # 写状态到 README 占位区
    update_readme_status(ok, dead)
    print(f'构建完成:')
    print(f'  主订阅(可用 {len([r for r in ok if not r.get("adult")])} 个): config/subscriptions.json')
    print(f'  失效源单独存放: sources/dead.json ({len(dead)} 个)')
    print(f'  成人源隔离: sources/adult.json ({len(adult)} 个)')


def update_readme_status(ok, dead):
    rp = os.path.join(ROOT, 'README.md')
    if not os.path.exists(rp):
        return
    txt = open(rp, encoding='utf-8').read()
    block = [f'<!-- STATUS:START -->',
             f'> 最近更新: {now_cn()}',
             f'> 可用 **{len(ok)}** 个 / 失效 **{len(dead)}** 个', '',
             '| 状态 | 名称 | 延迟 | 类型 |', '|---|---|---|---|']
    for r in ok[:40]:
        block.append(f'| ✅ | {r["name"][:26]} | {r["latency"]}s | {r.get("content","")} |')
    for r in dead:
        block.append(f'| ❌ | {r["name"][:26]} | - | {r["http_status"][:16]} |')
    block.append('<!-- STATUS:END -->')
    new = re.sub(r'<!-- STATUS:START -->.*?<!-- STATUS:END -->', '\n'.join(block), txt, flags=re.S)
    with open(rp, 'w', encoding='utf-8') as f:
        f.write(new)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='TVBox 源整合管理器')
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('collect', help='收集并展开上游源')
    pt = sub.add_parser('test', help='测试可用性')
    pt.add_argument('--workers', type=int, default=WORKERS)
    pt.add_argument('--limit', type=int, default=0)
    sub.add_parser('build', help='生成最终订阅文件')

    args = ap.parse_args()
    {'collect': cmd_collect, 'test': cmd_test, 'build': cmd_build}[args.cmd](args)
