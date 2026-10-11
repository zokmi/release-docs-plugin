# Resumable Evidence Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 release-docs 的 SQL 產製與證據審查改成可中斷、可恢復、可重跑的 workflow，並確保 metadata provider 不會混淆 `add`、`update`、`drop`。

**Architecture:** 保留既有 source-driven analysis、LocalDB executor injection、semantic review 與 lifecycle artifact 邊界；新增 durable `workflow_state.json` 與單一 resume coordinator。provider 以來源 operation 為 authoritative，finalize gate 以 fingerprint、hash、四輪 evidence 與 finding domain 重新核對後才產生通過報告。

**Tech Stack:** Python 3、pytest、JSON evidence/state、SHA-256 fingerprint、PowerShell 驗證命令；不連線正式 DB、不取得正式資料列。

**Spec:** `docs/superpowers/specs/2026-10-11-resumable-evidence-workflow-design.md`

## Global Constraints

- 先寫失敗測試，再修改 production code；每一項完成後跑 targeted pytest，再跑完整 suite。
- 不把 `expected` 當成 runner 的 `actual before/after`；fixture rows、seed rows、assertion mapping 缺一不可。
- `business_data_validation` 只能附加資訊，不得產生 `blocking` 或 `semantic_review_pending` 來阻擋 SQL correctness。
- `#5005` 排除物件不可進入 execution artifact、unit mapping 或 evidence receipt。
- 所有 command、exception、connection string 與 finding 寫入 durable evidence 前必須 redaction；無法可靠遮罩時 stage 必須停止。
- 不修改正式部署行為，不新增取得正式資料的路徑；保留既有 schema version=1 read compatibility。
- 不刪除未追蹤 pytest scratch 或使用者 artifacts；不得以 reset/checkout 覆蓋既有變更。

## Review Focus

- provider `add/update/drop` operation 或 fallback metadata 不一致時，renderer、descriptor、provenance 與 validator 必須一致拒絕。（Task 1）
- resume 遇到第一個未完成或 invalidated stage 時，只能重跑該 stage 及 downstream，並拒絕 finalized、無 lock、路徑不安全或 schema 不相容的 run。（Tasks 2–3）
- DATA gate 遇到空 rows、缺 seed row、缺 query mapping、缺 assertion 或 expected/actual 混用時，必須在 executor 前阻擋。（Task 4）
- finalize 遇到任何 evidence/hash/fingerprint 缺失或變更時，必須拒絕 SQL content passed。（Task 6）
- failure injection 必須證明 rollback、停止後續 unit、四輪 evidence distinct，且 rerun 使用相同 committed state。（Tasks 4、6–7）

## Task 1: Lock provider operation preservation with regression tests

**Files:**

- Modify: `tests/test_metadata_provider.py`
- Modify: `tests/test_release_unit_generator.py`
- Modify: `skills/release-docs/scripts/metadata_provider.py`
- Modify: `skills/release-docs/scripts/release_unit_generator.py`

**TDD steps:**

- [ ] RED: add tests for source add/update/drop parsing; assert add renders `sp_addextendedproperty`, update renders `sp_updateextendedproperty`, drop renders `sp_dropextendedproperty`, and no renderer branch chooses operation from object existence. If update fallback is retained, assert the update branch remains authoritative and provenance records the fallback policy without changing operation.
- [ ] RED: add a contract test proving excluded `#5005` objects never appear in provider output or provenance.
- [ ] RED: add a deterministic regeneration test asserting artifact bytes, descriptor, source/materialized operation mapping, provider version, fallback policy and input/output hashes are stable.
- [ ] Run targeted tests and record the exact failures.
- [ ] GREEN: make the smallest provider/generator change that preserves the authoritative operation without changing approved dynamic-DDL blocking behavior.
- [ ] Run `python -m pytest tests/test_metadata_provider.py tests/test_release_unit_generator.py -q` and the relevant SQL contract tests.
- [ ] Commit: `fix: preserve metadata provider operations`.

## Task 2: Add durable workflow state and controlled stage transitions

**Files:**

- Add: `skills/release-docs/scripts/workflow_state.py`
- Modify: `skills/release-docs/scripts/artifact_lifecycle.py`
- Modify: `skills/release-docs/scripts/lifecycle_store.py`
- Add: `tests/test_workflow_state.py`
- Modify: `tests/test_artifact_lifecycle.py`

**Interfaces:**

- `initialize_workflow_state(run_root, run_id, workflow_fingerprint, stages) -> dict`
- `load_workflow_state(run_root) -> dict`
- `record_stage(run_root, stage, *, status, input_fingerprint, output_files=(), error_summary="") -> dict`
- `invalidate_from(run_root, stage, reason) -> dict`
- `resume_checkpoint(run_root, current_fingerprint) -> str`

**TDD steps:**

- [ ] RED: test atomic state creation, monotonic stage order, attempt increments, durable output hashes, and rejection of unknown stage/status.
- [ ] RED: test interrupted state resumes at the first incomplete stage; unchanged completed outputs are reused; changed upstream fingerprint invalidates that stage and every downstream stage.
- [ ] RED: test legacy schema-1 run is readable but cannot resume; finalized run, missing lock, unsafe path and incompatible workflow schema are rejected.
- [ ] GREEN: implement state writes through a temporary file plus atomic replace, with lifecycle ownership/path checks and immutable evidence verification.
- [ ] Extend `artifact_lifecycle.initialize/fail/finish` so state is created, interruption is durable, and finalization records `delivery_finalized` before cleanup. Keep existing artifact ownership and ignore checks.
- [ ] Run `python -m pytest tests/test_workflow_state.py tests/test_artifact_lifecycle.py -q`.
- [ ] Commit: `feat: add durable release workflow checkpoints`.

## Task 3: Implement resumable production coordination

**Files:**

- Modify: `skills/release-docs/scripts/produce_release.py`
- Add: `skills/release-docs/scripts/resume_release.py`
- Add: `tests/test_resumable_workflow.py`
- Modify: `tests/test_release_review.py`

**Interfaces:**

- `resume_release(repo, run_root, *, current_inputs, adapters=None) -> ProductionResult`
- Internal stage handlers must return durable output paths and fingerprints, never only in-memory status.

**TDD steps:**

- [ ] RED: simulate interruption after source, fixture and LocalDB stages; assert resume does not rerun completed upstream work and produces a new attempt only for pending work.
- [ ] RED: change source/fixture/manifest/artifact input bytes; assert downstream evidence is invalidated and old passed receipt cannot be reused.
- [ ] RED: assert a failed external tool is recorded as retryable/blocked with sanitized error metadata, and a later resume can continue without manual stage selection.
- [ ] GREEN: extract stage boundaries from `produce_release`, initialize workflow state, and add one resume entry point that reuses valid evidence and stops at the first unresolved stage.
- [ ] Preserve `ProductionError` stage/code behavior and ensure intermediate results cannot be returned as final passed status.
- [ ] Run `python -m pytest tests/test_resumable_workflow.py tests/test_release_review.py -q`.
- [ ] Commit: `feat: make release evidence production resumable`.

## Task 4: Tighten fixture and validation-SQL evidence gates

**Files:**

- Modify: `skills/release-docs/scripts/run_local_validation.py`
- Modify: `skills/release-docs/scripts/validate_release_output.py`
- Modify: `skills/release-docs/scripts/produce_release.py`
- Modify: `tests/test_local_validation.py`
- Modify: `tests/test_release_review.py`
- Add: `tests/test_evidence_gates.py`

**TDD steps:**

- [ ] RED: empty manifest rows, seed rows not represented by fixture rows, duplicate/missing `seed_row_id`, absent executable validation mapping and expected-only data checks must return an explicit blocked finding before executor invocation.
- [ ] RED: add a non-mutating unit fixture proving preservation is `N/A` or passed with a source-based “no existing row mutation” explanation and no formal data-row evidence requirement.
- [ ] RED: add finding classification tests proving missing SQL execution evidence is `sql_correctness`/deployment validation, while missing formal business rows is only `business_data_validation` and non-blocking.
- [ ] GREEN: validate fixture content and assertion/query mapping before the four rounds; validate actual checks independently against expected assertions; do not manufacture actual values.
- [ ] Keep the existing four rounds (`validate_only`, `commit`, `rerun`, `injected_failure`) and require rollback, stop-after-failure, commit state and rerun identity evidence.
- [ ] Run `python -m pytest tests/test_local_validation.py tests/test_release_review.py tests/test_evidence_gates.py -q`.
- [ ] Commit: `fix: enforce executable validation evidence gates`.

## Task 5: Add shared secret redaction before durable evidence writes

**Files:**

- Add: `skills/release-docs/scripts/evidence_redaction.py`
- Modify: `skills/release-docs/scripts/run_local_validation.py`
- Modify: `skills/release-docs/scripts/lifecycle_store.py`
- Modify: `skills/release-docs/scripts/artifact_lifecycle.py`
- Add: `tests/test_evidence_redaction.py`

**Interfaces:**

- `redact_text(value) -> str`
- `redact_mapping(value) -> dict`
- `assert_safe_evidence(value) -> None`

**TDD steps:**

- [ ] RED: test password/token/secret/API key fields, SQL connection strings, command arguments and exception text are masked; ordinary SQL identifiers and hashes remain unchanged.
- [ ] RED: test unrecognized credential-like material causes a non-sensitive `secret_redaction_required` failure rather than being persisted.
- [ ] GREEN: apply the same redactor to command metadata, runner errors and review findings immediately before JSON/report writes; never log raw command lines containing credentials.
- [ ] Run `python -m pytest tests/test_evidence_redaction.py tests/test_local_validation.py tests/test_artifact_lifecycle.py -q`.
- [ ] Commit: `fix: redact secrets from release evidence`.

## Task 6: Make report finalization atomic and preserve finding domains

**Files:**

- Modify: `skills/release-docs-review/scripts/validate_release_output.py`
- Modify: `skills/release-docs-review/scripts/review_fingerprint.py` if receipt fingerprint checks need a shared helper
- Modify: `skills/release-docs/scripts/artifact_lifecycle.py`
- Modify: `skills/release-docs/scripts/render_release_documents.py`
- Add: `tests/test_atomic_finalize.py`
- Modify: `tests/test_release_review.py`

**TDD steps:**

- [ ] RED: report finalize must reject missing report/fingerprint/evidence receipt, changed artifact/fixture hash, incomplete four-round data checks, temporary paths, or a non-final workflow state.
- [ ] RED: a `business_data_validation` finding must remain visible as non-blocking and must not lower `sql_content_status`; any SQL contract/transaction/rerun/failure/#5005 finding remains blocking.
- [ ] RED: interrupted or failed runs must retain evidence and never emit SQL content passed; finalization must be atomic and idempotent for the same receipt.
- [ ] GREEN: implement a single finalization gate that rechecks current fingerprints, lifecycle receipt, evidence inventory and finding domains before writing the final review report; write to a temporary report then atomically replace.
- [ ] Ensure `delivery_finalized` is recorded only after final report and document hashes agree; preserve existing output path and lifecycle cleanup safeguards.
- [ ] Run `python -m pytest tests/test_atomic_finalize.py tests/test_release_review.py tests/test_artifact_lifecycle.py -q`.
- [ ] Commit: `fix: finalize release review atomically`.

## Task 7: Update operator guidance and run full verification

**Files:**

- Modify: `skills/release-docs/SKILL.md`
- Modify: `skills/release-docs-review/SKILL.md`
- Add: `tests/test_end_to_end.py`

**TDD/verification steps:**

- [ ] Add an end-to-end fixture that runs provider generation, source/schema checks, validation SQL, LocalDB four rounds, injected failure, rerun, fingerprint and finalization; assert `#5005` is absent.
- [ ] Add an interrupted-run resume scenario and a non-blocking formal-business-data limitation scenario.
- [ ] Document the stage state file, resume command, blocked vs failed semantics, finding domains, preservation N/A rule and the requirement to rotate any credential that was previously exposed in command logs.
- [ ] Run targeted suites for all changed modules.
- [ ] Run full verification: `python -m pytest -q`; run any repository-provided lint/type/contract commands; inspect `git diff --check`.
- [ ] Review generated evidence for raw secrets, temporary paths, `#5005`, and false SQL passed states.
- [ ] Commit: `test: verify resumable release evidence workflow`.

## Completion Gate

Before claiming completion, verify the full suite output and inspect the final diff. The implementation is complete only when provider update materialization, validation SQL, schema checks, LocalDB four rounds, rollback/stop behavior, rerun convergence, fingerprint invalidation, redaction, atomic report finalization and non-blocking business-data classification all have passing evidence. Publishing/tagging or updating local/Claude Code plugin installations is a separate release action and must not be inferred from this implementation plan alone.
