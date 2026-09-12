from __future__ import annotations

import importlib.util
from pathlib import Path

from app.benchmark import load_stage21_prerequisites


def _load_smoke_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "stage21_qwen_prompt2_testcase_smoke.py"
    )
    spec = importlib.util.spec_from_file_location("stage21_qwen_testcase_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_provider_smoke_cases_are_local_generation_without_java_authority() -> None:
    smoke = _load_smoke_module()
    tasks = (smoke._load_task(smoke.POSITIVE_TASK), smoke._load_task(smoke.INVALID_TASK))
    prerequisites = load_stage21_prerequisites()

    assert [task.benchmark_task_id for task in tasks] == [
        "bench_task_formal_testcase_happy_create_order_contract",
        "bench_task_formal_testcase_invalid_http_method",
    ]
    assert all(
        prerequisites[task.benchmark_task_id].required_operations == ("NO_JAVA_ACCESS",)
        for task in tasks
    )
