#!/usr/bin/env node
/**
 * ysp_fetch.mjs —— 用央视频匿名接口签发 63 个公开频道的 HLS 地址，生成 m3u。
 *
 * 原理与 akiralereal/iptv 项目的 yangshipin 抓取器一致（复用了它的 api.js/ckey.js，
 * 仅依赖 Node 内置模块）。接口返回的 m3u8 带短效签名，实测十余分钟内可用，
 * 因此每日抓取一次并配合 CDN purge 即可供电视端使用。
 *
 * 输出: raw/live_unstable/ysp.m3u  (标准 m3u, group-title="央视频")
 *
 * 重要：这是短效签名地址，属于"不稳定源"，不再进入每日稳定源扫描列表。
 * 仅在手动运行 scripts/update_unstable_live.sh 时重新签发，
 * 产物由 build_unstable_live.py 单独生成订阅，避免电视端误选短效线路。
 *
 * 用法: node scripts/ysp_fetch.mjs
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { requestPlayUrls } from './ysp_lib/api.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const CHANNELS = JSON.parse(fs.readFileSync(path.join(__dirname, 'ysp_lib', 'channels.json'), 'utf8'))
const OUT = path.join(ROOT, 'raw', 'live_unstable', 'ysp.m3u')
const CONCURRENCY = 4       // 并发签发数, 保守以免触发官方按 IP 限频
const INTERVAL_MS = 300     // 每批间隔

function sleep(ms) { return new Promise(r => setTimeout(r, ms)) }

async function signOne(row, idx) {
  const [id, name, channelId, livePid, defn] = row
  const ch = { channelId, livePid, defn }
  try {
    const r = await requestPlayUrls(ch, { timeoutMs: 12000 })
    const url = r.urls && r.urls[0]
    if (!url) return { ok: false, name, reason: '无URL' }
    return { ok: true, name, url, id }
  } catch (e) {
    return { ok: false, name, reason: String(e.message || e).slice(0, 60) }
  }
}

async function main() {
  const results = []
  for (let i = 0; i < CHANNELS.length; i += CONCURRENCY) {
    const batch = CHANNELS.slice(i, i + CONCURRENCY)
    const got = await Promise.all(batch.map((row, j) => signOne(row, i + j)))
    results.push(...got)
    process.stdout.write(`\r签发进度 ${Math.min(i + CONCURRENCY, CHANNELS.length)}/${CHANNELS.length}`)
    await sleep(INTERVAL_MS)
  }
  console.log('')

  const ok = results.filter(r => r.ok)
  const fail = results.filter(r => !r.ok)

  // 安全阀: 可用率过低(疑似接口变更/限频)则不覆盖旧文件, 保留上次成功结果
  if (ok.length < 10) {
    console.error(`可用频道仅 ${ok.length}/${results.length}, 疑似接口异常, 保留上次结果`)
    if (fs.existsSync(OUT)) {
      console.error(`保留: ${OUT}`)
      process.exit(0)
    }
    process.exit(1)
  }

  const lines = ['#EXTM3U', '# 央视频公开频道(匿名签发,每日更新)',
    `# 生成时间: ${new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}`,
    `# 可用 ${ok.length}/${results.length}`, '']
  for (const r of ok) {
    lines.push(`#EXTINF:-1 group-title="央视频",${r.name}`)
    lines.push(r.url)
  }
  fs.mkdirSync(path.dirname(OUT), { recursive: true })
  fs.writeFileSync(OUT, lines.join('\n') + '\n', 'utf8')

  console.log(`生成 ${OUT}: ${ok.length} 频道`)
  if (fail.length) {
    console.log('失败频道:', fail.map(f => f.name).join(', '))
  }
}

main().catch(e => { console.error(e); process.exit(1) })
