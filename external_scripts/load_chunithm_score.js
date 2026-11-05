// CHUNITHM-NET 成绩导出（chu-gen-videob30 专用）
//
// 用法：登录 CHUNITHM-NET → 浏览器开发者工具的 Console（控制台）→ 粘贴本文件全文 → 回车
//       左上角出现面板后点「下载 .json」，再拿到【获取 / 管理存档】页「我玩外服」上传。
//
// 输出（utils/DataUtils.py 的 intr 字段映射直接吃）：
//   {
//     "source": "chunithm-net",
//     "host": "chunithm-net-eng.com",
//     "exportedAt": "2026-11-05T04:30:00.000Z",
//     "best": [{ idx, title, difficulty, score, isAllJustice, isFullCombo, fullChainLv }, ...],
//     "new":  [{ ... }]
//   }
//
// 定数与单曲 rating 不在这里算：曲名对三服曲库、rating 都由工具本地完成
// （utils/PageUtils.py 的 _process_intl_data），免得两边各算一套、对不上账。
// 选择器取自 CHUNITHM-NET 移动端成绩页，改版时改下面 PAGES / 解析函数即可。

(async function () {
  "use strict"

  const host = location.hostname
  const supported = host === "chunithm-net-eng.com" || host === "chunithm-net.com" || host.endsWith(".chunithm-net.com")
  if (!supported) {
    alert("请先打开并登录 CHUNITHM-NET，再在它的页面上运行本脚本。")
    return
  }

  // 成绩页在 /mobile 下；有的部署会在 /mobile 前再套一层路径，跟着当前地址走
  const mobileMatch = location.pathname.match(/^(.*\/mobile)(?:\/|$)/)
  const baseUrl = location.origin + (mobileMatch ? mobileMatch[1] : "/mobile")

  // 与 utils/Variables.py 的 LEVEL_LABELS 一致：下标就是 CHUNITHM-NET 的 diff 值
  const DIFFICULTY_NAMES = ["BASIC", "ADVANCED", "EXPERT", "MASTER", "ULTIMA"]
  const PAGES = [
    { name: "旧曲 Best30", path: "/home/playerData/ratingDetailBest/" },
    { name: "新曲 New20", path: "/home/playerData/ratingDetailRecent/" }
  ]
  const REQUEST_INTERVAL_MS = 400

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

  // ---------- 页面浮层 ----------

  document.getElementById("chugen-chunithm-export")?.remove()

  const panel = document.createElement("div")
  panel.id = "chugen-chunithm-export"
  panel.style.cssText = [
    "position:fixed", "top:12px", "left:12px", "z-index:2147483647", "width:340px",
    "padding:14px 16px", "border-radius:10px", "background:rgba(24,26,38,.95)", "color:#fff",
    "font:14px/1.6 system-ui,'Microsoft YaHei',sans-serif", "box-shadow:0 8px 28px rgba(0,0,0,.45)"
  ].join(";")

  const titleEl = document.createElement("div")
  titleEl.textContent = "CHUNITHM-NET 成绩导出"
  titleEl.style.cssText = "font-weight:600;margin-bottom:6px"

  const statusEl = document.createElement("div")
  statusEl.style.cssText = "opacity:.85;min-height:44px;white-space:pre-wrap"

  const actions = document.createElement("div")
  actions.style.cssText = "display:flex;gap:8px;margin-top:10px"

  panel.append(titleEl, statusEl, actions)
  document.body.appendChild(panel)

  function setStatus(message) {
    statusEl.textContent = message
    console.log(`[chu-gen] ${message}`)
  }

  function addButton(label, onClick) {
    const button = document.createElement("button")
    button.textContent = label
    button.style.cssText = "flex:1;padding:8px 10px;border:0;border-radius:6px;background:#7b6ce7;color:#fff;font:14px system-ui,'Microsoft YaHei',sans-serif;cursor:pointer"
    button.onclick = onClick
    actions.appendChild(button)
    return button
  }

  // ---------- 解析 ----------

  function readScore(row) {
    const scoreEl = row.querySelector(".play_musicdata_highscore .text_b") || row.querySelector(".play_musicdata_highscore")
    const score = parseInt((scoreEl ? scoreEl.textContent : "").replace(/[^0-9]/g, ""), 10)
    return Number.isFinite(score) ? score : null
  }

  function readDifficultyId(row) {
    const diffEl = row.querySelector('input[name="diff"]')
    const fromInput = diffEl ? parseInt(diffEl.value, 10) : NaN
    if (fromInput >= 0 && fromInput < DIFFICULTY_NAMES.length) return fromInput
    // 有版本只给 bg_<难度> 的 class，不给 hidden input
    const bgClass = Array.from(row.classList).find((name) => name.startsWith("bg_"))
    return bgClass ? DIFFICULTY_NAMES.indexOf(bgClass.slice(3).toUpperCase()) : -1
  }

  // FC / AJ / CHAIN 在页面上是图标：类名、图片名或 alt 里带关键字。
  // 逐元素扫一遍比钉死选择器抗改版；扫不到就当没达成，不影响成绩本身。
  function readMarks(row) {
    const marks = { isAllJustice: false, isFullCombo: false, fullChainLv: 0 }
    row.querySelectorAll("[class], img").forEach((el) => {
      const token = [el.getAttribute("class"), el.getAttribute("src"), el.getAttribute("alt")]
        .filter(Boolean).join(" ").toLowerCase()
      if (token.includes("alljustice")) marks.isAllJustice = true
      else if (token.includes("fullcombo")) marks.isFullCombo = true
      if (token.includes("fullchain")) {
        marks.fullChainLv = token.includes("fullchain2") || token.includes("gold") ? 2 : 1
      }
    })
    return marks
  }

  function parseRows(doc) {
    const records = []
    const skipped = []
    doc.querySelectorAll(".musiclist_box").forEach((row) => {
      const titleEl = row.querySelector(".music_title")
      const idxEl = row.querySelector('input[name="idx"]')
      const title = titleEl ? titleEl.textContent.trim() : ""
      const idx = idxEl ? parseInt(idxEl.value, 10) : NaN
      const score = readScore(row)
      const difficultyId = readDifficultyId(row)
      // idx 是下游给图片 / 视频命名的依据（utils/DataUtils.py 的 video_tag），缺了整条没法用
      if (!title || score === null || !Number.isInteger(idx) || difficultyId < 0) {
        skipped.push(row)
        return
      }
      const marks = readMarks(row)
      records.push({
        idx,
        title,
        difficulty: DIFFICULTY_NAMES[difficultyId],
        score,
        isAllJustice: marks.isAllJustice,
        isFullCombo: marks.isAllJustice || marks.isFullCombo,
        fullChainLv: marks.fullChainLv
      })
    })
    skipped.forEach((row) => console.warn("[chu-gen] 跳过无法解析的成绩行", row))
    return records
  }

  async function fetchPage(page) {
    setStatus(`正在读取${page.name}…`)
    const response = await fetch(baseUrl + page.path, { credentials: "same-origin" })
    if (!response.ok) throw new Error(`${page.name}页面返回 HTTP ${response.status}，登录状态可能已失效`)
    const doc = new DOMParser().parseFromString(await response.text(), "text/html")
    return parseRows(doc)
  }

  // ---------- 落地 ----------

  function downloadJson(text) {
    const stamp = new Date().toISOString().replace(/[^0-9]/g, "").slice(0, 14)
    const url = URL.createObjectURL(new Blob([text], { type: "application/json" }))
    const link = document.createElement("a")
    link.href = url
    link.download = `chunithm-net_${stamp}.json`
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 10000)
  }

  async function copyJson(text) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return
    }
    const area = document.createElement("textarea")
    area.value = text
    area.style.cssText = "position:fixed;left:-9999px;top:0"
    document.body.appendChild(area)
    area.select()
    const ok = document.execCommand("copy")
    area.remove()
    if (!ok) throw new Error("浏览器拒绝了剪贴板访问")
  }

  try {
    setStatus("开始导出…")
    const best = await fetchPage(PAGES[0])
    await sleep(REQUEST_INTERVAL_MS)
    const current = await fetchPage(PAGES[1])
    if (best.length === 0 && current.length === 0) {
      throw new Error("两个成绩页都没有解析到数据，可能是未登录或页面改版")
    }

    const payload = {
      source: "chunithm-net",
      host: host,
      exportedAt: new Date().toISOString(),
      best: best,
      new: current
    }
    const text = JSON.stringify(payload, null, 2)
    setStatus(`旧曲 ${best.length} 首、新曲 ${current.length} 首。\n点「下载 .json」，再上传到工具「我玩外服」里。`)

    addButton("下载 .json", () => downloadJson(text))
    addButton("复制 JSON", async () => {
      try {
        await copyJson(text)
        setStatus(`已复制 ${best.length + current.length} 条成绩到剪贴板`)
      } catch (error) {
        setStatus(`复制失败：${error.message}，请改用「下载 .json」`)
      }
    })
  } catch (error) {
    console.error(error)
    setStatus(`导出失败：${error.message}`)
  }
})()
