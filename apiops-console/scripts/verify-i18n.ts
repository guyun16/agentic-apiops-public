import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import { translateDynamicUi, zhUi } from '../src/app/zhUi.ts'

const root = new URL('../src/', import.meta.url)
const dictionary = ts.createSourceFile('ConsoleLanguage.tsx', readFileSync(new URL('app/ConsoleLanguage.tsx', root), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const keys = new Set(Object.keys(zhUi))
function collectKeys(node: ts.Node) {
  if (ts.isPropertyAssignment(node) && (ts.isStringLiteral(node.name) || ts.isIdentifier(node.name))) keys.add(node.name.text)
  ts.forEachChild(node, collectKeys)
}
collectKeys(dictionary)
const missing = new Set<string>()
function checkArgument(node: ts.Node) {
  if (ts.isStringLiteral(node) && node.text && !keys.has(node.text)) missing.add(node.text)
  if (ts.isConditionalExpression(node)) { checkArgument(node.whenTrue); checkArgument(node.whenFalse) }
}
function visit(node: ts.Node) {
  if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'ui' && node.arguments[0]) checkArgument(node.arguments[0])
  ts.forEachChild(node, visit)
}
function walk(directory: string) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) walk(path)
    else if (entry.name.endsWith('.tsx')) visit(ts.createSourceFile(path, readFileSync(path, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX))
  }
}
walk(fileURLToPath(root))
// These strategy hints are selected dynamically and passed into ui() as data.
const studio = ts.createSourceFile('ApiStudioPage.tsx', readFileSync(new URL('features/api-studio/ApiStudioPage.tsx', root), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
function checkStrategyHints(node: ts.Node) {
  if (ts.isBinaryExpression(node) && ts.isIdentifier(node.left) && node.left.text === 'why' && node.operatorToken.kind === ts.SyntaxKind.EqualsToken) checkArgument(node.right)
  if (ts.isPropertyAssignment(node) && ts.isIdentifier(node.name) && node.name.text === 'reason') checkArgument(node.initializer)
  ts.forEachChild(node, checkStrategyHints)
}
checkStrategyHints(studio)
assert.deepEqual([...missing].sort(), [], 'Console ui() copy needs Chinese translations')
assert.ok(Object.values(zhUi).every(value => value.length > 0))
assert.equal(translateDynamicUi('2 validation fact unavailable'), '2 项校验事实不可用')
assert.equal(translateDynamicUi('2 / 3 PASS'), '2 / 3 通过')
assert.equal(translateDynamicUi('{"status":"SUCCESS"}'), undefined)
console.log('Chinese coverage: all literal ui() calls and conditional branches have translations.')
