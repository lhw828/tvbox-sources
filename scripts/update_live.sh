#!/usr/bin/env bash
# 直播源一键更新流水线
# 用法: bash scripts/update_live.sh
#   1) 重新抓取各来源聚合文件到 raw/live/
#   2) 聚合地址测活 (live_manager.py test)
#   3) 频道级全量探测 (build_own_live 依赖的结果)
#   4) 构建自建源 (build_own_live.py)
set -e
cd "$(dirname "$0")/.."

echo "=== [1/4] 重新抓取聚合源 ==="
mkdir -p raw/live
declare -A LIVE_URLS=(
  [liucn_tvlive.txt]="https://raw.liucn.cc/box/libs/tv/tvlive.txt"
  [kimentanm.m3u]="https://cdn.jsdelivr.net/gh/Kimentanm/aptv@master/m3u/iptv.m3u"
  [fanmingming_index.m3u]="https://cdn.jsdelivr.net/gh/fanmingming/live@main/tv/m3u/index.m3u"
  [yang_gather.m3u]="https://cdn.jsdelivr.net/gh/YanG-1989/m3u@main/Gather.m3u"
)
for f in "${!LIVE_URLS[@]}"; do
  curl -s -L -m 30 -o "raw/live/$f" "${LIVE_URLS[$f]}" && \
    echo "  ✓ $f ($(wc -c < "raw/live/$f") B)" || echo "  ✗ $f"
done

echo "=== [2/4] 聚合地址测活 ==="
python scripts/live_manager.py test

echo "=== [3/4] 频道级全量探测 ==="
python scripts/live_probe_all.py

echo "=== [4/4] 构建自建源 ==="
python scripts/build_own_live.py

echo ""
echo "全部完成。产物："
echo "  subscriptions/iptv_own.json      影视仓直播订阅(自建,分10组)"
echo "  subscriptions/iptv_own.m3u       自建 m3u"
echo "  subscriptions/iptv_verified.m3u  实测可播精选"
echo "  reports/live_own_report.md       报告"
