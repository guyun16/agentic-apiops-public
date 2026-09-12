"""Seed via Java public APIs only; benchmark results are read unchanged."""

import json
import os
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / ".local-run/hr-demo"


def data(response):
    response.raise_for_status()
    body = response.json()
    if body.get("code") not in ("SUCCESS", "00000", 200):
        raise RuntimeError(f"API rejected demo operation: {body.get('code')}")
    return body["data"]


def main():
    project = json.loads((LOCAL / "identity.json").read_text(encoding="utf-8-sig"))["projectId"]
    prefix = f"/api/v1/projects/{project}"
    with httpx.Client(base_url="http://127.0.0.1:19090", trust_env=False, timeout=30) as client:
        tokens = {}
        for user, key in [
            ("hr-presenter", "HR_PRESENTER_PASSWORD"),
            ("hr-viewer", "HR_VIEWER_PASSWORD"),
        ]:
            result = data(
                client.post(
                    "/api/v1/auth/login", json={"username": user, "password": os.environ[key]}
                )
            )
            tokens[user] = {"Authorization": "Bearer " + result["accessToken"]}
            projects = data(client.get("/api/v1/projects", headers=tokens[user]))
            assert len(projects) == 1 and int(projects[0]["projectId"]) == project, (
                "Demo project isolation failed"
            )
            assert client.get("/api/v1/projects/41", headers=tokens[user]).status_code == 403
        client.headers.update(tokens["hr-presenter"])
        source = json.loads(
            (ROOT / "docs/openapi/demo-order-service-openapi.json").read_text(encoding="utf-8-sig")
        )
        source["servers"] = [{"url": "http://127.0.0.1:18080"}]
        data(
            client.post(
                prefix + "/openapi/documents",
                data={"sourceKey": "hr-demo-order-v1"},
                files={"file": ("hr-order.json", json.dumps(source).encode(), "application/json")},
            )
        )
        apis = data(client.get(prefix + "/openapi/apis"))
        api = next(a for a in apis if a["method"] == "GET" and a["path"] == "/products")
        cases = []
        for suffix, name, expected in [
            ("success", "HR Demo: product list succeeds", 200),
            ("assertion-failure", "HR Demo: intentional assertion failure", 201),
        ]:
            cases.append(
                {
                    "schemaVersion": "1.0.0",
                    "caseId": "hr-demo-" + suffix,
                    "projectId": project,
                    "apiId": api["apiId"],
                    "name": name,
                    "description": "Real HTTP; intentional assertion failure."
                    if expected == 201
                    else "Real HTTP success against existing product fixtures.",
                    "environment": {"baseUrl": "http://127.0.0.1:18080", "variables": {}},
                    "tags": ["hr-demo", suffix],
                    "steps": [
                        {
                            "stepId": "products",
                            "name": name,
                            "request": {
                                "method": "GET",
                                "path": "/products",
                                "pathParams": {},
                                "query": {"pageNo": 1, "pageSize": 3},
                                "headers": {},
                                "body": None,
                            },
                            "assertions": [{"type": "STATUS_CODE", "expected": expected}],
                            "extractors": [],
                        }
                    ],
                }
            )
        runs = []
        for case in cases:
            valid = data(
                client.post(prefix + f"/openapi/apis/{api['apiId']}/testcases:validate", json=case)
            )
            assert valid["valid"], "Demo DSL validation failed"
            latest = data(
                client.get(prefix + "/test-runs/latest-by-case", params={"caseId": case["caseId"]})
            )
            if latest is None:
                submitted = data(client.post(prefix + "/test-batches", json={"testCases": [case]}))
                run_id = submitted["runIds"][0]
            else:
                run_id = latest["runId"]
            deadline = time.monotonic() + 90
            while True:
                run = data(client.get(prefix + f"/test-runs/{run_id}"))
                if run["status"] not in ("PENDING", "RUNNING"):
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("Demo execution timed out")
                time.sleep(1)
            report = data(client.get(prefix + f"/test-runs/{run_id}/report"))
            expected_status = (
                "SUCCESS" if case["caseId"].endswith("-success") else "ASSERTION_FAILED"
            )
            assert run["status"] == expected_status, (
                f"Unexpected status for {case['caseId']}: {run['status']}"
            )
            runs.append(
                {
                    "caseId": case["caseId"],
                    "runId": run_id,
                    "status": run["status"],
                    "failureType": run["failureType"],
                    "reportAvailable": report is not None,
                }
            )
        assert runs[0]["failureType"] == "NONE" and runs[1]["failureType"] != "NONE", (
            "Unexpected demo outcomes"
        )
        denied = client.post(
            prefix + "/test-batches", json={"testCases": [cases[0]]}, headers=tokens["hr-viewer"]
        )
        assert denied.status_code == 403, "Viewer must not execute cases"
        for run in runs:
            data(
                client.get(
                    prefix + f"/test-runs/{run['runId']}/report", headers=tokens["hr-viewer"]
                )
            )
        manifest = json.loads((ROOT / "artifacts/benchmark/portfolio-manifest.json").read_text())
        for publication in manifest["publications"]:
            assert (ROOT / publication["artifactLocation"]).is_file(), "Missing benchmark bundle"
        published = client.get("http://127.0.0.1:18000/api/v1/benchmark/results")
        published.raise_for_status()
        assert {p["evaluationRunId"] for p in published.json()} == {
            p["evaluationRunId"] for p in manifest["publications"]
        }, "Published benchmark history differs"
        result = {
            "projectId": project,
            "accounts": {"hr-presenter": "OWNER", "hr-viewer": "VIEWER"},
            "apiCount": len(apis),
            "runs": runs,
            "benchmarkRuns": len(manifest["publications"]),
            "benchmarkManifest": "artifacts/benchmark/portfolio-manifest.json",
            "exampleDirectory": "examples/",
            "testCases": cases,
        }
        (LOCAL / "demo-summary.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({k: v for k, v in result.items() if k != "testCases"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
