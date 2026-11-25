#!/usr/bin/env bash
# 直播源每日流水线（只处理"稳定、长期可用"来源）
# 用法: bash scripts/update_live.sh
#   1) 下载稳定来源聚合文件到 raw/live/（老刘备/Kimentanm/范明明/YanG/akira）
#   2) NativeWasmTv 内置频道表提取央视固定 CDN 地址 (ntv_fetch.py)
#   3) 聚合地址测活 (live_manager.py test)
#   4) 频道级全量探测 (live_probe_all.py，频道名规范化 + 安全阀)
#   5) 构建稳定源自建订阅 (build_own_live.py，type防护 + 失败回退)
#   6) 生成 nTv 插件加载清单 (ntv_plugin_fetch.py，仅指向本仓库配置)
#
# 短效/易过期源（央视频每日签发、聚盒聚合、webview://）不在此流水线，
# 请按需运行 scripts/update_unstable_live.sh，避免每日扫描浪费时间、误选失效线路。
set -e
cd "$(dirname "$0")/.."

echo "=== [1/6] 下载稳定聚合源 + 各来源聚合文件 ==="
mkdir -p raw/live
declare -A LIVE_URLS=(
  [liucn_tvlive.txt]="https://raw.liucn.cc/box/libs/tv/tvlive.txt"
  [kimentanm.m3u]="https://cdn.jsdelivr.net/gh/Kimentanm/aptv@master/m3u/iptv.m3u"
  [fanmingming_index.m3u]="https://cdn.jsdelivr.net/gh/fanmingming/live@main/tv/m3u/index.m3u"
  [yang_gather.m3u]="https://cdn.jsdelivr.net/gh/YanG-1989/m3u@main/Gather.m3u"
  [akira_iptv.m3u]="https://cdn.jsdelivr.net/gh/akiralereal/iptv@main/IPTV.m3u"
  [akira_overseas.m3u]="https://cdn.jsdelivr.net/gh/akiralereal/iptv@main/IPTV-overseas.m3u"
  [akira_web.m3u]="https://cdn.jsdelivr.net/gh/akiralereal/iptv@main/from-the-web/from-the-web.m3u"
)
for f in "${!LIVE_URLS[@]}"; do
  # 单源下载失败时保留原缓存文件，避免写空
  tmp="raw/live/${f}.tmp"
  if curl -s -L -m 30 --noproxy '*' -o "$tmp" "${LIVE_URLS[$f]}" && [ -s "$tmp" ]; then
    mv "$tmp" "raw/live/$f"
    echo "  ✓ $f ($(wc -c < "raw/live/$f") B)"
  else
    rm -f "$tmp"
    echo "  ✗ $f 下载失败，保留原缓存"
  fi
done

echo "=== [2/6] NativeWasmTv 内置频道表提取央视固定 CDN 地址(长期稳定) ==="
python scripts/ntv_fetch.py

echo "=== [3/6] 聚合地址测活 ==="
python scripts/live_manager.py test

echo "=== [4/6] 频道级全量探测(仅稳定源) ==="
python scripts/live_probe_all.py

echo "=== [5/6] 构建稳定源自建订阅 ==="
python scripts/build_own_live.py

echo "=== [6/6] 生成 nTv 插件加载清单 ==="
python scripts/ntv_plugin_fetch.py

echo ""
echo "全部完成。产物："
echo "  subscriptions/iptv_own.json      影视仓直播订阅(稳定源,分10组)"
echo "  subscriptions/iptv_own.m3u       稳定源 m3u"
echo "  subscriptions/ntv_all.m3u        nTv 插件清单(仅 nTv 应用可用)"
echo "  reports/live_own_report.md       报告"
echo ""
echo "短效源(央视频/聚盒/webview)请按需运行: bash scripts/update_unstable_live.sh"
