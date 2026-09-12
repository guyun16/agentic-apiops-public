"""Independent one-shot runner wiring; frozen outputs precede CODEX_REVIEW.

The original runner, workflow policies, GT contents and metric implementations
remain authorities. This wrapper adds admission, complete retention and a separate
evaluation-owned review ingress. It never supplies reviews to a generating agent.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import httpx
import stage21_final_revision_gate as gate
import stage21_final_v2_formal105 as formal
import stage21_real_model_baseline as baseline

from app.benchmark.auth_profiles import (
    AuthProfileResolver,
    AuthProfileWorkflowAdapter,
    Stage21AuthProfile,
)
from app.benchmark.dataset import lint_dataset, load_dataset
from app.benchmark.diagnosis_retention import DiagnosisRetention, RetainingLLM, write_once
from app.benchmark.mapping import to_evaluation_case
from app.benchmark.outcome_v2 import load_outcome_policy, project_outcome_v2
from app.benchmark.provider_integrity import verify_provider_integrity
from app.benchmark.real_model import RealModelStage20WorkflowAdapter
from app.benchmark.runner import (
    BenchmarkRun,
    BenchmarkRunner,
    BenchmarkRunPolicy,
    JsonBenchmarkResultStore,
)
from app.clients.java_apiops import JavaApiOpsClient
from app.core.settings import get_settings
from app.evaluator import EvaluationFacts, MetricName, RuleBasedEvaluator
from app.evaluator.diagnosis_review_ingress import (
    file_digest,
    load_content_review,
    verify_output_seal,
)
from app.tracing.redaction import canonical_json_hash

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "python-apiops-agentlab/tests/benchmark/fixtures"
LIVE_FIXTURES = FIXTURES / "revisions/diagnosis-contract-full105-v2"
MANIFEST = LIVE_FIXTURES / "dataset-manifest.json"
POLICY = FIXTURES / "outcome-policy-diagnosis-contract-full105-v2.json"
TASK_SCHEMA = ROOT / "shared-schemas/evaluation-task-diagnosis-contract-v1-schema.json"
CONFIG = Path(__file__).with_name("stage21-diagnosis-contract-full105-v2-revision.json")
REVISION = "stage21-diagnosis-contract-full105-v2"
PARENT = "stage21-diagnosis-contract-full105-v1"
EVALUATOR_VERSION = "rule-evaluator-v2-insufficient-evidence-live1"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def prepare() -> None:
    original = read(FIXTURES / "dataset-manifest.json")
    scoped = read(FIXTURES / "revisions/insufficient-evidence-v1/dataset-manifest.json")
    replacement = {entry["benchmarkTaskId"]: entry for entry in scoped["tasks"]}
    entries = []
    for entry in original["tasks"]:
        if entry["benchmarkTaskId"] in replacement:
            new = dict(replacement[entry["benchmarkTaskId"]])
            assert new["split"] == entry["split"]
            for field in ("taskFile", "groundTruthFile"):
                new[field] = "revisions/insufficient-evidence-v1/" + new[field]
            entries.append(new)
        else:
            entries.append(entry)
    for entry in entries:
        for field, directory in (("taskFile", "tasks"), ("groundTruthFile", "ground_truth")):
            source = FIXTURES / entry[field]
            destination = LIVE_FIXTURES / directory / (entry["benchmarkTaskId"] + ".json")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                shutil.copyfile(source, destination)
            if file_digest(source) != file_digest(destination):
                raise ValueError("copied versioned fixture differs from its source")
            entry[field] = destination.relative_to(LIVE_FIXTURES).as_posix()
    manifest = {**original, "datasetVersion": REVISION, "tasks": entries}
    policy = read(FIXTURES / "stage21-outcome-policy-v2.json")
    scoped_policy = read(FIXTURES / "revisions/insufficient-evidence-v1/outcome-policy.json")
    policy_replacements = {entry["benchmarkTaskId"]: entry for entry in scoped_policy["tasks"]}
    policy.update(
        policyVersion=REVISION,
        datasetVersion=REVISION,
        tasks=[
            policy_replacements.get(entry["benchmarkTaskId"], entry) for entry in policy["tasks"]
        ],
    )
    write_once(MANIFEST, manifest)
    if not POLICY.exists():
        write_once(POLICY, policy)
    configuration = {
        "schemaVersion": "stage21-final-revision-config/v1",
        "revision": REVISION,
        "parentRevision": PARENT,
        "executionMode": "REAL_MODEL_ONE_SHOT",
        "official105Eligible": True,
        "officialArtifactsMutable": False,
        "taskCount": 105,
        "devCount": 95,
        "heldOutCount": 10,
        "provider": "Qwen",
        "model": "qwen3.8-max",
        "minimumPassCount": 90,
        "contractVersion": "insufficient-evidence-v1",
        "admissionRequires": ["offline-quality", "runtime", "source-freeze", "output-retention"],
        "reviewMethod": "CODEX_REVIEW",
        "reviewer": "Codex",
        "datasetManifest": MANIFEST.relative_to(ROOT).as_posix(),
        "outcomePolicy": POLICY.relative_to(ROOT).as_posix(),
    }
    if CONFIG.exists():
        CONFIG.write_text(json.dumps(configuration, indent=2) + "\n", encoding="utf-8")
    else:
        write_once(CONFIG, configuration)
    schema = read(ROOT / "shared-schemas/evaluation-task-schema.json")

    def add_metric(node):
        if isinstance(node, dict):
            if "enum" in node and "diagnosis_accuracy" in node["enum"]:
                node["enum"].append("diagnosis_contract")
            for value in node.values():
                add_metric(value)
        elif isinstance(node, list):
            for value in node:
                add_metric(value)

    add_metric(schema)
    schema["$id"] = "https://apiops.dev/schemas/evaluation-task-diagnosis-contract-v1-schema.json"
    write_once(TASK_SCHEMA, schema)
    validate_dataset()


def validate_dataset():
    dataset = load_dataset(MANIFEST)
    original = load_dataset(FIXTURES / "dataset-manifest.json")
    if [t.benchmark_task_id for t in dataset.tasks] != [
        t.benchmark_task_id for t in original.tasks
    ]:
        raise RuntimeError("ordered 105 task set drift")
    if Counter(e.split.value for e in dataset.manifest.tasks) != {"dev": 95, "held_out": 10}:
        raise RuntimeError("split drift")
    if not lint_dataset(MANIFEST, schema_path=TASK_SCHEMA).dataset_ready:
        raise RuntimeError("dataset quality gate failed")
    load_outcome_policy(POLICY, dataset=dataset)
    return dataset


def source_identity() -> dict[str, str]:
    # UI/IDE edits are recorded separately, and do not execute this benchmark.
    inventory = gate.source_inventory()
    prefixes = (
        "python-apiops-agentlab/",
        "java-apiops-platform/",
        "shared-schemas/",
        "scripts/stage21_",
        "docs/stage21-",
    )
    selected = {key: value for key, value in inventory.items() if key.startswith(prefixes)}
    for module in ("apiops-web", "apiops-demo-order-service"):
        for jar in (ROOT / "java-apiops-platform" / module / "target").glob("*.jar"):
            selected[jar.relative_to(ROOT).as_posix()] = file_digest(jar)
    return selected


def assert_source(frozen: dict) -> None:
    if source_identity() != frozen["sourceInventory"]:
        raise RuntimeError("REVISION_DRIFT")


async def freeze(preparation: Path, root: Path) -> None:
    settings = get_settings()
    gate.configuration_check(settings)
    dataset = validate_dataset()
    quality = read(preparation / "quality-validation.json")
    identity = source_identity()
    if quality.get("status") != "PASS" or quality.get("sourceDigest") != canonical_json_hash(
        identity
    ):
        raise RuntimeError("offline quality evidence missing or source identity drifted")
    runtime = formal._runtime_preflight_evidence(preparation / "runtime-preflight-final")
    shared = await gate.shared_live_preflight(settings)
    provider = formal._qwen_provider_gate(settings)
    parent_source = read(
        ROOT / ("artifacts/stage21/final-revision-freeze-20260905T041500Z/freeze-manifest.json")
    )["sourceInventory"]
    provider_sources = {}
    for filename in ("qwen.py", "qwen_structured_output.py", "llm_provider.py", "llm.py"):
        relative = "python-apiops-agentlab/app/clients/" + filename
        if file_digest(ROOT / relative) != parent_source[relative]:
            raise RuntimeError("provider qualification source identity drift")
        provider_sources[relative] = parent_source[relative]
    if not formal._environment_readiness(settings, "qwen")["ready"]:
        raise RuntimeError("temporary provider/runtime environment incomplete")
    if root.exists():
        raise RuntimeError("new official root already exists")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"evaluation_run:stage21-diagnosis-contract-full105-{stamp}"
    path_preflight = formal._formal105_path_preflight(
        root,
        run_id,
        tuple(task.benchmark_task_id for task in dataset.tasks),
    )
    original_scoped = read(FIXTURES / "revisions/insufficient-evidence-v1/dataset-manifest.json")
    original_manifest = read(FIXTURES / "dataset-manifest.json")
    source_entries = {
        entry["benchmarkTaskId"]: (FIXTURES, entry) for entry in original_manifest["tasks"]
    }
    source_entries.update(
        {
            entry["benchmarkTaskId"]: (
                FIXTURES / "revisions/insufficient-evidence-v1",
                entry,
            )
            for entry in original_scoped["tasks"]
        }
    )
    copied = []
    for entry in dataset.manifest.tasks:
        parent_dir, parent_entry = source_entries[entry.benchmark_task_id]
        for key, reference in (
            ("taskFile", entry.task_file),
            ("groundTruthFile", entry.ground_truth_file),
        ):
            source = parent_dir / parent_entry[key]
            target = LIVE_FIXTURES / reference
            if file_digest(source) != file_digest(target):
                raise RuntimeError("versioned task/GT contents changed")
            copied.append(
                {
                    "taskId": entry.benchmark_task_id,
                    "kind": key,
                    "source": source.relative_to(ROOT).as_posix(),
                    "target": target.relative_to(ROOT).as_posix(),
                    "sha256": file_digest(source),
                }
            )
    frozen = {
        "schemaVersion": "stage21-executable-revision-freeze/v1",
        "revision": REVISION,
        "parentRevision": PARENT,
        "admission": "PASS",
        "replacementOf": {
            "evaluationRunId": "evaluation_run:stage21-diagnosis-contract-full105-20260906T023749Z",
            "root": "f105r/dc1-20260906T023147Z",
            "reason": "User-authorized replacement after shared authentication failure",
            "failedAttemptEvidencePreserved": True,
        },
        "sessionPolicy": {
            "authority": "Java login expiresAt",
            "minimumRemainingLifetimeSeconds": 190,
            "renewal": "same profile before task; no HTTP401/task replay",
            "receiptDirectory": "retention/auth",
        },
        "evaluationRunId": run_id,
        "officialRoot": str(root.resolve()),
        "sourceInventory": identity,
        "sourceDigest": canonical_json_hash(identity),
        "quality": quality,
        "runtime": runtime,
        "sharedLivePreflight": shared,
        "providerGate": provider,
        "providerSourceReuse": {
            "sourceRevision": "stage21-formal105-final-closure-v5",
            "matchingFiles": provider_sources,
            "scope": "provider protocol/client and native output schema only",
            "currentWorkflowOrModelBehaviorReused": False,
        },
        "provider": "Qwen",
        "model": "qwen3.8-max",
        "pathPreflight": path_preflight,
        "persistenceProbe": gate.persistence_probe(root.parent),
        "orderedTaskIds": [task.benchmark_task_id for task in dataset.tasks],
        "splits": {entry.benchmark_task_id: entry.split.value for entry in dataset.manifest.tasks},
        "byteIdenticalVersionedInputs": copied,
        "knownLimitation": gate.known_limitation(),
        "reviewRules": {
            "version": "insufficient-evidence-v1",
            "method": "CODEX_REVIEW",
            "reviewer": "Codex",
            "fixedCandidateReviewReuse": False,
            "source": "app/evaluator/diagnosis_review_ingress.py",
        },
        "retryPolicy": BenchmarkRunPolicy(
            taskTimeoutSeconds=180.0, cleanupTimeoutSeconds=10.0, maxInfrastructureAttempts=1
        ).model_dump(mode="json"),
        "historicalOfficial": {
            "revision": "stage21-formal105-final-closure-v5",
            "pass": 95,
            "fail": 9,
            "unknown": 1,
            "mutated": False,
        },
        "frozenAt": datetime.now(UTC).isoformat(),
    }
    write_once(preparation / "executable-revision-manifest.json", frozen)


def machine_evaluate(case, truth, records):
    # Explicit empty external reviews prevent any matrix/old GT review reuse.
    result = RuleBasedEvaluator().evaluate(case, truth, records, diagnosis_content_reviews=())
    return result.model_copy(
        update={
            "evaluator_version": EVALUATOR_VERSION,
            "evaluation_id": "evaluation:"
            + canonical_json_hash(
                {
                    "machineEvaluation": result.evaluation_id,
                    "revision": REVISION,
                }
            )[:24],
        }
    )


def persisted_task_integrity(run: BenchmarkRun, root: Path) -> int:
    paths = [path for path in (root / "raw").rglob("*.json") if path.name != "run.json"]
    stored = [read(path) for path in paths]
    indexed = {item["benchmarkTaskId"]: item for item in stored}
    if len(indexed) != len(stored) or len(indexed) != len(run.results):
        raise RuntimeError("missing or duplicate persisted task files")
    for result in run.results:
        if indexed.get(result.benchmark_task_id) != result.model_dump(mode="json"):
            raise RuntimeError("persisted task differs from execution result")
    return len(indexed)


def retention_integrity(run: BenchmarkRun, root: Path) -> dict:
    input_files = list((root / "retention/calls").glob("*-input.json"))
    output_files = list((root / "retention/calls").glob("*-output.json"))
    inputs = {read(path)["modelCallId"]: read(path) for path in input_files}
    outputs = {read(path)["modelCallId"]: read(path) for path in output_files}
    if len(inputs) != len(input_files) or len(outputs) != len(output_files):
        raise RuntimeError("duplicate retained model call")
    seen = set()
    reports = {
        read(path)["taskId"]: read(path) for path in (root / "retention/reports").glob("*.json")
    }
    for result in run.results:
        if result.evaluation_run_id != run.evaluation_run_id:
            raise RuntimeError("historical run identity mixed in")
        trace_records = (
            () if result.formal_evidence is None else result.formal_evidence.trace_evidence
        )
        terminal = [
            record
            for record in trace_records
            if record.get("record_type") == "model_call" and record.get("event") == "TERMINAL"
        ]
        terminal_ids = {record["model_call_id"] for record in terminal}
        if terminal_ids != set(result.model_call_ids) or seen.intersection(terminal_ids):
            raise RuntimeError("missing or duplicate terminal model calls")
        seen.update(terminal_ids)
        for call in terminal:
            call_id = call["model_call_id"]
            retained_input, retained_output = inputs[call_id], outputs[call_id]
            if (
                retained_input["originalInputDigest"] != call["model_input"]["sha256"]
                or retained_input["taskId"] != result.benchmark_task_id
                or retained_input["traceId"] != result.trace_id
                or retained_input["retainedInputDigest"]
                != canonical_json_hash(retained_input["modelVisibleInputRedacted"])
            ):
                raise RuntimeError("retained input / original trace digest mismatch")
            if call["status"] == "SUCCESS" and (
                retained_output["originalOutputDigest"] != call["model_output"]["sha256"]
                or retained_output["retainedOutputDigest"]
                != canonical_json_hash(retained_output["modelOutputRedacted"])
            ):
                raise RuntimeError("retained output / original trace digest mismatch")
        facts = (
            {}
            if result.formal_evidence is None
            else result.formal_evidence.normalized_evaluation_facts
        )
        observation = next(
            (
                fact["value"]
                for fact in facts.get("structured_facts", [])
                if fact["name"] == "diagnosis_contract_observation"
            ),
            None,
        )
        if observation is not None:
            report = reports[result.benchmark_task_id]
            if (
                report["contractObservation"] != observation
                or report["traceId"] != result.trace_id
                or not set(report["evidenceVisibleInModelCallIds"]).issubset(terminal_ids)
            ):
                raise RuntimeError("complete diagnosis / evaluator evidence mismatch")
    if seen != set(inputs) or seen != set(outputs):
        raise RuntimeError("orphan or missing model boundary retention")
    ledger = [read(path)["taskId"] for path in (root / "ledger").glob("*.json")]
    if len(ledger) != 105 or set(ledger) != set(run.selected_task_ids):
        raise RuntimeError("execution ledger does not cover unique 105 tasks")
    return {
        "status": "PASS",
        "terminalCalls": len(seen),
        "retainedInputs": len(inputs),
        "retainedOutputs": len(outputs),
        "completeDiagnoses": len(reports),
        "selected": 105,
        "executed": len(run.results),
        "persisted": len(ledger),
        "missing": 0,
        "duplicates": 0,
    }


class GuardedRunner(BenchmarkRunner):
    def __init__(self, *args, retention, frozen, root, **kwargs):
        super().__init__(*args, **kwargs)
        self.retention, self.frozen, self.root = retention, frozen, root
        self.completed = []

    async def run_task(self, task, ground_truth, **kwargs):
        assert_source(self.frozen)
        self.retention.task_id = task.benchmark_task_id
        self.retention.original_prompts.clear()
        write_once(
            self.root / "ledger" / (canonical_json_hash(task.benchmark_task_id)[:20] + ".json"),
            {"taskId": task.benchmark_task_id, "startedAt": datetime.now(UTC).isoformat()},
        )
        result = await super().run_task(task, ground_truth, **kwargs)
        self.completed.append(result)
        if self.retention.failure:
            raise RuntimeError(self.retention.failure)
        provenance = verify_provider_integrity(
            (result,),
            expected_provider="Qwen",
            expected_model="qwen3.8-max",
        )
        if provenance["status"] not in {"PROVIDER_PROVEN", "NO_MODEL_CALL"}:
            raise RuntimeError("PROVIDER_PROVENANCE_FAILURE")
        if result.failure_category in {
            "INFRASTRUCTURE_FAILURE",
            "SETUP_FAILURE",
            "EVALUATION_FAILURE",
            "CLEANUP_FAILURE",
            "PROVIDER_FAILURE",
        }:
            raise RuntimeError("SYSTEMIC_BOUNDARY_FAILURE")
        return result


def print_progress(progress) -> None:
    print(json.dumps(asdict(progress)), flush=True)


async def execute(root: Path, frozen_path: Path) -> None:
    frozen = read(frozen_path)
    settings = get_settings()
    gate.configuration_check(settings)
    assert_source(frozen)
    if frozen["revision"] != REVISION or frozen["admission"] != "PASS":
        raise RuntimeError("executable revision not admitted")
    if root.resolve() != Path(frozen["officialRoot"]).resolve():
        raise RuntimeError("official root mismatch")
    root.mkdir(parents=True, exist_ok=False)
    write_once(root / "run-intent.json", frozen)
    dataset = validate_dataset()
    sink = DiagnosisRetention(root / "retention", tuple(formal._known_secret_values(settings)))
    async with httpx.AsyncClient() as http:
        llm = RetainingLLM(baseline.build_llm(http, settings, provider="qwen"), sink)
        java = JavaApiOpsClient(
            http,
            base_url=settings.java_apiops_base_url,
            timeout_seconds=settings.java_apiops_timeout_seconds,
        )
        policy = BenchmarkRunPolicy(
            taskTimeoutSeconds=max(180.0, settings.qwen_timeout_seconds * 3),
            cleanupTimeoutSeconds=10.0,
            maxInfrastructureAttempts=1,
        )
        auth = AuthProfileResolver(
            java,
            minimum_validity_seconds=policy.task_timeout_seconds + policy.cleanup_timeout_seconds,
            session_observer=lambda event: write_once(
                root / "retention/auth" / (canonical_json_hash(event)[:20] + ".json"), event
            ),
        )
        adapters = {
            profile: RealModelStage20WorkflowAdapter(
                llm,
                java_client=java,
                token_provider=auth.token_provider(profile),
                repository_root=ROOT,
                diagnosis_observer=sink.observe,
            )
            for profile in Stage21AuthProfile
        }
        runner = GuardedRunner(
            AuthProfileWorkflowAdapter(adapters, auth),
            retention=sink,
            frozen=frozen,
            root=root,
            evaluator=machine_evaluate,
            result_store=JsonBenchmarkResultStore(root / "raw"),
            policy=policy,
        )
        try:
            run = await runner.run_batch(
                dataset,
                evaluation_run_id=frozen["evaluationRunId"],
                on_progress=print_progress,
            )
            if len(run.results) != 105 or run.aborted:
                raise RuntimeError("INCOMPLETE_EXECUTION")
            assert_source(frozen)
            integrity = retention_integrity(run, root)
            integrity["persistedTaskFiles"] = persisted_task_integrity(run, root)
            write_once(root / "retention-integrity.json", integrity)
            leaks = formal._scan_artifact_secrets(root, formal._known_secret_values(settings))
            if leaks:
                raise RuntimeError("ARTIFACT_SECRET_SCAN_FAILED")
            files = {
                path.relative_to(root).as_posix(): file_digest(path)
                for directory in ("raw", "retention", "ledger")
                for path in (root / directory).rglob("*")
                if path.is_file()
            }
            write_once(
                root / "output-seal.json",
                {
                    "revision": REVISION,
                    "evaluationRunId": run.evaluation_run_id,
                    "sealedAt": datetime.now(UTC).isoformat(),
                    "files": files,
                    "taskCount": len(run.results),
                    "contentReviewStarted": False,
                },
            )
        except BaseException as exc:
            write_once(
                root / "STOP.json",
                {
                    "status": "STOPPED_NO_SECOND_RUN",
                    "errorType": type(exc).__name__,
                    "reason": sink.safe(str(exc)),
                    "persistedTasks": len(runner.completed),
                },
            )
            raise


def finalize(root: Path) -> None:
    verify_output_seal(root)
    frozen = read(root / "run-intent.json")
    assert_source(frozen)
    run_paths = list((root / "raw").rglob("run.json"))
    if len(run_paths) != 1:
        raise ValueError("expected one raw execution run")
    run = BenchmarkRun.model_validate_json(run_paths[0].read_text(encoding="utf-8"))
    retention_integrity(run, root)
    persisted_task_integrity(run, root)
    dataset = validate_dataset()
    truths = formal._ground_truths(dataset)
    task_by_id = {task.benchmark_task_id: task for task in dataset.tasks}
    retained = {
        read(path)["taskId"]: read(path) for path in (root / "retention/reports").glob("*.json")
    }
    review_paths = list((root / "reviews").glob("*.json"))
    reviews = {read(path)["taskId"]: read(path) for path in review_paths}
    applicable = {
        task_id for task_id, truth in truths.items() if truth.diagnosis_contract is not None
    }
    if len(reviews) != len(review_paths) or not set(reviews).issubset(applicable):
        raise ValueError("duplicate or out-of-scope content reviews")
    seal_digest = file_digest(root / "output-seal.json")
    results, coverage = [], []
    for result in run.results:
        truth = truths[result.benchmark_task_id]
        if truth.diagnosis_contract is not None and result.evaluation_result is not None:
            review = reviews.get(result.benchmark_task_id)
            content = retained.get(result.benchmark_task_id)
            bound = (
                ()
                if review is None
                else (
                    load_content_review(
                        review,
                        content,
                        seal_digest=seal_digest,
                    ),
                )
            )
            facts = EvaluationFacts.model_validate_json(
                json.dumps(
                    result.formal_evidence.normalized_evaluation_facts,
                )
            )
            case = to_evaluation_case(
                task_by_id[result.benchmark_task_id],
                truth,
                case_id=result.evaluation_result.case_id,
                trace_id=result.trace_id,
                agent_run_id=result.agent_run_id,
                facts=facts,
            )
            metric = RuleBasedEvaluator._diagnosis_contract(case, truth, bound)
            old = result.evaluation_result
            new = old.model_copy(
                update={
                    "metrics": tuple(
                        metric if item.metric is MetricName.DIAGNOSIS_CONTRACT else item
                        for item in old.metrics
                    ),
                    "evaluation_id": "evaluation:"
                    + canonical_json_hash(
                        {
                            "machineEvaluation": old.evaluation_id,
                            "review": review,
                            "seal": seal_digest,
                        }
                    )[:24],
                }
            )
            result = result.model_copy(
                update={"evaluation_result": new, "evaluation_id": new.evaluation_id}
            )
            coverage.append(
                {
                    "taskId": result.benchmark_task_id,
                    "reviewed": bool(bound),
                    "metric": metric.model_dump(mode="json"),
                }
            )
        elif truth.diagnosis_contract is not None:
            coverage.append(
                {
                    "taskId": result.benchmark_task_id,
                    "reviewed": False,
                    "reason": "No completed machine evaluation; raw execution outcome retained",
                    "modelCallIds": list(result.model_call_ids),
                }
            )
        results.append(result)
    evaluated = run.model_copy(update={"results": tuple(results)})
    policy = load_outcome_policy(POLICY, dataset=dataset)
    projection = project_outcome_v2(evaluated, policy, source_artifact=run_paths[0])
    write_once(root / "evaluated/run.json", evaluated.model_dump(mode="json"))
    write_once(root / "evaluated/outcome-v2.json", projection.model_dump(mode="json"))
    write_once(root / "evaluated/content-review-coverage.json", coverage)
    write_once(
        root / "evaluated/provider-provenance.json",
        verify_provider_integrity(
            run.results,
            expected_provider="Qwen",
            expected_model="qwen3.8-max",
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "freeze", "execute", "finalize"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--preparation", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare()
    elif args.mode == "freeze":
        asyncio.run(freeze(args.preparation, args.root))
    elif args.mode == "execute":
        asyncio.run(execute(args.root, args.freeze))
    else:
        finalize(args.root)


if __name__ == "__main__":
    main()
