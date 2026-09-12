// Read-only projection of the sealed v5 result. Never imports an evaluator or writes source artifacts.
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import assert from 'node:assert/strict'
const repo = path.resolve(import.meta.dirname, '../../../..')
const root = 'f105r/v5o-20260905T053300Z'
const evidence = 'artifacts/stage21/v5-official105-launch-20260905T053300Z'
const sources = []
const read = relative => {
  const bytes = fs.readFileSync(path.join(repo, relative))
  sources.push({ path: relative, sha256: crypto.createHash('sha256').update(bytes).digest('hex') })
  return JSON.parse(bytes.toString('utf8').replace(/^\uFEFF/, ''))
}
const completion = read(evidence + '/completion-verification.json')
assert.equal(completion.benchmarkRevision, 'stage21-formal105-final-closure-v5')
const manifest = read(root + '/run-manifest.json')
const metrics = read(root + '/metrics.json')
const outcomes = read(root + '/outcome-v2.json')
const reproducibilityPath = root + '/reproducibility.json'
const reproducibility = read(reproducibilityPath)
assert.equal(reproducibility.schemaVersion, 'stage21-final-formal105-reproducibility/v1')
const configPath = root + '/full-105/results/run-32892b0b5903f34756209cc6/baseline-config.json'
const config = read(configPath)
const baselinePath = configPath.replace('baseline-config.json', 'baseline-run.json')
const baseline = read(baselinePath)
const leakage = read(evidence + '/post-run-leakage-scan.json')
assert.equal(manifest.evaluationRunId, completion.evaluationRunId)
assert.deepEqual(outcomes.v2StatusCounts, completion.outcomes)
const configuration = (value, source) => value?.availability ? value : ({value: value ?? null, availability: value == null ? 'UNAVAILABLE' : 'AVAILABLE', source, reason: null})
const tasks = outcomes.tasks.map(projected => {
  const file = fs.readdirSync(path.join(repo, root, 'task-results')).find(name => {
    const raw = JSON.parse(fs.readFileSync(path.join(repo, root, 'task-results', name), 'utf8'))
    return raw.benchmarkTaskId === projected.benchmarkTaskId
  })
  assert.ok(file, projected.benchmarkTaskId)
  const source = root + '/task-results/' + file
  const raw = read(source)
  assert.equal(raw.evaluationRunId, completion.evaluationRunId)
  const fields = ['evaluationRunId','benchmarkTaskId','caseId','taskType','status','executionMode','failureStage','failureCategory','failureCode','evaluationId','agentRunId','traceId','runId','reportId','durationMs','modelLatencyMs','promptTokens','completionTokens','totalTokens','taskSuccess']
  return { ...Object.fromEntries(fields.map(key => [key, raw[key] ?? null])),
    failureReason: projected.outcomeMetrics.filter(metric => metric.reason).map(metric => metric.reason).join(' · ') || null,
    metrics: (raw.evaluationResult?.metrics ?? []).map(metric => ({metric:metric.metric,status:metric.status,value:metric.value,unit:metric.unit,reason:metric.reason,details:[]})),
    artifactRef: source,
    formalOutcome: { revision:completion.benchmarkRevision, status:projected.v2Status, split:projected.split, authority:projected.outcomeAuthority, metrics:projected.outcomeMetrics, sourceRef:root + '/outcome-v2.json' },
  }
})
assert.equal(tasks.length, completion.persisted)
assert.equal(new Set(tasks.map(task => task.benchmarkTaskId)).size, tasks.length)
// All official files must still match the completion record, excluding only its inventory exclusions.
for (const source of sources.filter(item => item.path.startsWith(root + '/'))) {
  const sealed = completion.artifactHashesIncludingInventoryExclusions.find(item => item.path === source.path.slice(root.length + 1))
  assert.ok(sealed, 'Missing sealed digest: ' + source.path)
  assert.equal(source.sha256, sealed.sha256, 'Changed official artifact: ' + source.path)
}
const aggregateMetrics = (baseline.overallMetrics?.metrics ?? []).map(metric => ({ metric:metric.metric, state:metric.value_count > 0 ? 'VALUE' : metric.error_count > 0 ? 'ERROR' : metric.unknown_count > 0 ? 'UNKNOWN' : metric.not_applicable_count > 0 ? 'NOT_APPLICABLE' : 'MISSING', value:metric.rate ?? metric.mean, mean:metric.mean,rate:metric.rate,unit:metric.unit,reason:null,totalCount:metric.total_count,applicableCount:metric.applicable_count,valueCount:metric.value_count,notApplicableCount:metric.not_applicable_count,unknownCount:metric.unknown_count,errorCount:metric.error_count }))
const strict = baseline.taskSuccess
const detail = {
  evaluationRunId: completion.evaluationRunId, benchmarkRevision:completion.benchmarkRevision, resultSource:'VERIFIED_ARTIFACT_SNAPSHOT', datasetId:manifest.dataset.datasetId,datasetVersion:manifest.dataset.datasetVersion,datasetSplit:config.datasetSplit,taskSchemaVersion:config.taskSchemaVersion,status:'COMPLETED',selectedTaskCount:completion.selected,executedTaskCount:completion.executed,evaluatedTaskCount:tasks.filter(task=>task.evaluationId).length,completedTaskCount:completion.runtimeStatus.SUCCESS,failedTaskCount:completion.runtimeStatus.FAILED,startedAt:manifest.startedAt,completedAt:manifest.completedAt,
  model:configuration(config.modelIdentity,configPath),prompt:(config.promptIdentities ?? []).map(item=>configuration(item,configPath)),evaluator:configuration(config.evaluatorIdentity,configPath),benchmarkConfigVersion:config.benchmarkConfigVersion,dataSource:'ARTIFACT',aggregateMetrics,
  taskSuccess:{status:null,rate:strict?.taskSuccessRate ?? null,passCount:strict?.taskSuccessPass ?? null,failCount:strict?.taskSuccessFail ?? null,unknownCount:strict?.taskSuccessUnknown ?? null,notApplicableCount:strict?.taskSuccessNotApplicable ?? null},
  artifactReferences:{run:root+'/full-105/results/run-32892b0b5903f34756209cc6/run.json',baselineRun:baselinePath,baselineConfig:configPath,reproducibility:reproducibilityPath,evaluationCsv:root+'/full-105/results/run-32892b0b5903f34756209cc6/evaluation_result.csv',baselineReport:null,failureInventory:root+'/failure-taxonomy.json',collateralDamage:null,taskResults:tasks.map(task=>task.artifactRef)},
}
const provider = completion.providerProvenance
const snapshot = {
  schemaVersion:'benchmark-final-display/v1',sourceKind:'VERIFIED_ARTIFACT_SNAPSHOT',revision:completion.benchmarkRevision,sourceEvaluationRunId:completion.evaluationRunId,evaluationRunId:completion.evaluationRunId,verifiedAt:completion.verifiedAt,
  detail,tasks,
  outcomes:completion.outcomes,passRate:completion.passRate,outcomeAccuracy:completion.outcomeAccuracy,unknownRate:completion.unknownRate,acceptance:completion.finalAcceptance,
  gates:[{metric:'Pass Rate',actual:completion.passRate,threshold:0.85,passed:completion.targetPassRate85},{metric:'Outcome Accuracy',actual:completion.outcomeAccuracy,threshold:0.85,passed:completion.targetOutcomeAccuracy85}],
  splits:completion.splitResults,categories:completion.taskTypeResults,
  tool:{required:metrics.tool.TOOL_REQUIRED,invoked:metrics.tool['Required Tool Invoked'],miss:metrics.tool['Required Tool Miss']},
  execution:{selected:completion.selected,executed:completion.executed,persisted:completion.persisted,missing:completion.missing.length,duplicates:completion.duplicates.length,runtime:completion.runtimeStatus},
  provider:{name:provider.expectedProvider,model:provider.expectedModel,provenCalls:provider.callsWithResponseProof,totalCalls:provider.terminalModelCallCount,mismatch:provider.mismatchTaskIds.length,fallback:provider.actualFallbackTaskIds.length,unproven:provider.unprovenTaskIds.length,status:provider.status},
  integrity:{artifact:completion.artifactIntegrity,completeness:completion.runCompletenessGate,leakage:leakage.status,sourceFreeze:completion.sourceFreeze},
  reproducibility:{status:'NOT VERIFIED',source:reproducibilityPath,reason:'Artifact records reproducibility inputs and hashes, but no overall reproducibility gate verdict.'},
  // These remaining published display fields are explicitly supplied by the user, not recomputed or claimed as API fields.
  published:{source:'User-confirmed final v5 display statement',splitPassRate:{DEV:0.9053,HELD_OUT:0.90},qualityValidation:'PASS'},
  limitation:{taskId:completion.knownLimitationActualResult.benchmarkTaskId,status:completion.knownLimitationActualResult.v2Status,reason:completion.knownLimitationActualResult.outcomeMetrics.find(metric=>metric.reason)?.reason ?? null},
  sources,
}
const output = path.join(import.meta.dirname, 'final-result.snapshot.json')
const summaryOutput = path.join(import.meta.dirname, 'final-result.summary.json')
const { aggregateMetrics: _metrics, taskSuccess: _strict, artifactReferences: _references, ...summary } = detail
for (const reference of Object.values(detail.artifactReferences).flat().filter(Boolean)) {
  assert.ok(fs.existsSync(path.join(repo, reference)), 'Missing artifact reference: ' + reference)
}
if(process.argv.includes('--check')) {
  assert.deepEqual(JSON.parse(fs.readFileSync(output,'utf8')), snapshot)
  assert.deepEqual(JSON.parse(fs.readFileSync(summaryOutput,'utf8')), summary)
} else {
  fs.writeFileSync(output, JSON.stringify(snapshot,null,2)+'\n')
  fs.writeFileSync(summaryOutput, JSON.stringify(summary,null,2)+'\n')
}
console.log('PASS: sealed v5 source identity and digests; sanitized snapshot '+(process.argv.includes('--check')?'matches':'written')+'; no metrics recalculated')
