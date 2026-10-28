import assert from 'node:assert/strict'
import test from 'node:test'

function classifyOutlookRead(status) {
  if (status === 200) return 'success'
  if (status === 401 || status === 403) return 'unauthorized'
  if (status === 503) return 'mcp_unavailable'
  return 'error'
}

test('Outlook read result states remain distinct', () => {
  assert.equal(classifyOutlookRead(200), 'success')
  assert.equal(classifyOutlookRead(401), 'unauthorized')
  assert.equal(classifyOutlookRead(403), 'unauthorized')
  assert.equal(classifyOutlookRead(503), 'mcp_unavailable')
  assert.equal(classifyOutlookRead(502), 'error')
})
