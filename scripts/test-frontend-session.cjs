// Exercise the real patched upstream function called after site authentication.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const directory = '.build/public/assets'
const assets = fs.readdirSync(directory).filter(name => /^default-.*\.js$/.test(name))
const pattern = /function (\w+)\((\w+)=!1\)\{\/\* fnos-session-refresh \*\/if\(!\2&&window\.MoviePilotFnos\?\.refreshSession\)\{window\.MoviePilotFnos\.refreshSession\(\);return\}([^{}]+)\}/g
const matches = assets.flatMap(name => [...fs.readFileSync(path.join(directory, name), 'utf8').matchAll(pattern)])
assert.equal(matches.length, 1)
const [code, functionName, argument, body] = matches[0]
const names = body.match(/^(\w+)\(\),(\w+)\.value&&\(clearTimeout\(\2\.value\),\2\.value=null\),\w+\?(\w+)\.logout\(\):\3\.resetSession\(\),(\w+)\.reset\(\),(\w+)\.push\("\/login"\)$/)
assert.ok(names, 'Upstream reset behavior changed')
let refreshed = 0
let cleared = 0
let loggedOut = 0
const routes = []
const context = {
  window: { MoviePilotFnos: { refreshSession () { refreshed++ } } },
  clearTimeout () {},
  [names[1]] () {},
  [names[2]]: { value: null },
  [names[3]]: { logout () { loggedOut++ }, resetSession () { cleared++ } },
  [names[4]]: { reset () { cleared++ } },
  [names[5]]: { push (route) { routes.push(route) } },
}
vm.runInNewContext(code + `;this.resetAfterAuth=${functionName}`, context)
context.resetAfterAuth()
assert.equal(refreshed, 1)
assert.equal(cleared, 0)
assert.deepEqual(routes, [], 'Site authentication must not navigate to login')
context.resetAfterAuth(true)
assert.equal(loggedOut, 1, 'Explicit logout keeps its upstream behavior')
assert.deepEqual(routes, ['/login'])
delete context.window.MoviePilotFnos
context.resetAfterAuth()
assert.equal(cleared, 3, 'Without the fnOS adapter the upstream reset still works')
console.log('Actual upstream post-auth/reset function refreshes fnOS session without login redirect')
