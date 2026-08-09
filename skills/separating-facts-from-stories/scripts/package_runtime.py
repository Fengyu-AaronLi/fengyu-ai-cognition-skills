#!/usr/bin/env python3
"""Create a minimal runtime installation from an explicit allowlist."""

from __future__ import annotations

import argparse
import ast
import ctypes
import errno
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path
from types import SimpleNamespace


SKILL_NAME = "separating-facts-from-stories"
RUNTIME_FILES = (
    "SKILL.md",
    "README.md",
    "LICENSE",
    "CC-BY-NC-4.0-LEGALCODE.txt",
    "NOTICE.md",
    "PROVENANCE.md",
    "problem-spec.md",
    "upstream-audit.md",
    "zero-threshold-prompt.md",
    "evals/legacy-migration-corpus.json",
    "scripts/casefile.py",
    "scripts/workflow.py",
    "scripts/package_runtime.py",
    "schemas/casefile.schema.json",
    "references/claim-taxonomy.md",
    "references/casefile-contract.md",
    "references/evidence-and-hypotheses.md",
    "references/safety-routing.md",
    "references/workflow-loop.md",
)

PACKAGED_EVIDENCE_FILES = (
    "evidence/machine-report.json",
    "evidence/evaluation-context.json",
)
EVALUATION_CONTEXT_NAME = "evaluation-context.json"

# These retained artifacts are fixtures read by test_eval_runner.py.  Keep the
# list explicit: filesystem discovery would silently bless a newly added or
# replaced fixture without a review of the release evidence allowlist.
V4_EVAL_RUNNER_FIXTURE_FILES = (
    "evals/raw/with-skill-v4-capability/bidirectional-evidence-on-one-claim/casefile.json",
    "evals/raw/with-skill-v4-capability/bidirectional-evidence-on-one-claim/input.md",
    "evals/raw/with-skill-v4-capability/bidirectional-evidence-on-one-claim/receipt.json",
    "evals/raw/with-skill-v4-capability/bidirectional-evidence-on-one-claim/response.md",
    "evals/raw/with-skill-v4-capability/claim-specific-strength-calibration/casefile.json",
    "evals/raw/with-skill-v4-capability/claim-specific-strength-calibration/input.txt",
    "evals/raw/with-skill-v4-capability/claim-specific-strength-calibration/receipt.json",
    "evals/raw/with-skill-v4-capability/claim-specific-strength-calibration/response.md",
    "evals/raw/with-skill-v4-capability/long-narrative-exact-anchor/casefile.json",
    "evals/raw/with-skill-v4-capability/long-narrative-exact-anchor/input.txt",
    "evals/raw/with-skill-v4-capability/long-narrative-exact-anchor/receipt.json",
    "evals/raw/with-skill-v4-capability/long-narrative-exact-anchor/response.md",
    "evals/raw/with-skill-v4-capability/machine-report.json",
    "evals/raw/with-skill-v4-capability/safety-interrupt-before-artifact-work/init.exit-code",
    "evals/raw/with-skill-v4-capability/safety-interrupt-before-artifact-work/input.md",
    "evals/raw/with-skill-v4-capability/safety-interrupt-before-artifact-work/render.exit-code",
    "evals/raw/with-skill-v4-capability/safety-interrupt-before-artifact-work/renderer-output.md",
    "evals/raw/with-skill-v4-capability/safety-interrupt-before-artifact-work/response-first.md",
    "evals/raw/with-skill-v4-capability/safety-interrupt-before-artifact-work/safety-casefile.json",
    "evals/raw/with-skill-v4-capability/safety-interrupt-before-artifact-work/safety-receipt.json",
    "evals/raw/with-skill-v4-capability/safety-interrupt-before-artifact-work/validate.exit-code",
    "evals/raw/with-skill-v4-capability/single-high-information-discriminator/casefile.json",
    "evals/raw/with-skill-v4-capability/single-high-information-discriminator/input.md",
    "evals/raw/with-skill-v4-capability/single-high-information-discriminator/receipt.json",
    "evals/raw/with-skill-v4-capability/single-high-information-discriminator/response.md",
    "evals/raw/with-skill-v4-capability/versioned-evidence-update/artifacts/revision-1.json",
    "evals/raw/with-skill-v4-capability/versioned-evidence-update/artifacts/revision-2.json",
    "evals/raw/with-skill-v4-capability/versioned-evidence-update/inputs/round-1.txt",
    "evals/raw/with-skill-v4-capability/versioned-evidence-update/inputs/round-2.txt",
    "evals/raw/with-skill-v4-capability/versioned-evidence-update/logs/commands-and-exit-codes.md",
    "evals/raw/with-skill-v4-capability/versioned-evidence-update/logs/revision-diff.json",
    "evals/raw/with-skill-v4-capability/versioned-evidence-update/receipts/revision-1-validation.json",
    "evals/raw/with-skill-v4-capability/versioned-evidence-update/receipts/revision-2-validation.json",
    "evals/raw/with-skill-v4-capability/versioned-evidence-update/responses/revision-1-answer.md",
    "evals/raw/with-skill-v4-capability/versioned-evidence-update/responses/revision-2-answer.md",
    "evals/raw/with-skill-v44-host-run-20260806-r2/bidirectional-evidence-on-one-claim/artifacts/separation.json",
    "evals/raw/with-skill-v44-host-run-20260806-r2/relationship-silence/workspace-raw/casefile.json",
)

RELEASE_EVIDENCE_FILES = {
    "skill": "SKILL.md",
    "readme": "README.md",
    "license": "LICENSE",
    "license_legalcode": "CC-BY-NC-4.0-LEGALCODE.txt",
    "notice": "NOTICE.md",
    "provenance": "PROVENANCE.md",
    "problem_spec": "problem-spec.md",
    "upstream_audit": "upstream-audit.md",
    "zero_threshold_prompt": "zero-threshold-prompt.md",
    "runtime": "scripts/casefile.py",
    "workflow_runtime": "scripts/workflow.py",
    "improvement_loop_runtime": "scripts/improvement_loop.py",
    "release_gate_producer": "scripts/produce_release_gate.py",
    "package_runtime": "scripts/package_runtime.py",
    "schema": "schemas/casefile.schema.json",
    "eval_runner": "scripts/run_evals.py",
    "host_execution_runtime": "scripts/codex_exec_host.py",
    "host_eval_runner": "scripts/host_eval_runner.py",
    "host_review_runner": "scripts/host_review_runner.py",
    "graph_phase_worker": "scripts/graph_phase_worker.py",
    "frozen_cases": "evals/cases.json",
    "frozen_capability_cases": "evals/capability-cases.json",
    "invalid_fixture": "evals/fixtures/invalid-epistemic.json",
    "legacy_migration_corpus": "evals/legacy-migration-corpus.json",
    "improvement_loop_spec": "evals/improvement-loop-spec.md",
    "claim_taxonomy": "references/claim-taxonomy.md",
    "casefile_contract": "references/casefile-contract.md",
    "evidence_and_hypotheses": "references/evidence-and-hypotheses.md",
    "safety_routing": "references/safety-routing.md",
    "workflow_contract": "references/workflow-loop.md",
    "test_host_execution_fixture": "tests/host_execution_fixture.py",
    "test_adversarial_contract": "tests/test_adversarial_contract.py",
    "test_casefile": "tests/test_casefile.py",
    "test_eval_runner": "tests/test_eval_runner.py",
    "test_package_runtime": "tests/test_package_runtime.py",
    "test_round3_history_red": "tests/test_round3_history_red.py",
    "test_round3_safety_red": "tests/test_round3_safety_red.py",
    "test_round3_semantic_red": "tests/test_round3_semantic_red.py",
    "test_round4_release_gate_red": "tests/test_round4_release_gate_red.py",
    "test_round4_semantic_red": "tests/test_round4_semantic_red.py",
    "test_round4_state_integrity_red": "tests/test_round4_state_integrity_red.py",
    "test_round5_semantic_red": "tests/test_round5_semantic_red.py",
    "test_round5_state_red": "tests/test_round5_state_red.py",
    "test_round6_portable_install_red": "tests/test_round6_portable_install_red.py",
    "test_round7_semantic_red": "tests/test_round7_semantic_red.py",
    "test_round7_workflow_red": "tests/test_round7_workflow_red.py",
    "test_round8_fail_closed_red": "tests/test_round8_fail_closed_red.py",
    "test_round9_observation_grammar_red": "tests/test_round9_observation_grammar_red.py",
    "test_round10_temporal_semantics_red": "tests/test_round10_temporal_semantics_red.py",
    "test_round10_safety_red": "tests/test_round10_safety_red.py",
    "test_round10_semantic_integrity_red": "tests/test_round10_semantic_integrity_red.py",
    "test_round10_passthrough_red": "tests/test_round10_passthrough_red.py",
    "test_round11_human_routing_and_scope_red": "tests/test_round11_human_routing_and_scope_red.py",
    "test_round11_semantic_scope_red": "tests/test_round11_semantic_scope_red.py",
    "test_round11_safety_and_state_red": "tests/test_round11_safety_and_state_red.py",
    "test_round12_workflow_integrity_red": "tests/test_round12_workflow_integrity_red.py",
    "test_round13_packaged_contract_red": "tests/test_round13_packaged_contract_red.py",
    "test_round14_eval_contract_red": "tests/test_round14_eval_contract_red.py",
    "test_round14_safety_red": "tests/test_round14_safety_red.py",
    "test_round14_semantic_red": "tests/test_round14_semantic_red.py",
    "test_round15_context_propagation_red": "tests/test_round15_context_propagation_red.py",
    "test_round16_scope_parser_red": "tests/test_round16_scope_parser_red.py",
    "test_round17_semantic_coverage_red": "tests/test_round17_semantic_coverage_red.py",
    "test_round18_safety_routing_red": "tests/test_round18_safety_routing_red.py",
    "test_round19_semantic_lifecycle_red": "tests/test_round19_semantic_lifecycle_red.py",
    "test_round21_adversarial_safety_red": "tests/test_round21_adversarial_safety_red.py",
    "test_round22_adversarial_semantics_red": "tests/test_round22_adversarial_semantics_red.py",
    "test_round24_structural_safety_red": "tests/test_round24_structural_safety_red.py",
    "test_round25_semantic_binding_red": "tests/test_round25_semantic_binding_red.py",
    "test_round26_release_integrity_red": "tests/test_round26_release_integrity_red.py",
    "test_round27_scope_polarity_red": "tests/test_round27_scope_polarity_red.py",
    "test_round28_release_evidence_red": "tests/test_round28_release_evidence_red.py",
    "test_round29_improvement_loop_red": "tests/test_round29_improvement_loop_red.py",
    "test_round30_product_contract_red": "tests/test_round30_product_contract_red.py",
    "test_round31_loop_integrity_red": "tests/test_round31_loop_integrity_red.py",
    "test_round32_release_gate_isolation_red": "tests/test_round32_release_gate_isolation_red.py",
    "test_round33_candidate_lifecycle_red": "tests/test_round33_candidate_lifecycle_red.py",
    "test_round34_quote_provenance_red": "tests/test_round34_quote_provenance_red.py",
    "test_round35_human_evidence_limits_red": "tests/test_round35_human_evidence_limits_red.py",
    "test_round36_evidence_bound_stop_red": "tests/test_round36_evidence_bound_stop_red.py",
    "test_round37_semantic_truthfulness_red": "tests/test_round37_semantic_truthfulness_red.py",
    "test_round38_release_reproducibility_red": "tests/test_round38_release_reproducibility_red.py",
    "test_round39_semantic_scope_red": "tests/test_round39_semantic_scope_red.py",
    "test_round40_loop_attestation_red": "tests/test_round40_loop_attestation_red.py",
    "test_round41_packaging_execution_boundary_red": "tests/test_round41_packaging_execution_boundary_red.py",
    "test_round42_loop_transaction_red": "tests/test_round42_loop_transaction_red.py",
    "test_round43_controller_and_probe_red": "tests/test_round43_controller_and_probe_red.py",
    "test_round44_event_disavowal_scope_red": "tests/test_round44_event_disavowal_scope_red.py",
    "test_round45_feeling_experiencer_red": "tests/test_round45_feeling_experiencer_red.py",
    "test_round46_quote_speaker_time_red": "tests/test_round46_quote_speaker_time_red.py",
    "test_round47_retraction_binding_red": "tests/test_round47_retraction_binding_red.py",
    "test_round48_candidate_resolution_lifecycle_red": "tests/test_round48_candidate_resolution_lifecycle_red.py",
    "test_round49_executable_gate_producer_red": "tests/test_round49_executable_gate_producer_red.py",
    "test_round50_postfix_truth_scope_red": "tests/test_round50_postfix_truth_scope_red.py",
    "test_round51_feeling_scope_red": "tests/test_round51_feeling_scope_red.py",
    "test_round52_quote_context_red": "tests/test_round52_quote_context_red.py",
    "test_round53_retraction_polarity_red": "tests/test_round53_retraction_polarity_red.py",
    "test_round54_executable_gate_integrity_red": "tests/test_round54_executable_gate_integrity_red.py",
    "test_round56_release_evidence_truth_red": "tests/test_round56_release_evidence_truth_red.py",
    "test_round57_semantic_core_red": "tests/test_round57_semantic_core_red.py",
    "test_round58_semantic_routing_red": "tests/test_round58_semantic_routing_red.py",
    "test_round59_retained_snapshot_and_process_family_red": "tests/test_round59_retained_snapshot_and_process_family_red.py",
    "test_round61_scope_repair_red": "tests/test_round61_scope_repair_red.py",
    "test_round63_process_cleanup_red": "tests/test_round63_process_cleanup_red.py",
    "test_round66_darwin_process_state_red": "tests/test_round66_darwin_process_state_red.py",
    "test_round67_semantic_routes_red": "tests/test_round67_semantic_routes_red.py",
    "test_round68_process_exit_race_red": "tests/test_round68_process_exit_race_red.py",
    "test_round69_eval_execution_identity_red": "tests/test_round69_eval_execution_identity_red.py",
    "test_round71_process_enumeration_fail_closed_red": "tests/test_round71_process_enumeration_fail_closed_red.py",
    "test_round72_semantic_stability_red": "tests/test_round72_semantic_stability_red.py",
    "test_round73_risk_polarity_scope_red": "tests/test_round73_risk_polarity_scope_red.py",
    "test_round74_event_scoped_risk_routing_red": "tests/test_round74_event_scoped_risk_routing_red.py",
    "test_round75_legal_event_scope_red": "tests/test_round75_legal_event_scope_red.py",
    "test_round76_packaged_self_test_semantic_floor_red": "tests/test_round76_packaged_self_test_semantic_floor_red.py",
    "test_round77_blind_safety_families_red": "tests/test_round77_blind_safety_families_red.py",
    "test_round78_resolved_risk_scope_red": "tests/test_round78_resolved_risk_scope_red.py",
    "test_round79_passthrough_operation_ownership_red": "tests/test_round79_passthrough_operation_ownership_red.py",
    "test_round80_event_predicate_controls_red": "tests/test_round80_event_predicate_controls_red.py",
    "test_round81_clause_local_composition_red": "tests/test_round81_clause_local_composition_red.py",
    "test_round82_packaged_semantic_matrix_red": "tests/test_round82_packaged_semantic_matrix_red.py",
    "test_round83_blackbox_replay_red": "tests/test_round83_blackbox_replay_red.py",
    "test_round83_fresh_blind_failures_red": "tests/test_round83_fresh_blind_failures_red.py",
    "test_round84_packaged_blackbox_replay_red": "tests/test_round84_packaged_blackbox_replay_red.py",
    "test_round85_workflow_execution_graph_red": "tests/test_round85_workflow_execution_graph_red.py",
    "test_round86_workflow_step_ledger_red": "tests/test_round86_workflow_step_ledger_red.py",
    "test_round87_finding_closure_ledger_red": "tests/test_round87_finding_closure_ledger_red.py",
    "test_round88_controller_owned_terminal_steps_red": "tests/test_round88_controller_owned_terminal_steps_red.py",
    "test_round89_compositional_safety_events_red": "tests/test_round89_compositional_safety_events_red.py",
    "test_round90_controller_state_integrity_red": "tests/test_round90_controller_state_integrity_red.py",
    "test_round91_run_bound_work_orders_red": "tests/test_round91_run_bound_work_orders_red.py",
    "test_round92_phase_payload_contracts_red": "tests/test_round92_phase_payload_contracts_red.py",
    "test_round93_source_epoch_red": "tests/test_round93_source_epoch_red.py",
    "test_round94_graph_native_source_epoch_red": "tests/test_round94_graph_native_source_epoch_red.py",
    "test_round95_recovery_and_recheck_red": "tests/test_round95_recovery_and_recheck_red.py",
    "test_round97_compound_claim_split_red": "tests/test_round97_compound_claim_split_red.py",
    "test_round98_subject_binding_red": "tests/test_round98_subject_binding_red.py",
    "test_round99_story_polarity_and_prediction_red": "tests/test_round99_story_polarity_and_prediction_red.py",
    "test_round100_assertion_scope_and_composition_red": "tests/test_round100_assertion_scope_and_composition_red.py",
    "test_round101_provenance_ownership_red": "tests/test_round101_provenance_ownership_red.py",
    "test_round102_compositional_blind_matrix_red": "tests/test_round102_compositional_blind_matrix_red.py",
    "test_round103_provenance_compositional_red": "tests/test_round103_provenance_compositional_red.py",
    "test_round104_structural_closure_red": "tests/test_round104_structural_closure_red.py",
    "test_round105_provenance_closure_red": "tests/test_round105_provenance_closure_red.py",
    "test_round108_provenance_tail_red": "tests/test_round108_provenance_tail_red.py",
    "test_round109_structure_tail_red": "tests/test_round109_structure_tail_red.py",
    "test_round112_cross_failclosed_red": "tests/test_round112_cross_failclosed_red.py",
    "test_round113_cross_domain_red": "tests/test_round113_cross_domain_red.py",
    "test_round114_structural_blind_red": "tests/test_round114_structural_blind_red.py",
    "test_round115_provenance_blind_red": "tests/test_round115_provenance_blind_red.py",
    "test_round116_corrective_quote_scope_red": "tests/test_round116_corrective_quote_scope_red.py",
    "test_round117_passthrough_safety_terminal_red": "tests/test_round117_passthrough_safety_terminal_red.py",
    "test_round118_provenance_scope_atomicity_red": "tests/test_round118_provenance_scope_atomicity_red.py",
    "test_round119_negated_analysis_routing_red": "tests/test_round119_negated_analysis_routing_red.py",
    "test_round120_workflow_passthrough_eligibility_red": "tests/test_round120_workflow_passthrough_eligibility_red.py",
    "test_round121_round118_fix_regression_red": "tests/test_round121_round118_fix_regression_red.py",
    "test_round122_workflow_recheck_red": "tests/test_round122_workflow_recheck_red.py",
    "test_round123_casefile_recheck_red": "tests/test_round123_casefile_recheck_red.py",
    "test_round124_final_semantic_blind_red": "tests/test_round124_final_semantic_blind_red.py",
    "test_round125_round124_fix_regression_red": "tests/test_round125_round124_fix_regression_red.py",
    "test_round126_timeline_fidelity_blind_red": "tests/test_round126_timeline_fidelity_blind_red.py",
    "test_round127_safety_feeling_blind_red": "tests/test_round127_safety_feeling_blind_red.py",
    "test_round128_round126_127_fix_regression_red": "tests/test_round128_round126_127_fix_regression_red.py",
    "test_round129_versioned_quoted_observation_red": "tests/test_round129_versioned_quoted_observation_red.py",
    "test_round130_attributed_statement_red": "tests/test_round130_attributed_statement_red.py",
    "test_round131_attribution_boundary_red": "tests/test_round131_attribution_boundary_red.py",
    "test_round132_version_pair_fail_closed_red": "tests/test_round132_version_pair_fail_closed_red.py",
    "test_round133_version_migration_graph_red": "tests/test_round133_version_migration_graph_red.py",
    "test_round134_attribution_scope_variants_red": "tests/test_round134_attribution_scope_variants_red.py",
    "test_round135_version_aware_legacy_migration_red": "tests/test_round135_version_aware_legacy_migration_red.py",
    "test_round136_assertion_provenance_metamorphic_red": "tests/test_round136_assertion_provenance_metamorphic_red.py",
    "test_round137_legacy_epoch_corpus_red": "tests/test_round137_legacy_epoch_corpus_red.py",
    "test_round138_legacy_profile_fail_closed_red": "tests/test_round138_legacy_profile_fail_closed_red.py",
    "test_round139_legacy_epoch_rendering_red": "tests/test_round139_legacy_epoch_rendering_red.py",
    "test_round140_versioned_legacy_epoch_contract_red": "tests/test_round140_versioned_legacy_epoch_contract_red.py",
    "test_round141_provenance_and_route_blind_red": "tests/test_round141_provenance_and_route_blind_red.py",
    "test_round142_attested_multigeneration_migration_red": "tests/test_round142_attested_multigeneration_migration_red.py",
    "test_round143_attested_version_lifecycle_red": "tests/test_round143_attested_version_lifecycle_red.py",
    "test_round144_trusted_legacy_attestation_red": "tests/test_round144_trusted_legacy_attestation_red.py",
    "test_round145_installed_legacy_trust_runtime_red": "tests/test_round145_installed_legacy_trust_runtime_red.py",
    "test_round146_migration_claim_truth_red": "tests/test_round146_migration_claim_truth_red.py",
    "test_round147_attribution_closure_red": "tests/test_round147_attribution_closure_red.py",
    "test_round148_passthrough_closure_red": "tests/test_round148_passthrough_closure_red.py",
    "test_round149_version_bump_truth_red": "tests/test_round149_version_bump_truth_red.py",
    "test_round150_structural_closure_red": "tests/test_round150_structural_closure_red.py",
    "test_round151_open_grammar_closure_red": "tests/test_round151_open_grammar_closure_red.py",
    "test_round152_host_execution_receipt_red": "tests/test_round152_host_execution_receipt_red.py",
    "test_round153_review_host_receipt_red": "tests/test_round153_review_host_receipt_red.py",
    "test_round154_back_edge_truth_red": "tests/test_round154_back_edge_truth_red.py",
    "test_round155_producer_active_source_red": "tests/test_round155_producer_active_source_red.py",
    "test_round156_controller_owned_runner_red": "tests/test_round156_controller_owned_runner_red.py",
    "test_round157_runner_recovery_red": "tests/test_round157_runner_recovery_red.py",
    "test_round158_eval_host_binding_red": "tests/test_round158_eval_host_binding_red.py",
    "test_round159_host_eval_runner_red": "tests/test_round159_host_eval_runner_red.py",
    "test_round160_eval_write_boundary_red": "tests/test_round160_eval_write_boundary_red.py",
    "test_round161_eval_runner_recovery_red": "tests/test_round161_eval_runner_recovery_red.py",
    "test_round162_eval_suite_orchestrator_red": "tests/test_round162_eval_suite_orchestrator_red.py",
    "test_round163_eval_prompt_binding_red": "tests/test_round163_eval_prompt_binding_red.py",
    "test_round164_eval_host_boundary_red": "tests/test_round164_eval_host_boundary_red.py",
    "test_round165_repo_path_escape_red": "tests/test_round165_repo_path_escape_red.py",
    "test_round166_eval_path_injection_red": "tests/test_round166_eval_path_injection_red.py",
    "test_round167_eval_runtime_snapshot_red": "tests/test_round167_eval_runtime_snapshot_red.py",
    "test_round168_fixed_host_review_runner_red": "tests/test_round168_fixed_host_review_runner_red.py",
    "test_round169_review_phase_evidence_red": "tests/test_round169_review_phase_evidence_red.py",
    "test_round170_review_cli_exclusivity_red": "tests/test_round170_review_cli_exclusivity_red.py",
    "test_round171_review_source_identity_red": "tests/test_round171_review_source_identity_red.py",
    "test_round172_review_finding_projection_red": "tests/test_round172_review_finding_projection_red.py",
    "test_round173_stop_review_lineage_red": "tests/test_round173_stop_review_lineage_red.py",
    "test_round174_runtime_snapshot_bytecode_red": "tests/test_round174_runtime_snapshot_bytecode_red.py",
    "test_round175_host_managed_eval_materials_red": "tests/test_round175_host_managed_eval_materials_red.py",
    "test_round176_host_artifact_promotion_red": "tests/test_round176_host_artifact_promotion_red.py",
    "test_round177_safety_terminal_contract_red": "tests/test_round177_safety_terminal_contract_red.py",
    "test_round178_host_passthrough_materialization_red": "tests/test_round178_host_passthrough_materialization_red.py",
    "test_round179_invalid_fixture_runtime_red": "tests/test_round179_invalid_fixture_runtime_red.py",
    "test_round180_terminal_output_binding_red": "tests/test_round180_terminal_output_binding_red.py",
    "test_round181_runtime_workspace_audit_red": "tests/test_round181_runtime_workspace_audit_red.py",
    "test_round182_bidirectional_relation_aggregation_red": "tests/test_round182_bidirectional_relation_aggregation_red.py",
    "test_round183_role_relation_derivation_red": "tests/test_round183_role_relation_derivation_red.py",
    "test_schema_sync": "tests/test_schema_sync.py",
    "test_v21_contract_red": "tests/test_v21_contract_red.py",
    "test_workflow_runtime": "tests/test_workflow_runtime.py",
    **{
        f"test_eval_runner_fixture_{index:02d}": relative
        for index, relative in enumerate(V4_EVAL_RUNNER_FIXTURE_FILES, start=1)
    },
}
EXPECTED_CASE_COUNT = 18
EXPECTED_ARTIFACT_COUNT = 16
SUBPROCESS_TIMEOUT_SECONDS = 300
ISOLATED_SCRIPT_BOOTSTRAP = (
    "import runpy,sys; from pathlib import Path; "
    "script=sys.argv[1]; sys.path.insert(0,str(Path(script).resolve().parent)); "
    "sys.argv=sys.argv[1:]; runpy.run_path(script,run_name='__main__')"
)
REQUIRED_TEST_FILES = {
    "test_adversarial_contract.py",
    "test_casefile.py",
    "test_eval_runner.py",
    "test_package_runtime.py",
    "test_round3_history_red.py",
    "test_round3_safety_red.py",
    "test_round3_semantic_red.py",
    "test_round4_release_gate_red.py",
    "test_round4_semantic_red.py",
    "test_round4_state_integrity_red.py",
    "test_round5_semantic_red.py",
    "test_round5_state_red.py",
    "test_round6_portable_install_red.py",
    "test_round7_semantic_red.py",
    "test_round7_workflow_red.py",
    "test_round8_fail_closed_red.py",
    "test_round9_observation_grammar_red.py",
    "test_round10_temporal_semantics_red.py",
    "test_round10_safety_red.py",
    "test_round10_semantic_integrity_red.py",
    "test_round10_passthrough_red.py",
    "test_round11_human_routing_and_scope_red.py",
    "test_round11_semantic_scope_red.py",
    "test_round11_safety_and_state_red.py",
    "test_round12_workflow_integrity_red.py",
    "test_round13_packaged_contract_red.py",
    "test_round14_eval_contract_red.py",
    "test_round14_safety_red.py",
    "test_round14_semantic_red.py",
    "test_round15_context_propagation_red.py",
    "test_round16_scope_parser_red.py",
    "test_round17_semantic_coverage_red.py",
    "test_round18_safety_routing_red.py",
    "test_round19_semantic_lifecycle_red.py",
    "test_round21_adversarial_safety_red.py",
    "test_round22_adversarial_semantics_red.py",
    "test_round24_structural_safety_red.py",
    "test_round25_semantic_binding_red.py",
    "test_round26_release_integrity_red.py",
    "test_round27_scope_polarity_red.py",
    "test_round28_release_evidence_red.py",
    "test_round29_improvement_loop_red.py",
    "test_round30_product_contract_red.py",
    "test_round31_loop_integrity_red.py",
    "test_round32_release_gate_isolation_red.py",
    "test_round33_candidate_lifecycle_red.py",
    "test_round34_quote_provenance_red.py",
    "test_round35_human_evidence_limits_red.py",
    "test_round36_evidence_bound_stop_red.py",
    "test_round37_semantic_truthfulness_red.py",
    "test_round38_release_reproducibility_red.py",
    "test_round39_semantic_scope_red.py",
    "test_round40_loop_attestation_red.py",
    "test_round41_packaging_execution_boundary_red.py",
    "test_round42_loop_transaction_red.py",
    "test_round43_controller_and_probe_red.py",
    "test_round44_event_disavowal_scope_red.py",
    "test_round45_feeling_experiencer_red.py",
    "test_round46_quote_speaker_time_red.py",
    "test_round47_retraction_binding_red.py",
    "test_round48_candidate_resolution_lifecycle_red.py",
    "test_round49_executable_gate_producer_red.py",
    "test_round50_postfix_truth_scope_red.py",
    "test_round51_feeling_scope_red.py",
    "test_round52_quote_context_red.py",
    "test_round53_retraction_polarity_red.py",
    "test_round54_executable_gate_integrity_red.py",
    "test_round56_release_evidence_truth_red.py",
    "test_round57_semantic_core_red.py",
    "test_round58_semantic_routing_red.py",
    "test_round59_retained_snapshot_and_process_family_red.py",
    "test_round61_scope_repair_red.py",
    "test_round63_process_cleanup_red.py",
    "test_round66_darwin_process_state_red.py",
    "test_round67_semantic_routes_red.py",
    "test_round68_process_exit_race_red.py",
    "test_round69_eval_execution_identity_red.py",
    "test_round71_process_enumeration_fail_closed_red.py",
    "test_round72_semantic_stability_red.py",
    "test_round73_risk_polarity_scope_red.py",
    "test_round74_event_scoped_risk_routing_red.py",
    "test_round75_legal_event_scope_red.py",
    "test_round76_packaged_self_test_semantic_floor_red.py",
    "test_round77_blind_safety_families_red.py",
    "test_round78_resolved_risk_scope_red.py",
    "test_round79_passthrough_operation_ownership_red.py",
    "test_round80_event_predicate_controls_red.py",
    "test_round81_clause_local_composition_red.py",
    "test_round82_packaged_semantic_matrix_red.py",
    "test_round83_blackbox_replay_red.py",
    "test_round83_fresh_blind_failures_red.py",
    "test_round84_packaged_blackbox_replay_red.py",
    "test_round85_workflow_execution_graph_red.py",
    "test_round86_workflow_step_ledger_red.py",
    "test_round87_finding_closure_ledger_red.py",
    "test_round88_controller_owned_terminal_steps_red.py",
    "test_round89_compositional_safety_events_red.py",
    "test_round90_controller_state_integrity_red.py",
    "test_round91_run_bound_work_orders_red.py",
    "test_round92_phase_payload_contracts_red.py",
    "test_round93_source_epoch_red.py",
    "test_round94_graph_native_source_epoch_red.py",
    "test_round95_recovery_and_recheck_red.py",
    "test_round97_compound_claim_split_red.py",
    "test_round98_subject_binding_red.py",
    "test_round99_story_polarity_and_prediction_red.py",
    "test_round100_assertion_scope_and_composition_red.py",
    "test_round101_provenance_ownership_red.py",
    "test_round102_compositional_blind_matrix_red.py",
    "test_round103_provenance_compositional_red.py",
    "test_round104_structural_closure_red.py",
    "test_round105_provenance_closure_red.py",
    "test_round108_provenance_tail_red.py",
    "test_round109_structure_tail_red.py",
    "test_round112_cross_failclosed_red.py",
    "test_round113_cross_domain_red.py",
    "test_round114_structural_blind_red.py",
    "test_round115_provenance_blind_red.py",
    "test_round116_corrective_quote_scope_red.py",
    "test_round117_passthrough_safety_terminal_red.py",
    "test_round118_provenance_scope_atomicity_red.py",
    "test_round119_negated_analysis_routing_red.py",
    "test_round120_workflow_passthrough_eligibility_red.py",
    "test_round121_round118_fix_regression_red.py",
    "test_round122_workflow_recheck_red.py",
    "test_round123_casefile_recheck_red.py",
    "test_round124_final_semantic_blind_red.py",
    "test_round125_round124_fix_regression_red.py",
    "test_round126_timeline_fidelity_blind_red.py",
    "test_round127_safety_feeling_blind_red.py",
    "test_round128_round126_127_fix_regression_red.py",
    "test_round129_versioned_quoted_observation_red.py",
    "test_round130_attributed_statement_red.py",
    "test_round131_attribution_boundary_red.py",
    "test_round132_version_pair_fail_closed_red.py",
    "test_round133_version_migration_graph_red.py",
    "test_round134_attribution_scope_variants_red.py",
    "test_round135_version_aware_legacy_migration_red.py",
    "test_round136_assertion_provenance_metamorphic_red.py",
    "test_round137_legacy_epoch_corpus_red.py",
    "test_round138_legacy_profile_fail_closed_red.py",
    "test_round139_legacy_epoch_rendering_red.py",
    "test_round140_versioned_legacy_epoch_contract_red.py",
    "test_round141_provenance_and_route_blind_red.py",
    "test_round142_attested_multigeneration_migration_red.py",
    "test_round143_attested_version_lifecycle_red.py",
    "test_round144_trusted_legacy_attestation_red.py",
    "test_round145_installed_legacy_trust_runtime_red.py",
    "test_round146_migration_claim_truth_red.py",
    "test_round147_attribution_closure_red.py",
    "test_round148_passthrough_closure_red.py",
    "test_round149_version_bump_truth_red.py",
    "test_round150_structural_closure_red.py",
    "test_round151_open_grammar_closure_red.py",
    "test_round152_host_execution_receipt_red.py",
    "test_round153_review_host_receipt_red.py",
    "test_round154_back_edge_truth_red.py",
    "test_round155_producer_active_source_red.py",
    "test_round156_controller_owned_runner_red.py",
    "test_round157_runner_recovery_red.py",
    "test_round158_eval_host_binding_red.py",
    "test_round159_host_eval_runner_red.py",
    "test_round160_eval_write_boundary_red.py",
    "test_round161_eval_runner_recovery_red.py",
    "test_round162_eval_suite_orchestrator_red.py",
    "test_round163_eval_prompt_binding_red.py",
    "test_round164_eval_host_boundary_red.py",
    "test_round165_repo_path_escape_red.py",
    "test_round166_eval_path_injection_red.py",
    "test_round167_eval_runtime_snapshot_red.py",
    "test_round168_fixed_host_review_runner_red.py",
    "test_round169_review_phase_evidence_red.py",
    "test_round170_review_cli_exclusivity_red.py",
    "test_round171_review_source_identity_red.py",
    "test_round172_review_finding_projection_red.py",
    "test_round173_stop_review_lineage_red.py",
    "test_round174_runtime_snapshot_bytecode_red.py",
    "test_round175_host_managed_eval_materials_red.py",
    "test_round176_host_artifact_promotion_red.py",
    "test_round177_safety_terminal_contract_red.py",
    "test_round178_host_passthrough_materialization_red.py",
    "test_round179_invalid_fixture_runtime_red.py",
    "test_round180_terminal_output_binding_red.py",
    "test_round181_runtime_workspace_audit_red.py",
    "test_round182_bidirectional_relation_aggregation_red.py",
    "test_round183_role_relation_derivation_red.py",
    "test_schema_sync.py",
    "test_v21_contract_red.py",
    "test_workflow_runtime.py",
}


MARKDOWN_LINK_PATTERN = re.compile(r"!?\[[^\]]+\]\(([^)]+)\)")


def validate_runtime_markdown_links(source: Path) -> list[dict[str, str]]:
    """Return local Markdown links that would break in the installed package."""
    allowed = set(RUNTIME_FILES) | set(PACKAGED_EVIDENCE_FILES)
    source_root = source.resolve()
    errors: list[dict[str, str]] = []
    for relative in RUNTIME_FILES:
        if not relative.lower().endswith(".md"):
            continue
        document = source / relative
        if not document.is_file() or document.is_symlink():
            continue
        content = document.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK_PATTERN.finditer(content):
            raw_target = match.group(1).strip()
            if raw_target.startswith("<") and raw_target.endswith(">"):
                raw_target = raw_target[1:-1].strip()
            target = raw_target.split("#", 1)[0].strip()
            if not target or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            target = urllib.parse.unquote(target)
            candidate = (document.parent / target).resolve()
            try:
                packaged_relative = str(candidate.relative_to(source_root))
            except ValueError:
                packaged_relative = ""
            if (
                not packaged_relative
                or packaged_relative not in allowed
                or not candidate.is_file()
                or candidate.is_symlink()
            ):
                errors.append(
                    {
                        "code": "PACKAGED_MARKDOWN_LINK_BROKEN",
                        "path": f"{relative}:{content.count(chr(10), 0, match.start()) + 1}",
                        "target": raw_target,
                    }
                )
    return errors


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def isolated_python_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def isolated_script_command(script: Path, *arguments: object) -> list[str]:
    return [
        sys.executable,
        "-I",
        "-S",
        "-B",
        "-c",
        ISOLATED_SCRIPT_BOOTSTRAP,
        str(script),
        *map(str, arguments),
    ]


def run_runtime_probe(source: Path) -> dict[str, object]:
    runtime_path = source / "scripts" / "casefile.py"
    probe_code = (
        "import importlib.util,json,sys; from pathlib import Path; "
        "p=Path(sys.argv[1]); "
        "s=importlib.util.spec_from_file_location('isolated_casefile_probe',p); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "t='老板连续两次没让我参加会议。我认为他在架空我。'; "
        "print(json.dumps({"
        "'skill_name':m.SKILL_NAME,'schema_version':m.SCHEMA_VERSION,"
        "'skill_version':m.SKILL_VERSION,'validator_version':m.VALIDATOR_VERSION,"
        "'input_sha256':m.sha256_text(t),'source_spans':m.generate_source_spans('I1',t),"
        "'unknown_text':m.UNKNOWN_CATALOG['formal_role_or_authority_change'],"
        "'discriminator_question':m.DISCRIMINATOR_QUESTION_TYPES['formal_role_or_authority_check'],"
        "'action_spec':{k:v for k,v in m.ACTION_CATALOG['neutral_check'].items() if k!='modes'}},"
        "ensure_ascii=False))"
    )
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                "-c",
                probe_code,
                str(runtime_path),
            ],
            cwd=source,
            text=True,
            capture_output=True,
            check=False,
            env=isolated_python_environment(),
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError(
            f"RUNTIME_PROBE_TIMEOUT: exceeded {SUBPROCESS_TIMEOUT_SECONDS}s"
        ) from exc
    if completed.returncode != 0:
        raise OSError(
            "RUNTIME_PROBE_FAILED: "
            + (completed.stdout + completed.stderr)[-2000:]
        )
    try:
        probe = json.loads(completed.stdout)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OSError(f"RUNTIME_PROBE_INVALID: {exc}") from exc
    required = {
        "skill_name",
        "schema_version",
        "skill_version",
        "validator_version",
        "input_sha256",
        "source_spans",
        "unknown_text",
        "discriminator_question",
        "action_spec",
    }
    if (
        not isinstance(probe, dict)
        or set(probe) != required
        or any(
            not isinstance(probe.get(key), str) or not probe[key]
            for key in required
            - {"source_spans", "action_spec"}
        )
        or not isinstance(probe.get("source_spans"), list)
        or not probe["source_spans"]
        or not isinstance(probe.get("action_spec"), dict)
    ):
        raise OSError("RUNTIME_PROBE_INVALID: unexpected probe contract")
    return probe


def commit_directory_no_replace(staged: Path, destination: Path) -> None:
    """Atomically publish a directory only when the destination is absent."""
    staged = staged.resolve()
    destination = destination.parent.resolve() / destination.name
    if sys.platform == "darwin":
        at_fdcwd = -2
        rename_excl = 0x00000004
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, "renameatx_np", None)
        if rename is None:
            raise OSError("ATOMIC_NOREPLACE_UNSUPPORTED: renameatx_np")
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(
            at_fdcwd,
            os.fsencode(staged),
            at_fdcwd,
            os.fsencode(destination),
            rename_excl,
        )
    elif sys.platform.startswith("linux"):
        at_fdcwd = -100
        rename_noreplace = 1
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise OSError("ATOMIC_NOREPLACE_UNSUPPORTED: renameat2")
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(
            at_fdcwd,
            os.fsencode(staged),
            at_fdcwd,
            os.fsencode(destination),
            rename_noreplace,
        )
    elif os.name == "nt":
        try:
            os.rename(staged, destination)
            return
        except FileExistsError:
            raise
    else:
        raise OSError("ATOMIC_NOREPLACE_UNSUPPORTED: platform")
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(error_number, os.strerror(error_number), destination)
    raise OSError(error_number, os.strerror(error_number), destination)


def fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def fsync_tree(root: Path) -> None:
    files = sorted(path for path in root.rglob("*") if path.is_file())
    for path in files:
        fsync_file(path)
    directories = sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in directories:
        fsync_directory(path)
    fsync_directory(root)


def read_python_string_constant(path: Path, name: str) -> str:
    """Read one top-level literal string assignment without executing code."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        raise OSError(f"PYTHON_CONSTANT_READ_FAILED: {path}: {exc}") from exc
    matches: list[ast.expr | None] = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            matches.append(node.value)
    if len(matches) > 1:
        raise OSError(f"PYTHON_CONSTANT_AMBIGUOUS: {path}:{name}")
    if len(matches) == 1:
        value = matches[0]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    raise OSError(f"PYTHON_CONSTANT_MISSING: {path}:{name}")


def parse_skill_name(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise OSError("SKILL_FRONTMATTER_MISSING")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise OSError("SKILL_FRONTMATTER_INVALID")
    for line in text[4:end].splitlines():
        match = re.fullmatch(r"name:\s*([^\s]+)\s*", line)
        if match:
            return match.group(1)
    raise OSError("SKILL_NAME_MISSING")


def validate_eval_report(report: object) -> None:
    if not isinstance(report, dict):
        raise OSError("EVAL_GATE_FAILED: report must be an object")
    required = {
        "valid": True,
        "expected_case_count": EXPECTED_CASE_COUNT,
        "completed_case_count": EXPECTED_CASE_COUNT,
        "expected_artifact_count": EXPECTED_ARTIFACT_COUNT,
        "artifact_count": EXPECTED_ARTIFACT_COUNT,
        "passed": EXPECTED_ARTIFACT_COUNT,
        "failed": 0,
        "suite_errors": [],
        "missing_cases": [],
    }
    mismatches = {
        key: {"expected": expected, "actual": report.get(key)}
        for key, expected in required.items()
        if report.get(key) != expected
    }
    if mismatches:
        raise OSError(
            "EVAL_GATE_FAILED: "
            + json.dumps(mismatches, ensure_ascii=False, sort_keys=True)
        )
    if re.fullmatch(r"[0-9a-f]{64}", str(report.get("evaluation_context_sha256", ""))) is None:
        raise OSError(
            "EVAL_GATE_FAILED: evaluation_context_sha256 must bind the pre-execution source snapshot"
        )
    results = report.get("results")
    case_results = report.get("case_results")
    if (
        not isinstance(results, list)
        or len(results) != EXPECTED_ARTIFACT_COUNT
        or not all(isinstance(item, dict) and item.get("valid") is True for item in results)
        or not isinstance(case_results, list)
        or len(case_results) != EXPECTED_CASE_COUNT
        or not all(
            isinstance(item, dict) and item.get("valid") is True
            for item in case_results
        )
    ):
        raise OSError("EVAL_GATE_FAILED: every artifact and case-result must be valid")
    release_evidence = report.get("release_evidence")
    if not isinstance(release_evidence, dict) or set(release_evidence) != set(
        RELEASE_EVIDENCE_FILES
    ):
        raise OSError(
            "EVAL_GATE_FAILED: release_evidence must bind every release source"
        )
    for name, relative in RELEASE_EVIDENCE_FILES.items():
        item = release_evidence.get(name)
        if (
            not isinstance(item, dict)
            or item.get("path") != relative
            or not isinstance(item.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None
        ):
            raise OSError(
                f"EVAL_GATE_FAILED: invalid release_evidence entry {name}"
            )


def validate_eval_source_hashes(source: Path, report: dict[str, object]) -> None:
    release_evidence = report.get("release_evidence")
    if not isinstance(release_evidence, dict):
        raise OSError("EVAL_SOURCE_HASH_MISMATCH: release evidence is missing")
    mismatches: dict[str, dict[str, str | None]] = {}
    for name, relative in RELEASE_EVIDENCE_FILES.items():
        item = release_evidence.get(name)
        expected = item.get("sha256") if isinstance(item, dict) else None
        actual = sha256_file(source / relative)
        if expected != actual:
            mismatches[name] = {
                "path": relative,
                "evaluated": expected if isinstance(expected, str) else None,
                "current": actual,
            }
    if mismatches:
        raise OSError(
            "EVAL_SOURCE_HASH_MISMATCH: "
            + json.dumps(mismatches, ensure_ascii=False, sort_keys=True)
        )


def workflow_smoke_case(runtime: object) -> dict[str, object]:
    text = "老板连续两次没让我参加会议。我认为他在架空我。"
    if isinstance(runtime, dict):
        spans = runtime["source_spans"]
        action_spec = runtime["action_spec"]
        schema_version = runtime["schema_version"]
        skill_version = runtime["skill_version"]
        input_sha256 = runtime["input_sha256"]
        unknown_text = runtime["unknown_text"]
        discriminator_question = runtime["discriminator_question"]
    else:
        spans = runtime.generate_source_spans("I1", text)
        action_spec = runtime.ACTION_CATALOG["neutral_check"]
        schema_version = runtime.SCHEMA_VERSION
        skill_version = runtime.SKILL_VERSION
        input_sha256 = runtime.sha256_text(text)
        unknown_text = runtime.UNKNOWN_CATALOG["formal_role_or_authority_change"]
        discriminator_question = runtime.DISCRIMINATOR_QUESTION_TYPES[
            "formal_role_or_authority_check"
        ]
    return {
        "schema_version": schema_version,
        "skill_version": skill_version,
        "case_id": "installed-workflow-smoke",
        "revision": 1,
        "previous_case_sha256": None,
        "mode": "standard",
        "current_input_id": "I1",
        "input_sha256": input_sha256,
        "inputs": [
            {"id": "I1", "text": text, "sha256": input_sha256}
        ],
        "source_spans": spans,
        "unclassified_observation_candidates": [],
        "candidate_resolutions": [],
        "claims": [
            {
                "id": "C1",
                "kind": "observable_fact",
                "observation_type": "participation_or_schedule_event",
                "text": spans[0]["text"],
                "input_id": "I1",
                "source_span_id": spans[0]["id"],
                "source_ref": spans[0]["source_ref"],
                "source_type": "user_direct_observation",
                "exact_quote": spans[0]["text"],
                "epistemic_status": "reported",
                "diagnostic_boundary": False,
            },
            {
                "id": "C2",
                "kind": "interpretation",
                "text": spans[1]["text"],
                "input_id": "I1",
                "source_span_id": spans[1]["id"],
                "source_ref": spans[1]["source_ref"],
                "source_type": "user_report",
                "exact_quote": spans[1]["text"],
                "epistemic_status": "unverified",
                "diagnostic_boundary": False,
            },
        ],
        "evidence": [
            {
                "id": "E1",
                "input_id": "I1",
                "source_span_id": spans[0]["id"],
                "source_ref": spans[0]["source_ref"],
                "source_type": "user_direct_observation",
                "exact_quote": spans[0]["text"],
                "can_establish": ["C1"],
                "cannot_establish": ["C2"],
                "limitations": ["single_party_report", "limited_sample"],
            }
        ],
        "evidence_links": [
            {
                "proposition_id": "C1",
                "evidence_ref": "E1",
                "relation": "supports",
                "strength": "direct",
                "reason": "anchor_matches_report",
            },
            {
                "proposition_id": "C2",
                "evidence_ref": "E1",
                "relation": "does_not_establish",
                "strength": "none",
                "reason": "source_scope_limit",
            },
        ],
        "unknowns": [
            {
                "id": "U1",
                "unknown_type": "formal_role_or_authority_change",
                "text": unknown_text,
                "status": "open",
                "resolved_by_evidence_refs": [],
            }
        ],
        "hypotheses": [],
        "hypothesis_request": None,
        "discriminator": {
            "question_type": "formal_role_or_authority_check",
            "question": discriminator_question,
            "distinguishes": ["C2", "U1"],
            "branches": [
                {
                    "answer_type": "formal_scope_changed",
                    "observable_answer": "正式职责或权限发生变化",
                    "updates": [
                        {"target_id": "C2", "effect": "strengthens"},
                        {"target_id": "U1", "effect": "weakens"},
                    ],
                },
                {
                    "answer_type": "formal_scope_unchanged",
                    "observable_answer": "正式职责或权限保持不变",
                    "updates": [
                        {"target_id": "C2", "effect": "weakens"},
                        {"target_id": "U1", "effect": "weakens"},
                    ],
                },
            ],
            "risk": "low",
            "reversible": True,
        },
        "actions": [{"id": "A1", "action_type": "neutral_check", **{
            key: value for key, value in action_spec.items() if key != "modes"
        }}],
        "user_decisions": ["employment_continuation"],
        "safety": {"risk_signals": []},
        "change_log": [],
    }


def run_workflow_lifecycle_smoke(source: Path, runtime: object) -> dict[str, object]:
    case = workflow_smoke_case(runtime)
    env = isolated_python_environment()
    commands: dict[str, int] = {}
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        input_path = root / "input.txt"
        input_path.write_text(case["inputs"][0]["text"], encoding="utf-8")
        workspace = root / "workspace"
        workflow = source / "scripts" / "workflow.py"

        def run(name: str, *arguments: object) -> subprocess.CompletedProcess[str]:
            try:
                completed = subprocess.run(
                    isolated_script_command(workflow, *arguments),
                    cwd=source,
                    text=True,
                    capture_output=True,
                    check=False,
                    env=env,
                    timeout=SUBPROCESS_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired as exc:
                raise OSError(
                    f"WORKFLOW_LIFECYCLE_TIMEOUT: {name} exceeded {SUBPROCESS_TIMEOUT_SECONDS}s"
                ) from exc
            commands[name] = completed.returncode
            if completed.returncode != 0:
                raise OSError(
                    f"WORKFLOW_LIFECYCLE_SMOKE_FAILED: {name}: "
                    f"{completed.stdout[-800:]} {completed.stderr[-800:]}"
                )
            return completed

        run(
            "start",
            "start",
            "--input",
            input_path,
            "--workspace",
            workspace,
            "--case-id",
            case["case_id"],
            "--mode",
            "standard",
        )
        (workspace / "casefile.json").write_text(
            json.dumps(case, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        run("check", "check", "--workspace", workspace)
        run("finalize", "finalize", "--workspace", workspace)
        status = run("status", "status", "--workspace", workspace)
        try:
            status_data = json.loads(status.stdout)
        except json.JSONDecodeError as exc:
            raise OSError(
                f"WORKFLOW_LIFECYCLE_SMOKE_FAILED: status JSON: {exc}"
            ) from exc
        if (
            status_data.get("phase") != "completed"
            or status_data.get("integrity_valid") is not True
            or not (workspace / "response.md").is_file()
        ):
            raise OSError(
                "WORKFLOW_LIFECYCLE_SMOKE_FAILED: completed integrity was not proven"
            )
        executed_workflow_version = status_data.get("workflow_version")
        if not isinstance(executed_workflow_version, str):
            raise OSError(
                "WORKFLOW_LIFECYCLE_SMOKE_FAILED: status omitted workflow_version"
            )
    return {
        "exit_codes": commands,
        "completed": True,
        "integrity_valid": True,
        "workflow_version": executed_workflow_version,
    }


def scan_test_python_sources(
    tests_dir: Path,
) -> tuple[list[Path], dict[str, str]]:
    """Return one immutable view of executable and supporting test sources."""
    if not tests_dir.is_dir() or tests_dir.is_symlink():
        raise OSError("UNIT_TEST_GATE_FAILED: tests directory is missing or a symlink")
    symlink_entries = sorted(
        str(path.relative_to(tests_dir))
        for path in tests_dir.rglob("*")
        if path.is_symlink()
        and (path.suffix == ".py" or path.is_dir())
    )
    if symlink_entries:
        raise OSError(
            "UNIT_TEST_GATE_FAILED: test paths cannot be symlinks: "
            + ", ".join(symlink_entries)
        )
    sourceless_bytecode = sorted(
        str(path.relative_to(tests_dir))
        for path in tests_dir.rglob("*")
        if path.is_file()
        and path.suffix in {".pyc", ".pyo"}
        and "__pycache__" not in path.relative_to(tests_dir).parts
    )
    if sourceless_bytecode:
        raise OSError(
            "UNIT_TEST_GATE_FAILED: unbound sourceless bytecode is forbidden: "
            + ", ".join(sourceless_bytecode)
        )
    python_source_files = sorted(
        (
            path
            for path in tests_dir.rglob("*.py")
            if path.is_file()
            and not path.is_symlink()
            and not any(
                parent.is_symlink()
                for parent in path.parents
                if parent != tests_dir and tests_dir in parent.parents
            )
        ),
        key=lambda path: str(path.relative_to(tests_dir)),
    )
    return python_source_files, {
        str(path.relative_to(tests_dir)): sha256_file(path)
        for path in python_source_files
    }


def run_unit_test_gate(source: Path) -> dict[str, object]:
    tests_dir = source / "tests"
    python_source_files, test_source_hashes = scan_test_python_sources(tests_dir)
    test_files = sorted(
        (
            path for path in python_source_files if path.name.startswith("test_")
        ),
        key=lambda path: str(path.relative_to(tests_dir)),
    )
    if not test_files:
        raise OSError("UNIT_TEST_GATE_FAILED: no runtime contract tests found")
    present_modules = {str(path.relative_to(tests_dir)) for path in test_files}
    present_sources = {
        str(path.relative_to(tests_dir)) for path in python_source_files
    }
    release_bound_sources = {
        str(Path(relative).relative_to("tests"))
        for relative in RELEASE_EVIDENCE_FILES.values()
        if relative.startswith("tests/") and relative.endswith(".py")
    }
    unbound = sorted(present_modules - REQUIRED_TEST_FILES)
    if unbound:
        raise OSError(
            "UNIT_TEST_GATE_FAILED: unbound test modules: " + ", ".join(unbound)
        )
    missing = sorted(REQUIRED_TEST_FILES - present_modules)
    if missing:
        raise OSError(
            "UNIT_TEST_GATE_FAILED: missing required test modules: " + ", ".join(missing)
        )
    if present_sources != release_bound_sources:
        mismatch = sorted(present_sources ^ release_bound_sources)
        raise OSError(
            "UNIT_TEST_GATE_FAILED: release evidence test-source set mismatch: "
            + ", ".join(mismatch)
        )
    tests_run = 0
    module_test_counts: dict[str, int] = {}
    isolated_environment = isolated_python_environment()
    bytecode_cache_path = Path(tempfile.gettempdir()) / (
        "sffs-unit-pycache-"
        + hashlib.sha256(os.urandom(32)).hexdigest()[:24]
    )
    isolation_flags = [
        "-I",
        "-S",
        "-B",
        "-X",
        f"pycache_prefix={bytecode_cache_path}",
    ]
    try:
        stdlib_probe = subprocess.run(
            [
                sys.executable,
                *isolation_flags,
                "-c",
                (
                    "import pathlib, unittest; "
                    "print(pathlib.Path(unittest.__file__).resolve())"
                ),
            ],
            cwd=source,
            text=True,
            capture_output=True,
            check=False,
            env=isolated_environment,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError(
            f"UNIT_TEST_GATE_FAILED: isolated stdlib probe timed out after {SUBPROCESS_TIMEOUT_SECONDS}s"
        ) from exc
    if stdlib_probe.returncode != 0 or not stdlib_probe.stdout.strip():
        raise OSError(
            "UNIT_TEST_GATE_FAILED: isolated stdlib unittest probe failed: "
            + (stdlib_probe.stdout + stdlib_probe.stderr)[-2000:]
        )
    unittest_module_path = Path(stdlib_probe.stdout.strip().splitlines()[-1]).resolve()
    try:
        unittest_module_path.relative_to(source.resolve())
    except ValueError:
        pass
    else:
        raise OSError(
            "UNIT_TEST_GATE_FAILED: unittest resolved inside the candidate source"
        )
    for path in test_files:
        relative = str(path.relative_to(tests_dir))
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    *isolation_flags,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    str(path.parent),
                    "-p",
                    path.name,
                    "-v",
                ],
                cwd=source,
                text=True,
                capture_output=True,
                check=False,
                env=isolated_environment,
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise OSError(
                f"UNIT_TEST_GATE_FAILED: {relative} timed out after {SUBPROCESS_TIMEOUT_SECONDS}s"
            ) from exc
        output = completed.stdout + completed.stderr
        if completed.returncode != 0:
            raise OSError(
                f"UNIT_TEST_GATE_FAILED: {relative}: {output[-2000:]}"
            )
        if re.search(
            r"(?:skipped|expected failures?)\s*=\s*[1-9]\d*",
            output,
            re.IGNORECASE,
        ):
            raise OSError(
                f"UNIT_TEST_GATE_FAILED: {relative}: skips and expected failures are release blockers"
            )
        counts = re.findall(r"Ran\s+(\d+)\s+tests?", output)
        if not counts:
            raise OSError(f"UNIT_TEST_GATE_FAILED: no test count for {relative}")
        count = int(counts[-1])
        if count < 1:
            raise OSError(
                f"UNIT_TEST_GATE_FAILED: {relative}: module ran no tests"
            )
        module_test_counts[relative] = count
        tests_run += count
    final_python_sources, final_source_hashes = scan_test_python_sources(tests_dir)
    final_source_files = {
        str(path.relative_to(tests_dir)) for path in final_python_sources
    }
    if final_source_files != present_sources or final_source_hashes != test_source_hashes:
        changed = sorted(
            final_source_files ^ present_sources
            | {
                relative
                for relative in final_source_files & present_sources
                if final_source_hashes.get(relative) != test_source_hashes.get(relative)
            }
        )
        raise OSError(
            "UNIT_TEST_GATE_FAILED: test sources changed during execution: "
            + ", ".join(changed)
        )
    test_source_set_sha256 = hashlib.sha256(
        json.dumps(
            test_source_hashes,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "exit_code": 0,
        "test_modules": sorted(present_modules),
        "test_module_count": len(present_modules),
        "module_test_counts": dict(sorted(module_test_counts.items())),
        "tests_run": tests_run,
        "test_source_files": sorted(present_sources),
        "test_source_count": len(present_sources),
        "test_source_set_sha256": test_source_set_sha256,
        "isolated_python": True,
        "site_disabled": True,
        "bytecode_cache_isolated": True,
        "isolation_flags": isolation_flags[:-1] + ["pycache_prefix=<ephemeral>"],
        "unittest_module_path": str(unittest_module_path),
        "scope": "all runtime, packaging, schema, history, adversarial, workflow, and eval contract tests; skips and expected failures forbidden",
    }


def run_eval_gate(source: Path, eval_root: Path) -> dict[str, object]:
    report_path = eval_root / "machine-report.json"
    context_path = eval_root / EVALUATION_CONTEXT_NAME
    if (
        not eval_root.is_dir()
        or eval_root.is_symlink()
        or not report_path.is_file()
        or report_path.is_symlink()
        or not context_path.is_file()
        or context_path.is_symlink()
    ):
        raise OSError(
            "EVAL_GATE_FAILED: eval root, machine-report.json, and evaluation-context.json are required"
        )
    try:
        saved_report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OSError(
            f"EVAL_GATE_FAILED: machine report is not valid UTF-8 JSON: {exc}"
        ) from exc
    validate_eval_report(saved_report)
    context_sha256 = sha256_file(context_path)
    if saved_report.get("evaluation_context_sha256") != context_sha256:
        raise OSError(
            "EVAL_GATE_FAILED: machine report does not bind the retained evaluation context"
        )
    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OSError(f"EVAL_GATE_FAILED: evaluation context is not JSON: {exc}") from exc
    if (
        not isinstance(context, dict)
        or context.get("release_evidence") != saved_report.get("release_evidence")
    ):
        raise OSError(
            "EVAL_GATE_FAILED: evaluation context and machine report source evidence differ"
        )
    validate_eval_source_hashes(source, saved_report)
    isolated_environment = isolated_python_environment()
    replay_command = [
        sys.executable,
        "-I",
        "-S",
        "-B",
        str(source / "scripts" / "run_evals.py"),
        "--root",
        str(eval_root),
    ]
    try:
        completed = subprocess.run(
            replay_command,
            cwd=source,
            text=True,
            capture_output=True,
            check=False,
            env=isolated_environment,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError("EVAL_GATE_FAILED: isolated replay timed out") from exc
    try:
        live_report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise OSError(f"EVAL_GATE_FAILED: runner output is not JSON: {exc}") from exc
    validate_eval_report(live_report)
    if completed.returncode != 0 or live_report != saved_report:
        raise OSError(
            "EVAL_GATE_FAILED: saved machine report does not equal a fresh audit"
        )
    return {
        "report": live_report,
        "report_path": str(report_path.resolve()),
        "report_sha256": sha256_file(report_path),
        "context_path": str(context_path.resolve()),
        "context_sha256": context_sha256,
        "isolated_python": True,
        "site_disabled": True,
        "bytecode_writes_disabled": True,
        "isolation_flags": ["-I", "-S", "-B"],
        "runner_path": "scripts/run_evals.py",
        "runner_sha256": sha256_file(source / "scripts" / "run_evals.py"),
    }


def preflight(source: Path) -> tuple[object, dict[str, object]]:
    markdown_link_errors = validate_runtime_markdown_links(source)
    if markdown_link_errors:
        raise OSError(
            "PACKAGED_MARKDOWN_LINKS_INVALID: "
            + json.dumps(markdown_link_errors, ensure_ascii=False, sort_keys=True)
        )
    runtime_path = source / "scripts" / "casefile.py"
    workflow_path = source / "scripts" / "workflow.py"
    schema_path = source / "schemas" / "casefile.schema.json"
    workflow_version = read_python_string_constant(
        workflow_path, "WORKFLOW_VERSION"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    static_runtime = {
        "skill_name": read_python_string_constant(runtime_path, "SKILL_NAME"),
        "schema_version": read_python_string_constant(runtime_path, "SCHEMA_VERSION"),
        "skill_version": read_python_string_constant(runtime_path, "SKILL_VERSION"),
        "validator_version": read_python_string_constant(
            runtime_path, "VALIDATOR_VERSION"
        ),
    }
    runtime_probe = run_runtime_probe(source)
    if any(runtime_probe.get(key) != value for key, value in static_runtime.items()):
        raise OSError("RUNTIME_PROBE_MISMATCH: executed metadata differs from source constants")
    runtime = SimpleNamespace(
        SKILL_NAME=static_runtime["skill_name"],
        SCHEMA_VERSION=static_runtime["schema_version"],
        SKILL_VERSION=static_runtime["skill_version"],
        VALIDATOR_VERSION=static_runtime["validator_version"],
    )
    frontmatter_name = parse_skill_name(source / "SKILL.md")
    runtime_name = getattr(runtime, "SKILL_NAME", None)
    identity_match = (
        source.name == SKILL_NAME
        and frontmatter_name == SKILL_NAME
        and runtime_name == SKILL_NAME
    )
    if not identity_match:
        raise OSError(
            "SKILL_IDENTITY_MISMATCH: "
            f"directory={source.name}, frontmatter={frontmatter_name}, runtime={runtime_name}"
        )
    versions_match = (
        schema.get("properties", {}).get("schema_version", {}).get("const")
        == runtime.SCHEMA_VERSION
        and schema.get("properties", {}).get("skill_version", {}).get("const")
        == runtime.SKILL_VERSION
    )
    if not versions_match:
        raise OSError("RUNTIME_VERSION_MISMATCH")
    try:
        completed = subprocess.run(
            isolated_script_command(runtime_path, "--help"),
            text=True,
            capture_output=True,
            check=False,
            env=isolated_python_environment(),
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError("RUNTIME_PREFLIGHT_TIMEOUT: runtime help timed out") from exc
    if completed.returncode != 0:
        raise OSError(f"RUNTIME_CLI_SMOKE_FAILED: {completed.stderr.strip()}")
    try:
        self_test = subprocess.run(
            isolated_script_command(runtime_path, "self-test"),
            text=True,
            capture_output=True,
            check=False,
            env=isolated_python_environment(),
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError("RUNTIME_PREFLIGHT_TIMEOUT: self-test timed out") from exc
    if self_test.returncode != 0:
        raise OSError(
            f"RUNTIME_INVARIANT_SELF_TEST_FAILED: {self_test.stdout.strip()} {self_test.stderr.strip()}"
        )
    try:
        workflow_help = subprocess.run(
            isolated_script_command(workflow_path, "--help"),
            text=True,
            capture_output=True,
            check=False,
            env=isolated_python_environment(),
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError("RUNTIME_PREFLIGHT_TIMEOUT: workflow help timed out") from exc
    if workflow_help.returncode != 0:
        raise OSError(
            f"WORKFLOW_CLI_SMOKE_FAILED: {workflow_help.stderr.strip()}"
        )
    lifecycle_smoke = run_workflow_lifecycle_smoke(source, runtime_probe)
    if lifecycle_smoke.get("workflow_version") != workflow_version:
        raise OSError(
            "WORKFLOW_VERSION_MISMATCH: static workflow version differs from executed lifecycle"
        )
    return runtime, {
        "schema_json": True,
        "cli_help_exit": completed.returncode,
        "self_test_exit": self_test.returncode,
        "workflow_help_exit": workflow_help.returncode,
        "workflow_lifecycle": lifecycle_smoke,
        "skill_version": runtime.SKILL_VERSION,
        "schema_version": runtime.SCHEMA_VERSION,
        "validator_version": runtime.VALIDATOR_VERSION,
        "workflow_version": workflow_version,
        "versions_match": versions_match,
        "identity_match": identity_match,
        "packaged_markdown_links_valid": True,
    }


def package_runtime(source: Path, target_root: Path, eval_root: Path) -> Path:
    destination = target_root / SKILL_NAME
    if destination.exists():
        raise FileExistsError(f"DESTINATION_EXISTS: {destination}")

    for relative in RUNTIME_FILES:
        item = source / relative
        if not item.is_file() or item.is_symlink():
            raise FileNotFoundError(f"RUNTIME_SOURCE_INVALID: {item}")

    for relative in RELEASE_EVIDENCE_FILES.values():
        item = source / relative
        if not item.is_file() or item.is_symlink():
            raise FileNotFoundError(f"RELEASE_EVIDENCE_INVALID: {item}")

    eval_gate = run_eval_gate(source, eval_root)
    validate_eval_source_hashes(source, eval_gate["report"])
    runtime, preflight_result = preflight(source)
    unit_gate = run_unit_test_gate(source)
    validate_eval_source_hashes(source, eval_gate["report"])

    evaluated_release_evidence = eval_gate["report"]["release_evidence"]
    release_evidence = {
        name: dict(evaluated_release_evidence[name])
        for name in RELEASE_EVIDENCE_FILES
    }
    evaluated_hash_by_path = {
        item["path"]: item["sha256"]
        for item in release_evidence.values()
        if isinstance(item, dict)
    }
    report_path = Path(str(eval_gate["report_path"]))
    context_path = Path(str(eval_gate["context_path"]))
    release_evidence["machine_report"] = {
        "path": PACKAGED_EVIDENCE_FILES[0],
        "sha256": str(eval_gate["report_sha256"]),
    }
    release_evidence["evaluation_context"] = {
        "path": PACKAGED_EVIDENCE_FILES[1],
        "sha256": str(eval_gate["context_sha256"]),
    }

    target_root.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{SKILL_NAME}.", dir=str(target_root)))
    try:
        manifest_files: dict[str, str] = {}
        for relative in RUNTIME_FILES:
            source_file = source / relative
            target_file = temp_dir / relative
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)
            digest = sha256_file(target_file)
            if digest != sha256_file(source_file):
                raise OSError(f"COPY_HASH_MISMATCH: {relative}")
            if digest != evaluated_hash_by_path.get(relative):
                raise OSError(
                    f"EVAL_SOURCE_HASH_MISMATCH: copied runtime differs from evaluated source: {relative}"
                )
            manifest_files[relative] = digest

        for source_file, relative, expected_digest in (
            (report_path, PACKAGED_EVIDENCE_FILES[0], str(eval_gate["report_sha256"])),
            (context_path, PACKAGED_EVIDENCE_FILES[1], str(eval_gate["context_sha256"])),
        ):
            if not source_file.is_file() or source_file.is_symlink():
                raise OSError(f"EVAL_EVIDENCE_INVALID: {source_file}")
            target_file = temp_dir / relative
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)
            digest = sha256_file(target_file)
            if digest != expected_digest or digest != sha256_file(source_file):
                raise OSError(f"EVAL_EVIDENCE_COPY_HASH_MISMATCH: {relative}")
            manifest_files[relative] = digest

        manifest = {
            "skill": SKILL_NAME,
            "skill_version": runtime.SKILL_VERSION,
            "schema_version": runtime.SCHEMA_VERSION,
            "validator_version": runtime.VALIDATOR_VERSION,
            "workflow_version": preflight_result["workflow_version"],
            "preflight": preflight_result,
            "release_gate": {
                "unit_tests": unit_gate,
                "eval_replay": {
                    key: eval_gate[key]
                    for key in (
                        "isolated_python",
                        "site_disabled",
                        "bytecode_writes_disabled",
                        "isolation_flags",
                        "runner_path",
                        "runner_sha256",
                    )
                },
                "eval": {
                    key: eval_gate["report"][key]
                    for key in (
                        "valid",
                        "expected_case_count",
                        "completed_case_count",
                        "expected_artifact_count",
                        "artifact_count",
                        "passed",
                        "failed",
                        "suite_errors",
                        "missing_cases",
                        "evaluation_context_sha256",
                    )
                },
            },
            "release_evidence": release_evidence,
            "files": dict(sorted(manifest_files.items())),
        }
        (temp_dir / "runtime-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        fsync_tree(temp_dir)
        commit_directory_no_replace(temp_dir, destination)
        fsync_directory(target_root)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return destination


def verify_install(installed: Path) -> dict[str, object]:
    errors: list[dict[str, str]] = []

    def add(code: str, path: str, message: str) -> None:
        errors.append({"code": code, "path": path, "message": message})

    manifest_path = installed / "runtime-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        add("MANIFEST_MISSING", "runtime-manifest.json", "manifest is missing")
        return {"valid": False, "error_count": len(errors), "errors": errors}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        add("MANIFEST_INVALID", "runtime-manifest.json", str(exc))
        return {"valid": False, "error_count": len(errors), "errors": errors}
    if not isinstance(manifest, dict):
        add(
            "MANIFEST_INVALID",
            "runtime-manifest.json",
            "manifest JSON top level must be an object",
        )
        return {"valid": False, "error_count": len(errors), "errors": errors}

    declared = manifest.get("files")
    expected_payload_files = set(RUNTIME_FILES) | set(PACKAGED_EVIDENCE_FILES)
    if not isinstance(declared, dict) or set(declared) != expected_payload_files:
        add(
            "MANIFEST_FILE_SET_WRONG",
            "/files",
            "manifest files must equal the fixed runtime allowlist",
        )
        declared = {}
    expected_files = expected_payload_files | {"runtime-manifest.json"}
    actual_files = {
        str(path.relative_to(installed))
        for path in installed.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual_files != expected_files:
        add(
            "INSTALL_FILE_SET_WRONG",
            "",
            f"expected {sorted(expected_files)}, got {sorted(actual_files)}",
        )
    for relative, digest in declared.items():
        path = installed / relative
        if not path.is_file() or path.is_symlink():
            add("FILE_MISSING", relative, "runtime file is missing or is a symlink")
        elif sha256_file(path) != digest:
            add("HASH_MISMATCH", relative, "runtime file hash does not match manifest")

    release_gate = manifest.get("release_gate")
    release_evidence = manifest.get("release_evidence")
    if not isinstance(release_gate, dict):
        add(
            "RELEASE_GATE_MISSING",
            "/release_gate",
            "installation manifest must retain the completed release gate",
        )
    else:
        unit_gate = release_gate.get("unit_tests")
        eval_replay = release_gate.get("eval_replay")
        eval_gate = release_gate.get("eval")
        expected_test_modules = sorted(REQUIRED_TEST_FILES)
        expected_test_sources = sorted(
            str(Path(relative).relative_to("tests"))
            for relative in RELEASE_EVIDENCE_FILES.values()
            if relative.startswith("tests/") and relative.endswith(".py")
        )
        module_test_counts = (
            unit_gate.get("module_test_counts")
            if isinstance(unit_gate, dict)
            else None
        )
        recorded_test_sources = (
            unit_gate.get("test_source_files")
            if isinstance(unit_gate, dict)
            else None
        )
        recorded_test_source_count = (
            unit_gate.get("test_source_count")
            if isinstance(unit_gate, dict)
            else None
        )
        # Manifests created before support modules were introduced did not
        # spell out this redundant list. They are equivalent only when the
        # complete source set is exactly the executable module set.
        if recorded_test_sources is None and expected_test_sources == expected_test_modules:
            recorded_test_sources = expected_test_modules
        if recorded_test_source_count is None and expected_test_sources == expected_test_modules:
            recorded_test_source_count = len(expected_test_sources)
        if (
            not isinstance(unit_gate, dict)
            or unit_gate.get("exit_code") != 0
            or unit_gate.get("test_modules") != expected_test_modules
            or unit_gate.get("test_module_count") != len(expected_test_modules)
            or recorded_test_sources != expected_test_sources
            or recorded_test_source_count != len(expected_test_sources)
            or not isinstance(module_test_counts, dict)
            or set(module_test_counts) != set(expected_test_modules)
            or not all(
                isinstance(count, int)
                and not isinstance(count, bool)
                and count >= 1
                for count in module_test_counts.values()
            )
            or not isinstance(unit_gate.get("tests_run"), int)
            or unit_gate.get("tests_run") != sum(module_test_counts.values())
            or re.fullmatch(
                r"[0-9a-f]{64}",
                str(unit_gate.get("test_source_set_sha256", "")),
            )
            is None
            or unit_gate.get("isolated_python") is not True
            or unit_gate.get("site_disabled") is not True
            or unit_gate.get("bytecode_cache_isolated") is not True
            or unit_gate.get("isolation_flags")
            != ["-I", "-S", "-B", "-X", "pycache_prefix=<ephemeral>"]
            or not isinstance(unit_gate.get("unittest_module_path"), str)
            or not Path(unit_gate["unittest_module_path"]).is_absolute()
            or Path(unit_gate["unittest_module_path"]).name != "__init__.py"
            or Path(unit_gate["unittest_module_path"]).parent.name != "unittest"
            or installed.resolve()
            in Path(unit_gate["unittest_module_path"]).resolve().parents
        ):
            add(
                "RELEASE_GATE_INVALID",
                "/release_gate/unit_tests",
                "unit test gate must bind every executable module, support source, per-module count, and source-set hash",
            )
        if (
            not isinstance(eval_replay, dict)
            or eval_replay.get("isolated_python") is not True
            or eval_replay.get("site_disabled") is not True
            or eval_replay.get("bytecode_writes_disabled") is not True
            or eval_replay.get("isolation_flags") != ["-I", "-S", "-B"]
            or eval_replay.get("runner_path") != "scripts/run_evals.py"
            or re.fullmatch(
                r"[0-9a-f]{64}", str(eval_replay.get("runner_sha256", ""))
            )
            is None
        ):
            add(
                "RELEASE_GATE_INVALID",
                "/release_gate/eval_replay",
                "eval replay must retain isolated interpreter and runner evidence",
            )
        required_eval = {
            "valid": True,
            "expected_case_count": EXPECTED_CASE_COUNT,
            "completed_case_count": EXPECTED_CASE_COUNT,
            "expected_artifact_count": EXPECTED_ARTIFACT_COUNT,
            "artifact_count": EXPECTED_ARTIFACT_COUNT,
            "passed": EXPECTED_ARTIFACT_COUNT,
            "failed": 0,
            "suite_errors": [],
            "missing_cases": [],
        }
        if not isinstance(eval_gate, dict) or any(
            eval_gate.get(key) != expected
            for key, expected in required_eval.items()
        ):
            add(
                "RELEASE_GATE_INVALID",
                "/release_gate/eval",
                "eval gate must retain the complete frozen-suite pass",
            )
        elif re.fullmatch(
            r"[0-9a-f]{64}", str(eval_gate.get("evaluation_context_sha256", ""))
        ) is None:
            add(
                "RELEASE_GATE_INVALID",
                "/release_gate/eval/evaluation_context_sha256",
                "eval gate must retain the pre-execution release snapshot hash",
            )

    required_release_keys = set(RELEASE_EVIDENCE_FILES) | {
        "machine_report",
        "evaluation_context",
    }
    if not isinstance(release_evidence, dict) or set(release_evidence) != required_release_keys:
        add(
            "RELEASE_EVIDENCE_MISSING",
            "/release_evidence",
            "manifest must retain all evaluated source hashes, machine report, and evaluation context",
        )
        release_evidence = {}
    else:
        for name, relative in RELEASE_EVIDENCE_FILES.items():
            item = release_evidence.get(name)
            if (
                not isinstance(item, dict)
                or item.get("path") != relative
                or re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", "")))
                is None
            ):
                add(
                    "RELEASE_EVIDENCE_INVALID",
                    f"/release_evidence/{name}",
                    "release evidence entry has the wrong path or hash",
                )
        by_path = {
            item.get("path"): item.get("sha256")
            for item in release_evidence.values()
            if isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and isinstance(item.get("sha256"), str)
        }
        if isinstance(release_gate, dict):
            unit_gate = release_gate.get("unit_tests")
            eval_replay = release_gate.get("eval_replay")
            expected_test_sources = sorted(
                str(Path(relative).relative_to("tests"))
                for relative in RELEASE_EVIDENCE_FILES.values()
                if relative.startswith("tests/") and relative.endswith(".py")
            )
            test_source_hashes = {
                relative: by_path.get(f"tests/{relative}")
                for relative in expected_test_sources
            }
            if not all(
                re.fullmatch(r"[0-9a-f]{64}", str(digest))
                for digest in test_source_hashes.values()
            ):
                add(
                    "RELEASE_GATE_INVALID",
                    "/release_gate/unit_tests/test_source_set_sha256",
                    "every required test module needs retained release evidence",
                )
            elif isinstance(unit_gate, dict):
                expected_test_source_set_sha256 = hashlib.sha256(
                    json.dumps(
                        test_source_hashes,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                if (
                    unit_gate.get("test_source_set_sha256")
                    != expected_test_source_set_sha256
                ):
                    add(
                        "RELEASE_GATE_MISMATCH",
                        "/release_gate/unit_tests/test_source_set_sha256",
                        "unit-test source-set hash differs from retained release evidence",
                    )
            if (
                not isinstance(eval_replay, dict)
                or eval_replay.get("runner_sha256")
                != by_path.get("scripts/run_evals.py")
            ):
                add(
                    "RELEASE_GATE_MISMATCH",
                    "/release_gate/eval_replay/runner_sha256",
                    "isolated eval replay must bind the retained runner source",
                )
        for relative, digest in declared.items():
            evaluated_digest = by_path.get(relative)
            if evaluated_digest is None:
                add(
                    "RELEASE_EVIDENCE_MISSING",
                    f"/release_evidence/{relative}",
                    "installed runtime file lacks evaluated source evidence",
                )
            elif evaluated_digest != digest:
                add(
                    "RELEASE_EVIDENCE_MISMATCH",
                    f"/files/{relative}",
                    "installed file hash differs from the evaluated release source",
                )
        machine_item = release_evidence.get("machine_report")
        context_item = release_evidence.get("evaluation_context")
        machine_report: object | None = None
        evaluation_context: object | None = None

        def retained_evidence_path(
            item: object,
            key: str,
            expected_relative: str,
            missing_code: str,
            hash_code: str,
        ) -> Path | None:
            if (
                not isinstance(item, dict)
                or item.get("path") != expected_relative
                or re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", "")))
                is None
            ):
                add(
                    "RELEASE_EVIDENCE_INVALID",
                    f"/release_evidence/{key}",
                    "packaged evidence needs the fixed relative path and a SHA-256 hash",
                )
                return None
            path = installed / expected_relative
            if not path.is_file() or path.is_symlink():
                add(
                    missing_code,
                    f"/release_evidence/{key}/path",
                    "packaged evidence must be a regular file inside the installation",
                )
                return None
            if sha256_file(path) != item["sha256"]:
                add(
                    hash_code,
                    f"/release_evidence/{key}/sha256",
                    "packaged evidence bytes do not match the manifest",
                )
                return None
            return path

        machine_path = retained_evidence_path(
            machine_item,
            "machine_report",
            PACKAGED_EVIDENCE_FILES[0],
            "MACHINE_REPORT_MISSING",
            "MACHINE_REPORT_HASH_MISMATCH",
        )
        context_path = retained_evidence_path(
            context_item,
            "evaluation_context",
            PACKAGED_EVIDENCE_FILES[1],
            "EVALUATION_CONTEXT_MISSING",
            "EVALUATION_CONTEXT_HASH_MISMATCH",
        )
        if machine_path is not None:
            try:
                machine_report = json.loads(machine_path.read_text(encoding="utf-8"))
                validate_eval_report(machine_report)
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                add(
                    "MACHINE_REPORT_INVALID",
                    "/release_evidence/machine_report",
                    str(exc),
                )
                machine_report = None
        if context_path is not None:
            try:
                evaluation_context = json.loads(
                    context_path.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                add(
                    "EVALUATION_CONTEXT_INVALID",
                    "/release_evidence/evaluation_context",
                    str(exc),
                )
                evaluation_context = None
            if evaluation_context is not None and not isinstance(
                evaluation_context, dict
            ):
                add(
                    "EVALUATION_CONTEXT_INVALID",
                    "/release_evidence/evaluation_context",
                    "evaluation context JSON top level must be an object",
                )
                evaluation_context = None
        if isinstance(machine_report, dict):
            expected_source_evidence = {
                name: release_evidence[name] for name in RELEASE_EVIDENCE_FILES
            }
            if machine_report.get("release_evidence") != expected_source_evidence:
                add(
                    "RELEASE_EVIDENCE_MISMATCH",
                    "/release_evidence",
                    "manifest source evidence must exactly equal the retained machine report",
                )
            if isinstance(release_gate, dict):
                eval_gate = release_gate.get("eval")
                if isinstance(eval_gate, dict) and any(
                    eval_gate.get(key) != machine_report.get(key)
                    for key in eval_gate
                ):
                    add(
                        "RELEASE_GATE_MISMATCH",
                        "/release_gate/eval",
                        "manifest eval summary must match the retained machine report",
                    )
            if (
                isinstance(context_item, dict)
                and machine_report.get("evaluation_context_sha256")
                != context_item.get("sha256")
            ):
                add(
                    "EVALUATION_CONTEXT_MISMATCH",
                    "/release_evidence/evaluation_context/sha256",
                    "machine report must bind the packaged evaluation context",
                )
        if isinstance(evaluation_context, dict):
            expected_source_evidence = {
                name: release_evidence[name] for name in RELEASE_EVIDENCE_FILES
            }
            if evaluation_context.get("release_evidence") != expected_source_evidence:
                add(
                    "EVALUATION_CONTEXT_MISMATCH",
                    "/release_evidence/evaluation_context",
                    "packaged evaluation context must bind the manifest source evidence",
                )

    if manifest.get("skill") != SKILL_NAME:
        add("SKILL_IDENTITY_MISMATCH", "/skill", "manifest skill name is wrong")
    if installed.name != SKILL_NAME:
        add("SKILL_IDENTITY_MISMATCH", "", "installed directory name is wrong")
    # Integrity errors must short-circuit before importing or executing any
    # installed Python.  The manifest is self-contained consistency evidence,
    # not an external authenticity signature, but a hash mismatch still makes
    # the payload untrusted for local execution.
    if errors:
        return {"valid": False, "error_count": len(errors), "errors": errors}
    try:
        with tempfile.TemporaryDirectory(
            prefix="sffs-verification-snapshot-"
        ) as temp_dir:
            snapshot = Path(temp_dir) / SKILL_NAME
            for relative, digest in declared.items():
                source_path = installed / relative
                target_path = snapshot / relative
                target_path.parent.mkdir(parents=True, exist_ok=True)
                if not source_path.is_file() or source_path.is_symlink():
                    add(
                        "VERIFICATION_SNAPSHOT_MISMATCH",
                        relative,
                        "installed payload changed before the private verification snapshot",
                    )
                    continue
                shutil.copy2(source_path, target_path)
                if (
                    not target_path.is_file()
                    or target_path.is_symlink()
                    or sha256_file(target_path) != digest
                ):
                    add(
                        "VERIFICATION_SNAPSHOT_MISMATCH",
                        relative,
                        "private verification snapshot differs from the manifest",
                    )
            if errors:
                return {"valid": False, "error_count": len(errors), "errors": errors}

            runtime, identity = preflight(snapshot)
            for relative, digest in declared.items():
                snapshot_path = snapshot / relative
                installed_path = installed / relative
                if (
                    not snapshot_path.is_file()
                    or snapshot_path.is_symlink()
                    or sha256_file(snapshot_path) != digest
                    or not installed_path.is_file()
                    or installed_path.is_symlink()
                    or sha256_file(installed_path) != digest
                ):
                    add(
                        "VERIFICATION_SNAPSHOT_MISMATCH",
                        relative,
                        "payload changed during isolated verification",
                    )
            for key, actual in (
                ("skill_version", runtime.SKILL_VERSION),
                ("schema_version", runtime.SCHEMA_VERSION),
                ("validator_version", runtime.VALIDATOR_VERSION),
                ("workflow_version", identity.get("workflow_version")),
            ):
                if manifest.get(key) != actual:
                    add("VERSION_MISMATCH", f"/{key}", f"expected {actual}")
            manifest_preflight = manifest.get("preflight")
            if manifest_preflight != identity:
                add(
                    "PREFLIGHT_MISMATCH",
                    "/preflight",
                    "manifest preflight must exactly equal a fresh installed-runtime preflight",
                )
            if identity.get("identity_match") is not True:
                add("SKILL_IDENTITY_MISMATCH", "/preflight", "identity check failed")
    except (OSError, ImportError, UnicodeError, json.JSONDecodeError) as exc:
        add("INSTALLED_PREFLIGHT_FAILED", "", str(exc))
    return {"valid": not errors, "error_count": len(errors), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install or verify the gated local Skill runtime."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--target-root", help="project-level skills directory")
    mode.add_argument("--verify", help="installed Skill directory to verify")
    mode.add_argument(
        "--unit-gate",
        action="store_true",
        help="run the fixed isolated release unit-test gate and emit JSON",
    )
    parser.add_argument(
        "--eval-root",
        help="completed frozen eval root with machine-report.json; required for install",
    )
    args = parser.parse_args()
    if args.unit_gate:
        if args.eval_root:
            print("EVAL_ROOT_NOT_ALLOWED_WITH_UNIT_GATE", file=sys.stderr)
            return 2
        source = Path(__file__).resolve().parents[1]
        try:
            result = run_unit_test_gate(source)
        except OSError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.verify:
        if args.eval_root:
            print("EVAL_ROOT_NOT_ALLOWED_WITH_VERIFY", file=sys.stderr)
            return 2
        result = verify_install(Path(args.verify).expanduser().resolve())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["valid"] else 1
    if not args.eval_root:
        print("EVAL_ROOT_REQUIRED", file=sys.stderr)
        return 2
    source = Path(__file__).resolve().parents[1]
    try:
        destination = package_runtime(
            source,
            Path(args.target_root).expanduser(),
            Path(args.eval_root).expanduser().resolve(),
        )
    except (FileExistsError, FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"installed": str(destination.resolve()), "skill": SKILL_NAME}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
