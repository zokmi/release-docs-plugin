# release-docs SQL Safety and EF Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement automatic EF-based analysis for one SQL Server database and produce a manually executable, transaction-safe release SQL package with fixture-backed LocalDB validation.

**Architecture:** Extend the existing evidence → unit analysis → SQL assembly → lifecycle → document review pipeline. Add a dedicated EF detection boundary, make unit completeness and exclusion provenance fail closed, generate plain T-SQL whose runtime mode comes from `SESSION_CONTEXT`, and make LocalDB validation execute against documented baseline data plus expected-result fixtures. Keep SQL content review separate from deployment evidence.

**Tech Stack:** Python 3, pytest, Git revision-pinned reads, SQL Server/SSMS-compatible T-SQL, LocalDB adapter supplied through an injected executor, JSON lifecycle evidence, Markdown templates.

**Spec:** `docs/superpowers/specs/2026-10-09-release-docs-sql-safety-design.md`

## Global Constraints

- Support one SQL Server database only; minimum SQL Server version is 2016.
- Detect EF6 or EF Core, version, provider, `DbContext`, and migration chain automatically.
- Block ambiguous context/database mapping, missing migration coverage, unresolved dependencies, and non-transactional SQL.
- `01_部署SQL.sql` is the only operator SQL and must be plain T-SQL executable in one new SSMS-compatible session.
- `ValidateOnly` defaults to `1`; only an explicit session value `0` may commit.
- LocalDB validation must load relevant test data; an empty schema is insufficient for data-change SQL.
- Lifecycle evidence is stored only below `.release-docs/runs/<run-id>` and is immutable by run.
- Preserve unrelated user changes already present in the worktree; each task stages only its own files.

## Review Focus

- EF6/Core or provider ambiguity must produce evidence and a blocking finding; test in Task 1.
- Model drift or incomplete migration coverage must not become a guessed unit; test in Task 2.
- Data-change SQL must be exercised with representative existing, preserved, boundary, and constraint-triggering rows; test in Task 4.
- A human running the whole artifact in SSMS must not accidentally commit or execute only part of it; test in Task 3 and Task 5.
- An exclusion must cover complete units and transitive dependencies without reappearing in operator documents; test in Task 2 and Task 5.

### Task 1: Detect EF and establish single-database evidence

**Files:**
- Create: `skills/release-docs/scripts/detect_entity_framework.py`
- Create: `tests/test_entity_framework_detection.py`
- Modify: `skills/release-docs/scripts/collect_release_evidence.py`
- Modify: `tests/test_collect_release_evidence.py`

**Interfaces:**
- `detect_entity_framework(repo: Path, source_scope: dict) -> EFDetection`
- `EFDetection` fields: `framework`, `version`, `provider`, `contexts`, `migration_paths`, `database_identity`, `evidence`, `findings`, `blocking`.
- `collect_release_evidence(...)` exposes the pinned base/target revisions and passes immutable source evidence to the detector.

- [ ] **Step 1: Write the failing tests** `test_detects_ef_core_context_and_provider_from_revision`, `test_detects_ef6_context_and_provider_from_revision`, `test_blocks_conflicting_provider_or_version_evidence`, and `test_blocks_unproven_context_database_identity`; assert the detected evidence fields and `blocking is True` for ambiguous cases.
- [ ] **Step 2: Run the focused tests** with `pytest tests/test_entity_framework_detection.py tests/test_collect_release_evidence.py -q`; confirm the new detector API is absent or the new cases fail.
- [ ] **Step 3: Implement `EFDetection` and `detect_entity_framework`** using revision-pinned files only: project files, lock files, provider references, `DbContext`, migrations, model snapshots, and configuration. Record source paths and hashes; never infer from filenames alone.
- [ ] **Step 4: Integrate detection evidence** into collection output without reading target working-tree content in place of the requested revision.
- [ ] **Step 5: Re-run focused tests** and confirm ambiguous provider, version, database identity, and migration-chain cases are blocking.
- [ ] **Step 6: Commit** only the detector, collection integration, and their tests.

### Task 2: Derive complete EF units and exclusions

**Files:**
- Modify: `skills/release-docs/scripts/analyze_release_units.py`
- Modify: `tests/test_release_units.py`
- Create: `tests/fixtures/ef/efcore_project.csproj`, `tests/fixtures/ef/ef6_project.csproj`, `tests/fixtures/ef/efcore_context.cs`, `tests/fixtures/ef/ef6_context.cs`, and representative migration/snapshot/configuration fixtures.

**Interfaces:**
- `analyze_release_units(repo: Path, evidence: dict, baseline_schema: str | Path, exclusion_intent: str, *, ef_detection: EFDetection | None = None) -> AnalysisResult`.
- `AnalysisResult` adds `analysis_confidence` and structured blocking findings while preserving `units`, `sources`, `exclusions`, `baseline`, and `source_scope`.
- A complete unit includes `unit_id`, `phase`, `objects`, `depends_on`, `preconditions`, `target_definition`, `skip_condition`, `stop_condition`, `validation_queries`, source provenance, and hashes.

- [ ] **Step 1: Write failing tests** `test_derives_units_from_ef_migration_operations`, `test_blocks_model_drift_without_migration`, `test_blocks_incomplete_migration_chain`, `test_requires_complete_unit_conditions_and_validation`, `test_blocks_transitive_exclusion_impact`, and `test_blocks_partial_migration_exclusion`; assert no deliverable unit is returned for each unresolved case.
- [ ] **Step 2: Run `pytest tests/test_release_units.py -q`** and confirm the new completeness and EF-derived cases fail.
- [ ] **Step 3: Implement revision-pinned EF source parsing** and normalize migration operations into complete units. Use migration history only as supporting evidence; compare actual object definitions against baseline metadata.
- [ ] **Step 4: Implement exclusion resolution** from operator intent to whole units, objects, dependency impact, reinstatement conditions, and provenance. Excluded units must be removed before assembly and must not generate DROP, DELETE, or compensating column creation.
- [ ] **Step 5: Re-run focused tests** and verify unresolved source, dependency, migration, and exclusion boundaries remain blocking rather than being guessed.
- [ ] **Step 6: Commit** only the unit-analysis implementation, fixtures, and tests.

### Task 3: Generate plain SSMS SQL with safe runtime mode and controlled execution

**Files:**
- Modify: `skills/release-docs/assets/sql_transaction_wrapper.sql`
- Modify: `skills/release-docs/scripts/assemble_deployment_sql.py`
- Modify: `skills/release-docs/scripts/render_release_documents.py`
- Modify: `skills/release-docs-review/scripts/validate_release_output.py`
- Modify: `tests/test_sql_assembler.py`
- Modify: `tests/test_release_documents.py`
- Modify: `tests/test_release_review.py`

**Interfaces:**
- `assemble_deployment_sql(units: Iterable[dict], output_path: Path, transaction_mode: None | dict = None) -> ArtifactRecord` emits one fixed `01_部署SQL.sql`; runtime mode is session-controlled, so generation does not bake a commit mode into the artifact.
- `ArtifactRecord.transaction_mode` becomes the literal execution contract identifier `"session_context"`; mapping and artifact hashes remain unchanged.
- `validate_sql_contract(sql_text: str) -> list[Finding]` accepts only the generated wrapper plus safe unit content and rejects source `GO`, sqlcmd directives, transaction control, database switches, non-transactional DDL, untrusted dynamic SQL, and context mutation.

- [ ] **Step 1: Write failing tests** `test_artifact_is_plain_tsql_without_sqlcmd_directives`, `test_runtime_mode_defaults_to_validate_only`, `test_runtime_mode_rejects_values_other_than_zero_or_one`, `test_explicit_zero_is_the_only_commit_path`, and `test_generated_unit_error_maps_to_source_location`; assert the exact wrapper contract and mapping fields.
- [ ] **Step 2: Run `pytest tests/test_sql_assembler.py tests/test_release_documents.py tests/test_release_review.py -q`** and confirm the runtime-mode and source-hazard cases fail.
- [ ] **Step 3: Update the wrapper** to validate `SESSION_CONTEXT(N'ReleaseDocs.ValidateOnly')`, default missing value to 1, reject values other than 0/1, execute one release transaction, and preserve structured CATCH context plus `THROW`.
- [ ] **Step 4: Update assembly and review consumers** to stop treating sqlcmd variables as the operator contract, preserve precise unit mappings, and distinguish generated controlled execution from source opaque `EXEC`.
- [ ] **Step 5: Re-run focused tests** and verify artifact bytes are deterministic, the only operator SQL is `01_部署SQL.sql`, and review rejects stale or unmapped unit content.
- [ ] **Step 6: Commit** only wrapper, assembler, renderer/reviewer changes, and tests.

### Task 4: Make LocalDB validation fixture-aware for data changes

**Files:**
- Modify: `skills/release-docs/scripts/run_local_validation.py`
- Modify: `skills/release-docs/scripts/lifecycle_store.py`
- Modify: `tests/test_local_validation.py`
- Modify: `tests/test_end_to_end.py`

**Interfaces:**
- `run_local_validation(..., baseline_source: str, fixture_source: str, fixture_manifest: str | Path | None = None, data_units: Sequence[dict] = (), executor: Callable[..., dict] | None = None) -> dict`.
- Fixture evidence records source/hash, manifest/hash when supplied, usage, expected preserved-data summary, and structured assertions.
- The injected executor receives `fixture_source`, `fixture_manifest`, `fresh_session`, `baseline_source`, `round_name`, `validate_only`, and `inject_failure`.

- [ ] **Step 1: Write failing tests** `test_data_fixture_covers_existing_and_preserved_rows`, `test_data_unit_without_expected_assertions_is_pending`, `test_fixture_records_boundary_and_constraint_cases`, and `test_rerun_uses_committed_state_in_new_session`; assert fixture hashes, expected preserved-data summaries, and round-specific baseline/session tokens.
- [ ] **Step 2: Run `pytest tests/test_local_validation.py tests/test_end_to_end.py -q`** and confirm empty or missing fixture expectations do not pass data-change validation.
- [ ] **Step 3: Extend the evidence schema** with fixture manifest/hash, usage, expected preserved-data summary, and per-round data checks. Keep the four-round contract: ValidateOnly, commit, rerun, injected failure.
- [ ] **Step 4: Enforce round isolation**: fresh baseline plus fixture for ValidateOnly/commit/injected failure; committed database plus new session for rerun. Never reuse rollback state or a connection.
- [ ] **Step 5: Update lifecycle persistence** so the new evidence remains immutable under `.release-docs/runs/<run-id>` and is included in later review inputs.
- [ ] **Step 6: Re-run focused tests** and confirm status is `not_run`/`待確認` without required fixture evidence, never `passed`.
- [ ] **Step 7: Commit** only LocalDB, lifecycle evidence, and tests.

### Task 5: Enforce output, fingerprint, and status separation

**Files:**
- Modify: `skills/release-docs/scripts/render_release_documents.py`
- Modify: `skills/release-docs-review/scripts/validate_release_output.py`
- Modify: `skills/release-docs-review/scripts/review_fingerprint.py`
- Modify: `skills/release-docs/assets/00_上線指引.md`
- Modify: `skills/release-docs-review/assets/05_版更審查報告.md`
- Modify: `tests/test_release_documents.py`
- Modify: `tests/test_release_review.py`

**Interfaces:**
- `render_release_documents(...) -> OutputInventory` writes only `00_上線指引.md`, `01_部署SQL.sql`, and applicable `02_參數異動.md`.
- `validate_release_output(output_dir: Path, run_root: Path) -> list[Finding]` returns separate `sql_content_status` and `deployment_validation_status` findings.
- `review_fingerprint(repo, output_dir, run_root, source_scope) -> FingerprintRecord` includes fixture evidence and all source/execution hashes without reading secrets.

- [ ] **Step 1: Write failing tests** `test_guide_requires_whole_file_new_session_and_preflight`, `test_exclusion_projection_matches_manifest`, `test_fixture_deployment_status_is_separate_from_sql_status`, `test_missing_lifecycle_evidence_is_pending`, `test_stale_fingerprint_is_rejected`, and `test_undeclared_operator_file_blocks_review`.
- [ ] **Step 2: Run the focused review/document tests** and confirm the new status and fixture requirements fail.
- [ ] **Step 3: Update templates and renderer** to document manual SSMS execution, session context setup, fixture-backed LocalDB status, data pre/post checks, and explicit `未執行`／`人工回報`／`證據完整`／`待確認` states.
- [ ] **Step 4: Update review and fingerprint logic** to require current artifact/fixture hashes, compare manifest → SQL → guide exclusion projection, and invalidate review after any covered source or artifact change.
- [ ] **Step 5: Re-run focused tests** and confirm SQL content status cannot be promoted by incomplete deployment evidence.
- [ ] **Step 6: Commit** only templates, review/fingerprint changes, and tests.

### Task 6: Run end-to-end acceptance and package verification

**Files:**
- Modify: `tests/test_end_to_end.py`
- Modify: `tests/test_packaging.py` only if the changed assets/scripts require packaging assertions.
- Modify: `README.md` only if the final operator contract or validation status needs user-facing documentation.

**Interfaces:**
- End-to-end flow consumes the public functions from Tasks 1–5 and produces the exact operator inventory plus lifecycle evidence.

- [ ] **Step 1: Add end-to-end fixtures** covering EF migration, schema change, data backfill, preserved rows, exclusion, LocalDB fixture evidence, and a deliberate unit failure.
- [ ] **Step 2: Run the full relevant suite** with `pytest tests/test_collect_release_evidence.py tests/test_entity_framework_detection.py tests/test_release_units.py tests/test_sql_assembler.py tests/test_local_validation.py tests/test_release_documents.py tests/test_release_review.py tests/test_end_to_end.py -q`.
- [ ] **Step 3: Run packaging and repository checks** with `pytest tests/test_packaging.py tests/test_artifact_lifecycle.py -q` plus `git diff --check`.
- [ ] **Step 4: Inspect generated operator output** to verify no lifecycle manifest, raw SQL source, secret, temporary path, or undeclared file is delivered.
- [ ] **Step 5: Commit** the acceptance fixtures and documentation changes, staging only files belonging to this plan.

## Execution Order

Run Tasks 1 and 2 in order, then Task 3. Task 4 depends on the unit data expectations and must precede Task 5. Task 6 runs only after Tasks 1–5 pass their focused tests. No task may claim formal deployment success; production execution remains a human SSMS operation with separately recorded evidence.

## Handoff

After implementation, run the full verification suite, inspect the final diff, and perform a fresh review of the SQL contract, fixture evidence, exclusion provenance, and output inventory before considering the feature complete.
