# 📺 TVBox 影视仓 / 影视 播放源整合

> 一个自动维护的电视播放源（订阅）整合仓库。把零散、失效、需要代理的源，整理成**电视能直接打开**的订阅文件。

![订阅数](https://img.shields.io/badge/主订阅-102源-brightgreen) ![直播](https://img.shields.io/badge/稳定直播-909频道-blue) ![更新](https://img.shields.io/badge/每日自动更新-orange) ![License](https://img.shields.io/badge/license-MIT-lightgrey) [![每日源自动更新](https://github.com/lhw828/tvbox-sources/actions/workflows/daily_test.yml/badge.svg?branch=main)](https://github.com/lhw828/tvbox-sources/actions/workflows/daily_test.yml)
---

## 🎯 为什么有这个项目

在电视（尤其国内网络、老安卓设备）上用影视仓 / TVBox / 影视 时，常遇到三类问题：

1. 订阅源东一块西一块，格式不统一；
2. 很多源挂了、过期了，或者变成"域名待售"页面；
3. 大量好源托管在 GitHub，电视直连打不开，得靠 `gh-proxy` 之类代理——而这些代理本身也经常失效。

本项目做了三件事：

- **整合**：把多个上游多仓列表收敛去重；
- **修复**：把 GitHub 源统一改写成 `cdn.jsdelivr.net/gh/...` 直连地址（电视无需代理即可打开）；失效的源单独隔离；
- **可维护**：一条命令重新测活、重新生成，并配有每日自动检测的 GitHub Actions。

---

## 📊 当前状态

<!-- STATUS:START -->
> 最近一次检测：2026-11-25 09:30:51 CST（直连(模拟电视,无代理)）
> 汇总：收录 **240** 个源 ｜ 电视可用 **102** 个 ｜ 主订阅 **102** 个 ｜ 改写救活 **33** 个 ｜ 失效隔离 **138** 个
<!-- STATUS:END -->

---

## 📡 如何使用（电视端）

在影视仓 / TVBox / 影视 的「设置 → 订阅 / 配置地址 / 仓库」中填入下面任一地址。所有地址已套用 jsDelivr CDN，**电视无需代理即可直连**，复制整条粘贴到电视即可。

### 点播源

| 用途 | 订阅地址（CDN 直链） |
|---|---|
| **主订阅（推荐）** | `https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@refs/heads/main/subscriptions/tvbox.json` |
| **精选快速源** | `https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@refs/heads/main/subscriptions/tvbox_fast.json` |
| **纯链接 TXT** | `https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@refs/heads/main/subscriptions/tvbox.txt` |
| **按来源分组** | `https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@refs/heads/main/subscriptions/by_source.json` |

> 主订阅含全部已验证可用的源，按响应速度排序；快速源只保留延迟 < 1.5s 的；分组订阅含「大象」分组。
> CDN 可能有几分钟缓存，刚更新后未生效可稍等，或在地址末尾加 `?t=时间戳` 强制刷新。`@refs/heads/main` 也可换成更短的 `@main`（等价）。

### 📺 直播源（独立，与点播互不影响）

直播源已按**稳定性**拆成两套，互不干扰：

| 类别 | 来源 | 更新方式 | 订阅地址 |
|---|---|---|---|
| **✅ 稳定源（推荐）** | 老刘备 / Kimentanm / 范明明 / YanG / akira 三源 / NativeWasmTv 央视固定 CDN | 每日自动刷新、每日探测 | `https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@main/subscriptions/iptv_own.json` |
| **⚠️ 短效备用源** | 央视频匿名签发（短效签名）/ 聚盒聚合站 | **不进每日流水线**，按需手动刷新 | `https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@main/subscriptions/live_unstable.json` |

其他格式：

| 用途 | 订阅地址（CDN 直链） |
|---|---|
| 稳定源 m3u | `https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@main/subscriptions/iptv_own.m3u` |
| 实测可播精选 | `https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@main/subscriptions/iptv_verified.m3u` |
| 短效源 m3u | `https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@main/subscriptions/live_unstable.m3u` |

> 稳定源每条频道保留多条线路并按可用性排序：实测可播优先 → 电视专用协议(mitv/rtmp) → 运营商直连 → 普通 m3u8 → 带鉴权参数的排最后。`mitv://` 为小米电视专用协议，自动探测工具测不出但在电视上可播，已保留。
> 短效源**已去重**且完全独立存放，不参与每日扫描（探测线路从 634 降至 540），避免电视端误选几小时就过期的线路。央视频频道需要重新签发时才更新，刷新后记得清 CDN 缓存。详细统计见 [`reports/live_own_report.md`](reports/live_own_report.md)。

---

## 📁 目录结构

```
tvbox-sources/
├── subscriptions/          # 最终给电视用的订阅文件（直接用这里）
│   ├── tvbox.json          # 主订阅：全部可用源，按速度排序
│   ├── tvbox_fast.json     # 精选：快速源
│   ├── tvbox.txt           # 纯链接，逐行导入用
│   ├── by_source.json      # 按上游来源分组
│   ├── iptv_own.json       # 自建直播源（独立于点播）
│   ├── iptv_own.m3u        # 自建直播 m3u（全量）
│   ├── iptv_verified.m3u   # 实测可播精选 m3u
│   ├── live_*.txt          # 稳定源分组明细
│   ├── live_unstable.*     # 短效备用源(m3u/txt/json)
│   ├── ntv_all.m3u         # nTv 插件清单(非影视仓)
│   └── ntv_webview.txt     # nTv webview 频道(非影视仓)
├── sources/                # 分类隔离
│   ├── dead.json           # 失效源（含失败原因）
│   ├── rewritten.json      # 改写记录（原始 → 电视友好地址）
│   └── adult.json          # 大象分组
├── data/
│   ├── all_sources.json    # 收集去重后的全量源
│   ├── extra_seeds.json    # 额外种子（可自行增删）
│   ├── juhe_sources.json   # 聚合站抓取的链接缓存
│   ├── tv_result.json      # 直连检测原始结果
│   └── last_good/          # 上次成功的订阅快照（失败时回退）
├── reports/                # 检测报告与资产清单
├── scripts/                # 抓取 / 测活 / 构建 / 一键更新脚本
└── .github/workflows/
    └── daily_test.yml      # 每日自动检测并更新
```

---

## 🔄 本地更新

```bash
pip install requests
bash scripts/update_all.sh          # 更新点播源
bash scripts/update_live.sh         # 更新直播稳定源（每日流水线）
bash scripts/update_unstable_live.sh # 按需刷新短效源（央视频签发/聚盒/webview）
```

> 短效源**不要**每日跑：它不进入每日扫描，需要时手动执行，刷新后建议运行 `python scripts/purge_jsdelivr.py` 清 CDN 缓存。
> 如果电脑直连外网不通，可设置 `TVBOX_PROXY=http://127.0.0.1:2080`（仅用于抓取上游列表；电视可用性检测始终走直连，保证贴近电视真实环境）。
> 想新增稳定直播来源，编辑 `scripts/live_probe_all.py` 与 `scripts/build_own_live.py` 的 `SOURCE_FILES`。

---

## 🛡️ 失败回退（保证不返回空订阅）

点播与直播的构建脚本在写出交付文件前都会做异常检测：可用源为空、或较上次成功结果骤降超过 50% 时，**自动从 `data/last_good/` 恢复上一次成功的订阅文件**。每次构建成功后会自动快照到该目录。GitHub Actions 里即使某一步失败，也会保留上次成功的订阅内容。

---

## 🔧 改写规则

| 原始形式 | 电视友好地址 |
|---|---|
| `raw.githubusercontent.com/u/r/branch/path` | `cdn.jsdelivr.net/gh/u/r@branch/path` |
| `github.com/u/r/blob/branch/path` | `cdn.jsdelivr.net/gh/u/r@branch/path` |
| `gh-proxy.com` / `ghproxy.net` / `fastgit.cc` / `ghfast.top` 等代理前缀 | `cdn.jsdelivr.net/gh/...` |
| `raw.bgithub.xyz/u/r/branch/path` | `cdn.jsdelivr.net/gh/u/r@branch/path` |
| 含中文的路径 | 自动做百分号编码 |

只有改写后**直连复测通过**的才会进入主订阅；改不活的进 `sources/dead.json`。

---

## ⏰ 自动更新

GitHub Actions 每天 **北京时间 15:37**（UTC 07:37，低负载时段）自动跑一遍**点播 + 直播稳定源**两套更新：可用的源会更新订阅文件并自动提交，失效的会被移出主订阅；任一步失败都会保留上次成功的订阅内容。短效源不在此列，需手动刷新。也可在 Actions 页面手动触发。

---

## ⚠️ 免责声明

- 本项目**不存储任何视频内容**，仅整理公开网络的订阅配置地址；
- 所有资源来自互联网，仅供学习研究，请勿用于商业用途；
- 源的可用性随时间变化，不保证长期有效；请使用方遵守当地法律法规。

---

## 📄 License

[MIT](LICENSE)
