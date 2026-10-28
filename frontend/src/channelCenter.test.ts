import assert from 'node:assert/strict'
import test from 'node:test'

import {
  fakeAuthorize,
  fakeChannels,
  fakeRevoke,
  canStartFakeAuthorization,
  statusLabel,
} from './channelCenter.js'

test('fake channels are explicitly test-only and use current provider contracts', () => {
  assert.equal(fakeChannels.length, 3)
  assert.ok(fakeChannels.every((channel) => channel.test_only))
  assert.equal(fakeChannels.find((channel) => channel.channel_type === 'gmail')?.provider, 'gmail_api_pubsub')
  assert.equal(fakeChannels.find((channel) => channel.channel_type === 'whatsapp')?.provider, 'whatsapp_web_baileys')
  assert.equal(fakeChannels.find((channel) => channel.channel_type === 'outlook')?.provider, 'outlook_mcp_graph')
})

test('fake authorization changes only fixture state', () => {
  const channel = fakeChannels[0]
  const connected = fakeAuthorize(channel)

  assert.equal(channel.status, 'not_connected')
  assert.equal(connected.status, 'connected')
  assert.equal(connected.test_only, true)
  assert.match(connected.message, /不代表真实 provider/)
})

test('fake revoke is explicit and re-authorization is available', () => {
  const revoked = fakeRevoke(fakeAuthorize(fakeChannels[1]))

  assert.equal(revoked.status, 'revoked')
  assert.equal(canStartFakeAuthorization(revoked), true)
  assert.equal(statusLabel(revoked.status), '已撤销')
})
