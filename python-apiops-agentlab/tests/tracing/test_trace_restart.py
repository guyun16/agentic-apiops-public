from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
TRACE_ID = "trace:process-restart"
AGENT_RUN_ID = "agent_run:process-restart"

WRITER = """
import sys
from datetime import UTC, datetime

from app.core.settings import AppSettings
from app.tracing import AgentRun, TraceEvent, TraceStatus, create_trace_recorder

settings = AppSettings(
    trace_sink="jsonl",
    trace_jsonl_path=sys.argv[1],
    trace_max_file_bytes=1024 * 1024,
)
recorder = create_trace_recorder(settings)
started_at = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
recorder.record(
    AgentRun(
        trace_id="trace:process-restart",
        agent_run_id="agent_run:process-restart",
        project_id=41,
        event=TraceEvent.START,
        status=TraceStatus.RUNNING,
        timestamp=started_at,
    )
)
recorder.record(
    AgentRun(
        trace_id="trace:process-restart",
        agent_run_id="agent_run:process-restart",
        project_id=41,
        event=TraceEvent.TERMINAL,
        status=TraceStatus.SUCCESS,
        timestamp=started_at.replace(second=1),
    )
)
assert recorder.accepted_records == 2
"""

READER = """
import json
import sys

from app.core.settings import AppSettings
from app.tracing import query_persisted_trace_records

settings = AppSettings(
    trace_sink="jsonl",
    trace_jsonl_path=sys.argv[1],
    trace_max_file_bytes=1024 * 1024,
)
trace_records = query_persisted_trace_records(
    trace_id="trace:process-restart",
    settings=settings,
)
agent_run_records = query_persisted_trace_records(
    agent_run_id="agent_run:process-restart",
    settings=settings,
)
print(json.dumps({
    "traceCount": len(trace_records),
    "agentRunCount": len(agent_run_records),
    "traceId": trace_records[0].trace_id,
    "agentRunId": trace_records[0].agent_run_id,
    "projectId": trace_records[0].project_id,
    "sequences": [record.sequence for record in trace_records],
}, sort_keys=True))
"""


def _run_process(script: str, trace_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script, str(trace_path)],
        cwd=PACKAGE_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_trace_readback_survives_independent_python_process_restart(tmp_path: Path) -> None:
    trace_path = tmp_path / "restart-traces.jsonl"

    writer = _run_process(WRITER, trace_path)
    assert writer.returncode == 0, writer.stderr
    assert trace_path.exists()

    reader = _run_process(READER, trace_path)
    assert reader.returncode == 0, reader.stderr
    evidence = json.loads(reader.stdout)

    assert evidence == {
        "agentRunCount": 2,
        "agentRunId": AGENT_RUN_ID,
        "projectId": 41,
        "sequences": [1, 2],
        "traceCount": 2,
        "traceId": TRACE_ID,
    }
