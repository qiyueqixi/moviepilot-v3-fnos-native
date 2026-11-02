(() => {
  // Keep V3 frontend state separate when V2 shares this NAS origin.
  const prefix = 'moviepilot-v3:'
  const original = Object.fromEntries(['getItem', 'setItem', 'removeItem', 'key', 'clear']
    .map(name => [name, Storage.prototype[name]]))
  Storage.prototype.getItem = function (key) { return original.getItem.call(this, prefix + key) }
  Storage.prototype.setItem = function (key, value) { return original.setItem.call(this, prefix + key, value) }
  Storage.prototype.removeItem = function (key) { return original.removeItem.call(this, prefix + key) }
  Storage.prototype.clear = function () {
    const keys = []
    for (let i = 0; i < this.length; i++) {
      const key = original.key.call(this, i)
      if (key?.startsWith(prefix)) keys.push(key)
    }
    for (const key of keys) original.removeItem.call(this, key)
  }
  const apiBase = new URL('./api/', document.baseURI)
  const isNativeApi = value => {
    try {
      const url = new URL(value, document.baseURI)
      return url.origin === apiBase.origin && url.pathname.startsWith(apiBase.pathname)
    } catch (_) { return false }
  }
  const nativeRequests = new WeakSet()
  const xhrOpen = XMLHttpRequest.prototype.open
  const xhrHeader = XMLHttpRequest.prototype.setRequestHeader
  XMLHttpRequest.prototype.open = function (method, url, ...args) {
    nativeRequests.delete(this)
    if (isNativeApi(url)) nativeRequests.add(this)
    return xhrOpen.call(this, method, url, ...args)
  }
  XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
    if (nativeRequests.has(this) && name.toLowerCase() === 'authorization') return
    return xhrHeader.call(this, name, value)
  }
  const originalFetch = window.fetch
  window.fetch = function (input, init) {
    const url = input instanceof Request ? input.url : input
    if (!isNativeApi(url)) return originalFetch.call(this, input, init)
    const headers = new Headers(init?.headers || (input instanceof Request ? input.headers : undefined))
    headers.delete('Authorization')
    return originalFetch.call(this, input, { ...init, headers })
  }
  function storeSession (session) {
    if (!session.access_token || !Number.isInteger(session.user_id)) throw new Error('Invalid native session')
    localStorage.setItem('auth', JSON.stringify({
      token: session.access_token, remember: true, originalPath: null,
    }))
    localStorage.setItem('user', JSON.stringify({
      superUser: session.super_user, userID: session.user_id, userName: session.user_name,
      avatar: session.avatar || '', level: session.level, permissions: session.permissions || {},
    }))
  }
  let refreshing = null
  window.MoviePilotFnos = {
    // Site authentication changes the real level. Obtain a new token before
    // reloading the current page so the Vue stores hydrate the updated session.
    refreshSession () {
      if (refreshing) return refreshing
      refreshing = (async () => {
        for (let attempt = 0; attempt < 30; attempt++) {
          try {
            const response = await window.fetch(new URL('v1/login/access-token', apiBase), {
              method: 'POST', credentials: 'same-origin', cache: 'no-store',
              headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
              body: 'username=admin&password=fnos',
              signal: AbortSignal.timeout(5000),
            })
            if (!response.ok) throw new Error('Native session is not ready')
            storeSession(await response.json())
            window.location.reload()
            return
          } catch (_) {
            await new Promise(resolve => window.setTimeout(resolve, 1000))
          }
        }
        // Let the existing startup page show service errors and readiness.
        window.location.reload()
      })().finally(() => { refreshing = null })
      return refreshing
    },
  }
  try {
    const request = new XMLHttpRequest()
    request.open('POST', new URL('v1/login/access-token', apiBase).href, false)
    request.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded')
    request.send('username=admin&password=fnos')
    if (request.status !== 200) return
    const session = JSON.parse(request.responseText)
    storeSession(session)
  } catch (_) {}
})()
