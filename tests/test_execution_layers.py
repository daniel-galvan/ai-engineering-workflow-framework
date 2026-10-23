"""Keep shared workflow invariants separate from provider and source policies."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ExecutionLayers(unittest.TestCase):
    def test_compaction_preserves_the_prepared_run_without_bootstrap_discovery(self):
        for path in ("skills/run/SKILL.md", "providers/codex.md", "providers/codex/agents/orchestrator.toml"):
            text = " ".join((ROOT / path).read_text().split())
            with self.subTest(path=path):
                self.assertIn("Context compaction does not start a new invocation", text)
                for value in ("Run ID", "pinned package root", "lifecycle", "user decisions", "worker handles",
                              "next pending gate", "role_bindings.json", "finalization_packet.json",
                              "runtime_dispatches.json", "run_inputs.json", "its hash unchanged",
                              "Do not rerun preflight or preparation", "search local memory"):
                    self.assertIn(value, text)

    def test_core_keeps_invariants_and_normalized_seams_without_concrete_operations(self):
        core = (ROOT / "contracts/workflow_execution.md").read_text()
        for number in range(1, 42):
            self.assertIn(f"`INV-{number:02d}`", core)
        for heading in ("# Human Control Model", "# Work-Item Read Contract", "# Worker Contract",
                        "# Stage Completion and Fan-In", "## Worker Runtime Closure", "# Workflow State Machine"):
            self.assertIn(heading, core)
        for detail in ("MCP", "Atlassian", "Rovo", "Codex", "browser", "spawn_agent", "create_thread", "fork_thread",
                       "send_message_to_thread", "fork_context", ".codex/agents", "list_agents", "read_thread",
                       "wait_threads", "source_access_receipt.py", "plugin-backed launcher"):
            with self.subTest(detail=detail):
                self.assertNotIn(detail, core)
        self.assertIn("../providers/README.md", core)
        self.assertIn("../integrations/jira.md#read-path", core)

    def test_worker_binding_uses_dispatch_arguments_when_applied_telemetry_is_unavailable(self):
        core = (ROOT / "contracts/workflow_execution.md").read_text()
        self.assertIn("The native dispatch record MUST prove those exact launch arguments were sent", core)
        self.assertIn("Missing applied telemetry alone does not", core)
        self.assertIn("do not claim that binding was observed as", core)
        self.assertNotIn("Missing metadata is an unverified binding", core)

    def test_codex_handle_only_spawn_result_uses_native_activation_evidence(self):
        for path in ("providers/codex.md", "providers/codex/agents/orchestrator.toml", "skills/run/SKILL.md"):
            text = " ".join((ROOT / path).read_text().split())
            self.assertIn("spawn_agent", text)
            self.assertIn("task handle", text)
            self.assertIn("SubAgentActivity", text)
        self.assertIn("Never interrupt a worker solely because the spawn result contains only its handle",
                      " ".join((ROOT / "providers/codex.md").read_text().split()))

    def test_adapter_preserves_launch_routing_activation_and_closure_controls(self):
        adapter = (ROOT / "providers/codex.md").read_text()
        for control in ("first framework tool call", "direct Atlassian MCP connector first", "source_access_receipt.py",
                        "worker_activation_attempts: 0", "plugin_revision_mismatch", "fork_context: false",
                        "spawn_agent", "Never use `create_thread`", "fork_thread", "send_message_to_thread",
                        "list_agents", "read_thread", "wait_threads", "terminal_observations",
                        "does not assert capacity release", "worker_runtime_release_unavailable"):
            with self.subTest(control=control):
                self.assertIn(control, adapter)
        self.assertIn("../integrations/jira.md#feature-delivery-source-access-gate", adapter)

    def test_idle_worker_corrections_require_an_execution_triggering_dispatch(self):
        for path in ("providers/codex.md", "skills/run/SKILL.md"):
            text = (ROOT / path).read_text()
            self.assertIn("followup_task", text)
            self.assertIn("does not start an idle worker", text)

    def test_publisher_is_required_after_finalization(self):
        for path in ("skills/run/SKILL.md", "providers/codex/agents/orchestrator.toml"):
            text = " ".join((ROOT / path).read_text().split())
            self.assertIn("--publish-response", text)
            self.assertIn("validation diagnostic, not part of", text)
            self.assertIn("pending", text)

    def test_handoff_recovery_preserves_worker_rows_and_rejected_dispatches(self):
        worker = (ROOT / "providers/codex/agents/documenter.toml").read_text()
        for control in ("every Evidence row", "every Claim", "every Decision", "byte-for-byte",
                        "handoff-owned", "do not edit analytical rows"):
            self.assertIn(control, worker)
        adapter = (ROOT / "providers/codex.md").read_text()
        for control in ("collab tool failed: agent thread limit reached", "stop dispatch retries",
                        "Do not interrupt completed workers", "workflow-failure finalization"):
            self.assertIn(control, adapter)

    def test_techops_workflow_result_is_plain_language_not_a_status_token(self):
        worker = " ".join((ROOT / "providers/codex/agents/documenter.toml").read_text().split())
        for instruction in ("handoff.workflow_result` must be a one- or two-sentence plain-language summary",
                            "`Partially answered` is a Technical Spike disposition only",
                            "Even when `State: awaiting_input`, summarize the finding",
                            "place that clarification content in the assigned finalization packet or an assigned plan",
                            "Do not create a separate clarification file unless its exact path is listed as an assigned artifact"):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, worker)
        playbook = " ".join((ROOT / "playbooks/techops_issue_remediation.md").read_text().split())
        self.assertIn("A disposition token such as `Partially answered` or `Blocked` is not a work summary either", playbook)

    def test_material_user_decisions_wait_in_the_same_run_before_finalization(self):
        contract = " ".join((ROOT / "contracts/workflow_execution.md").read_text().split())
        for rule in ("## Interactive Decision Gate", "same user-facing run session", "wait for the user's response",
                     "paused, nonterminal state", "Do not continue dependent work", "Do not rewrite the prepared, hashed run-input manifest",
                     "unanswered user questions from the originating request", "planning interpretation",
                     "does not resolve a user-owned choice", "Current code evidence can establish what the system does"):
            with self.subTest(rule=rule):
                self.assertIn(rule, contract)
        for path in ("providers/codex.md", "providers/codex/agents/orchestrator.toml", "skills/run/SKILL.md"):
            text = " ".join((ROOT / path).read_text().split())
            with self.subTest(path=path):
                self.assertIn("functions.request_user_input", text)
                self.assertIn("wait for an explicit user reply", text)
                self.assertIn("same run", text)
        adapter = (ROOT / "providers/codex.md").read_text()
        self.assertIn("`functions.request_user_input_async`", adapter)
        self.assertIn("empty or missing answers remains unanswered", " ".join(adapter.split()))
        self.assertIn("not user-visible rendering or an answer", adapter)
        self.assertIn("unanswered questions into a fresh run as pending inputs", " ".join(adapter.split()))
        launcher = " ".join((ROOT / "skills/run/SKILL.md").read_text().split())
        self.assertIn("carry each explicit unanswered user-owned question into the launch prompt and input manifest", launcher)
        template = " ".join((ROOT / "templates/techops_issue_run_prompt.md").read_text().split())
        self.assertIn("Unanswered material user decisions carried from the current request", template)
        orchestrator = " ".join((ROOT / "providers/codex/agents/orchestrator.toml").read_text().split())
        self.assertIn("Do not treat a Coordinator-owned `planning interpretation`", orchestrator)

    def test_techops_launch_prompt_is_minimal_and_uses_playbook_defaults(self):
        template = (ROOT / "templates/techops_issue_run_prompt.md").read_text()
        launch = re.search(r"## Minimal launch\s+.*?```text\n(.*?)```", template, re.S)
        self.assertIsNotNone(launch)
        self.assertEqual(launch.group(1).strip(), (
            "$ai-engineering-workflows:run Run the TechOps Issue Remediation playbook.\n\n"
            "Work item: <TECHOPS-JIRA-ID-OR-URL>\n"
            "Playbook: playbooks/techops_issue_remediation.md"
        ))
        self.assertNotIn("Execution profile:", launch.group(1))
        self.assertNotIn("Lifecycle:", launch.group(1))
        launcher = " ".join((ROOT / "skills/run/SKILL.md").read_text().split())
        self.assertIn("the only required user-authored launcher values are the work-item ID or URL and the selected TechOps playbook", launcher)
        self.assertIn("resolve to `standard` and `planning`", launcher)

    def test_unreleased_stale_run_requires_a_separate_artifact_root_for_new_planning(self):
        launcher = " ".join((ROOT / "skills/run/SKILL.md").read_text().split())
        self.assertIn("separate execution repository and artifact root", launcher)
        self.assertIn("does not authorize deleting, resetting, or reusing the blocked work-item root", launcher)
        self.assertIn("preserve the old files and satisfy the stale-archive checks above first", launcher)

    def test_ordinary_handle_join_does_not_create_a_post_spawn_dispatch(self):
        for path in ("providers/codex.md", "skills/run/SKILL.md"):
            text = " ".join((ROOT / path).read_text().split())
            with self.subTest(path=path):
                self.assertIn("Do not send a post-spawn message solely to supply that handle", text)
                self.assertIn("Every later message remains a dispatch requiring fresh consumption evidence", text)
                self.assertIn("explicit Sentry Fix Design", text)

    def test_jira_owns_source_coverage_and_failures_and_sentry_owns_acquisition(self):
        jira = (ROOT / "integrations/jira.md").read_text()
        for policy in ("## Feature Delivery Source-Access Gate", "at most one distinct configured Jira connector",
                       "## TechOps Issue Remediation Source-Access Gate", "source_access_receipt.py --source Jira",
                       "not connector-wide authentication failures", "Inventory every member of that collection",
                       "## Freshness and reconciliation", "## Write boundary", "## Privacy and sharing"):
            with self.subTest(policy=policy):
                self.assertIn(policy, " ".join(jira.split()) if "at most one" in policy else jira)
        self.assertIn("../contracts/workflow_execution.md#work-item-read-contract", jira)
        launcher = (ROOT / "skills/run/SKILL.md").read_text()
        techops_gate = launcher.split("5a. For Jira-backed TechOps Issue Remediation", 1)[1].split("5b. For Jira-backed Feature Delivery", 1)[0]
        for phrase in ("read the exact supplied issue key", "before creating an input manifest",
                       "OPERATION_UNAVAILABLE", "zero worker activation attempts",
                       "no artifact root or work record"):
            with self.subTest(techops_gate=phrase):
                self.assertIn(phrase, techops_gate)
        sentry = (ROOT / "integrations/sentry.md").read_text()
        self.assertIn("## Acquisition Ownership", sentry)
        self.assertIn("Before Evidence Topology activation", sentry)
        self.assertIn("## Source-Access Gate", sentry)

    def test_jira_retry_policy_reaches_both_launchers_and_evidence_workers(self):
        jira = " ".join((ROOT / "integrations/jira.md").read_text().split())
        recovery = jira.split("## Transient Read Recovery", 1)[1].split("## TechOps", 1)[0]
        for boundary in ("at most two retries", "wait 1 minute before the first retry",
                         "3 minutes before the second retry", "at most three calls total",
                         "same connector, operation, and arguments", "MCP_REQUEST_TIMEOUT",
                         "observation timeout", "completion is unknown", "authentication failures",
                         "`permission_denied`", "`not_found`", "Jira writes", "retry due time",
                         "without creating files", "existing authorized artifact root",
                         "do not consume an analytical correction allowance"):
            with self.subTest(boundary=boundary):
                self.assertIn(boundary, recovery)
        launcher = (ROOT / "skills/run/SKILL.md").read_text()
        for start, end in (("5a. For Jira-backed TechOps", "5b. For Jira-backed Feature Delivery"),
                           ("5b. For Jira-backed Feature Delivery", "5c. For Sentry")):
            gate = launcher.split(start, 1)[1].split(end, 1)[0]
            self.assertIn("jira.md#transient-read-recovery", gate)
        self.assertIn("jira.md#transient-read-recovery", (ROOT / "providers/codex.md").read_text())
        worker = (ROOT / "providers/codex/agents/current_state_investigator.toml").read_text()
        self.assertIn("Transient Read Recovery", worker)
        self.assertIn("Preserve the existing call handle", worker)

    def test_access_observations_preserve_the_prepared_input_manifest(self):
        launcher = " ".join((ROOT / "skills/run/SKILL.md").read_text().split())
        self.assertIn("Run filename discovery in a separate tool result from content reads or searches", launcher)
        self.assertIn("`.thoughts/<WORK-ITEM-ID>` directory is only the artifact root", launcher)
        self.assertIn("do not check it or its `.thoughts` parent for `AGENTS.md`", launcher)
        for name in ("skills/run/SKILL.md", "contracts/workflow_execution.md"):
            text = " ".join((ROOT / name).read_text().split())
            with self.subTest(file=name):
                self.assertIn("Before preparation", text)
                self.assertIn("access-status updates in the source manifest before", text)
                self.assertIn("`run_inputs.json` is frozen; do not edit it or replace its recorded hash", text)
                self.assertIn("Record later access observations in the current-run evidence and work record", text)

    def test_sentry_access_failure_stops_before_preparation_without_log_fallback(self):
        launcher = (ROOT / "skills/run/SKILL.md").read_text()
        gate = launcher.split("5c. For Sentry Issue Remediation", 1)[1].split("6. For Standard Sentry planning", 1)[0]
        for phrase in ("issue and its latest event", "--source Sentry", "OPERATION_UNAVAILABLE",
                       "zero worker activation attempts", "no artifact root or work record",
                       "Supplied logs do not", "explicitly selects an offline", "30 seconds", "90 seconds"):
            self.assertIn(phrase, gate)
        investigator = (ROOT / "providers/codex/agents/sentry_current_state_investigator.toml").read_text()
        self.assertIn("return a blocked result with `required_source_unavailable` immediately", investigator)
        self.assertNotIn("fallback search and stop with bounded uncertainty", investigator)
        for file in ("templates/sentry_issue_run_prompt.md", "providers/codex/agents/sentry_orchestrator.toml"):
            text = (ROOT / file).read_text()
            self.assertIn("required_source_unavailable", text)
            self.assertIn("Supplied logs do not waive", text)
        playbook = (ROOT / "playbooks/sentry_issue_remediation.md").read_text()
        self.assertNotIn("then retain `supplied_occurrence` and the bounded uncertainty", playbook)

    def test_sentry_uses_existing_source_access_receipt(self):
        from datetime import datetime
        from scripts.source_access_receipt import blocked_receipt

        for code in ("OPERATION_UNAVAILABLE", "PERMISSION_DENIED", "UNAUTHENTICATED", "NOT_FOUND", "TIMEOUT"):
            with self.subTest(code=code):
                receipt = blocked_receipt("Sentry", "ISSUE-1", "issue_event_read", code,
                                          "2026-10-13T12:00:00Z",
                                          observed_at=datetime.fromisoformat("2026-10-13T12:00:30+00:00"))
                self.assertEqual(receipt["status"], "blocked")
                self.assertEqual(receipt["reason"], "required_source_unavailable")
                self.assertEqual(receipt["worker_activation_attempts"], 0)
                self.assertIsNone(receipt["artifact_root"])

    def test_jira_source_access_receipt_blocks_techops_before_run_initialization(self):
        from datetime import datetime
        from scripts.source_access_receipt import blocked_receipt

        receipt = blocked_receipt("Jira", "ECHO-2806", "getJiraIssue", "OPERATION_UNAVAILABLE",
                                  "2026-10-21T16:00:00Z",
                                  observed_at=datetime.fromisoformat("2026-10-21T16:01:00+00:00"))
        self.assertEqual(receipt["status"], "blocked")
        self.assertEqual(receipt["reason"], "required_source_unavailable")
        self.assertEqual(receipt["worker_activation_attempts"], 0)
        self.assertIsNone(receipt["artifact_root"])

    def test_cross_layer_links_resolve_to_existing_headings(self):
        for name in ("contracts/workflow_execution.md", "providers/codex.md", "integrations/jira.md"):
            source = ROOT / name
            for target, anchor in re.findall(r"\]\(([^()]+\.md)#([^()]+)\)", source.read_text()):
                destination = (source.parent / target).resolve()
                if destination == source:
                    continue
                headings = re.findall(r"^#+ (.+)$", destination.read_text(), re.M)
                slugs = {re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-") for heading in headings}
                with self.subTest(source=name, link=f"{target}#{anchor}"):
                    self.assertIn(anchor, slugs)


if __name__ == "__main__":
    unittest.main()
