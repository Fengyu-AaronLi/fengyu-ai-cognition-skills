PYTHON ?= python3
DIST_ROOT ?= dist
PACKAGE_VERSION := $(shell tr -d '\n' < VERSION)
PACKAGE_DIR ?= $(DIST_ROOT)/breaking-identity-labels-$(PACKAGE_VERSION)
PACKAGE_ARCHIVE ?= $(DIST_ROOT)/breaking-identity-labels-$(PACKAGE_VERSION).zip
WORKFLOW_PATH ?= workflows/v78-final-release.json
RUN_ID ?= local-workflow-$(shell date -u +%Y%m%dT%H%M%S)
RUN_DIR ?= evals/runs/$(RUN_ID)
CANDIDATE_ID ?= breaking-identity-labels-$(RUN_ID)
RELEASE_STATE ?= evals/release-gate.json

.PHONY: runtime-loop boundary-loop forward-loop adversarial-loop v7-loop v8-loop v9-loop release-loop test eval eval-verify refresh-evidence package-check package-check-release-state evolution-gate release-gate sync-test-manifest dependency-sync dependency-check development-package development-package-check release-package release-package-check workflow verify verify-release demo demo-verify red-evidence-verify baseline-evidence-verify live-e2e-verify historical-live-e2e-verify fresh-live-e2e-verify historical-live-retest-verify audit-harness-check
.NOTPARALLEL: workflow verify verify-release evolution-gate release-gate release-package release-package-check refresh-evidence

runtime-loop:
	$(PYTHON) -m unittest discover -s tests -p 'test_identity_label_case.py' -v
	$(PYTHON) -m unittest discover -s tests -p 'test_workflow_loop.py' -v

boundary-loop:
	$(PYTHON) -m unittest discover -s tests -p 'test_refinement_regressions.py' -v

forward-loop:
	$(PYTHON) -m unittest discover -s tests -p 'test_final_forward_regressions.py' -v

adversarial-loop:
	$(PYTHON) -m unittest discover -s tests -p 'test_v6_adversarial_regressions.py' -v

v7-loop:
	$(PYTHON) -m unittest discover -s tests -p 'test_v7_*.py' -v

v8-loop:
	$(PYTHON) -m unittest discover -s tests -p 'test_v8_*.py' -v

v9-loop:
	$(PYTHON) -m unittest discover -s tests -p 'test_v9_*.py' -v

release-loop:
	$(PYTHON) -m unittest discover -s tests -p 'test_v2_acceptance.py' -v
	$(PYTHON) -m unittest discover -s tests -p 'test_release_package.py' -v
	$(PYTHON) -m unittest discover -s tests -p 'test_release_loop_contract.py' -v

test:
	$(PYTHON) -m unittest discover -s tests -v

eval:
	$(PYTHON) evals/run_v2_evals.py --output evals/v2-results.json

eval-verify:
	$(PYTHON) scripts/verify_evaluation.py --results evals/v2-results.json

refresh-evidence: eval demo

package-check:
	$(PYTHON) evals/validate.py

package-check-release-state:
	$(PYTHON) evals/validate.py --include-release-state --release-state evals/release-gate.json

evolution-gate:
	$(PYTHON) scripts/run_evolution.py check --allow-blocked

release-gate:
	$(PYTHON) scripts/run_evolution.py check --strict-release

sync-test-manifest:
	$(PYTHON) scripts/run_evolution.py sync-tests

dependency-sync:
	$(PYTHON) scripts/sync_regression_dependencies.py sync --manifest evals/regression-dependency-manifest.json --skill-root . --repository-root ../..

dependency-check:
	$(PYTHON) scripts/sync_regression_dependencies.py check --manifest evals/regression-dependency-manifest.json --skill-root . --repository-root ../..

development-package:
	$(PYTHON) scripts/build_package.py build --out "$(PACKAGE_DIR)" --archive "$(PACKAGE_ARCHIVE)"

development-package-check:
	$(PYTHON) scripts/build_package.py verify --package "$(PACKAGE_DIR)"

release-package: release-gate
	$(PYTHON) scripts/run_evolution.py export-package --state "$(RELEASE_STATE)" --out-dir "$(PACKAGE_DIR)" --out-archive "$(PACKAGE_ARCHIVE)"

release-package-check: release-gate
	$(PYTHON) scripts/run_evolution.py export-package --state "$(RELEASE_STATE)" --out-dir "$(PACKAGE_DIR)" --out-archive "$(PACKAGE_ARCHIVE)" --verify-only

workflow:
	$(PYTHON) scripts/run_evolution.py run --workflow "$(WORKFLOW_PATH)" --run-dir "$(RUN_DIR)" --run-id "$(RUN_ID)" --candidate-id "$(CANDIDATE_ID)"

verify: dependency-check test eval-verify demo-verify red-evidence-verify baseline-evidence-verify live-e2e-verify audit-harness-check package-check

verify-release: verify release-gate

demo:
	$(PYTHON) scripts/build_demo.py --force

demo-verify:
	$(PYTHON) scripts/verify_demo.py --demo-dir examples/real-run

red-evidence-verify:
	$(PYTHON) scripts/verify_red_evidence_manifest.py --root . --manifest evals/red-evidence-manifest.json

baseline-evidence-verify:
	$(PYTHON) scripts/verify_baseline_evidence.py --root . --manifest evals/baseline-evidence-manifest.json

live-e2e-verify: historical-live-e2e-verify fresh-live-e2e-verify

historical-live-e2e-verify:
	$(PYTHON) scripts/verify_live_e2e.py --root . --manifest evals/live-e2e-manifest.json

fresh-live-e2e-verify:
	$(PYTHON) scripts/verify_live_e2e.py --root . --manifest evals/fresh-candidate-e2e-manifest.json

historical-live-retest-verify:
	$(PYTHON) scripts/verify_live_retest.py --manifest evals/live-retest-manifest.json

audit-harness-check:
	$(PYTHON) scripts/run_release_audits.py self-check
