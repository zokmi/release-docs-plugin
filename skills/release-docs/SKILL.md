---
name: release-docs
description: Use when 使用者要依指定 Git 範圍整理過版／上線文件、結構 SQL、資料 SQL、appsettings 異動與執行指引；也適用功能收尾的版更文件，不用於實際執行部署或自動產生 SQL。
---

# 版更文件生成

依 Git 與完整來源產出必要 SQL／Markdown 文件，再進行必要審查；審查結果在對話收尾回報，不另產生報告檔。每個結論附來源；未知寫「待確認（原因與所需證據）」。只複製來源完整 SQL，不憑空生成、拆分、修改或執行部署 SQL，不連正式資料庫。Redmine 只在工具可用且有指定單號時補充需求，不是必要相依；需求素材不能取代程式事實。

## 確認與蒐集

1. 讀目標專案 AGENTS.md、CLAUDE.md、資料庫與部署慣例。确认目標 repo、base/target 或明確 commit 清單、diff 模式、文件識別（版本／單號）、當地日期與工作區納入決策。已提供的不用重問。缺範圍先詢問，不猜 main；沒有單號也可用確認的版本識別。非 Git／無權讀取时要求正確目標，不任選輸出位置。
2. 使用所在 shell 可用的 Python 與 Git，不強制 Bash。以插件內部工具取得根目錄及路徑 metadata：

   ```text
   python <此技能目录>/scripts/collect_release_evidence.py --repo "<目标或巢状目录>" --base <base> --target <target> --diff-mode <direct或merge-base>
   ```

   消費 schema_version=1、repo_root、base_sha、target_sha、diff_mode、committed_changes、working_tree_changes 的 staged/unstaged/untracked。記錄解析後 SHA，保留刪除與 rename 原路徑。工作區始終分列，標每項是否納入；不明時請使用者決定，先盤點但不混入部署步骤。
3. metadata 不含檔案內容。完整讀實際 revision 的 SQL、migration、相關程式及設定的前後版本。已提交新增／修改取 target SHA，刪除取 base SHA；rename 对照旧路徑。`git show <SHA>:<path>` 只在安全且可遮罩的工具介面讀取，敏感內容不得出現在可留存日誌。index 用 `git show :<path>`，unstaged/untracked 讀工作區；刪除項讀 metadata 指示的舊來源。各來源明確分開，不用目前檔案代替舊 target。
4. 明確 commit 清單逐個解析 SHA，保留原順序與每個 commit 的選定 direct parent；merge commit 必須明確選 parent，root commit 的 parent 為 null。以 JSON 有序清單保存 `[{"commit":"<revision>","parent":"<revision或null>"}, ...]`，傳給必要審查與 fingerprint 的 `--commit-scope <JSON檔>`，解析後每一對 SHA 必須一致。逐對蒐集 name/status 與完整前後來源，root 取空樹對 commit；collector 只支援 range，不對清單冒填 base/target 或將 A、C 擴為包含 B 的 range。未納入中間 commit 的相依列待確認；即使完整 source tree 有相依內容，也不將中間 commit 的異動列為此次執行範圍。
5. 盤點全 repo 的 SQL、migration、ORM/model/schema、內嵌 SQL、設定消費處及部署流程，不限副檔名或固定目錄。零搜尋命中不是已查證的「無」；缺 ORM 对应脚本、方言、實際設定来源或部署 artifact 时列缺口。

## 判讀與文件

涉及資料庫時讀 [SQL 判讀規則](../../references/sql-review-rules.md)；涉及設定時讀 [設定判讀規則](../../references/config-rules.md)。結構、設定與上線指引必須產出；只有確認存在資料異動時才產出資料 SQL。結構內容優先以 EF model／migration 差異或資料庫專案 schema compare／部署腳本驗證，並記錄 provider、工具版本與 artifact；只有 ORM 類別或 migration 名稱時不得自行推導 SQL。

- 使用 [01_結構SQL](../../assets/01_結構SQL.sql)、[02_資料SQL](../../assets/02_資料SQL.sql)、[03_appsettings異動](../../assets/03_appsettings異動.md)、[04_上線指引](../../assets/04_上線指引.md)。共同標頭記日期、識別、範圍類型、range 的 base/target SHA 與 diff 模式，或清單模式的完整有序 commit_scope（解析後 commit／parent SHA；root 為 null，range 欄位不適用）、工作區范围與來源證據；保留真實行號、來源版本及範圍限制。
- 每個原始 SQL／migration 執行單位分配唯一 ID，兩份 SQL 文件的混合說明引用同一 ID；04 只排一次完整執行單位。按實際 SQL／設定／程式／人工作業相依排程，寫明依據、前後檢查、預期結果、停止點、部分成功與回復限制。
- 正式設定未知寫待填及安全来源。敏感值在持久化、工具输出、diff 摘錄及文件前遮罩；不為文件開啟会把 secrets 印到日誌的原始 diff/show。可用本機程式读取并僅返回遮罩後摘要；無安全介面則列待確認，不洩漏原值。

## 可執行 SQL 交付

有資料異動時產出 `02_資料SQL.sql`；沒有 seed、回填、修正、遷移或刪除等資料異動時不要建立該檔案。`01_結構SQL.sql` 必須產出。說明、標頭、來源、風險、檢查與更新紀錄一律使用 `--` SQL 註解，不能有未註解的 Markdown 表格、標題或程式碼圍欄。所有模板佔位符必須填妥或移除。部署語句放在註解之外，從已核對來源完整複製，保留方言、GO／delimiter、交易與工作階段設定；04 寫明相容引擎與執行工具。前後檢查及回復範例只作註解，避免執行成品時一併執行。

SQL 檔寫入後只能在隔離的本機資料庫或 disposable container 驗證；不得連線或執行正式資料庫。本機資料庫引擎、主要版本與 provider 必須和正式機完全一致，並一致使用 collation／相容性設定、schema 初始狀態與部署工具。若正式機版本或 provider 不明，或無法證明本機完全一致，必須先請使用者提供／確認版本並暫停 SQL 驗證，不得猜測或以近似版本代替。確認一致後依「建立／還原本機基準 → 執行完整 SQL／migration → 驗證 schema、索引／約束、資料與 migration history」執行，記錄正式機版本依據、本機版本、工具版本、命令、目標識別、exit code、錯誤輸出與結果；lint、parser、dry-run 或只產生 script 不算成功。沒有可用本機引擎、版本未確認、引擎／provider 不一致或執行失敗時，對話收尾回報必須標示待確認／未通過，不得宣稱可上線。

混合 DDL/DML 完整內容僅放在一份 SQL，另一份以註解引用同 ID 與檔案；04 只執行一次。不可將不同方言／工具、互斥條件、需穿插程式或設定步驟的來源直接串接為一次執行；保留來源單位，以 04 指定工具、條件與執行的行號範圍，每個範圍須是完整批次／交易且不能含其他單位。無法在這兩份 SQL 中保持可執行完整單位時列阻擋與待確認，不交付假可執行內容。

无異動時僅產註解「無異動」與盤點證據，執行為無動作。缺 SQL artifact 的 ORM／migration 不可將 Up/Down 翻寫為 SQL，在 SQL 註解及 04 列缺口、禁止執行，審查不得通過。含敏感值而不能安全交付亦阻擋，不能以遮罩或待填值替換語句後聲稱可執行。格式可執行不代表資料庫已測試；未連資料庫驗證不得聲稱已測試。

## 輸出與必要審查

04 必須簡潔，只保留執行順序、完整來源／命令、前置與後驗證、停止／回復限制、本機驗證結果，以及分支驗證、回合併／PR、tag 與分支清理的條件。每項附來源與負責人；未知寫待確認，未執行維持未執行。不猜分支名稱或合併策略，不實際合併、推送、建立 tag 或刪除分支。

預設寫入 `<repo_root>/docs/release-doc/<當地YYYY-MM-DD>/`，日期目錄不附加識別，識別記在文件標頭。若使用者明確指定其他目錄，移除識別中的 `/`、`\`、控制字元及 Windows 不合法字元，去尾端空白／句點，拒絕空值、`.`、`..`、保留裝置名；記錄原識別與安全識別的對應。寫入前解析 `docs/release-doc` 與候選目錄實際路徑，確認仍在 Git 根目錄內；symlink/junction 指向外部即停止，不僅作字串前綴比較。

先讀已有四份文件、審查與簽核／執行紀錄。沒有紀錄可就地更新並留時間與異動摘要；已有任一紀錄或無法判定時使用下一個未占用的 `_v2`／`_v3` 目錄，保留舊文件並記取代理由。先選定最終版本目錄，再執行以下唯讀 preflight；首次建立目錄／文件前，以及每次立即更新、修正、04 狀態更新或 fallback 寫入前，都必須重跑（包含最終對話回報）：

```text
python <此技能目錄>/scripts/validate_output_paths.py --repo "<repo>" --documents "<最終版本目錄>"
```

檢查 Git 根目錄 docs 內的實際目錄及三個必備成品，並在存在時檢查 `02_資料SQL.sql`；拒絕任何成品 symlink（即使指向 repo 內）、非一般檔案與 `st_nlink > 1` hard-link 別名。拒絕時立即停止所有該目錄寫入，只在對話交付阻擋原因；不能先寫草稿、05 待確認或覆寫 alias 後才讓 review 檢查。preflight 不建立目錄也不寫檔，通過後才建立或寫入；已有簽核紀錄的版本選擇規則仍適用。

**生成後必須调用 `release-docs-review`** 進行另一輪來源與成品審查，在對話收尾回報審查狀態。無此技能／無法審查時回報「待確認（未完成必要審查，缺少能力／證據）」；不能自評通過。狀態僅通過、待確認、未通過；有阻擋或必要待補證據不得通過。最多三輪修正複審。

04 審查狀態必須在最終文件識別計算與 05 寫入前更新。之後任何四份文件或來源改動都使舊審查失效；重新審查，不能在 fingerprint 完成後改 04 狀態。交付完整路徑、必要執行單位與相依、審查狀態及未解問題；文件審查通過不代表 SQL 已測試、正式已驗證或人工簽核完成。
