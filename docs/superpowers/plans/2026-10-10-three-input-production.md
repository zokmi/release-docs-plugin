# Three-input Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 使用者只提供正式 DB baseline、Git diff 範圍與例外意圖，插件自動取得證據並產製可審查的部署輸入與文件。

**Architecture:** 新增 discovery 與 derived-source 契約，再串接既有 analyzer、producer、lifecycle、review。將工具產製、來源推導與 DB 實測分開；任一未知不得變成通過。

**Tech Stack:** Python 標準函式庫、Git、pytest；實際可用的 SQL Server／SqlPackage／專案建置工具及隔離 runner。

**Spec:** ../specs/2026-10-10-three-input-production-design.md

## Global Constraints

- 不執行正式部署、不讀取正式資料作 fixture、不自動改 repo／commit。
- 工作區異動預設排除並清楚回報；實際 DB baseline 與 Git 比較起點分開保存。
- 不要求使用者提供整份 descriptor、fixture、四輪預期；來源歧義只問最小問題。
- 保留現有 pinned_git 行為；未知 source type、provider、語法與不可交易 DDL fail closed。
- 所有永久證據存於 run；四輪執行與独立審查後才能宣稱符合交付門檻。
- Python 3.11–3.13、Windows／Linux 保持兼容，無強制新增 Python 套件。

## Review Focus

1. target-only project 不捏造 base project（Task 3）。
2. 正式 baseline 已有 excluded object，保留原定義而非 DROP（Task 3/4）。
3. 同一來源有多個 provider/context 或 migration 分叉，不能選第一個（Task 1）。
4. 動態 SQL／獨立 COMMIT 不因 metadata 完整就合格（Task 4）。
5. 衍生 artifact 被覆寫、連結或換來源後舊報告失效（Task 2/5）。
6. 既有 SSMS／sqlcmd migration 的 `GO`、內部 transaction、dynamic `EXEC`、metadata procedure 與 `RAISERROR` 不由 assembler 靜默改寫；必須由 provider 產生 `derived_artifact`，或保留 blocking finding（Task 3/4）。

## 支援策略與介面共同約定

`ProductionInputs(repo: Path, baseline: Path, base: str, target: str, exclusion_intent: list[dict], diff_mode='direct', workspace_policy='excluded')` 為程式入口；後兩項為固定預設與既有決策，不增加使用者必填。

discovery 自動取得 source inventory／provider／chain／tool capabilities；完整來源語意、排除歸屬、fixture assertions 由代理按技能分析生成機器可讀候選，程式負責驗證，不能聲稱已有任意 SQL 語意解析器。第一階段執行 provider 為 SQL Server；既有 EF 支援保持。SSDT 使用實際 build／SqlPackage 工具；legacy SQL 以精確来源及經核對的衍生 repair 接入。未支援操作保留 blocker。

### Task 1: 自動來源與能力探索

**Files:** Create `skills/release-docs/scripts/discover_release_sources.py`; Test `tests/test_source_discovery.py`; Modify `detect_entity_framework.py` only where reuse requires it.

**Interfaces:** `discover_release_sources(inputs: ProductionInputs) -> DiscoveryResult`；result 包含 evidence、sources、provider_evidence、migration_chain、capabilities、findings。sources 為 revision/path/hash/kind，capabilities 為工具 path/version/status，不含 secret。

- [ ] 寫 RED：`test_only_three_required_inputs` 可從真實測試 Git repo 找到未變動引用；`test_provider_conflict_blocks`；`test_chain_gap_not_empty_release`；`test_missing_path_tool_fallback`；斷言 pinned revisions、候選保留、未知不自動通過。
- [ ] 執行 `python -X utf8 -m pytest tests/test_source_discovery.py -q` 確認有意義失敗。
- [ ] 實作完整 tree 與安全工具探測；重用 collector／EF detection，不執行 repo 任意腳本、不輸出原始配置值。
- [ ] 跑同檔與既有 EF detection 測試，全部通過；提交本任務精確檔案。

### Task 2: 不可變衍生來源

**Files:** Create `skills/release-docs/scripts/derived_sources.py`; Test `tests/test_derived_sources.py`; Modify `analyze_release_units.py`, `produce_release.py`, `lifecycle_store.py`。

**Interfaces:** `register_derived_source(run_root: Path, sql_bytes: bytes, provenance: dict) -> dict`; `verify_source(repo: Path, run_root: Path, source: dict, scope: dict) -> bytes`。schema_version=2，source_type 為 pinned_git／derived_artifact；provenance 綁定 scope、baseline hash、輸入 sources、method/tool/version/arguments、mapping、輸入／輸出 hash。既有 schema_version=1 讀取為 pinned_git。

- [ ] RED：`test_derived_bytes_do_not_require_git_commit` 驗證無新 commit亦可合法讀取；`test_mutated_input_or_output_rejected`；`test_link_and_external_path_rejected`；`test_unknown_type_rejected`；`test_v1_git_compatibility`。
- [ ] 執行 `python -X utf8 -m pytest tests/test_derived_sources.py -q` 確認失敗。
- [ ] 實作永久 bytes／provenance 保存及共同驗證；analyzer/producer 改調共同 verifier，不偽填 revision；lifecycle 保存完整 source type與 chain。
- [ ] 同檔、release units、producer 回歸通過後提交。

### Task 3: SQL 工具產製 adapter

**Files:** Create `skills/release-docs/scripts/database_project_adapter.py`; Test `tests/test_database_project_adapter.py` and `tests/integration/test_database_project_execution.py`。

**Interfaces:** `generate_project_artifact(inputs: ProductionInputs, discovery: DiscoveryResult, run_root: Path, model_transform: dict | None = None) -> dict`；返回 Task 2 source 或具體 blocking finding。只用已核對建置方式、官方工具 help 與隔離路徑；model_transform 記錄排除來源副本變換，不改原 repo。

- [ ] RED：`test_target_only_uses_formal_baseline`、`test_existing_excluded_object_preserved`、`test_tool_failure_retains_evidence`、`test_target_create_script_not_deployment`；斷言輸入 hash／工具命令及原 repo 不變。
- [ ] 執行 adapter 測試，確認失敗。
- [ ] 實作 build/model compare與原始 plan/script 保存；target-only 使用已授權隔離 DB物化 baseline後取模型。不能安全排除即 blocker，不刪除 SQL文字。對 `GO`、dynamic `EXEC`、metadata procedure、RAISERROR 與 unit transaction 逐項保存 finding；只有 provider 產生帶 mapping 的 derived execution body 才能接入 producer。
- [ ] 跑單元測試及實際工具整合；未安裝工具的整合測試明確 skip、不冒稱成功。成功案例須真實 SqlPackage 與 disposable DB；提交並回報實測能力。

### Task 4: 三項輸入 orchestration 與機器可讀候選

**Files:** Create `skills/release-docs/scripts/prepare_release.py`; Test `tests/test_prepare_release.py`; Modify `source-discovery.md`, `SKILL.md`。

**Interfaces:** `prepare_release(inputs: ProductionInputs, run_root: Path, semantic_inputs: dict | None = None) -> PreparationResult`。semantic_inputs 是插件代理由來源自行生成的 descriptors／descriptions／fixtures／assertions／exclusions／parameters，不是使用者第四項輸入。result 含 discovery、candidate_inventory、analysis、permanent_inputs、stage_statuses、findings；候選未齊可保存準備狀態，不調 producer。

- [ ] RED：`test_three_input_flow_consumes_generated_descriptors`、`test_blocked_analysis_keeps_candidates`、`test_mixed_schema_data_effects`、`test_transaction_hazards_remain_blocked`、`test_missing_business_rule_is_precise_gap`；不能填恆真查詢或擴大排除。
- [ ] 跑 `python -X utf8 -m pytest tests/test_prepare_release.py -q` 確認失敗。
- [ ] 串接 discovery/adapter/derived sources，驗證代理產製 schema、fixture coverage／四輪預期、參數適用性；先固定 expected，再交 runner。缺欄位回報定位並允許補齊後新 run，不停在計畫文件。
- [ ] 同檔與 producer／runner 回歸通過；技能記錄真實 API與來源修復迴圈，提交。

### Task 5: 衍生來源審查與指紋

**Files:** Modify `skills/release-docs-review/scripts/review_fingerprint.py`, `semantic_review.py`, `validate_release_output.py`, review `SKILL.md`; Test `tests/test_derived_review.py`。

**Interfaces:** 既有 review API 保持兼容；schema=2 unit review 使用 source_type/source_identity／provenance 引用，schema=1 保留 Git欄位。fingerprint 綁定完整來源閉包、baseline、工具原始產物／repair／descriptor／fixture／expected與 operator files，排除衍生 review/report循環。

- [ ] RED：`test_generated_source_independently_reviewed`、`test_all_derivation_inputs_invalidate_report`、`test_missing_mapping_pending`、`test_legacy_review_still_supported`。
- [ ] 跑該檔確認失敗，再實作 source verifier整合與版本化語意紀錄；不能 auto passed。
- [ ] 該檔、semantic review、release review全部通過後提交。

### Task 6: 兩張異動表與最終驗收

**Files:** Modify `render_release_documents.py`, `analyze_release_units.py`, `lifecycle_store.py`, `produce_release.py`, `validate_release_output.py`; Test `tests/test_release_documents.py`, `tests/test_three_input_end_to_end.py`; Update `README.md`。

**Interfaces:** 結構描述沿用既有欄位並可加 before/after/source_location；data_changes descriptor 為 unit_id/object/operation/condition/before/after/preservation/validation/source_location，持久化 schema=2。renderer 輸出兩張符合技能欄位的 Markdown 表；未知不省略、不稱無異動。

- [ ] RED：`test_both_change_tables_required`、`test_dynamic_data_effect_in_schema_unit`、`test_excluded_rows_not_rendered`、`test_no_change_requires_analysis_reason`；新增完整三項輸入的真實 Git end-to-end。
- [ ] 執行兩檔確認失敗，再實作 rendering／descriptor資格／文件查核；重新算 inventory與 fingerprint，不後補文件繞過。
- [ ] 用真實隔離 adapter驗證四輪及 mutation 後注入失敗；沒有 adapter的端到端只證明文件／內容流程、部署 not_run。
- [ ] 執行 `python -X utf8 -m pytest tests -q`；必要平台矩陣、套件檢查与獨立審查通過。README 明列支援操作及未實測能力，不更新發布版本直到使用者要求發布。
- [ ] 提交精確檔案並回報結果／限制。

## 執行準備與自審

執行時先套用 using-git-worktrees；若 sandbox不允許使用 native worktree，使用先前已核准的本地 feature branch fallback並保留無關未追蹤檔案。測試用實際 Python313 executable，Git寫入依環境 escalation。每任務 RED→GREEN，不並行改共享介面。

自審：規格各段分別映射 Task1–6；五項 review focus均有對應測試；schema=2明確保存兼容行為；無工具／adapter不偽造成功。全自動業務語意由代理工作流完成，程式不承諾通用SQL解析；這項能力區分在Task4與README驗收。
