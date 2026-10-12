# 自動產製參數異動文件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 從 pinned base/target source diff 自動建立參數異動 descriptor，並產出含 Markdown 說明與可複製脫敏 JSON 的 `02_參數異動.md`。

**Architecture:** 新增純函式參數 diff/discovery 層，輸入已核對的 base/target bytes 與來源 metadata，輸出 parameter descriptors 及檢查範圍。既有 production flow 使用該結果填入 `AnalysisResult`，renderer 以同一批 sanitized descriptors 同時產生範本式業務情境表、分組設定 JSON、環境變數範例、部署查核與 canonical JSON，lifecycle metadata 保存 applicability 與檢查證據。

**Tech Stack:** Python 3.11+, pytest, stdlib `json`／`configparser`／`xml.etree`，既有 release-docs lifecycle 與 redaction utilities。

**Spec:** `docs/superpowers/specs/2026-10-12-automatic-parameter-change-document-design.md`

## Global Constraints

- 只讀取 pinned base/target revision，不讀 working tree 代替來源。
- 不輸出正式 secret、raw sensitive old/new value 或 credential。
- `environment`、`service`、完整 `key` 缺任一項時阻擋產製。
- `parameter_group`、`business_context`、`module`、`users`、`impact` 必須有來源或明確標示 `待確認`，不得從 key 名稱猜測。
- 有參數異動必須產出 `02_參數異動.md`；無異動不得產出。
- table 與 JSON 必須來自同一批 sanitized descriptors。
- `02_參數異動.md` 必須依範本順序包含來源/安全說明、業務情境與模組對照、參數分節、設定 JSON、環境變數覆寫與部署後查核。
- 不修改 `01_部署SQL.sql` 或正式資料驗證邏輯。

## Review Focus

- appsettings nested object／array index 必須展平成完整 key。
- 新增、修改、刪除與 `null`／空字串／`false`／`0` 必須區分。
- environment variable double-underscore mapping 不得誤判優先順序。
- 設定異動存在但 environment/service/consumer 證據不足時不得靜默略過。
- JSON 中不得洩漏 secret、URL credential 或敏感 assignment。

---

### Task 1: 建立設定 diff 與 descriptor discovery

**Files:**
- Create: `skills/release-docs/scripts/parameter_discovery.py`
- Test: `tests/test_parameter_discovery.py`

**Interfaces:**
- `discover_parameter_changes(base_sources: list[dict], target_sources: list[dict], *, consumer_sources: list[dict] | None = None, deployment_sources: list[dict] | None = None) -> ParameterDiscoveryResult`
- `ParameterDiscoveryResult.changes: list[dict]`
- `ParameterDiscoveryResult.checked_sources: list[dict]`
- `ParameterDiscoveryResult.applicable: bool | None`
- `ParameterDiscoveryResult.findings: list[dict]`

- [x] **Step 1: Write failing tests** for JSON object diff, add/update/remove, null/false/0 distinction, nested keys, array indices, source references, and no-change checked scope.
- [x] **Step 2: Run discovery tests and verify expected failure** because the module/API does not exist.
- [x] **Step 3: Implement minimal recursive JSON diff** with stable key ordering and explicit missing sentinel; preserve source path/revision/line metadata and presentation metadata supplied by caller.
- [x] **Step 4: Add environment variable mapping tests and implementation** for `Foo__Bar` → `Foo:Bar`, without assuming provider precedence when consumer/provider evidence is absent.
- [x] **Step 5: Add descriptor completeness validation** so missing environment/service/key yields a blocking finding rather than an omitted change.
- [x] **Step 6: Run `pytest tests/test_parameter_discovery.py -q` and verify pass.**
- [x] **Step 7: Commit** `feat: discover parameter changes from pinned sources`.

### Task 2: 將 discovery 接入 analysis/production contract

**Files:**
- Modify: `skills/release-docs/scripts/analyze_release_units.py`
- Modify: `skills/release-docs/scripts/produce_release.py`
- Modify: `skills/release-docs/scripts/lifecycle_store.py`
- Test: `tests/test_produce_release.py`
- Test: `tests/test_analysis_metadata.py`

**Interfaces:**
- Analysis keeps `parameter_changes`, `parameters_applicable`, and adds checked parameter source metadata without changing SQL unit contracts.
- Production preflight rejects a confirmed config diff whose descriptor set is incomplete or missing.

- [x] **Step 1: Write failing integration tests** proving an appsettings-only change populates `analysis.parameter_changes`, sets applicability true, and cannot produce SQL-only output.
- [x] **Step 2: Run the focused tests and verify failure** showing the current empty-list default causes omission.
- [x] **Step 3: Wire discovery output into analysis preparation** using pinned source inventory, preserving checked sources and findings.
- [x] **Step 4: Tighten production preflight** to distinguish `no confirmed config changes` from `config changes detected but unresolved`; reject the latter before any operator output is written.
- [x] **Step 5: Persist `parameters_applicable` and checked-source evidence in lifecycle metadata** while preserving secret redaction.
- [x] **Step 6: Run focused producer/metadata tests and verify pass.**
- [x] **Step 7: Commit** `feat: enforce automatic parameter document eligibility`.

### Task 3: 產生範本式參數文件與可複製 JSON

**Files:**
- Modify: `skills/release-docs/scripts/render_release_documents.py`
- Modify: `skills/release-docs/assets/02_參數異動.md`
- Test: `tests/test_release_documents.py`

- [x] **Step 1: Write failing tests** asserting the parameter document follows the template order: source/safety preface, business/module table, grouped parameter sections, per-section configuration JSON, optional `text` environment overrides, deployment checklist, canonical fenced JSON array, and table/JSON values from the same sanitized descriptors.
- [x] **Step 2: Run the focused renderer tests and verify failure** because the current renderer emits only a table.
- [x] **Step 3: Implement one sanitized descriptor projection** used by table, business/module mapping, grouped configuration JSON, environment-variable examples, checklist, and canonical JSON; include `add`/`update`/`remove`, old/new values only after redaction, and `source_reference`.
- [x] **Step 4: Update the asset template** with stable sections, ` ```json ` and ` ```text ` blocks, business/module table, deployment checklist, and copy instructions.
- [x] **Step 5: Add parser and secret-leak assertions** for JSON validity, sensitive key masking, URL credentials, and known secret removal.
- [x] **Step 6: Run `pytest tests/test_release_documents.py -q` and verify pass.**
- [x] **Step 7: Commit** `feat: render copyable parameter change json`.

### Task 4: End-to-end regression and documentation

**Files:**
- Modify: `skills/release-docs/SKILL.md`
- Modify: `skills/release-docs/source-discovery.md`
- Modify: `README.md`
- Test: `tests/test_packaging.py`
- Test: `tests/test_end_to_end.py`

- [x] **Step 1: Add end-to-end tests** for appsettings add/update/remove producing exactly `00_上線指引.md`, `01_部署SQL.sql`, and `02_參數異動.md`; no-change producing only the first two.
- [x] **Step 2: Add a blocked-case test** proving incomplete config evidence stops before partial output.
- [x] **Step 3: Update skill documentation** to state automatic discovery, JSON contract, and blocking behavior.
- [x] **Step 4: Run focused end-to-end/packaging tests and verify pass.**
- [x] **Step 5: Run the complete test suite, `git diff --check`, and release gate checks.**
- [x] **Step 6: Commit** `docs: document automatic parameter change delivery`.

## Verification Commands

```powershell
pytest.exe tests/test_parameter_discovery.py tests/test_produce_release.py tests/test_analysis_metadata.py tests/test_release_documents.py tests/test_end_to_end.py tests/test_packaging.py -q
pytest.exe tests -q
git diff --check
```

## Completion evidence

Tasks 1–4 completed. Full regression at baseline revision `d56e9de`: 961 passed, no skips. Later renderer privacy changes: impacted integration suite 187 passed; final alias-only renderer suite 79 passed; independent scoped review clean. These are separate verification runs, not one whole-suite result for the final renderer revision. Exact commands, revisions and limitations are in `task-4-report.md`.

Package resources/version and whitespace gates passed. Tag/remote-main publication gates remain a release-time step; no merge, push or publication was performed in this feature task.

## Self-review

- Spec coverage: discovery, applicability, blocking, redaction, JSON, no-change behavior, and regression tests are mapped to Tasks 1–4.
- Step scan: each task has a failing-test step before implementation and an independently runnable verification command.
- Type consistency: discovery result fields feed the existing analysis fields; renderer consumes the sanitized descriptor list without changing SQL artifact interfaces.
- Review focus: all five listed failure modes have tests in Tasks 1–4.
- Proportion: the plan adds one focused discovery module and extends existing lifecycle/render paths without unrelated refactoring.
