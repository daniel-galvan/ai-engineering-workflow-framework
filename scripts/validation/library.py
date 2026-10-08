"""Run library checks in their established fail-fast order."""

from .common import (
    ROOT,
    fail,
)
from .contracts import (
    validate_coordinator_authority,
    validate_execution_contracts,
    validate_source_contracts,
)
from .finalization import (
    validate_closure_definitions,
    validate_final_documenter_rules,
    validate_finalization_definitions,
)
from .markdown import (
    markdown_errors,
)
from .playbooks import (
    validate_bounded_vulnerability_route,
    validate_feature_asset_gate,
    validate_playbook_metadata,
    validate_scenario_readiness,
    validate_sentry_execution,
    validate_technical_spike_definition,
    validate_worker_graphs,
)
from .provider_policy import (
    validate_provider_policy,
    validate_runtime_mapping,
    validate_skill_mappings,
)
from .roles import (
    validate_activation_roles,
    validate_coordination_and_delivery_roles,
    validate_delivery_roles,
    validate_documenter_role,
    validate_repository_readiness_role,
    validate_sentry_roles,
    validate_technical_roles,
)
from .templates import (
    validate_evaluation_and_provenance,
    validate_evaluation_timing_and_toolchain,
    validate_planning_and_evaluation_templates,
    validate_portable_handoff_template,
    validate_run_prompt_basics,
    validate_sentry_prompt_and_isolation,
    validate_work_record_template,
)
try:
    from framework_manifest import manifest_errors
except ModuleNotFoundError:
    from scripts.framework_manifest import manifest_errors
try:
    from playbook_catalog import catalog_errors
except ModuleNotFoundError:
    from scripts.playbook_catalog import catalog_errors


def validate_library() -> None:
    for error in manifest_errors(ROOT):
        fail(error)
    for error in catalog_errors(ROOT):
        fail(error)
    for error in markdown_errors(ROOT):
        fail(error)

    agent_configs = validate_provider_policy()
    validate_activation_roles(agent_configs)
    validate_playbook_metadata()
    validate_run_prompt_basics()
    validate_worker_graphs()
    validate_source_contracts()
    validate_scenario_readiness()
    validate_feature_asset_gate()
    validate_technical_spike_definition()
    validate_repository_readiness_role(agent_configs)
    validate_execution_contracts()
    validate_finalization_definitions()
    validate_runtime_mapping()
    validate_closure_definitions()
    validate_work_record_template()
    validate_delivery_roles()
    validate_planning_and_evaluation_templates()
    validate_documenter_role()
    validate_bounded_vulnerability_route()
    validate_evaluation_timing_and_toolchain()
    validate_coordination_and_delivery_roles()
    validate_sentry_execution()
    validate_sentry_roles()
    validate_sentry_prompt_and_isolation()
    validate_final_documenter_rules()
    validate_technical_roles()
    validate_coordinator_authority()
    validate_evaluation_and_provenance()
    validate_portable_handoff_template()
    validate_skill_mappings()
