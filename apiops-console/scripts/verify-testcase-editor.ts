import assert from 'node:assert/strict'
import { runnerRequestForEditor } from '../src/features/api-studio/types.ts'

const original = { caseId: 'case', projectId: 42, apiId: 'orders', steps: [{ request: { body: { quantity: 1 } } }] }
const edited = { ...original, steps: [{ request: { body: { quantity: 2 } } }] }
const originalText = JSON.stringify(original)
const editedText = JSON.stringify(edited)

assert.deepEqual(runnerRequestForEditor('ACCEPTED', original, originalText, originalText), { testCases: [original] })
// An edit or an old response must not authorize execution of unvalidated text.
assert.equal(runnerRequestForEditor('ACCEPTED', original, editedText, originalText), null)
assert.equal(runnerRequestForEditor('ACCEPTED', original, '{', originalText), null)
assert.equal(runnerRequestForEditor('ACCEPTED', original, originalText, null), null)
for (const status of ['VALIDATING', 'REJECTED', 'FAILED', null] as const) {
  assert.equal(runnerRequestForEditor(status, edited, editedText, editedText), null)
}
assert.deepEqual(runnerRequestForEditor('ACCEPTED', edited, editedText, editedText), { testCases: [edited] })
console.log('TestCase editor validation and current-snapshot submission: passed')
