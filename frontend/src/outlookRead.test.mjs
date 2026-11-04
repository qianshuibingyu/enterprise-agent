import assert from 'node:assert/strict'
import test from 'node:test'

function summarize(result) {
  return Array.isArray(result)
    ? {
        total: result.length,
        created: result.filter((item) => item.created).length,
        duplicates: result.filter((item) => !item.created).length,
      }
    : result
}

test('Outlook read summary handles the new backend response', () => {
  assert.deepEqual(summarize({
    messages: [{ id: 1, created: false }, { id: 2, created: true }],
    total: 2,
    created: 1,
    duplicates: 1,
  }), {
    messages: [{ id: 1, created: false }, { id: 2, created: true }],
    total: 2,
    created: 1,
    duplicates: 1,
  })
})

test('Outlook read summary remains compatible with an older backend array', () => {
  assert.deepEqual(summarize([
    { id: 1, created: false },
    { id: 2, created: true },
  ]), {
    total: 2,
    created: 1,
    duplicates: 1,
  })
})
