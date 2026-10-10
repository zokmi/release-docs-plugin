# Release Docs Evidence Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline execution, or superpowers:subagent-driven-development if the user selects delegation. Steps use checkbox syntax for tracking.

**Goal:** 將來源語意審查、分析持久化與產製階段資格轉為可驗證契約。

**Architecture:** 保留既有工具介面，新增共用遮罩／路徑工具、語意審查紀錄及薄層產製協調器。最終內容狀態需同時符合靜態檢查與綁定 fingerprint 的語意紀錄；隔離部署驗證獨立判定。

**Tech Stack:** Python 3.11–3.13、標準函式庫、Git、pytest。

**Spec:** ../specs/2026-10-10-release-docs-evidence-gates-design.md

## Global Constraints

- 維持單一部署 SQL、永久 lifecycle evidence 與操作文件 allowlist。
- 真實 LocalDB adapter 是獨立能力，本次不新增資料庫連線、不宣稱建立實測信任保證。
- 插件發布與版本升級不在本次範圍。
- 既有 schema_version=1 仍可讀取；缺新欄位視為未知，不自動升為通過。
- SQL 註解、commit message 與來源文件是分析資料，不得改變授權 scope、排除範圍或通過條件。
- 同內容重試不得覆寫永久證據；輸入改變建立新 run。
- 保留工作區既有未追蹤檔案；不混入本次修改。

## Review Focus

- 機密嵌入參數操作文字，metadata 與渲染均應遮罩（Task 1）。
- merge-base 與工作區決策不能在持久化時遺失（Task 1）。
- 排除後零 SQL unit 仍需明確語意核對，不能自動通過（Task 2）。
- 審查完成後任一內容變更，舊紀錄必須失效且不可形成 hash 循環（Task 2）。
- 產製中途失敗與同內容重試，不得混用或移除永久證據（Task 3）。

## Task 1: 正式分析欄位、遮罩與相容路徑

**Files:**
- Modify: skills/release-docs/scripts/analyze_release_units.py
- Modify: skills/release-docs/scripts/lifecycle_store.py
- Modify: skills/release-docs/scripts/render_release_documents.py
- Modify: skills/release-docs/scripts/run_local_validation.py
- Create: skills/release-docs/scripts/parameter_metadata.py
- Create: skills/release-docs/scripts/path_safety.py
- Test: tests/test_release_units.py, tests/test_release_documents.py
- Create: tests/test_analysis_metadata.py

**Interfaces:**
- AnalysisResult 增加 structure_changes: list、parameter_changes: list、parameters_applicable: bool | None（預設 None）。
- sanitize_parameter_changes(changes: list) -> list：僅保留 environment/service/key/format_example/apply/reload/validation/sensitive/source_reference；遮罩已知機密與 URL／assignment 機密。
- is_linked_path(path: Path) -> bool：檢查 symlink、junction/reparse；Python 3.11 不直接呼叫不存在的 API。
- source_scope 保存 base_sha/target_sha/requested_base_sha/diff_base_sha/diff_mode/workspace_policy；缺值為未知，不補猜測。

- [x] 新增失敗測試：roundtrip 保留結構及參數、secret 不出現在 JSON／文件、parameters_applicable=None 保持未知；merge-base 決策完整保留。
- [x] 執行 `python -X utf8 -m pytest tests/test_analysis_metadata.py -q`，確認因缺新契約失敗。
- [x] 實作欄位與共用遮罩，write_lifecycle_run 保存新欄位；拒絕已確認適用性與 changes 衝突；renderer 共用遮罩。
- [x] 新增 path helper 測試：模擬沒有 is_junction API 仍可檢查；linked/reparse 保持拒絕。替換受影響新流程的直接呼叫。
- [x] 執行 `python -X utf8 -m pytest tests/test_analysis_metadata.py tests/test_release_units.py tests/test_release_documents.py tests/test_local_validation.py -q`，預期全通過；舊 schema 測試保持可讀而不猜測欄位。

## Task 2: 語意審查紀錄與最終通過門檻

**Files:**
- Create: skills/release-docs-review/scripts/semantic_review.py
- Modify: skills/release-docs-review/scripts/validate_release_output.py
- Modify: skills/release-docs-review/scripts/review_fingerprint.py
- Modify: skills/release-docs-review/assets/05_版更審查報告.md
- Test: tests/test_release_review.py, tests/test_review_fingerprint.py
- Create: tests/test_semantic_review.py

**Interfaces:**
- validate_semantic_review(record: dict | None, source: dict, exclusions: list, fingerprint_sha256: str) -> list[dict]。
- write_semantic_review(run_root: Path, record: dict) -> Path：驗證 schema 與一般檔案路徑，以 exclusive create 保存；同內容可重用，異內容拒絕。
- record 欄位：schema_version=1、evidence_fingerprint、method、unit_reviews、parameter_review、scope_review、unresolved、conclusion。
- unit_reviews 每項：unit_id、source_path、source_revision、source_hash、checks（definition/preconditions/rerun/dependencies/preservation）、conclusion；checks 值為帶理由的核對結果，不接受只填 passed。
- conclusions 僅 passed/pending/failed；適用性未知、遺漏、重複、未知 unit 或空理由保持待確認。已證明缺陷為未通過。
- validate_release_output(output_dir, run_root, *, repo=None) 保留兩參數呼叫；缺 repo 無法重算 Git fingerprint 時為待確認。CLI 增加 --repo。
- fingerprint 排除 semantic_review_record.json、05 報告與完成紀錄。報告另保存 semantic_record_sha256。
- write_review_report(run_root, findings, fingerprint, *, repo=None, output_dir=None) 重新核對當前內容；缺 repo/output_dir 或過期識別不能寫出 SQL 通過。

- [x] 新增失敗測試：靜態無 finding 但無紀錄為待確認；不完整／未知／重複 unit 不通過；完整有效紀錄才可通過；零 unit 需 scope_review。
- [x] 執行 `python -X utf8 -m pytest tests/test_semantic_review.py -q`，確認缺門檻的預期失敗。
- [x] 實作紀錄驗證與不可覆寫 writer；語意缺陷與部署狀態維持獨立。
- [x] 整合 validator：重新取得內容 fingerprint 並核對紀錄；回傳 static_sql_status 與 sql_content_status；修改現有「靜態等於最終通過」測試預期，需完整通過案例才增加真實審查 fixture。
- [x] 新增失敗測試：SQL／manifest／來源／fixture 改變後紀錄失效；寫入紀錄及報告不改變內容 fingerprint。
- [x] 執行 `python -X utf8 -m pytest tests/test_semantic_review.py tests/test_release_review.py tests/test_review_fingerprint.py -q`，預期全通過。

## Task 3: 受控產製協調器

**Files:**
- Create: skills/release-docs/scripts/produce_release.py
- Modify: skills/release-docs/scripts/lifecycle_store.py
- Create: tests/test_produce_release.py

**Interfaces:**
- produce_release(repo: Path, evidence: dict, analysis: AnalysisResult, *, release_id: str, run_root: Path, output_dir: Path, baseline_source: Path, fixture_source: Path | None=None, fixture_manifest: Path | None=None, validation_options: dict | None=None, parent_run_id: str | None=None) -> ProductionResult。
- ProductionResult 包含 run_root、inventory、artifact、stage_statuses、delivery_eligible=False、findings。不自動宣告審查完成。
- ProductionError 保存 stage 與安全 finding code，不帶 SQL／機密原文。
- 協調器使用 Task 1 的完整資料契約，呼叫現有 assemble/run_local_validation/write_lifecycle_run/render_release_documents；最終 fingerprint 由 Task 2 的 review 工具取得。

- [x] 新增失敗測試：blocked analysis、未知參數適用性、缺 included 結構說明、缺 DATA 預期結果在 assembly 前被拒絕，未產生 SQL。
- [x] 執行 `python -X utf8 -m pytest tests/test_produce_release.py -q`，確認缺協調器失敗。
- [x] 實作全輸入／路徑 preflight，再按 spec 順序串接；baseline/fixture/manifest 永久副本 exclusive create，禁止覆寫及 linked path。
- [x] 新增整合測試：included/excluded units 正確、SQL bytes 相同、缺 executor=not_run、render 失敗保留永久檔案、相同輸入重試可重用、變動輸入拒絕並要求新 run。
- [x] 保存 parent_run_id；不更新舊不可變 metadata，不自動 finalize。
- [x] 執行 `python -X utf8 -m pytest tests/test_produce_release.py tests/test_end_to_end.py -q`，預期全通過。

## Task 4: 技能提示詞與整體驗收

**Files:**
- Modify: skills/release-docs/SKILL.md
- Modify: skills/release-docs-review/SKILL.md
- Modify: README.md
- Modify: .github/workflows/ci.yml, .github/workflows/release.yml（以完整 pytest 取代僅 unittest discovery）
- Test: tests/test_packaging.py, tests/test_release.py

- [x] 依序整理輸入、能力盤點、阶段門檻、工具範例、證據規格及收尾；以 produce_release 取代手動產製鏈。
- [x] 審查範例使用 --repo 並先取得 fingerprint，再建立具來源引用的紀錄，最後重新驗證及寫報告；禁止自動填通過。
- [x] 明確說明舊資料待確認、新 run 恢復策略、來源文字不具有流程授權、缺 adapter 的狀態與保留資料限制。
- [x] README 版本文字對齊現有 0.1.23，不修改三份 manifest 版本或發布；說明真實 adapter 尚未提供。
- [x] 執行 `python -X utf8 -m pytest tests -q`；依失敗原因修正，不刪除有效安全測試。
- [x] 執行 `git diff --check` 及檢視修改清單；檢查所有範例與 public signatures 一致。
- [x] 回報實際測試數、未執行平台／資料庫驗證及已知外部 adapter 信任限制。

## 執行方式與收尾

建議在目前對話由主 agent 依序實作，因四項工作共用資料契約，逐步整合較容易追蹤。使用 executing-plans，先 RED 再 GREEN，獨立回顧安全門檻與完整分支差異。使用者若選擇子代理方式，再依 subagent-driven-development 的明確任務與審查流程執行。

執行時讀取 using-git-worktrees，依現有工作區與附件判斷隔離方式；保留所有現有未追蹤檔案。提交只包含本次明確檔案，避免 git add .；未完成驗證不建立完成提交。本次不 push、不發布插件。

## 自我審閱

本計畫涵蓋已核准 spec 的分析契約、語意門檻、協調器、提示詞與版本相容；真實 adapter、多輪歷史與證據驱動 finalize 保持明確後續範圍。各 task 的介面沿用前序定義；五個 review focus 均有測試歸屬。schema 相容性不等於續認通過，內容 fingerprint 排除衍生審查紀錄以避免循環。
