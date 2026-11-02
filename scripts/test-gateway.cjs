const assert = require('node:assert/strict')
const http = require('node:http')
const net = require('node:net')
const { spawn } = require('node:child_process')
const { setTimeout: delay } = require('node:timers/promises')
const { once } = require('node:events')
const path = require('node:path')

async function listen (server) {
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  return server.address().port
}

async function main () {
  let ready = false
  let upgradedPath = null
  const backend = http.createServer((req, res) => {
    if (req.url === '/health/ready') {
      res.writeHead(ready ? 200 : 503).end('{}')
    } else if (req.url === '/api/v1/stream') {
      res.writeHead(200, { 'Content-Type': 'text/event-stream' })
      res.write('data: first\n\n')
      const timer = setTimeout(() => res.end('data: last\n\n'), 2000)
      res.on('close', () => clearTimeout(timer))
    } else {
      res.setHeader('Content-Type', 'application/json')
      res.end(JSON.stringify({ path: req.url }))
    }
  })
  backend.on('upgrade', (req, socket) => {
    upgradedPath = req.url
    socket.end('HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n')
  })
  const backendPort = await listen(backend)
  const reservation = http.createServer()
  const frontendPort = await listen(reservation)
  await new Promise(resolve => reservation.close(resolve))
  const child = spawn(process.execPath, [path.resolve('.build/public/service.js')], {
    env: { ...process.env, PORT: String(backendPort), NGINX_PORT: String(frontendPort),
      SOCKET_PATH: '', GATEWAY_PREFIX: '/app/moviepilot-v3' },
    stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true,
  })
  let output = ''
  child.stderr.on('data', value => { output += value })
  const origin = `http://127.0.0.1:${frontendPort}`
  const prefix = `${origin}/app/moviepilot-v3`
  try {
    let connected = false
    for (let i = 0; i < 50; i++) {
      if (child.exitCode !== null) throw new Error(output)
      try { await fetch(`${prefix}/fnos-ready`); connected = true; break } catch (_) { await delay(100) }
    }
    assert.equal(connected, true, 'Gateway failed to start: ' + output)
    assert.match(await (await fetch(prefix + '/')).text(), /正在启动/)
    assert.equal((await (await fetch(prefix + '/fnos-ready')).json()).ready, false)
    ready = true
    assert.equal((await (await fetch(prefix + '/fnos-ready')).json()).ready, true)
    const html = await (await fetch(prefix + '/?fnos=1')).text()
    assert.match(html, /<base href="\/app\/moviepilot-v3\/">/)
    assert.match(html, /src="\.\/no-auth.js"/)
    assert.match(html, /fnos-compact-ui/)
    const api = await (await fetch(prefix + '/api/v1/test?x=1')).json()
    assert.equal(api.path, '/api/v1/test?x=1')
    const blocked = await fetch(prefix + '/api/v1/system/update/install', { method: 'POST' })
    assert.equal(blocked.status, 409)
    const started = Date.now()
    const stream = await fetch(prefix + '/api/v1/stream')
    const reader = stream.body.getReader()
    const first = await reader.read()
    assert.match(new TextDecoder().decode(first.value), /data: first/)
    assert.ok(Date.now() - started < 1500, 'SSE response was buffered')
    await reader.cancel()
    await new Promise((resolve, reject) => {
      const socket = net.connect(frontendPort, '127.0.0.1')
      socket.on('error', reject)
      socket.setTimeout(3000, () => { socket.destroy(); reject(new Error('WebSocket upgrade timed out')) })
      socket.on('connect', () => socket.write('GET /app/moviepilot-v3/api/v1/ws?token=x HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n'))
      socket.once('data', data => {
        try { assert.match(data.toString(), /^HTTP\/1.1 101/); resolve() } catch (error) { reject(error) }
        socket.destroy()
      })
    })
    assert.equal(upgradedPath, '/api/v1/ws?token=x')
    console.log('Gateway readiness, prefix, API query, update guard, SSE streaming and WebSocket upgrade tests passed')
  } finally {
    child.kill()
    backend.closeAllConnections()
    backend.close()
  }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
