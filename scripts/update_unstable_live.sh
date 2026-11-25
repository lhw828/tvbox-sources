#!/usr/bin/env bash
# 短效/易过期直播源按需刷新（不进每日流水线）
# 用法: bash scripts/update_unstable_live.sh
#   1) 央视频匿名签发 63 个公开频道 (ysp_fetch.mjs，短效签名)
#   2) 聚盒聚合站直播链接下载 (juhe_live_fetch.py，易变动)
#   3) nTv webview:// 频道清单镜像 (仅供 nTv/WebView 应用)
#   4) 单独构建短效源订阅 (build_unstable_live.py)
#
# 注意：这些地址可能几小时~几天内过期，不要放进稳定源主订阅。
# 刷新后建议运行 python scripts/purge_jsdelivr.py 让电视端立即拿到新地址。
set -e
cd "$(dirname "$0")/.."

echo "=== [1/4] 央视频匿名签发(短效地址) ==="
mkdir -p raw/live_unstable
if node scripts/ysp_fetch.mjs; then
  echo "  ✓ 央视频签发完成 ($(grep -c '#EXTINF' raw/live_unstable/ysp.m3u 2>/dev/null || echo 0) 频道)"
else
  echo "  ✗ 央视频签发失败，保留原 ysp.m3u(若有)"
fi

echo "=== [2/4] 聚盒聚合直播链接 ==="
# 默认使用已有 data/juhe_sources.json 缓存；需要重新抓聚合站页面时设 REFRESH_JUHE=1
if [ "${REFRESH_JUHE:-0}" = "1" ] || [ ! -f data/juhe_sources.json ]; then
  python scripts/juhe_scraper.py
fi
python scripts/juhe_live_fetch.py

echo "=== [3/4] 镜像 nTv webview 频道清单(仅 nTv 应用可用) ==="
tmp="raw/live_unstable/webview.api.json"
if curl -s -L -m 30 --noproxy '*' -o "$tmp" \
    "https://api.github.com/repos/buhanzhe/webSourceM3U8/contents/webview.txt?ref=main" \
    && python - "$tmp" <<'PY'
import sys, json, base64
try:
    data = json.load(open(sys.argv[1], encoding='utf-8'))
    text = base64.b64decode(data['content']).decode('utf-8', errors='replace')
    open('raw/live_unstable/ntv_webview.txt', 'w', encoding='utf-8').write(text)
except Exception:
    sys.exit(1)
PY
then
  echo "  ✓ ntv_webview.txt ($(wc -c < raw/live_unstable/ntv_webview.txt) B)"
  rm -f "$tmp"
else
  rm -f "$tmp"
  echo "  ✗ 拉取失败，保留原 ntv_webview.txt"
fi

echo "=== [4/4] 构建短效源订阅 ==="
python scripts/build_unstable_live.py

echo ""
echo "产物："
echo "  subscriptions/live_unstable.json  影视仓短效备用订阅"
echo "  subscriptions/live_unstable.m3u   通用 m3u"
echo "  subscriptions/ntv_webview.txt     nTv webview 频道(影视仓不可播)"
