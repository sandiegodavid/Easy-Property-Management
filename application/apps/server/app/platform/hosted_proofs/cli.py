"""Read-only specification/report tooling; all proof executors remain unavailable."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from pydantic import ValidationError

from app.platform.hosted_proofs.models import ProofReport, Result, Specification, validate_report

MAX_DOCUMENT_BYTES = 1024 * 1024
EXECUTOR_UNAVAILABLE = 3


def unique_fields(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate document field.")
        result[name] = value
    return result


def load_document(path: Path, model):
    with path.open("rb") as stream:
        content = stream.read(MAX_DOCUMENT_BYTES + 1)
    if len(content) > MAX_DOCUMENT_BYTES:
        raise ValueError("Document size exceeded.")
    json.loads(content, object_pairs_hook=unique_fields)
    return model.model_validate_json(content), sha256(content).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    describe = commands.add_parser("describe", help="Inspect a specification; never run a proof.")
    describe.add_argument("--spec", type=Path, required=True)
    validate = commands.add_parser(
        "validate", help="Validate evidence shape/coverage, not authenticity."
    )
    validate.add_argument("--spec", type=Path, required=True)
    validate.add_argument("--report", type=Path, required=True)
    execute = commands.add_parser("execute", help="Unavailable H02–H05 executor interface.")
    execute.add_argument("--spec", type=Path, required=True)
    execute.add_argument("--inputs", type=Path, required=True)
    execute.add_argument("--output", type=Path, required=True)
    execute.add_argument("--phase", choices=("run", "after-reboot", "manual"), default="run")
    args = parser.parse_args(argv)
    if args.command == "execute":
        print("proof_executor_unavailable: owning H02–H05 executor is not implemented.")
        return EXECUTOR_UNAVAILABLE
    try:
        specification, digest = load_document(args.spec, Specification)
        if args.command == "describe":
            print(f"{specification.proof.value}: owner={specification.owner}; spec_sha256={digest}")
            print("levels: " + ", ".join(item.value for item in specification.levels))
            print("cases: " + ", ".join(specification.cases))
            print("Specification only; no proof executed or release gate established.")
            return 0
        report, _ = load_document(args.report, ProofReport)
        validate_report(specification, digest, report)
    except OSError, ValueError, ValidationError, RecursionError:
        print("proof_document_invalid: check the declared format, pins and complete case coverage.")
        return 1
    print(f"Valid {report.environment.level.value} report: {report.status.value}.")
    print("Evidence authenticity and release acceptance require owning review; no gate is enabled.")
    return 0 if report.status == Result.PASSED else 2
