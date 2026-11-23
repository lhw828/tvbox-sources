#!/usr/bin/env bash
# 直播源一键更新流水线
# 用法: bash scripts/update_live.sh
#   0) 若无 juhe_sources.json 则抓取一次聚合站页面(只抓这一处)
#   1) 下载 juwanhezi 直播链接 + 各来源聚合文件到 raw/live/
#   2) 央视频匿名签发 63 个公开频道 (ysp_fetch.mjs)
#   3) 聚合地址测活 (live_manager.py test)
#   4) 频道级全量探测 (live_probe_all.py，频道名规范化 + 安全阀)
#   5) 构建自建源 (build_own_live.py，type防护 + 失败回退)
set -e
cd "$(dirname "$0")/.."

# 若还没有聚盒链接缓存(或明确要求刷新)，抓一次页面；后续只读缓存不再访问页面
if [ "${REFRESH_JUHE:-0}" = "1" ] || [ ! -f data/juhe_sources.json ]; then
  echo "=== [0/6] 抓取 juwanhezi 聚合站链接 ==="
  python scripts/juhe_scraper.py
else
  echo "=== [0/6] 使用已有 juhe_sources.json (需刷新设 REFRESH_JUHE=1) ==="
fi

echo "=== [1/6] 下载聚盒直播源 + 各来源聚合文件 ==="
mkdir -p raw/live
python scripts/juhe_live_fetch.py
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

echo "=== [2/6] 央视频匿名签发 63 个公开频道(短效地址, 每次重签) ==="
if node scripts/ysp_fetch.mjs; then
  echo "  ✓ 央视频签发完成 ($(grep -c '#EXTINF' raw/live/ysp.m3u 2>/dev/null || echo 0) 频道)"
else
  echo "  ✗ 央视频签发失败, 保留原 ysp.m3u(若有)"
fi

echo "=== [3/6] 聚合地址测活 ==="
python scripts/live_manager.py test

echo "=== [4/6] 频道级全量探测 ==="
python scripts/live_probe_all.py

echo "=== [5/6] 构建自建源 ==="
python scripts/build_own_live.py

echo ""
echo "全部完成。产物："
echo "  subscriptions/iptv_own.json      影视仓直播订阅(自建,分10组)"
echo "  subscriptions/iptv_own.m3u       自建 m3u"
echo "  subscriptions/iptv_verified.m3u  实测可播精选"
echo "  reports/live_own_report.md       报告"
