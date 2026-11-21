# TVBox 影视仓 / 影视 播放源整合

> 一个自动维护的电视播放源（订阅）整合仓库。把所有零散、失效、需要代理的源，整理成**电视能直接打开**的订阅文件。

## 为什么有这个项目

在电视（尤其国内网络、老安卓设备）上用影视仓 / TVBox / 影视 时，常遇到三类问题：

1. 订阅源东一块西一块，格式不统一；
2. 很多源挂了、过期了，或者变成"域名待售"页面；
3. 大量好源托管在 GitHub，电视直连打不开，得靠 `gh-proxy` 之类代理——而这些代理本身也经常失效。

本项目做了三件事：

- **整合**：把多个上游多仓列表收敛去重；
- **修复**：把 GitHub 源统一改写成 `cdn.jsdelivr.net/gh/...` 直连地址（电视无需代理即可打开）；失效的源单独隔离；
- **可维护**：一条命令重新测活、重新生成，并配有每日自动检测的 GitHub Actions。

## 当前状态

<!-- STATUS:START -->
> 最近一次检测：2026-11-21 14:21:14 CST（直连(模拟电视,无代理)）
> 汇总：收录 **89** 个源 ｜ 电视可用 **54** 个 ｜ 主订阅 **54** 个 ｜ 改写救活 **20** 个 ｜ 失效隔离 **35** 个
<!-- STATUS:END -->

## 如何使用（电视端）

在影视仓 / TVBox / 影视 的「设置 → 订阅 / 配置地址 / 仓库」中填入下面任一地址（Raw 链接）：

下面地址已套用 jsdelivr CDN 代理（`cdn.jsdelivr.net`），**电视无需代理即可直连**，复制整条粘贴到电视即可。

| 用途 | 订阅地址（CDN 直链） | 说明 |
|---|---|---|
| **主订阅（推荐）** | `https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@refs/heads/main/subscriptions/tvbox.json` | 全部已验证可用的源，按响应速度排序 |
| **精选快速源** | `https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@refs/heads/main/subscriptions/tvbox_fast.json` | 延迟 < 1.5s 的源，条数少、加载快 |
| **纯链接 TXT** | `https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@refs/heads/main/subscriptions/tvbox.txt` | 部分"影视"类软件支持逐行批量导入 |
| **按来源分组** | `https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@refs/heads/main/subscriptions/by_source.json` | 按上游分组；含「大象」分组 |

> 以上为纯文本地址，方便直接复制进电视。CDN 可能有最多几分钟缓存，刚更新后若未生效可稍等或在地址末尾加 `?t=时间戳` 强制刷新。
> 想用更短的地址，也可把 `@refs/heads/main` 换成 `@main`（两者等价，均已验证可用）。

### 📺 直播源（独立，与点播互不影响）

把多个公开来源的直播频道整合、重新分组、按实测可用性排序，形成**自建直播源**。电视端在「直播 / 列表订阅」中填入：

| 用途 | 订阅地址（CDN 直链） | 说明 |
|---|---|---|
| **自建直播（推荐）** | `https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@main/subscriptions/iptv_own.json` | 802 频道 / 1104 线路，分 10 组（央视/卫视/4K/国际/地方等） |
| **实测可播精选** | `https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@main/subscriptions/iptv_verified.m3u` | 39 个实测连通的频道，通用 m3u 格式 |
| **自建 m3u** | `https://cdn.jsdelivr.net/gh/lhw828/tvbox-sources@main/subscriptions/iptv_own.m3u` | 全量频道，每频道取最优线路 |

- 每条频道保留多条线路并按可用性排序：**实测可播优先 → 电视专用协议(mitv/rtmp) → 运营商直连 → 普通 m3u8 → 带鉴权参数的排最后**，播放器会逐个尝试。
- `mitv://` 为小米电视专用协议、`rtmp://` 需专用内核，自动探测工具测不出来但在电视上可播，已保留。
- 详细分组与统计见 [`reports/live_own_report.md`](reports/live_own_report.md)。

## 目录结构

```
tvbox-sources/
├── subscriptions/          # 最终给电视用的订阅文件（直接用这里）
│   ├── tvbox.json          # 主订阅：全部可用源，按速度排序
│   ├── tvbox_fast.json     # 精选：快速源
│   ├── tvbox.txt           # 纯链接，逐行导入用
│   ├── by_source.json      # 按上游来源分组
│   ├── iptv_own.json       # 自建直播源（分组订阅，独立于点播）
│   ├── iptv_own.m3u        # 自建直播 m3u（全量）
│   ├── iptv_verified.m3u   # 实测可播精选 m3u
│   └── live_*.txt          # 直播分组明细（cctv/satellite/... 供 iptv_own.json 引用）
├── sources/                # 分类隔离
│   ├── dead.json           # 失效源（含失败原因）
│   ├── rewritten.json      # 被改写的源（记录 原始 → 电视友好地址）
│   └── adult.json          # 大象分组（已纳入主订阅，此处单独列出便于查看）
├── data/
│   ├── all_sources.json    # 收集去重后的全量源
│   ├── extra_seeds.json    # 额外种子（网上搜集的公开仓库，可自行增删）
│   └── tv_result.json      # 每次直连检测的原始结果
├── reports/
│   ├── tv_report.md        # 电视可用性报告（人读）
│   ├── inventory.md        # 资产清单 + 改写映射
│   └── history/            # 历史检测快照
├── scripts/
│   ├── manager.py          # 收集 / 测活 / 构建
│   ├── tv_rewriter.py      # 电视网络复测 + GitHub→jsdelivr 改写
│   ├── build_final.py      # 生成最终订阅文件（点播）
│   ├── update_all.sh       # 一键更新（点播）
│   ├── live_manager.py     # 直播源聚合测活
│   ├── live_probe_all.py   # 频道级全量探测
│   ├── build_own_live.py   # 构建自建直播源
│   └── update_live.sh      # 一键更新（直播）
└── .github/workflows/
    └── daily_test.yml      # 每日自动检测并更新
```

## 本地更新

```bash
pip install requests
bash scripts/update_all.sh
```

三步流程：

1. `manager.py collect` — 抓取所有上游列表，展开、去重、中文域名转 punycode；
2. `tv_rewriter.py` — 用**直连**（模拟电视无代理网络）逐个复测，并把 GitHub 源改写成 jsdelivr；
3. `build_final.py` — 按可用性排序，生成所有交付文件。

> 如果你的电脑直连外网不通，可在第 1 步设置 `TVBOX_PROXY=http://127.0.0.1:2080`（仅用于抓取上游列表；第 2 步的电视可用性检测始终走直连，以保证结果贴近电视真实环境）。

更新**直播源**（需在国内网络环境本地运行，因为频道连通探测依赖国内网络）：

```bash
bash scripts/update_live.sh
```

四步：抓取聚合源 → 聚合地址测活 → 频道级全量探测 → 构建自建直播源。直播源不在 GitHub Actions 上运行（海外服务器会把国内可播源误判为失效）。想新增直播来源，编辑 `scripts/live_manager.py` 的 `load_seeds()` 和 `scripts/build_own_live.py` 的 `SOURCE_FILES`。

## 改写规则

| 原始形式 | 电视友好地址 |
|---|---|
| `raw.githubusercontent.com/u/r/branch/path` | `cdn.jsdelivr.net/gh/u/r@branch/path` |
| `github.com/u/r/blob/branch/path` | `cdn.jsdelivr.net/gh/u/r@branch/path` |
| `gh-proxy.com/https://raw.githubusercontent.com/...` | `cdn.jsdelivr.net/gh/...` |
| `github.moeyy.xyz/https://raw.githubusercontent.com/...` | `cdn.jsdelivr.net/gh/...` |
| `raw.bgithub.xyz/u/r/branch/path` | `cdn.jsdelivr.net/gh/u/r@branch/path` |
| 含中文的路径 | 自动做百分号编码 |

只有改写后**直连复测通过**的才会进入主订阅；改不活的进 `sources/dead.json`。

## 自动更新

GitHub Actions 每天北京时间 08:00 自动跑一遍检测：可用的源会更新订阅文件并自动提交；失效的会被移出主订阅。也可在 Actions 页面手动触发。

## 免责声明

- 本项目**不存储任何视频内容**，仅整理公开网络的订阅配置地址；
- 所有资源来自互联网，仅供学习研究，请勿用于商业用途；
- 源的可用性随时间变化，不保证长期有效；请使用方遵守当地法律法规。

## License

[MIT](LICENSE)
