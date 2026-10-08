# Task2 fixture 應用與語意查驗紀錄

日期：2026-10-08。方法：本實作 agent 完整讀取來源，按新技能實際撰寫 focused fixture 的四份輸出，逐項比較來源與成品。這是人工語意應用與查驗，不是獨立 agent 測試，不是呼叫 LLM 的自動評分，也沒有執行 SQL／正式設定操作／安裝。

## 基準與限制

撰寫技能前建立 `scenarios.json` 的12項輸入與判準，執行所需檔案契約檢查得到 `Missing contracts: 7`、exit 1。七項為入口、兩份規則、四份範本。此基準只證明缺少交付結構，不能稱為無技能 agent 行為失敗。依本task的禁止subagent／不安裝指示，未進行 writing-skills 建議的無技能／有技能獨立代理壓力對照；技能行為有效性仍需後續獨立評估。

## 已實際產出四份成品的 focused fixture

來源位於 `task2/sources/`，成品位於 `task2/outputs/`。`check_outputs.py` 以來源建立真實暫存 Git repo、產生 base/target commits，消費 Task1 metadata，只填入成品的真實 SHA；正文是本agent讀來源後手寫。暫存 repo 檢查後移除，保留完整來源快照與可重建腳本。

| 情境 | 來源事實 | 對照實際成品的語意結果 |
| --- | --- | --- |
| mixed-transaction | mixed.sql:1-7 包含 GO、XACT_ABORT、BEGIN/COMMIT；4建Flags、5插入一列字串 | 01/02均為SQL-001，04唯一執行表SQL-001一列；全文保留來源引用，不另產部署SQL。已人工核對無拆批次、無重複執行 |
| 字串假陽性 | mixed.sql:5 的 DELETE FROM Users／CREATE TABLE Decoy 是 N字串值 | 01明寫沒有Decoy；02明寫沒有刪Users且只插入一列Flags。不是以regex分類當SQL parser |
| config-add-change-delete | base/target appsettings:1，Old被刪、Enabled新增、Timeout10→20 | 03逐鍵明寫完整Feature鍵與值，區別刪除與false/null；缺消費處沒有冒稱安全，待確認 |
| arrays-env-override | Program.cs:1 Clear，2環境，3 JSON；4讀Endpoints:0:Url；deployment.yaml:2有同鍵環境值 | 03完整索引與環境雙底線映射；JSON最後加入，fixture有效Url為base.example。正式artifact未提供，所以正式有效值待確認，而非採環境優先的預設假設 |
| 內嵌憑證 | 舊新連線字串包含User Id及Password的虛構fixture值 | 03整體[已遮罩]而非只遮Password；四份輸出人工查看與已知值assert均無原憑證。不宣稱能識別所有未知secret |
| 相依與失敗 | README:3 schema／設定須在程式前；缺正式artifact、備份、工具續跑策略 | 04明寫SQL與CFG無互相相依證據，但均在APP前；01-04不宣稱可直接重跑或安全DROP恢復。未提供部分批次結果與備份流程均待確認 |
| 審查 | focused fixture未執行獨立release-docs-review，未提供05 | 04明寫待確認及未執行，05缺失是可見限制，不能將四份fixture當完成的可上線交付。Task3/Task4負責實際審查與全面評估 |

人工核對上述來源中的SQL Server驗證查詢型態、欄位及預期：01查OBJECT_ID須NULL，新表欄位Id/int/非NULL與Note/nvarchar/可NULL，PK一筆；02 VALUES明確一筆且Note原字串不變。這只判讀來源與查詢，沒有在SQL Server執行；COUNT全表一筆附沒有併行新增限制。

## 其餘情境的桌面應用產物

下列是使用 `scenarios.json` 內完整小型來源所產生的具體判讀／輸出片段，再逐條人工對照判準。它們不是完整部署文件，也不是實際Git／審查流程通過紀錄；全面end-to-end結果由Task4提供。

| 情境 | 實際判讀／產物片段 | 核對與限制 |
| --- | --- | --- |
| structure-only | `01：Flags，Id int NOT NULL PK、Enabled bit NOT NULL；02：無資料異動；SQL-001執行一次，直接重跑同名表衝突。` | CREATE只有結構，未杜撰seed。每新表需存在性查验；全面四文件尚未另跑 |
| data-only | `01：無結構異動；02：只更新Enabled IS NULL者為1，保留非NULL人工值，影響筆數待確認；同時寫入限制下查剩餘NULL應為0。` | WHERE符合來源，不把資料量寫成固定數字；方言与既有欄位未提供，先待確認 |
| migration | `20261008_AddEnabled，Up新增Users.Enabled bool非NULL預設true；Down刪欄資料流失。UAT指令有來源，正式bundle artifact未提供待確認。` | 不生成手工SQL；不將UAT指令當正式artifact，history與provider仍待確認 |
| orm-missing-script | `Invoice與DbSet新增，未找到schema／migration證據；待確認資料庫部署缺口。04：停止相關部署，不可寫無SQL。必要審查不可通過。` | 來源可證新model但不能推定正式表不存在；需進一步schema／migration證據，不虛構建表腳本 |
| no-changes | `01/02/03：無（同SHA及相關來源盤點完畢）；04：無部署動作，仍需05審查與空白簽核。` | 無結論以已完成盤點為條件。空sources情境只是桌面輸入，不冒充已實際蒐集完整repo |
| unknown-base | `請提供基準revision、目標revision、比較方式及文件識別；可以先查慣例與Git根目錄。` | 沒有預設main或生成錯誤範圍；本紀錄不是已向使用者發出問題 |
| uncommitted | `已提交target用OldVersion；另列index:StagedVersion、working-tree:WorkVersion、untracked:new.sql，納入決策待確認。` | 三種來源不同，不能用工作區替代OldVersion；未得到納入決策不得混入執行表 |
| path-and-signoff | `../#42\\正式 → #42正式；由Git根目錄解析docs實際邊界；已有小王／小李紀錄另建_v2並記取代理由。` | 是規則應用片段，未對真實簽核檔動作。symlink/junction外部需停止，不能以字串前綴放行 |
| required-review | `生成後呼叫release-docs-review；不可用則05待確認、04待確認；先更新04再最終fingerprint，最多三輪。` | 入口清楚包含此流程。focused fixture未呼叫審查，不宣稱完成；不能以靜態內容匹配證明agent會遵守 |

## 機械驗證界線

`check_outputs.py` 真實執行Git與collector、檢查四份成品共通SHA／欄位、混合執行表次數、完整設定鍵、已知敏感值不存在及未解狀態，並確認技能frontmatter和相對連結。它不閱讀SQL語意、不評估LLM、不證明部署可行、不產05、不代替必要審查。`quick_validate.py` 因bundled Python缺PyYAML而未完成，未安裝套件；stdlib契約檢查是替代的有限結構驗證。
