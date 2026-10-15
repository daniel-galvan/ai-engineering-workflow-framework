"""Shared playbook identities and terminal disposition policy."""

import re

PROMPT_TEMPLATES = {
    "feature_delivery": "feature_delivery_run_prompt.md",
    "sentry_issue_remediation": "sentry_issue_run_prompt.md",
    "technical_spike": "technical_spike_run_prompt.md",
    "techops_issue_remediation": "techops_issue_run_prompt.md",
    "vulnerability_investigation": "vulnerability_issue_run_prompt.md",
}

FEATURE_ASSESSMENT_DISPOSITIONS = {
    "awaiting_input": {"Not ready for implementation"},
    "ready_for_implementation": {"Ready for implementation", "Ready with explicit follow-ups"},
}

TECHNICAL_SPIKE_DISPOSITIONS = {
    "execute technical spike": {
        "Question answered": "solved",
        "Partially answered": "partially_solved",
        "Inconclusive": "partially_solved",
    },
    "review technical spike": {
        "Accepted": "solved",
        "Changes required": "partially_solved",
        "Inconclusive": "partially_solved",
    },
}

NO_ACTIVE_HANDLES = re.compile(
    r"^(?:none|0)(?:\s+(?:observed|confirmed) after close request)?$", re.IGNORECASE
)
