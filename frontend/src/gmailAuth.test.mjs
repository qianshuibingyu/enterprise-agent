import assert from 'node:assert/strict'
import test from 'node:test'

function callbackState(search) {
  const params = new URLSearchParams(search)
  const state = params.get('gmail')
  if (state === 'connected') return { kind: 'success', message: 'Gmail 授权完成' }
  if (state === 'error') return { kind: 'error', message: params.get('message') || 'Gmail 授权失败' }
  return null
}

test('Gmail callback success is represented without credentials', () => {
  assert.deepEqual(callbackState('?gmail=connected'), {
    kind: 'success',
    message: 'Gmail 授权完成',
  })
})

test('Gmail callback error is represented without exposing provider data', () => {
  assert.deepEqual(callbackState('?gmail=error&message=denied'), {
    kind: 'error',
    message: 'denied',
  })
})
