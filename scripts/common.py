#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common.py —— tvbox-sources 脚本共享工具

借鉴 riowang88/tvbox-source-aggregator 的 4 个思路：
  1) 频道名规范化（繁简转换 + 去 HD/4K/1080p 后缀 + 压空白）→ normalize_channel_name
  2) 测速安全阀（可用率过低判为环境误判，保留全部）→ safety_valve
  3) type 字面量防护（URL 中 type→%74ype，防 TVBox 误判 FongMi 格式）→ scrub_url_type
  4) 深度验活（按内容类型校验 list/class 或 XML 结构，非仅 HTTP 200）→ deep_validate_config

另外提供：
  - fetch_last_good / atomic_write：失败保留上一次成功内容，避免返回空订阅
"""
import os, re, json, time, tempfile
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'data')
LAST_GOOD = os.path.join(BASE, 'data', 'last_good')
UA_TV = 'okhttp/3.12.0'
UA_BROWSER = 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36'


def now_cn():
    return datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S CST')


# ===========================================================================
# 思路 1: 频道名规范化
# ===========================================================================
TRAD_SIMP = {
    '電': '电', '視': '视', '臺': '台', '頻': '频', '綜': '综', '藝': '艺',
    '體': '体', '劇': '剧', '經': '经', '華': '华', '東': '东', '國': '国',
    '際': '际', '亞': '亚', '歐': '欧', '財': '财', '鳳': '凤', '衛': '卫',
    '視': '视', '頻': '频', '頻': '频', '畫': '画', '質': '质', '碼': '码',
    '無': '无', '線': '线', '數': '数', '頻道': '频道', ' Movie': '',
}
# 顺序很重要：长后缀先匹配
SUFFIX_PATTERNS = [
    r'\s*[\[\(【]?\s*4K\s*[\]\)】]?\s*$',
    r'\s*[\[\(【]?\s*8K\s*[\]\)】]?\s*$',
    r'\s*[\[\(【]?\s*UHD\s*[\]\)】]?\s*$',
    r'\s*[\[\(【]?\s*FHD\s*[\]\)】]?\s*$',
    r'\s*[\[\(【]?\s*1080P?\s*[\]\)】]?\s*$',
    r'\s*[\[\(【]?\s*720P?\s*[\]\)】]?\s*$',
    r'\s*[\[\(【]?\s*HD\s*[\]\)】]?\s*$',
    r'\s*[\[\(【]?\s*高清\s*[\]\)】]?\s*$',
    r'\s*[\[\(【]?\s*超清\s*[\]\)】]?\s*$',
    r'\s*[\[\(【]?\s*蓝光\s*[\]\)】]?\s*$',
    r'\s*[\[\(【]?\s*藍光\s*[\]\)】]?\s*$',
]


def normalize_channel_name(raw):
    """繁简转换 → 去画质后缀 → 去空白 → 大写，用于跨源合并同一频道。"""
    if not raw:
        return ''
    s = str(raw).strip()
    s = ''.join(TRAD_SIMP.get(c, c) for c in s)
    for p in SUFFIX_PATTERNS:
        s = re.sub(p, '', s, flags=re.I)
    s = re.sub(r'\s+', '', s)
    # 复合写法 "中央卫视CCTV-1" -> 去掉中央/卫视前缀后交给 CCTV 匹配
    s = re.sub(r'^中央(?:卫视|电视台)?(?=CCTV)', '', s)
    # 常见的 "CCTV-1"/"CCTV1"/"中央1"/"中央卫视1" 统一成 CCTV1
    # 先处理带"中央"前缀的复合写法：中央1/中央卫视1/中央1套 -> CCTV1
    m = re.match(r'^中央(?:卫视|电视台)?[-—]?(\d+)', s)
    if m:
        return 'CCTV' + m.group(1)
    # 去掉 "卫视/电视台" 这类修饰词后再匹配 CCTV 数字
    s = re.sub(r'^(?:CCTV)?(?:卫视|电视台)', '', s)
    m = re.match(r'^CCTV[-—]?(\d+)', s, re.I)
    if m:
        return 'CCTV' + m.group(1)
    return s.upper() or str(raw).strip()


# ===========================================================================
# 思路 2: 测速安全阀
# ===========================================================================
def safety_valve(results, ok_key='ok', min_rate=0.10, min_total=5):
    """
    可用率过低时判为网络/环境误判，返回 (True, 全部视为可用)。
    results: list[dict]; ok_key: 结果中标记成功的布尔字段。
    返回 (triggered, effective_ok_list)
    """
    total = len(results)
    oks = [r for r in results if r.get(ok_key)]
    if total >= min_total and len(oks) / total < min_rate:
        return True, list(results)
    return False, oks


# ===========================================================================
# 思路 3: type 字面量防护
# ===========================================================================
def scrub_url_type(url, skip_signed=True):
    """
    URL 中的 type 首字符做百分号编码（type→%74ype），防 TVBox lives.contains('type') 误判为 FongMi 格式。
    skip_signed=True 时，含鉴权/签名参数(mac/authinfo/token/sign 等)的 URL 不改写，避免破坏签名校验。
    """
    if not url:
        return url
    if skip_signed and re.search(r'(mac=|authinfo=|livodtoken=|gmac=|token=|sign=|key=)', url, re.I):
        return url
    return re.sub(r'type', lambda m: '%74ype', url, flags=re.I)


def scrub_name_type(name):
    """名称中的 type 字样替换为 tp（仅用于 lives Native 输出）。"""
    return re.sub(r'type', 'tp', str(name), flags=re.I) if name else name


# ===========================================================================
# 思路 4: 深度验活
# ===========================================================================
def deep_validate_config(text, expect='config'):
    """
    按内容类型做结构校验（非仅 HTTP 200）。
    expect: 'config' 期待含 sites/urls；'live' 期待 m3u/txt 频道结构；'any' 宽松。
    返回 (valid: bool, detail: str)
    """
    if not text or len(text) < 20:
        return False, '内容过短'
    head = text[:500].lower()
    if '<html' in head and ('for sale' in head or '待售' in head or 'domain' in head or '404' in head):
        return False, 'HTML落地页/404'
    stripped = text.lstrip('\ufeff').strip()
    if expect in ('config', 'any'):
        try:
            data = json.loads(stripped)
        except Exception:
            # 容错：JSONP / // 注释
            m = re.match(r'^\w+\((.*)\)$', stripped, re.S)
            c = m.group(1) if m else re.sub(r'^\s*//.*$', '', stripped, flags=re.M)
            try:
                data = json.loads(c)
            except Exception:
                data = None
        if isinstance(data, dict):
            if isinstance(data.get('sites'), list) and data['sites']:
                return True, 'sites(%d)' % len(data['sites'])
            if isinstance(data.get('urls'), list) and data['urls']:
                return True, 'urls(%d)' % len(data['urls'])
            if expect == 'any':
                return True, 'json'
            return False, 'JSON无有效sites/urls'
    if expect in ('live', 'any'):
        if '#EXTM3U' in text or '#EXTINF' in text:
            n = text.count('#EXTINF')
            return (n > 0, 'm3u(%d)' % n)
        if '#genre#' in text or re.search(r'^.+,https?://', text, re.M):
            n = len(re.findall(r'^.+,https?://', text, re.M))
            return (n > 0, 'txt(%d)' % n)
    return False, '无法识别的内容格式'


# ===========================================================================
# 失败回退：保留上一次成功内容，原子写入
# ===========================================================================
def atomic_write(path, content, mode='w'):
    """原子写：先写临时文件再 os.replace，避免写一半被中断产生空文件。"""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix='.tmp')
    try:
        with os.fdopen(fd, mode, encoding='utf-8' if 'b' not in mode else None) as f:
            f.write(content)
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        return False


def atomic_write_json(path, obj):
    return atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=2))


def save_last_good(files):
    """把本次成功生成的交付文件快照到 data/last_good/。files: [相对路径]"""
    os.makedirs(LAST_GOOD, exist_ok=True)
    saved = []
    for rel in files:
        src = os.path.join(BASE, rel)
        if os.path.exists(src) and os.path.getsize(src) > 0:
            dst = os.path.join(LAST_GOOD, rel.replace('/', '__'))
            atomic_write(dst, open(src, encoding='utf-8').read())
            saved.append(rel)
    return saved


def restore_last_good(files):
    """当新构建失败/为空时，从上次成功快照恢复交付文件。返回恢复的文件列表。"""
    restored = []
    for rel in files:
        src = os.path.join(LAST_GOOD, rel.replace('/', '__'))
        if os.path.exists(src) and os.path.getsize(src) > 0:
            dst = os.path.join(BASE, rel)
            atomic_write(dst, open(src, encoding='utf-8').read())
            restored.append(rel)
    return restored


def has_content(rel, min_size=50):
    p = os.path.join(BASE, rel)
    return os.path.exists(p) and os.path.getsize(p) >= min_size
