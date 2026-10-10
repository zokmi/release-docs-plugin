# release-docs

依目標 Git 專案的實際證據產出必要版更文件、精簡審查摘要及對話回報。名稱 `release-docs`，版本 `0.1.21`，無 MCP、資料庫連線或外部服務必要相依；Redmine 是選用需求來源。文件審查不代表已執行 SQL、正式驗證或人工簽核。

## 插件安裝

[原始碼](https://github.com/zokmi/release-docs-plugin) 為公開專案，可直接透過插件管理器從 GitHub 安裝，不需先 clone、不需複製 skills，也不需設定 GitHub API token。Marketplace 名稱為 `release-docs-plugins`，插件 ID 為 `release-docs@release-docs-plugins`。兩份 marketplace 的相對來源 `./` 指向下載後的完整專案根目錄。

### Claude Code

在終端機執行：

```sh
claude plugin marketplace add https://github.com/zokmi/release-docs-plugin.git --scope user --json
claude plugin install release-docs@release-docs-plugins --scope user --json
```

也可在 Claude Code 對話使用插件指令：

```text
/plugin marketplace add zokmi/release-docs-plugin
/plugin install release-docs@release-docs-plugins
```

更新：

```sh
claude plugin marketplace update release-docs-plugins --json
claude plugin update release-docs@release-docs-plugins --scope user --json
```

移除：

```sh
claude plugin uninstall release-docs@release-docs-plugins --scope user --json
claude plugin marketplace remove release-docs-plugins --json
```

### Codex

在終端機執行：

```sh
codex plugin marketplace add https://github.com/zokmi/release-docs-plugin.git --ref main --json
codex plugin add release-docs@release-docs-plugins --json
```

Codex CLI 的安裝子命令是 `plugin add`，不是 `plugin install`。桌面版可在加入 marketplace 後重新啟動 app，於插件目錄選擇 `Release Docs Plugins` 安裝 `Release Docs`。

更新 marketplace 與重新安裝插件：

```sh
codex plugin marketplace upgrade release-docs-plugins --json
codex plugin remove release-docs@release-docs-plugins --json
codex plugin add release-docs@release-docs-plugins --json
```

此 CLI 沒有獨立的 `plugin update`；上述流程透過插件管理器重新安裝更新後的來源。

移除：

```sh
codex plugin remove release-docs@release-docs-plugins --json
codex plugin marketplace remove release-docs-plugins --json
```

安裝／更新後開啟新對話以載入技能。以上安裝指令均以 GitHub repository 為來源，由插件管理器下載與安裝；不使用本機資料夾路徑作為安裝來源。2026-10-08 已在隔離的 Claude／Codex 設定目錄，實際完成上述遠端 marketplace 註冊與首次安裝，沒有改動既有使用者安裝。更新、移除及桌面介面操作尚未實際測試。

Codex marketplace 與桌面插件目錄方式依 [OpenAI 官方封裝文件](https://developers.openai.com/plugins/build/plugins)，具體 CLI 子命令以本機 help 為準。

### 給 agent 的安裝流程

使用者要求安裝時，先判斷目標為 Claude Code 或 Codex，僅對指定工具執行上方插件管理器流程。先查 marketplace／插件狀態；已註冊就更新，未註冊才新增，避免重複。Marketplace 同名但來源不同時，先確認與處理該來源，不修改其他 marketplace 或插件。完成後回讀插件狀態，確認 ID、版本與技能檔案，接著依下節清理已確認的舊版手動 skill，再回報安裝及刪除結果；缺 CLI 或實際安裝失敗時保留舊 skill 並說明結果，不以複製 skills 代替安裝。

### 安裝成功後清理舊版手動 skills（agent 必做）

確認 `release-docs@release-docs-plugins` 已成功安裝且啟用，並確認快取內的 `release-docs`、`release-docs-review`、腳本及範本完整後，才進行清理。安裝失敗、缺檔或插件未啟用時，保留舊 skills 並回報問題。插件管理器本身不會自動移除以前手動安裝的 skill；由執行安裝任務的 agent 完成以下收尾。

1. 僅盤點指定工具的手動 skill 載入目錄：Claude Code 的 `~/.claude/skills/`；Codex 的 `~/.codex/skills/`、共用的 `~/.agents/skills/`，以及目標專案實際使用的 skills 目錄。
2. 已知被取代的舊技能是 `sql-release-signoff`（SQL 上線簽單）。讀取候選 `SKILL.md` 確認名稱、用途與來源，不以含有 SQL 或 release 字樣就判定可刪。手動安裝的同名 `release-docs`／`release-docs-review` 僅在確認屬於這個插件的舊副本時清理；使用者自行擴充的版本先保留並說明差異。
3. 舊版已棄用，直接刪除已確認被取代的整個手動 skill 目錄及其中的 assets、references、scripts，不建立備份。先前安裝本插件時為同一舊 skill 建立的備份亦直接刪除；不清理其他用途的備份。
4. 刪除前驗證解析後的絕對路徑，目標必須是已確認的那個舊 skill，或本插件先前為它建立的備份。遇到符號連結或 junction 先確認目標，不遞迴跟隨未知連結。使用所在平台原生檔案工具與 literal path 刪除，不刪除整個 skills 根目錄、備份根目錄或插件 cache。
5. 確認舊目錄及本次指定備份已不存在，並再次確認插件仍已安裝且啟用。開啟新對話載入插件技能，回報刪除的 skill、完整路徑及略過原因。舊版不存在就回報「無需清理」。

保留插件管理器維護的所有 cache、其他工具設定與其他 skills。`redmine` 插件的 `release-change-items`、`redmine-issue-writing`、`issue-code-consistency-check` 不在本次清理範圍：它們提供版更 TSV、開單與需求查核，未被本插件完整取代。

## 使用

預期流程：**先確認差異範圍 → 自動產生規範文件 → 驗證與審核 → 修正複審**。範圍已明確時直接解析 SHA 與核對工作區決策；大量 diff 分批分析，完成 SQL 分類、重複／替代核對與相依排序，不以異動量大停止。缺 SQL artifact 時，使用專案既有且版本／provider 已確認的 EF 或資料庫專案工具，在隔離副本產生此次範圍的腳本並保留生成證據，不手寫推測 SQL。輸出文件依 release 情境提供上板所需的命令、順序、驗證與停止條件；完整來源追溯、工具輸出與驗證日誌保留在 artifact metadata／審查輸入。缺正式版本、基準或安全設定來源時，只暫停受影響步驟，繼續其他文件產出與來源審查；收尾分別回報產出、來源審查、本機執行驗證及最終審核狀態。

Claude Code 可用 `/release-docs:release-docs`、`/release-docs:release-docs-review`；Codex 在對話選取對應技能，或明確指定插件技能名稱 `release-docs`／`release-docs-review`。

```text
請使用 release-docs，目標 repo C:/work/my-app，base v1.2.0，target v1.3.0，direct 比較，
release 分支 release/2026-10-08，識別 v1.3.0，產出日期 2026-10-09／Asia/Taipei；工作區內容不納入。
依完整來源產出必要文件，並使用 release-docs-review 重新比對來源與成品，結果於對話收尾回報。
不要執行資料庫 SQL。
```

```text
請使用 release-docs-review 重新審查 C:/work/my-app/docs/release-doc/2026-10-08，
base v1.2.0、target v1.3.0、direct，工作區不納入。
舊通過報告需要重新驗證識別；缺必要來源保持待確認。
```

日期目錄取已確認 release 分支名稱中的有效日期，例如 `release/2026-10-08` 在 2026-10-09 產出仍使用 `2026-10-08`；輸出文件另記產出日期／時區與日期來源。分支或日期不明先確認，不改用當天或 commit 日期。

SQL Server 最低支援 2016。交付目錄只包含 `00_上線指引.md`、唯一人工執行的 `01_部署SQL.sql`，以及有參數異動時的 `02_參數異動.md`。SQL 依序包含 SCHEMA、REPAIR、DATA、VALIDATION，在新 SSMS connection/session 一次執行，不依賴 GO 或 sqlcmd 指令。

未設定 `SESSION_CONTEXT(N'ReleaseDocs.ValidateOnly')` 時預設 ValidateOnly=1，完整執行並驗證後 rollback。上板人員先確認唯讀 preflight、備份與維護窗口，再在同一新 session 設定以下值並執行整份 SQL，才可 commit：

```sql
EXEC sys.sp_set_session_context @key=N'ReleaseDocs.ValidateOnly', @value=0;
```

插件不連線或修改正式資料庫。EF6／EF Core 偵測以 pinned source revision 為依據；目前自動產製支援可核對完整定義的簡單建表、單欄 PK 與單欄非唯一索引，其他 operation 或無法證明的型別／基準會阻擋。既有物件只在定義相符時跳過，缺少時建立，不相容時 THROW，整份 release rollback 並停止。

排除意圖經完整 unit 與 dependency 分析後寫入 `.release-docs/runs/<run-id>/lifecycle_exclusion_manifest.json`。此 manifest 是唯一排除真相，指引只顯示其操作摘要；原始 SQL、source metadata、fixture、baseline、execution artifact、fingerprint、review record 與 LocalDB evidence 都留在 lifecycle 永久區。

SQL 內容審核與部署驗證分開回報「通過」「待確認」「未通過」。隔離 LocalDB adapter 需四輪：fresh baseline rollback、fresh baseline commit、已提交 database 的新 session rerun、fresh baseline 注入錯誤。含 DATA 異動時必須有既有值、保留資料、NULL、重複候選、邊界與筆數的 fixture 和逐輪前後查核。每輪保存 artifact／baseline／fixture／manifest hash、版本、session/database、committed-state lineage、不同 checks 與實際保留資料摘要。缺 adapter 是未執行，缺證據是待確認，不以 fixture test double 冒充資料庫實測。

使用 `skills/release-docs-review/scripts/validate_release_output.py --output-dir <operator> --run-root <run>` 核對交付 allowlist、排除、SQL 契約與部署證據。exit 0 仍可能待確認；需讀取 SQL 內容與部署驗證兩個狀態並完成來源語意審查。任何來源、SQL、排除、參數或 fixture 變動都使先前 fingerprint 失效。

## 維護與 Release

目前插件版本以三份 manifest 為準。此分支改採單一交易 SQL 與 lifecycle evidence；舊版 01_結構SQL／02_資料SQL／03_例外排除／04_參數異動不再是新流程的交付契約。正式執行與人工簽核由上板流程另行保存證據。

需要 Python 3.11–3.13 與 Git；腳本僅用標準函式庫。CI 在 Linux／Windows 執行：

```text
python -X utf8 -m pytest tests -q
claude plugin validate .claude-plugin/plugin.json --json --strict
claude plugin validate .claude-plugin/marketplace.json --json --strict
```

發布前同時更新 `plugin.json`、`.claude-plugin/plugin.json`、`.codex-plugin/plugin.json` 的版本，更新 README，執行測試，review 後合併到 main，再建立 annotated tag：

```text
git switch main
git pull --ff-only
python -X utf8 -m pytest tests -q
git tag -a v0.1.21 -m "release-docs 0.1.21"
git push origin v0.1.21
```

以上是維護者發布流程；一般使用者僅需插件管理器安裝，不需建立 tag。不要 force 覆寫 tag；版本錯誤使用新版本。Release workflow 支援推送 `v*` tag 與 workflow_dispatch 重跑既有 tag，先驗證嚴格 `vMAJOR.MINOR.PATCH`（禁止前導零與 prerelease），再 checkout。檢查三份版本、必備資源、tag commit 位於 `origin/main` 且 checkout 一致，Linux／Windows 測試通過才建立 GitHub Release。預設 contents:read，僅 release job contents:write。已有 Release 不修改；建立使用 `--verify-tag --generate-notes`。workflow 本身需在預設分支才可手動觸發；此專案已公開；GitHub Release 不等於上架到官方插件目錄，安裝來源仍是上述 Git marketplace。

## 驗證界線

[實際情境結果](evals/results.md) 區分真實來源／技能執行／必要審查與未測項；`evals/task2/` 是既有手寫契約範例，不代替實際評估。沒有執行 SQL 或正式環境驗證。

重現來源fixture需明確給定兩個尚不存在的目的地：`python -X utf8 evals/prepare_actual_fixtures.py --run-root .superpowers/actual-rerun-2026-10-09 --archive-root evals/rerun-2026-10-09`。run或archive任一存在就先拒絕、完全不寫入；新clone的 `evals/actual/` 是保留的原評估證據，不能覆用。腳本只準備來源，後續仍須agent實際生成／審查，見上述情境結果的重現步驟。

## 暫存產物管理

每次產製使用不可覆寫的 `.release-docs/runs/<run-id>/` 並排除於 Git。成功交付及審查後，`finalize_lifecycle_run` 僅清除明確標記的 temporary／.tmp，保留永久 manifest、source metadata、review record 與 execution evidence。失敗或中斷保留七天，過期也只清理受控 temporary。操作目錄不可含 lifecycle JSON、原始工具日誌、暫存路徑或未宣告檔案。既有 `artifact_lifecycle.py` 屬舊版流程，不用它清除新流程的永久證據。



