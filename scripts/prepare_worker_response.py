#!/usr/bin/env python3
"""Validate a worker's draft and print a strict JSON response without accepting it."""

import argparse
import json
import re
import sys
from pathlib import Path

try:
    from merge_techops_result import validated_result
    from provider_runtime import strict_json_loads
    from review_evidence import plan_review_coverage_errors, review_report_errors, review_candidate_metadata_errors
except ModuleNotFoundError:
    from scripts.merge_techops_result import validated_result
    from scripts.provider_runtime import strict_json_loads
    from scripts.review_evidence import plan_review_coverage_errors, review_report_errors, review_candidate_metadata_errors


def validate_response(packet_path: Path, agent: str, response: dict) -> str:
    packet_path = packet_path.resolve()
    packet = json.loads(packet_path.read_text())
    bindings = json.loads((packet_path.parent / "role_bindings.json").read_text())
    if bindings.get("run_id") != packet.get("identity", {}).get("Run ID"):
        raise ValueError("worker_response_binding_run_mismatch")
    contract = bindings.get("worker_contracts", {}).get(agent, {})
    allowed = {"output", "result"} | ({"asset_manifest"} if contract.get("asset_inventory") else set())
    if (not isinstance(response, dict) or set(response) - allowed
            or not isinstance(response.get("output"), str) or not response["output"].strip()
            or not isinstance(response.get("result"), dict)):
        raise ValueError("worker_response_envelope_invalid")
    if contract.get("asset_inventory") and not isinstance(response.get("asset_manifest"), dict):
        raise ValueError("worker_asset_manifest_response_required")
    candidate = validated_result(packet, response["result"], bindings, agent)
    if (bindings.get("playbook") == "feature_delivery" and bindings.get("lifecycle") == "planning"
            and agent == "solution_architect" and response["result"]["worker_result"]["Outcome"] == "complete"
            and (packet_path.parent / "asset_manifest.json").is_file()):
        try:
            from asset_manifest import link_design_assets
        except ModuleNotFoundError:
            from scripts.asset_manifest import link_design_assets
        link_design_assets(json.loads((packet_path.parent / "asset_manifest.json").read_text()),
                           response["output"], candidate)
    if (agent == "reviewer" and bindings.get("lifecycle") == "remediation"
            and bindings.get("playbook") in {"techops_issue_remediation", "feature_delivery"}
            and re.search(r"^Disposition:\s*accepted\s*$", response["output"], re.M)):
        errors = review_report_errors(response["output"], require_accepted=True)
        errors += review_candidate_metadata_errors(response["output"], expected_repository=Path(bindings["source_checkout"]))
        errors += plan_review_coverage_errors((packet_path.parent / "implementation_plan.md").read_text(),
                                              response["output"])
        if errors:
            raise ValueError("review_plan_coverage_invalid:" + ";".join(errors))
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
