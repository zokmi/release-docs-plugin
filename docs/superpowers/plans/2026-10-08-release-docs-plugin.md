# release-docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 建立獨立版更文件插件，在目標 Git 根目錄產出四份文件與必要審查報告。

**Architecture:** 一個入口技能負責 Git 蒐集、來源判讀與文件生成，另一個審查技能重新比對來源並產出審查報告。共用五份 Markdown 範本與 Python 標準函式庫的證據／文件識別工具；語意審查由 agent 完成，工具不冒充 SQL 正確性審查。

**Tech Stack:** Claude Code／Codex JSON manifests、Markdown skills、Python 3 標準函式庫、unittest、Git CLI。

**Spec:** `docs/superpowers/specs/2026-10-08-release-docs-plugin-design.md`

## Global Constraints

- 插件位於 ``，獨立命名 `release-docs`、初始版本 `0.1.0`；不改現有 Redmine 插件、README 或已安裝 skills。
- 無 MCP、無外部服務必要相依；Redmine 只在可用且有指定單號時補充需求。
- 產品只提供插件管理器安裝／更新／移除。提供本地 marketplace 入口與封裝；遠端發布來源未定不得使用虛構網址。
- 產出 Markdown，不拆分、生成或執行部署 SQL；不安裝、不發布、不建立遠端 repository。
- 文件位於目標 Git 根目錄 `docs/<當地日期>_<識別>/`；混合腳本保持完整且只執行一次。
- 審查報告必須存在；狀態只有通過、待確認、未通過；最多三輪修正複審。
- 通過必須沒有未解決問題；通過不等於已執行資料庫測試或人工簽核。

## Review Focus

- 巢狀 cwd、中文與空白路徑：仍定位正確 Git 根目錄；測試歸 Task 1。
- 指定舊 revision 而工作區不同：來源使用指定版本，工作區分列；測試歸 Task 1。
- 混合 SQL 有 GO、交易及字串中的 SQL 關鍵字：分類候選不得當成可靠 SQL parser；情境歸 Task 2。
- appsettings 陣列、環境覆寫與內嵌憑證：保留完整鍵、讀程式確認來源且遮罩；情境歸 Task 2。
- 文件修改後沿用舊通過報告：識別不符即失效；測試歸 Task 3。

### Task 1: Git 證據蒐集與插件封裝

**Files:** `{plugin.json,.claude-plugin/plugin.json,.codex-plugin/plugin.json,README.md,LICENSE}`；`skills/release-docs/scripts/collect_release_evidence.py`；`tests/test_evidence.py`、`tests/test_packaging.py`。

**Interfaces:** CLI `collect_release_evidence.py --repo PATH --base REV --target REV --diff-mode {direct,merge-base}`，stdout JSON：`schema_version, repo_root, base_sha, target_sha, diff_mode, committed_changes, working_tree_changes`。檔案項包含 status、old_path、path 與來源 revision；不输出設定或 SQL 原文，避免敏感值外洩。工具僅蒐集已指定版本範圍；明確 commit 清單由技能用各 commit parent 差異與完整來源另行蒐集，不偽装成連續範圍。

- [ ] 先寫 unittest：臨時 Git repo 有 A/M/D/R、巢狀 cwd、中文與空白路徑、指定舊 target、staged／unstaged／untracked；assert revision 正確、工作區分列、無設定原值、不明 revision 回傳非零。
- [ ] 執行 `python -m unittest discover -s tests -p 'test_evidence.py' -v`，確認新工具缺失造成預期失敗。
- [ ] 實作標準函式庫 subprocess Git 呼叫，使用 argument list 與 NUL 分隔路徑；失敗 stderr 明確、無 repo 或不明 revision 不猜測。兩種 diff-mode 的定義寫進 README。
- [ ] 建立三個 manifest，skills 指向 `./skills/`，不含 MCP；不填尚未建立的遠端網址。封裝測試 assert 名稱與版本一致、引用存在、沒有必要 MCP。
- [ ] 重跑 Task 1 測試，確認通過；僅提交本 task 新增檔案，不納入既有 README 改動。

### Task 2: 文件生成技能與四份範本

**Files:** `skills/release-docs/SKILL.md`、`references/sql-review-rules.md`、`references/config-rules.md`、`assets/01_結構SQL.md` 至 `assets/04_上線指引.md`；`evals/scenarios.json`。

**Interfaces:** 入口接收目標 repo、指定範圍、版本／單號與是否納入未提交內容。消費 Task 1 metadata，再以 Git revision 讀取來源；輸出 spec 定義的四份文件。範本共用標頭：產出日期、識別、base/target SHA、diff 模式、工作區範圍、來源證據。

- [ ] 撰寫行為情境及預期判準：純結構、純資料、混合交易 SQL、migration、ORM 缺腳本、無異動、不明基準、未提交檔、設定新增修改刪除、陣列與環境覆寫。
- [ ] 建立入口技能：先確認缺失輸入，完整閱讀來源，區分事實與待確認，安全化文件識別並檢查 docs 邊界，保留已有簽核文件。使用所在 shell 可用工具，不強制 Bash。
- [ ] 編寫 SQL／設定判讀 references 與四份範本。混合脚本兩份說明引用同一執行 ID，上線指引只列一次；敏感值遮罩，驗證與回復規則需證據。
- [ ] 上線指引包含備份、相依順序、停止條件、UAT／正式紀錄、簽核與審查狀態。生成結束必須呼叫審查技能，不可直接宣稱完成或可上線。
- [ ] 逐一用 fixture 來源與成品跑行為情境並保存結果；靜態範本檢查只能證明結構，不能冒充語意驗證。提交本 task 檔案。

### Task 3: 必要審查與失效識別

**Files:** `skills/release-docs-review/SKILL.md`、`assets/05_版更審查報告.md`、`skills/release-docs/scripts/review_fingerprint.py`、`tests/test_review_fingerprint.py`；擴充 `evals/scenarios.json`。

**Interfaces:** 審查技能接收同一 repo／範圍及輸出資料夾，重新讀來源與四份成品。CLI `review_fingerprint.py --repo PATH --documents PATH --base REV --target REV --diff-mode MODE` 输出 SHA-256 JSON，涵蓋四份文件的原始 bytes、解析後 SHA、模式、Git tracked diff／untracked 檔案內容識別；不输出原文。審查報告儲存此 snapshot。狀態判讀留在技能，fingerprint 不產生通過結論。

- [ ] 先寫測試 assert 文件內容、base/target、模式、staged／unstaged／untracked 來源改變會改變 fingerprint；同內容不變；路徑越界或缺四份文件失敗。
- [ ] 執行 Task 3 測試確認預期失敗，再實作 fingerprint 工具，重跑測試通過。
- [ ] 建立審查技能與報告範本：覆蓋設計中的五項必檢，逐項記錄證據、缺陷等級、修正與複審，不能只重讀產出摘要。
- [ ] 上線指引先更新最終審查狀態，再計算最終 fingerprint 並寫報告，避免標示狀態本身導致識別失效。若審查中來源改變，丟棄該輪結論重新審查。
- [ ] 三輪未解決即交付未通過／待確認及具體缺口；保留舊簽核，修改需新版本。不得將證據不足自動降低成通過。
- [ ] 執行刻意缺陷情境：漏 SQL、重複混合 SQL、錯設定鍵、敏感值、無預期驗證、錯回復方式、舊報告失效；核對審查有來源證據且阻擋通過，修正後再審。提交本 task 檔案。

### Task 4: 整體驗證與交付

**Files:** 更新插件 README、eval 情境結果文件 `evals/results.md`；必要時修正前三 task 新檔案。

**Interfaces:** README 提供本地插件載入與任務提示範例，範例以 `release-docs`／`release-docs-review` 命名；實際可用 CLI 以本機 help 驗證，未驗證不承諾安裝。

- [ ] 查看 Claude Code／Codex 的 plugin 與 marketplace CLI help，建立各自支援的本地 marketplace metadata，來源指向獨立插件目錄。新增封裝測試驗證 marketplace 名稱、plugin 名稱、來源路徑與入口一致；README 只寫插件管理器安裝、更新與移除流程，不要求使用者手動複製 skills。不具備的 CLI 能力明示未驗證，實際安裝留待使用者要求。

- [ ] 執行 `python -m unittest discover -s tests -v`，全部通過；驗證 manifests 與 references 完整。
- [ ] 在臨時 Git fixture 走一輪生成、刻意引入缺陷、審查、修正、複審；回讀五份文件確認來源、連結、執行單位與遮罩。保存實際驗證結果與未測範圍。
- [ ] 依可用 skill validator 檢查兩個技能；檢查 git diff，確保現有 Redmine 套件與個人 skills 未被改動。
- [ ] 完成整體 review，修正剩餘問題，只有有新異動時重跑受影響驗證；交付插件位置與限制，不宣稱已安裝或發布。

## 執行方式

建議本對話直接執行，四個 task 的來源與範本共用介面較多，集中實作可減少反覆交接。選擇 subagent 執行時，按 task 逐個實作及審查，不平行修改共用檔案。實作前閱讀 skill-creator、writing-skills、verification-before-completion 與所選執行技能；決定隔離方式時保留現有 README 修改。

