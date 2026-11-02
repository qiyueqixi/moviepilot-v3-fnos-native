const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
class Storage {
  constructor () { this.data = new Map() }
  get length () { return this.data.size }
  getItem (k) { return this.data.get(String(k)) ?? null }
  setItem (k, v) { this.data.set(String(k), String(v)) }
  removeItem (k) { this.data.delete(String(k)) }
  key (i) { return [...this.data.keys()][i] ?? null }
  clear () { this.data.clear() }
}
const localStorage = new Storage()
localStorage.setItem('auth', 'v2 token')
localStorage.setItem('user', 'v2 user')
const calls = []
class XHR {
  open (method, url) { this.url = String(url) }
  setRequestHeader (key, value) { calls.push([this.url, key, value]) }
  send () {
    this.status = 200
    this.responseText = JSON.stringify({ access_token: 'v3 signed token', user_id: 7, user_name: 'existing-admin', super_user: true, level: 3 })
  }
}
const context = { Storage, localStorage, XMLHttpRequest: XHR, URL, Request, Headers,
  document: { baseURI: 'http://nas/app/moviepilot-v3/' },
  window: { fetch: async (input, init) => ({ input, init }) } }
vm.runInNewContext(fs.readFileSync('fnos/resources/no-auth.js', 'utf8'), context)
assert.equal(localStorage.data.get('auth'), 'v2 token')
assert.equal(localStorage.data.get('user'), 'v2 user')
assert.equal(JSON.parse(localStorage.getItem('auth')).token, 'v3 signed token')
assert.equal(JSON.parse(localStorage.getItem('user')).userID, 7)
assert.equal(JSON.parse(localStorage.getItem('user')).level, 3)
const native = new XHR()
native.open('GET', './api/v1/site')
native.setRequestHeader('Authorization', 'Bearer v3')
assert.equal(calls.some(c => c[0] === './api/v1/site'), false)
const other = new XHR()
other.open('GET', '/app/moviepilot/api/v1/site')
other.setRequestHeader('Authorization', 'Bearer v2')
assert.equal(calls.at(-1)[2], 'Bearer v2')
localStorage.clear()
assert.equal(localStorage.data.get('auth'), 'v2 token')
assert.equal(localStorage.getItem('auth'), null)
context.window.fetch('./api/v1/site', { headers: { Authorization: 'Bearer v3' } }).then(result => {
  assert.equal(result.init.headers.has('Authorization'), false)
  console.log('V2/V3 storage isolation, real user identity, and gateway header tests passed')
})
