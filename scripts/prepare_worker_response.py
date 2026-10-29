#!/usr/bin/env python3
"""Validate a worker's draft and print a strict JSON response without accepting it."""

import argparse
import json
import sys
from pathlib import Path

try:
    from merge_techops_result import validated_result
    from provider_runtime import strict_json_loads
except ModuleNotFoundError:
    from scripts.merge_techops_result import validated_result
    from scripts.provider_runtime import strict_json_loads


def validate_response(packet_path: Path, agent: str, response: dict) -> str:
    packet_path = packet_path.resolve()
    packet = json.loads(packet_path.read_text())
    bindings = json.loads((packet_path.parent / "role_bindings.json").read_text())
    if bindings.get("run_id") != packet.get("identity", {}).get("Run ID"):
        raise ValueError("worker_response_binding_run_mismatch")
    if (not isinstance(response, dict) or set(response) != {"output", "result"}
            or not isinstance(response["output"], str) or not response["output"].strip()):
        raise ValueError("worker_response_envelope_invalid")
    validated_result(packet, response["result"], bindings, agent)
    return json.dumps(response, ensure_ascii=False, separators=(",", ":"))


def prepare_response(packet_path: Path, agent: str, result_path: Path, output_path: Path) -> str:
    return validate_response(packet_path, agent, {"output": output_path.read_text(),
                                                  "result": strict_json_loads(result_path.read_text())})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--result-draft", type=Path)
    parser.add_argument("--output-draft", type=Path)
    parser.add_argument("--response-stdin", action="store_true")
    args = parser.parse_args()
    if args.response_stdin == bool(args.result_draft or args.output_draft) or (not args.response_stdin and not (args.result_draft and args.output_draft)):
        parser.error("provide --response-stdin or both --result-draft and --output-draft")
    try:
        response = (validate_response(args.packet, args.agent, strict_json_loads(sys.stdin.read()))
                    if args.response_stdin else prepare_response(args.packet, args.agent, args.result_draft, args.output_draft))
        print(response)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(json.dumps({"status": "invalid", "reason": str(error)}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
