# Resumable Evidence Workflow Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development for implementation tasks when the user selects that execution mode. Otherwise use superpowers:executing-plans for inline execution.

## Goal

把 release-docs 的 SQL 產製與證據審查改成可中斷、可恢復、可重跑的 workflow，並先修正 metadata provider 對 `sp_updateextendedproperty` 的 operation preservation。最終只有 SQL correctness、validation SQL、LocalDB 四輪交易、rerun、failure rollback、fingerprint 與排除範圍都通過時，才產生 SQL content passed；正式資料業務結果仍分流為非阻塞的 `business_data_validation`。

## Architecture

- 保留現有 source-driven analysis、`produce_release`、`run_local_validation`、semantic review 與 lifecycle artifact 邊界。
- 以 lifecycle run 內的 `workflow_state.json` 保存固定 stage、attempt、input/output fingerprint、錯誤摘要與狀態。
- 以單一 resume coordinator 依序處理 `source_collected -> fixture_ready -> local_validation_passed -> semantic_review_passed -> report_finalized -> delivery_finalized`；上游輸入變更時使 downstream invalidated。
- 所有永久 evidence 先寫入並核對 hash，再 atomic replace workflow state；未完成 stage 不得成為 passed。
- provider 以來源 metadata operation 為 authoritative：source `update` 必須輸出 `sp_updateextendedproperty`，source `add` 才輸出 add；物件存在性只用於 guarded execution。

## Tech Stack

- Python 3、現有 release-docs scripts、pytest。
- JSON evidence/state、SHA-256 fingerprint、既有 LocalDB executor injection。
- PowerShell 驗證命令；不連線正式 DB、不取得正式資料列。

## Spec

`docs/superpowers/specs/2026-10-11-resumable-evidence-workflow-design.md`

## Global Constraints

- 先寫失敗測試，再修改 production code；每一項完成後跑 targeted pytest，再跑完整 suite。
- 不把 `expected` 當成 runner 的 `actual before/after`；fixture rows、seed rows、assertion mapping 缺一不可。
- `business_data_validation` 只能附加資訊，不得產生 `blocking` 或 `semantic_review_pending` 來阻擋 SQL correctness。
- `#5005` 排除物件不可進入 execution artifact、unit mapping 或 evidence receipt。
- 所有 command、exception、connection string 與 finding 寫入 durable evidence 前必須 redaction；無法可靠遮罩時 stage 必須停止。
- 不修改正式部署行為，不新增取得正式資料的路徑；保留既有 schema version=1 read compatibility。
- 不刪除未追蹤 pytest scratch 或使用者 artifacts；不得以 reset/checkout 覆蓋既有變更。

## Review Focus

1. provider 是否保留來源 operation、source mapping、provider version 與 input/output hash，且 update 不退化成 add。
2. resume 是否只重跑第一個未完成或 invalidated stage，並拒絕 finalized、無 lock、路徑不安全或 schema 不相容的 run。
3. DATA gate 是否在 executor 前阻擋空 rows、缺 seed row、缺 query mapping、缺 assertion 或 expected/actual 混用。
4. finalize 是否在任何 evidence/hash/fingerprint 缺失時拒絕 SQL content passed。
5. failure injection 是否確實 rollback 並停止後續 unit；四輪 evidence 必須 distinct 且可重放。

## Task 1: Lock provider operation preservation with regression tests

**Files:**

- Modify: `tests/test_metadata_provider.py`
- Modify: `tests/test_release_unit_generator.py` if needed by the existing test layout
- Modify: `skills/release-docs/scripts/metadata_provider.py` only if a failing test proves the current materialization/provenance contract is incomplete
- Modify: `skills/release-docs/scripts/release_unit_generator.py` only if provider provenance is not propagated

**TDD steps:**

1. RED: add tests for source add/update/drop parsing; assert source update renders `sp_updateextendedproperty`, guarded update fallback remains update-first, and source add renders only add semantics. Add a deterministic regeneration test asserting artifact bytes, descriptor, operation mapping, provider version and input/output hashes are stable.
2. RED: add a contract test proving excluded `#5005` objects never appear in provider output or provenance.
3. Run targeted tests and record the exact failures.
4. GREEN: make the smallest provider/generator change that preserves the authoritative operation without changing approved dynamic-DDL blocking behavior.
5. Run `python -m pytest tests/test_metadata_provider.py tests/test_release_unit_generator.py -q` and the relevant SQL contract tests.
6. Commit: `fix: preserve metadata provider operations`.

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

1. RED: test atomic state creation, monotonic stage order, attempt increments, durable output hashes, and rejection of unknown stage/status.
2. RED: test interrupted state resumes at the first incomplete stage; unchanged completed outputs are reused; changed upstream fingerprint invalidates that stage and every downstream stage.
3. RED: test legacy schema-1 run is readable but cannot resume; finalized run, missing lock, unsafe path and incompatible workflow schema are rejected.
4. GREEN: implement state writes through a temporary file plus atomic replace, with lifecycle ownership/path checks and immutable evidence verification.
5. Extend `artifact_lifecycle.initialize/fail/finish` so state is created, interruption is durable, and finalization records `delivery_finalized` before cleanup. Keep existing artifact ownership and ignore checks.
6. Run `python -m pytest tests/test_workflow_state.py tests/test_artifact_lifecycle.py -q`.
7. Commit: `feat: add durable release workflow checkpoints`.

## Task 3: Implement resumable production coordination

**Files:**

- Modify: `skills/release-docs/scripts/produce_release.py`
- Add or modify: `skills/release-docs/scripts/resume_release.py` (use the existing production CLI location if one already exists)
- Add: `tests/test_resumable_workflow.py`
- Modify: `tests/test_release_review.py`

**Interfaces:**

- `resume_release(repo, run_root, *, current_inputs, adapters=None) -> ProductionResult`
- Internal stage handlers must return durable output paths and fingerprints, never only in-memory status.

**TDD steps:**

1. RED: simulate interruption after source, fixture and LocalDB stages; assert resume does not rerun completed upstream work and produces a new attempt only for pending work.
2. RED: change source/fixture/manifest/artifact input bytes; assert downstream evidence is invalidated and old passed receipt cannot be reused.
3. RED: assert a failed external tool is recorded as retryable/blocked with sanitized error metadata, and a later resume can continue without manual stage selection.
4. GREEN: extract stage boundaries from `produce_release`, initialize workflow state, and add one resume entry point that reuses valid evidence and stops at the first unresolved stage.
5. Preserve `ProductionError` stage/code behavior and ensure intermediate results cannot be returned as final passed status.
6. Run `python -m pytest tests/test_resumable_workflow.py tests/test_release_review.py -q`.
7. Commit: `feat: make release evidence production resumable`.

## Task 4: Tighten fixture and validation-SQL evidence gates

**Files:**

- Modify: `skills/release-docs/scripts/run_local_validation.py`
- Modify: `skills/release-docs/scripts/validate_release_output.py`
- Modify: `skills/release-docs/scripts/produce_release.py`
- Modify: `tests/test_local_validation.py`
- Modify: `tests/test_release_review.py`
- Add: `tests/test_evidence_gates.py` if existing test modules do not provide a clear home

**TDD steps:**

1. RED: empty manifest rows, seed rows not represented by fixture rows, duplicate/missing `seed_row_id`, absent executable validation mapping and expected-only data checks must return an explicit blocked finding before executor invocation.
2. RED: add a non-mutating unit fixture proving preservation is `N/A` or passed with a source-based “no existing row mutation” explanation and no formal data-row evidence requirement.
3. RED: add finding classification tests proving missing SQL execution evidence is `sql_correctness`/deployment validation, while missing formal business rows is only `business_data_validation` and non-blocking.
4. GREEN: validate fixture content and assertion/query mapping before the four rounds; validate actual checks independently against expected assertions; do not manufacture actual values.
5. Keep the existing four rounds (`validate_only`, `commit`, `rerun`, `injected_failure`) and require rollback, stop-after-failure, commit state and rerun identity evidence.
6. Run `python -m pytest tests/test_local_validation.py tests/test_release_review.py tests/test_evidence_gates.py -q`.
7. Commit: `fix: enforce executable validation evidence gates`.

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

1. RED: test password/token/secret/API key fields, SQL connection strings, command arguments and exception text are masked; ordinary SQL identifiers and hashes remain unchanged.
2. RED: test unrecognized credential-like material causes a non-sensitive `secret_redaction_required` failure rather than being persisted.
3. GREEN: apply the same redactor to command metadata, runner errors and review findings immediately before JSON/report writes; never log raw command lines containing credentials.
4. Run `python -m pytest tests/test_evidence_redaction.py tests/test_local_validation.py tests/test_artifact_lifecycle.py -q`.
5. Commit: `fix: redact secrets from release evidence`.

## Task 6: Make report finalization atomic and preserve finding domains

**Files:**

- Modify: `skills/release-docs-review/scripts/validate_release_output.py`
- Modify: `skills/release-docs-review/scripts/review_fingerprint.py` if receipt fingerprint checks need a shared helper
- Modify: `skills/release-docs/scripts/artifact_lifecycle.py`
- Modify: `skills/release-docs/scripts/render_release_documents.py`
- Add or modify: `tests/test_atomic_finalize.py`
- Modify: `tests/test_release_review.py`

**TDD steps:**

1. RED: report finalize must reject missing report/fingerprint/evidence receipt, changed artifact/fixture hash, incomplete four-round data checks, temporary paths, or a non-final workflow state.
2. RED: a `business_data_validation` finding must remain visible as non-blocking and must not lower `sql_content_status`; any SQL contract/transaction/rerun/failure/#5005 finding remains blocking.
3. RED: interrupted or failed runs must retain evidence and never emit SQL content passed; finalization must be atomic and idempotent for the same receipt.
4. GREEN: implement a single finalization gate that rechecks current fingerprints, lifecycle receipt, evidence inventory and finding domains before writing the final review report; write to a temporary report then atomically replace.
5. Ensure `delivery_finalized` is recorded only after final report and document hashes agree; preserve existing output path and lifecycle cleanup safeguards.
6. Run `python -m pytest tests/test_atomic_finalize.py tests/test_release_review.py tests/test_artifact_lifecycle.py -q`.
7. Commit: `fix: finalize release review atomically`.

## Task 7: Update operator guidance and run full verification

**Files:**

- Modify: `skills/release-docs/SKILL.md`
- Modify: `skills/release-docs-review/SKILL.md`
- Modify: `README.md` only if the repository documents the plugin command entry point there
- Add or modify: `tests/test_end_to_end.py`

**TDD/verification steps:**

1. Add an end-to-end fixture that runs provider generation, source/schema checks, validation SQL, LocalDB four rounds, injected failure, rerun, fingerprint and finalization; assert `#5005` is absent.
2. Add an interrupted-run resume scenario and a non-blocking formal-business-data limitation scenario.
3. Document the stage state file, resume command, blocked vs failed semantics, finding domains, preservation N/A rule and the requirement to rotate any credential that was previously exposed in command logs.
4. Run targeted suites for all changed modules.
5. Run full verification: `python -m pytest -q`; run any repository-provided lint/type/contract commands; inspect `git diff --check`.
6. Review generated evidence for raw secrets, temporary paths, `#5005`, and false SQL passed states.
7. Commit: `test: verify resumable release evidence workflow`.

## Completion Gate

Before claiming completion, verify the full suite output and inspect the final diff. The implementation is complete only when provider update materialization, validation SQL, schema checks, LocalDB four rounds, rollback/stop behavior, rerun convergence, fingerprint invalidation, redaction, atomic report finalization and non-blocking business-data classification all have passing evidence. Publishing/tagging or updating local/Claude Code plugin installations is a separate release action and must not be inferred from this implementation plan alone.
