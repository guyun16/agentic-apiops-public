import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


VALID_CASES = [
    (
        "shared-schemas/testcase-dsl-schema.json",
        "examples/testcase-valid.json",
    ),
    (
        "shared-schemas/testcase-dsl-schema.json",
        "examples/testcase-missing-token-valid.json",
    ),
    (
        "shared-schemas/testcase-dsl-schema.json",
        "examples/testcase-invalid-quantity-valid.json",
    ),
    (
        "shared-schemas/testcase-dsl-schema.json",
        "examples/testcase-insufficient-stock-valid.json",
    ),
    (
        "shared-schemas/tool-call-schema.json",
        "examples/tool-call-valid.json",
    ),
    (
        "shared-schemas/tool-result-schema.json",
        "examples/tool-result-valid.json",
    ),
    (
        "shared-schemas/diagnosis-report-schema.json",
        "examples/diagnosis-report-valid.json",
    ),
]


INVALID_CASES = [
    (
        "shared-schemas/testcase-dsl-schema.json",
        "examples/invalid/testcase-missing-api-id.json",
    ),
    (
        "shared-schemas/testcase-dsl-schema.json",
        "examples/invalid/testcase-invalid-method.json",
    ),
    (
        "shared-schemas/testcase-dsl-schema.json",
        "examples/invalid/testcase-extra-field.json",
    ),
    (
        "shared-schemas/testcase-dsl-schema.json",
        "examples/invalid/testcase-missing-schema-version.json",
    ),
    (
        "shared-schemas/testcase-dsl-schema.json",
        "examples/invalid/testcase-project-id-string.json",
    ),
    (
        "shared-schemas/testcase-dsl-schema.json",
        "examples/invalid/testcase-unknown-assertion.json",
    ),
    (
        "shared-schemas/testcase-dsl-schema.json",
        "examples/invalid/testcase-status-code-missing-expected.json",
    ),
    (
        "shared-schemas/testcase-dsl-schema.json",
        "examples/invalid/testcase-json-path-equals-missing-expected.json",
    ),
    (
        "shared-schemas/tool-call-schema.json",
        "examples/invalid/tool-call-unknown-field.json",
    ),
    (
        "shared-schemas/tool-call-schema.json",
        "examples/invalid/tool-call-legacy-tool-name.json",
    ),
    (
        "shared-schemas/tool-result-schema.json",
        "examples/invalid/tool-result-unknown-field.json",
    ),
]


TOOL_RESULT_STATUSES = (
    "SUCCESS",
    "FORBIDDEN",
    "PARAM_INVALID",
    "RESULT_INVALID",
    "FAILED",
    "TIMEOUT",
)


def load_json(relative_path: str) -> dict:
    path = ROOT / relative_path
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def validate_instance(schema_path: str, instance_path: str) -> list[str]:
    schema = load_json(schema_path)
    instance = load_json(instance_path)

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda error: error.path)

    return [error.message for error in errors]


def validate_valid_cases() -> bool:
    all_passed = True

    print("== Valid examples ==")

    for schema_path, instance_path in VALID_CASES:
        errors = validate_instance(schema_path, instance_path)

        if errors:
            all_passed = False
            print(f"[FAIL] {instance_path}")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"[PASS] {instance_path}")

    return all_passed


def validate_invalid_cases() -> bool:
    all_rejected = True

    print()
    print("== Invalid examples ==")

    for schema_path, instance_path in INVALID_CASES:
        errors = validate_instance(schema_path, instance_path)

        if errors:
            print(f"[PASS: rejected as expected] {instance_path}")
            for error in errors:
                print(f"  - {error}")
        else:
            all_rejected = False
            print(f"[FAIL: should have been rejected] {instance_path}")

    return all_rejected


def validate_tool_result_statuses() -> bool:
    schema_path = "shared-schemas/tool-result-schema.json"
    instance = load_json("examples/tool-result-valid.json")
    validator = Draft202012Validator(load_json(schema_path))
    all_passed = True

    print()
    print("== ToolResult core statuses ==")

    for status in TOOL_RESULT_STATUSES:
        candidate = dict(instance)
        candidate["status"] = status
        errors = sorted(validator.iter_errors(candidate), key=lambda error: error.path)

        if errors:
            all_passed = False
            print(f"[FAIL] status={status}")
            for error in errors:
                print(f"  - {error.message}")
        else:
            print(f"[PASS] status={status}")

    return all_passed


def main() -> None:
    valid_ok = validate_valid_cases()
    invalid_ok = validate_invalid_cases()
    statuses_ok = validate_tool_result_statuses()

    print()
    print("== Summary ==")

    if valid_ok and invalid_ok and statuses_ok:
        print("Schema validation completed successfully.")
    else:
        print("Schema validation failed.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
