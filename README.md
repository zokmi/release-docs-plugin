# release-docs

依目標 Git 專案的實際證據產出四份版更文件及必要審查報告。名稱 `release-docs`，版本 `0.1.0`，無 MCP、資料庫連線或外部服務必要相依；Redmine 是選用需求來源。文件審查不代表已執行 SQL、正式驗證或人工簽核。

## 插件管理器

[原始碼](https://github.com/zokmi/release-docs-plugin) 目前為 private；遠端下載與 Release 需要有該 repository 的存取權，公開使用者目前不能直接安裝。提供 Claude `.claude-plugin/marketplace.json` 與 Codex `.agents/plugins/marketplace.json`，marketplace 名稱均為 `release-docs-plugins`，來源 `./` 指向這個独立專案根目錄。已以本機 CLI help 與只讀 Claude validator 驗證命令／封裝；未實際安裝、更新或移除使用者插件，未發布 Release，GitHub Actions 尚未在線執行。

Claude Code（將本地路徑換成自己的 clone；亦可用有權限的遠端 URL）：

```text
claude plugin marketplace add "C:/path/release-docs-plugin"
claude plugin install release-docs@release-docs-plugins
claude plugin marketplace update release-docs-plugins
claude plugin update release-docs@release-docs-plugins
claude plugin uninstall release-docs@release-docs-plugins
claude plugin marketplace remove release-docs-plugins
```

Codex（本機 CLI 支援 add/remove，沒有 plugin install/update 子命令）：

```text
codex plugin marketplace add "C:/path/release-docs-plugin" --json
codex plugin add release-docs@release-docs-plugins --json
codex plugin marketplace upgrade release-docs-plugins --json
codex plugin remove release-docs@release-docs-plugins --json
codex plugin add release-docs@release-docs-plugins --json
```

`marketplace upgrade` 只更新 Git marketplace 快照；本地 clone 先透過 Git 更新。此 CLI 未提供獨立 plugin update，更新插件可經管理器移除後重新 add；這是可用命令組合，實際更新行為尚未驗證。移除 marketplace 用 `codex plugin marketplace remove release-docs-plugins`。安裝／更新後開始新對話以載入技能。產品只使用插件管理器，不要求手動複製 skills。

Codex marketplace 路徑規則及 CLI 來源格式依 [OpenAI 官方封裝文件](https://developers.openai.com/plugins/build/plugins)，具體命令以本機 help（2026-10-08）為準。

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

輸出為 Git 根目錄 `docs/<當地日期>_<安全識別>/01_結構SQL.md`、`02_資料SQL.md`、`03_appsettings異動.md`、`04_上線指引.md`、`05_版更審查報告.md`。沒有類別異動也產文件并記錄盤點範圍。缺基準／識別先詢問；未提交內容分列，不冒充指定 revision。已有執行或簽核記錄另建 `_v2` 等版本。混合 SQL 保持完整執行單位且只執行一次。

必要審查僅「通過」「待確認」「未通過」，最多三輪。hash 只驗證證據未變，不替代語意審查；任何文件或來源異動令舊審查失效。敏感值整值遮罩，正式值與部署來源缺漏不可宣稱可上線。

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

以上是維護者發布流程，本次沒有執行 tag／push／Release。不要 force 覆寫 tag；版本錯誤使用新版本。Release workflow 支援推送 `v*` tag 與 workflow_dispatch 重跑既有 tag，先驗證嚴格 `vMAJOR.MINOR.PATCH`（禁止前導零與 prerelease），再 checkout。檢查三份版本、必備資源、tag commit 位於 `origin/main` 且 checkout 一致，Linux／Windows 測試通過才建立 GitHub Release。預設 contents:read，僅 release job contents:write。已有 Release 不修改；建立使用 `--verify-tag --generate-notes`。workflow 本身需在預設分支才可手動觸發；private repository 的 Release 仍受存取權限制，Release 不等於公開 marketplace 上架。

## 驗證界線

[實際情境結果](evals/results.md) 區分真實來源／技能執行／必要審查與未測項；`evals/task2/` 是既有手寫契約範例，不代替實際評估。沒有執行 SQL 或正式環境驗證。

重現來源fixture需明確給定兩個尚不存在的目的地：`python -X utf8 evals/prepare_actual_fixtures.py --run-root .superpowers/actual-rerun-2026-10-09 --archive-root evals/rerun-2026-10-09`。run或archive任一存在就先拒絕、完全不寫入；新clone的 `evals/actual/` 是保留的原評估證據，不能覆用。腳本只準備來源，後續仍須agent實際生成／審查，見上述情境結果的重現步驟。
