const http = require('node:http')
const fs = require('node:fs')
const path = require('node:path')
const express = require('express')
const httpProxy = require('http-proxy')

const app = express()
const backendHost = process.env.MOVIEPILOT_BACKEND_HOST || '127.0.0.1'
const backendPort = Number(process.env.PORT || 3101)
const frontendPort = Number(process.env.NGINX_PORT || 0)
const gatewayPrefix = process.env.GATEWAY_PREFIX || '/app/moviepilot-v3'
const socketPath = process.env.SOCKET_PATH || ''
const backendUrl = `${backendHost}:${backendPort}`
const proxy = httpProxy.createProxyServer({ target: `http://${backendUrl}`, ws: true })
proxy.on('error', (_error, _req, res) => {
  if (res.writeHead) res.writeHead(502, { 'Content-Type': 'application/json' })
  res.end('{"success":false,"message":"后台服务暂不可用"}')
})
const assetsPath = path.join(__dirname, 'assets')
const indexPath = path.join(__dirname, 'index.html')
const configPath = process.env.CONFIG_DIR || path.join(__dirname, '..', 'config')
const logPath = process.env.MOVIEPILOT_LOG_FILE || path.join(configPath, '..', 'logs', 'moviepilot-v3.log')
const backendPidPath = process.env.MOVIEPILOT_PID_FILE || ''
const fnosScale = 0.92
const fnosCompactStyle = `<style id="fnos-compact-ui">
@media (min-width: 900px) {
  html {
    zoom: ${fnosScale};
  }
}
</style>`
const loadingBackgroundNames = [
  'loading-background.webp',
  'loading-background.jpg',
  'loading-background.jpeg',
  'loading-background.png',
]
const bundledLoadingBackgroundPath = path.join(__dirname, 'loading-background.jpg')
let isBackendReady = false

function loadingPage (basePath = '/') {
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <base href="${basePath}">
  <title>MoviePilot 正在启动</title>
  <style>
    :root { color-scheme: light dark; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    * { box-sizing: border-box; }
    html, body { width: 100%; height: 100%; margin: 0; overflow: hidden; }
    body {
      display: grid;
      place-items: center;
      color: #25262b;
      background: #f3f4f7 url('./fnos-loading-background') center / cover no-repeat;
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      background: rgba(247, 248, 251, .10);
      backdrop-filter: blur(2px);
    }
    main { position: relative; width: min(420px, calc(100vw - 48px)); text-align: center; }
    .logo { width: 72px; height: 72px; margin-bottom: 22px; }
    h1 { margin: 0; font-size: 22px; font-weight: 650; letter-spacing: 0; }
    p { margin: 10px 0 0; color: #6b6f78; font-size: 14px; line-height: 1.6; }
    #error { display: none; max-height: 132px; margin: 18px 0 0; padding: 12px 14px; overflow: auto; border: 1px solid #e4a7aa; border-radius: 6px; color: #9f242a; background: rgba(255, 244, 244, .9); font: 12px/1.55 ui-monospace, SFMono-Regular, Consolas, monospace; text-align: left; white-space: pre-wrap; overflow-wrap: anywhere; }
    .progress { width: 220px; height: 3px; margin: 28px auto 0; overflow: hidden; background: #dfe1e7; border-radius: 2px; }
    .progress::after {
      content: "";
      display: block;
      width: 42%;
      height: 100%;
      background: #8d51f9;
      animation: loading 1.25s ease-in-out infinite;
    }
    #detail { min-height: 23px; }
    #retry { display: none; margin: 18px auto 0; padding: 8px 18px; border: 1px solid #8d51f9; border-radius: 6px; color: #7540d0; background: transparent; cursor: pointer; }
    @keyframes loading { from { transform: translateX(-120%); } to { transform: translateX(340%); } }
    @media (prefers-color-scheme: dark) {
      body { color: #f2f2f4; background-color: #14161a; }
      body::before { background: rgba(18, 20, 24, .10); }
      p { color: #a8abb3; }
      .progress { background: #343740; }
      #retry { color: #b99af7; }
      #error { border-color: #744247; color: #ffb3b7; background: rgba(69, 27, 31, .82); }
    }
  </style>
</head>
<body>
  <main>
    <img class="logo" src="./logo.svg" alt="MoviePilot">
    <h1>MoviePilot 正在启动</h1>
    <p id="detail">正在初始化运行环境和后台服务</p>
    <pre id="error" role="alert"></pre>
    <div class="progress" aria-label="启动中"></div>
    <button id="retry" type="button">重新检查</button>
  </main>
  <script>
    const startedAt = Date.now()
    const detail = document.querySelector('#detail')
    const error = document.querySelector('#error')
    const progress = document.querySelector('.progress')
    const retry = document.querySelector('#retry')
    let checking = false

    async function check () {
      if (checking) return
      checking = true
      try {
        const response = await fetch('./fnos-ready?t=' + Date.now(), { cache: 'no-store' })
        const result = await response.json()
        if (result.ready) {
          detail.textContent = '启动完成，正在进入应用'
          location.reload()
          return
        }
        detail.textContent = result.status || '后台服务启动中'
        if (result.error) {
          error.textContent = result.error
          error.style.display = 'block'
          progress.style.display = 'none'
          retry.style.display = 'block'
        } else {
          error.textContent = ''
          error.style.display = 'none'
          progress.style.display = 'block'
        }
      } catch (_) {}
      checking = false
      const seconds = Math.floor((Date.now() - startedAt) / 1000)
      if (seconds >= 90 && !error.textContent) {
        detail.textContent = '启动时间较长，可在应用文件的 logs/moviepilot-v3.log 查看日志'
        retry.style.display = 'block'
      }
    }

    retry.addEventListener('click', check)
    check()
    setInterval(check, 1000)
  </script>
</body>
</html>`
}

function backendReady () {
  return new Promise(resolve => {
    const request = http.get({ host: backendHost, port: backendPort, path: '/health/ready', timeout: 3000 }, response => {
      response.resume()
      resolve(response.statusCode === 200)
    })
    request.on('error', () => resolve(false))
    request.on('timeout', () => { request.destroy(); resolve(false) })
  })
}

function cleanLogLine (line) {
  return line
    .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '')
    .replace(/([?&](?:token|apikey|api_key)=)[^&\s]+/gi, '$1***')
    .replace(/((?:token|apikey|api_key|password|passwd|secret)\s*[=:]\s*)[^\s&,]+/gi, '$1***')
    .trim()
}

function backendProcessRunning () {
  if (!backendPidPath) return true
  try {
    const pid = Number(fs.readFileSync(backendPidPath, 'utf8').trim())
    if (!Number.isInteger(pid) || pid <= 0) return false
    process.kill(pid, 0)
    return true
  } catch (_) {
    return false
  }
}

function startupState () {
  let content
  try {
    const stat = fs.statSync(logPath)
    const length = Math.min(stat.size, 128 * 1024)
    const buffer = Buffer.alloc(length)
    const fd = fs.openSync(logPath, 'r')
    try {
      fs.readSync(fd, buffer, 0, length, stat.size - length)
    } finally {
      fs.closeSync(fd)
    }
    content = buffer.toString('utf8')
  } catch (_) {
    return { status: '正在准备运行环境', error: null }
  }

  const marker = '[fnOS] MoviePilot service starting'
  const markerIndex = content.lastIndexOf(marker)
  const current = (markerIndex >= 0 ? content.slice(markerIndex + marker.length) : content).replace(
    /\(trapped\) error reading bcrypt version[\s\S]*?AttributeError:\s*module ['"]bcrypt['"] has no attribute ['"]__about__['"]\s*/gi,
    '',
  )
  const lines = current.split(/\r?\n/).map(cleanLogLine).filter(Boolean)
  const useful = lines.filter(line =>
    !/^INFO:\s+127\.0\.0\.1:/.test(line) &&
    !/^SQLite database journal mode set to:/.test(line) &&
    !/^Async SQLite database journal mode set to:/.test(line)
  )
  const processRunning = backendProcessRunning()
  const errorPatterns = /(?:\bERROR\b|Traceback \(most recent call last\)|Fatal Python error|\w*(?:Error|Exception):|Permission denied|ModuleNotFoundError)/i
  const errorIndex = processRunning ? -1 : useful.findLastIndex(line => errorPatterns.test(line))
  let error = null
  if (errorIndex >= 0) {
    const first = Math.max(0, errorIndex - 2)
    error = useful.slice(first, errorIndex + 1).join('\n').slice(-900)
  }
  if (!processRunning) {
    error = error || 'MoviePilot 后台进程已退出，请查看 logs/moviepilot-v3.log 获取完整日志。'
  }
  const statusLine = [...useful].reverse().find(line =>
    !errorPatterns.test(line) &&
    !/^(?:WARNING:|收到信号|Shutting down|INFO:\s+(?:Shutting down|Finished server process|Application shutdown complete))/i.test(line)
  )
  const status = statusLine
    ? statusLine.replace(/^(?:INFO|DEBUG):\s*/, '').slice(0, 180)
    : '后台服务启动中'
  return { status, error }
}

function scaleMediaQueries (css) {
  return css.replace(/@media[^\{]+/g, query => query.replace(/(\d+(?:\.\d+)?)px/g, (_match, value) => {
    const scaled = Math.round(Number(value) * fnosScale * 100) / 100
    return `${scaled}px`
  }))
}

function scaleVuetifyBreakpoints (javascript) {
  const scaled = value => Math.round(value * fnosScale * 100) / 100
  return javascript.replace(
    'lg:1280,xl:1920,xxl:2560',
    `lg:${scaled(1280)},xl:${scaled(1920)},xxl:${scaled(2560)}`,
  )
}

function sendIndex (req, res) {
  if (!isBackendReady) {
    const pathname = new URL(req.originalUrl, 'http://localhost').pathname
    const basePath = (pathname.endsWith('/') ? pathname : `${pathname}/`).replaceAll('"', '%22')
    res.set('Cache-Control', 'no-store')
    res.type('html').send(loadingPage(basePath))
    return
  }
  fs.readFile(indexPath, 'utf8', (error, html) => {
    if (error) {
      res.sendStatus(500)
      return
    }
    if (req.query.fnos === '1') {
      html = html
        .replaceAll('./assets/', './fnos-assets/')
        .replace('</head>', `${fnosCompactStyle}</head>`)
    }
    if (req.originalUrl.startsWith(`${gatewayPrefix}/`) || req.originalUrl === gatewayPrefix) {
      html = html
        .replace('<head>', `<head><base href="${gatewayPrefix}/">`)
        .replaceAll('src="/no-auth.js"', 'src="./no-auth.js"')
        .replaceAll("fetch('/logo.svg')", "fetch('./logo.svg')")
    }
    res.set('Cache-Control', 'no-store')
    res.type('html').send(html)
  })
}

app.use((req, res, next) => {
  if (req.path === gatewayPrefix) {
    const query = req.originalUrl.includes('?') ? req.originalUrl.slice(req.originalUrl.indexOf('?')) : ''
    res.redirect(307, `${gatewayPrefix}/${query}`)
    return
  }
  if (req.path.startsWith(`${gatewayPrefix}/`)) {
    req.url = req.url.slice(gatewayPrefix.length) || '/'
  }
  next()
})

app.get('/fnos-ready', async (_req, res) => {
  isBackendReady = await backendReady()
  const state = isBackendReady ? { status: '启动完成', error: null } : startupState()
  res.set('Cache-Control', 'no-store').json({ ready: isBackendReady, ...state })
})
app.get('/fnos-loading-background', (_req, res) => {
  const background = loadingBackgroundNames
    .map(name => path.join(configPath, name))
    .find(candidate => fs.existsSync(candidate) && fs.statSync(candidate).isFile()) ||
    (fs.existsSync(bundledLoadingBackgroundPath) ? bundledLoadingBackgroundPath : null)
  if (!background) {
    res.sendStatus(404)
    return
  }
  res.set('Cache-Control', 'no-cache').sendFile(background)
})

app.use('/fnos-assets', (req, res, next) => {
  const assetName = path.basename(req.path)
  if (!assetName || req.path !== `/${assetName}`) {
    res.sendStatus(404)
    return
  }
  const extension = path.extname(assetName)
  if (extension !== '.css' && extension !== '.js') {
    next()
    return
  }
  fs.readFile(path.join(assetsPath, assetName), 'utf8', (error, content) => {
    if (error) {
      res.sendStatus(error.code === 'ENOENT' ? 404 : 500)
      return
    }
    const transformed = extension === '.css'
      ? scaleMediaQueries(content)
      : scaleVuetifyBreakpoints(content)
    res.set('Cache-Control', 'no-store')
    res.type(extension).send(transformed)
  })
})
app.use('/fnos-assets', express.static(assetsPath))
app.get(['/', '/index.html'], sendIndex)
app.use(express.static(__dirname, { index: false }))
// Install native dependency and source updates together through FPK.
app.use((req, res, next) => {
  const blocked = ['/api/v1/system/upgrade', '/api/v1/system/update/download', '/api/v1/system/update/install']
  if (req.method === 'POST' && blocked.includes(req.path)) {
    res.status(409).json({ success: false, message: '请在飞牛应用中心安装 MoviePilot V3 的 FPK 更新包。' })
    return
  }
  next()
})
for (const route of ['/api', '/cookiecloud', '/health']) {
  app.use(route, (req, res) => {
    req.url = route + req.url
    proxy.web(req, res)
  })
}
app.get('*', sendIndex)

function start () {
  const listenTarget = socketPath || frontendPort
  if (socketPath) fs.rmSync(socketPath, { force: true })
  const server = socketPath
    ? app.listen(listenTarget)
    : app.listen(listenTarget, '127.0.0.1')
  server.on('listening', () => { if (socketPath) fs.chmodSync(socketPath, 0o660) })
  server.on('upgrade', (req, socket, head) => {
    const pathname = new URL(req.url, 'http://localhost').pathname
    if (!pathname.startsWith(`${gatewayPrefix}/api/`)) { socket.destroy(); return }
    req.url = req.url.slice(gatewayPrefix.length)
    proxy.ws(req, socket, head)
  })
  const readinessTimer = setInterval(async () => {
    isBackendReady = await backendReady()
  }, 1000)
  backendReady().then(ready => { isBackendReady = ready })
  const stop = () => server.close(() => {
    if (socketPath) fs.rmSync(socketPath, { force: true })
    process.exit(0)
  })
  process.on('SIGTERM', () => { clearInterval(readinessTimer); stop() })
  process.on('SIGINT', () => { clearInterval(readinessTimer); stop() })
}
start()
