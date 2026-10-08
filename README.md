# release-docs

依目標 Git 專案的實際證據產出四份版更文件及必要審查報告。名稱 `release-docs`，版本 `0.1.0`，無 MCP、資料庫連線或外部服務必要相依；Redmine 是選用需求來源。文件審查不代表已執行 SQL、正式驗證或人工簽核。

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

使用者要求安裝時，先判斷目標為 Claude Code 或 Codex，僅對指定工具執行上方插件管理器流程。先查 marketplace／插件狀態；已註冊就更新，未註冊才新增，避免重複。Marketplace 同名但來源不同時，先確認與處理該來源，不修改其他 marketplace 或插件。完成後回讀插件狀態，確認 ID、版本與技能檔案，接著依下節清理已確認的舊版手動 skill，再回報安裝及備份結果；缺 CLI 或實際安裝失敗時保留舊 skill 並說明結果，不以複製 skills 代替安裝。

### 安裝成功後清理舊版手動 skills（agent 必做）

確認 `release-docs@release-docs-plugins` 已成功安裝且啟用，並確認快取內的 `release-docs`、`release-docs-review`、腳本及範本完整後，才進行清理。安裝失敗、缺檔或插件未啟用時，保留舊 skills 並回報問題。插件管理器本身不會自動移除以前手動安裝的 skill；由執行安裝任務的 agent 完成以下收尾。

1. 僅盤點指定工具的手動 skill 載入目錄：Claude Code 的 `~/.claude/skills/`；Codex 的 `~/.codex/skills/`、共用的 `~/.agents/skills/`，以及目標專案實際使用的 skills 目錄。
2. 已知被取代的舊技能是 `sql-release-signoff`（SQL 上線簽單）。讀取候選 `SKILL.md` 確認名稱、用途與來源，不以含有 SQL 或 release 字樣就判定可刪。手動安裝的同名 `release-docs`／`release-docs-review` 僅在確認屬於這個插件的舊副本時清理；使用者自行擴充的版本先保留並說明差異。
3. 備份至載入目錄外，例如 Claude 的 `~/.claude/skill-backups/release-docs/<YYYYMMDD_HHMMSS>/`，或 Codex 的 `~/.codex/skill-backups/release-docs/<YYYYMMDD_HHMMSS>/`。備份不得放回任何 `skills/` 目錄內，避免被再次載入。路徑已存在就另開名稱，不覆寫舊備份。
4. 驗證來源與備份目的地的解析後絕對路徑，來源必須是已確認的那個手動 skill，目的地必須在選定備份目錄內。遇到符號連結或 junction 先確認目標，不遞迴跟隨未知連結。使用所在平台原生檔案工具將整個舊 skill 目錄搬到備份目錄，保留 assets、references 與 scripts；不刪除整個 skills 根目錄。
5. 確認原載入位置已無舊目錄、備份完整可還原，並再次確認插件仍已安裝且啟用。開啟新對話載入插件技能，回報移除的 skill、原位置、備份完整路徑及略過原因。舊版不存在就回報「無需清理」，不重複建立備份。

保留插件管理器維護的所有 cache、其他工具設定與其他 skills。`redmine` 插件的 `release-change-items`、`redmine-issue-writing`、`issue-code-consistency-check` 不在本次清理範圍：它們提供版更 TSV、開單與需求查核，未被本插件完整取代。

## 使用

Claude Code 可用 `/release-docs:release-docs`、`/release-docs:release-docs-review`；Codex 在對話選取對應技能，或明確指定插件技能名稱 `release-docs`／`release-docs-review`。

```text
請使用 release-docs，目標 repo C:/work/my-app，base v1.2.0，target v1.3.0，direct 比較，
識別 v1.3.0，日期 2026-10-08／Asia/Taipei；工作區內容不納入。
依完整來源產出四份文件，並使用 release-docs-review 重新比對來源與成品。
不要執行資料庫 SQL。
```

```text
請使用 release-docs-review 重新審查 C:/work/my-app/docs/2026-10-08_v1.3.0，
base v1.2.0、target v1.3.0、direct，工作區不納入。
舊通過報告需要重新驗證識別；缺必要來源保持待確認。
```

輸出為 Git 根目錄 `docs/<當地日期>_<安全識別>/01_結構SQL.md`、`02_資料SQL.md`、`03_appsettings異動.md`、`04_上線指引.md`、`05_版更審查報告.md`。沒有類別異動也產文件並記錄盤點範圍。缺基準／識別先詢問；未提交內容分列，不冒充指定 revision。已有執行或簽核記錄另建 `_v2` 等版本。混合 SQL 保持完整執行單位且只執行一次。

必要審查僅「通過」「待確認」「未通過」，最多三輪。hash 只驗證證據未變，不替代語意審查；任何文件或來源異動令舊審查失效。敏感值整值遮罩，正式值與部署來源缺漏不可宣稱可上線。

明確非連續 commit 清單保留選定順序及每個 direct parent，merge 必須明確選 parent、root 的 parent 為 null。生成與必要審查共用 JSON 有序清單，例如 `[{"commit":"<A>","parent":"<A-parent>"},{"commit":"<C>","parent":"<C-parent>"}]`，不把 A、C 擴為包含 B 的 range；中間相依不足列待確認。collector 仍只接受 range；清單逐對蒐集完整證據。fingerprint 解析每對 SHA、識別 source trees 及選定差異，不在清單 snapshot 虛構 range 欄位：

```text
python skills/release-docs/scripts/review_fingerprint.py --repo <repo> --documents <repo/docs/日期_識別> --commit-scope <JSON檔>
```

`--commit-scope` 與 `--base`／`--target`／`--diff-mode` 互斥；既有 range 介面保持相容。開始審查、最終保存及再次使用報告時保留同一範圍；比較來源識別時包含完整有序 `commit_scope`，任何 pair、順序、樹、差異或工作區變動都需重審。hash 相符仍不能替代語意審查。

每次首次建立或立即更新／fallback 寫入前（含第五報告），先選定保留既有簽核的最終版本目錄，再執行唯讀 guard：

```text
python skills/release-docs/scripts/validate_output_paths.py --repo <repo> --documents <repo/docs/日期_識別>
```

拒絕越界目錄、五個具名成品的 symlink、非一般檔案及 hard-link 別名。失敗只在對話報告，不嘗試寫 blocked 文件或報告。preflight 不建立目錄，安全的新目錄可在通過後建立；fingerprint 使用同一 guard。

## 維護與 Release

需要 Python 3.11–3.13 與 Git；腳本僅用標準函式庫。CI 在 Linux／Windows 執行：

```text
python -X utf8 -m unittest discover -s tests -v
claude plugin validate .claude-plugin/plugin.json --json --strict
claude plugin validate .claude-plugin/marketplace.json --json --strict
```

發布前同時更新 `plugin.json`、`.claude-plugin/plugin.json`、`.codex-plugin/plugin.json` 的版本，更新 README，執行測試，review 後合併到 main，再建立 annotated tag：

```text
git switch main
git pull --ff-only
python -X utf8 -m unittest discover -s tests -v
git tag -a v0.1.0 -m "release-docs 0.1.0"
git push origin v0.1.0
```

以上是維護者發布流程；一般使用者僅需插件管理器安裝，不需建立 tag。不要 force 覆寫 tag；版本錯誤使用新版本。Release workflow 支援推送 `v*` tag 與 workflow_dispatch 重跑既有 tag，先驗證嚴格 `vMAJOR.MINOR.PATCH`（禁止前導零與 prerelease），再 checkout。檢查三份版本、必備資源、tag commit 位於 `origin/main` 且 checkout 一致，Linux／Windows 測試通過才建立 GitHub Release。預設 contents:read，僅 release job contents:write。已有 Release 不修改；建立使用 `--verify-tag --generate-notes`。workflow 本身需在預設分支才可手動觸發；此專案已公開；GitHub Release 不等於上架到官方插件目錄，安裝來源仍是上述 Git marketplace。

## 驗證界線

[實際情境結果](evals/results.md) 區分真實來源／技能執行／必要審查與未測項；`evals/task2/` 是既有手寫契約範例，不代替實際評估。沒有執行 SQL 或正式環境驗證。

重現來源fixture需明確給定兩個尚不存在的目的地：`python -X utf8 evals/prepare_actual_fixtures.py --run-root .superpowers/actual-rerun-2026-10-09 --archive-root evals/rerun-2026-10-09`。run或archive任一存在就先拒絕、完全不寫入；新clone的 `evals/actual/` 是保留的原評估證據，不能覆用。腳本只準備來源，後續仍須agent實際生成／審查，見上述情境結果的重現步驟。
