---
name: release-docs
description: Use when 使用者要依指定 Git 範圍整理過版／上線文件、結構 SQL、資料 SQL、appsettings 異動與執行指引；也適用功能收尾的版更文件，不用於實際執行部署或自動產生 SQL。
---

# 版更文件生成

依 Git 與完整來源產出四份可供執行者查驗的 Markdown 文件，再進行必要審查。每個結論附來源；未知寫「待確認（原因與所需證據）」。不生成、拆分、修改或執行部署 SQL，不連正式資料庫。Redmine 只在工具可用且有指定單號時補充需求，不是必要相依；需求素材不能取代程式事實。

## 確認與蒐集

1. 讀目標專案 AGENTS.md、CLAUDE.md、資料庫與部署慣例。确认目標 repo、base/target 或明確 commit 清單、diff 模式、文件識別（版本／單號）、當地日期與工作區納入決策。已提供的不用重問。缺範圍先詢問，不猜 main；沒有單號也可用確認的版本識別。非 Git／無權讀取时要求正確目標，不任選輸出位置。
2. 使用所在 shell 可用的 Python 與 Git，不強制 Bash。以插件內部工具取得根目錄及路徑 metadata：

   ```text
   python <此技能目录>/scripts/collect_release_evidence.py --repo "<目标或巢状目录>" --base <base> --target <target> --diff-mode <direct或merge-base>
   ```

   消費 schema_version=1、repo_root、base_sha、target_sha、diff_mode、committed_changes、working_tree_changes 的 staged/unstaged/untracked。記錄解析後 SHA，保留刪除與 rename 原路徑。工作區始終分列，標每項是否納入；不明時請使用者決定，先盤點但不混入部署步骤。
3. metadata 不含檔案內容。完整讀實際 revision 的 SQL、migration、相關程式及設定的前後版本。已提交新增／修改取 target SHA，刪除取 base SHA；rename 对照旧路徑。`git show <SHA>:<path>` 只在安全且可遮罩的工具介面讀取，敏感內容不得出現在可留存日誌。index 用 `git show :<path>`，unstaged/untracked 讀工作區；刪除項讀 metadata 指示的舊來源。各來源明確分開，不用目前檔案代替舊 target。
4. 明確 commit 清單逐個解析 SHA，讀各 commit 的 parent 差異與完整來源，記錄清單与順序；merge commit 要確認比較 parent，不偽裝連續 range。未納入中間 commit 的相依列待確認。
5. 盤點全 repo 的 SQL、migration、ORM/model/schema、內嵌 SQL、設定消費處及部署流程，不限副檔名或固定目錄。零搜尋命中不是已查證的「無」；缺 ORM 对应脚本、方言、實際設定来源或部署 artifact 时列缺口。

## 判讀與文件

涉及資料庫時讀 [SQL 判讀規則](../../references/sql-review-rules.md)；涉及設定時讀 [設定判讀規則](../../references/config-rules.md)。即使無異動也以完整盤點證據寫「無」，四份必須全部產出。

- 使用 [01_結構SQL](../../assets/01_結構SQL.md)、[02_資料SQL](../../assets/02_資料SQL.md)、[03_appsettings異動](../../assets/03_appsettings異動.md)、[04_上線指引](../../assets/04_上線指引.md)。共同標頭記日期、識別、base/target SHA（清單模式另記所有 SHA／parent）、diff 模式、工作區范围與來源證據；保留真實行號、來源版本及範圍限制。
- 每個原始 SQL／migration 執行單位分配唯一 ID，兩份 SQL 文件的混合說明引用同一 ID；04 只排一次完整執行單位。按實際 SQL／設定／程式／人工作業相依排程，寫明依據、前後檢查、預期結果、停止點、部分成功與回復限制。
- 正式設定未知寫待填及安全来源。敏感值在持久化、工具输出、diff 摘錄及文件前遮罩；不為文件開啟会把 secrets 印到日誌的原始 diff/show。可用本機程式读取并僅返回遮罩後摘要；無安全介面則列待確認，不洩漏原值。

## 輸出與必要審查

固定寫 `<repo_root>/docs/<當地YYYY-MM-DD>_<識別>/`。移除識別中的 `/`、`\`、控制字元及 Windows 不合法字元，去尾端空白／句點，拒絕空值、`.`、`..`、保留裝置名；記錄原識別與安全識別的對應。寫入前解析 docs 與候選目錄實際路徑，確認仍在 Git 根目錄 docs 内；symlink/junction 指向外部即停止，不僅作字串前綴比較。

先讀已有四份文件、審查與簽核／執行紀錄。沒有紀錄可就地更新並留時間與異動摘要；已有任一紀錄或無法判定時使用下一個未占用的 `_v2`／`_v3` 目錄，保留舊文件並記取代理由。

**生成後必須调用 `release-docs-review`** 進行另一輪來源與成品審查，寫同目錄 `05_版更審查報告.md`。無此技能／無法審查時保留四份草稿並写 05「待確認（未完成必要審查，缺少能力／證據）」，不能自評通過。狀態僅通過、待確認、未通過；有阻擋或必要待補證據不得通過。最多三輪修正複審。

04 審查狀態必須在最終文件識別計算與 05 寫入前更新。之後任何四份文件或來源改動都使舊審查失效；重新審查，不能在 fingerprint 完成後改 04 狀態。交付完整路徑、必要執行單位與相依、審查狀態及未解問題；文件審查通過不代表 SQL 已測試、正式已驗證或人工簽核完成。
