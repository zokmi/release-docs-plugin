# 實際技能流程評估

2026-10-08，Task4 agent 完整讀取 `skills/release-docs/SKILL.md`、`skills/release-docs-review/SKILL.md`、兩份判讀規則與五份範本，直接應用於15個**新建独立Git fixture**。這是同一agent的實際讀檔、生成、另一輪來源／成品語意審查；沒有呼叫外部LLM評分器、沒有跨模型獨立盲測、沒有安裝插件或執行SQL。既有 `task2/outputs` 是手寫契約範例，不作本次執行證據。

每案在 [actual](actual/) 有 `invocation.json`（實際root/cwd/SHA/輸入）、完整前後安全來源匯出、source原bytes hash、collector metadata、各輪起始／已審snapshot與讀取log、五份最終輸出及outcome。原Git fixture留在本專案忽略的 `.superpowers/sdd/2026-10-08-release-docs-plugin/actual-run/`，SQL與原始synthetic秘密只在fixture，持久證據匯出整值遮罩。hash/log證明讀取與範圍，語意判定及理由見05，沒有用substring命中直接標PASS。

| 宣告情境 | 已觀察結果與直接證據 | 文件審查狀態／未測界線 |
| --- | --- | --- |
| structure-only | [來源與五文件](actual/structure-only/)：Flags兩欄與PK完整列入；OBJECT_ID前檢、欄位長度/NULL與PK Id後檢，SQL-001完整一次 | 待確認：正式工具、artifact、備份／恢复缺證 |
| data-only | [來源與五文件](actual/data-only/)：WHERE Enabled IS NULL保留非NULL值；無捏造筆數，排除並行寫入才預期NULL剩餘0 | 待確認：方言、既有schema、trigger與工具缺證 |
| mixed-transaction | [來源與五文件](actual/mixed-transaction/)：GO、交易、XACT_ABORT完整讀取；01/02同SQL-001，04唯一一列；字串不是Decoy DDL或Users刪除 | 待確認：正式批次續跑／备份工具缺證；未執行SQL |
| migration | [來源與五文件](actual/migration/)：Up/Down完整，保留EF單位/history確認；UAT命令不冒充正式bundle，Down有資料損失 | 待確認：provider、版本、正式bundle、備份缺證 |
| orm-missing-script | [來源與五文件](actual/orm-missing-script/)：Invoice/DbSet新增但無schema/migration，明列缺口並停止相關部署，無自造SQL | 未通過：部署缺口未解 |
| no-changes | [來源與五文件](actual/no-changes/)：base=target、全樹僅AGENTS、工作區空；四份仍有無結論/來源、05五項review、04無動作/空簽核 | 通過（僅無部署動作文書審查；非DB測試） |
| unknown-base | [實際要求輸入](actual/unknown-base/interaction.md)：先查Git根與慣例，未提供base/target/識別即停止；invocation輸入為null，沒有01–05 | stopped/requested-input；沒有向目前人類重問，不預設main |
| uncommitted | [來源與五文件](actual/uncommitted/)：target OldVersion，另有HEAD LaterHead/index StagedVersion/work WorkVersion/untracked全表UPDATE；collector實際分層，要求納入決策 | 待確認：沒有回答所以不混入已提交步驟；「批准納入」分支未測 |
| config-add-change-delete | [來源與五文件](actual/config-add-change-delete/)：Old刪除/Enabled新增/Timeout10→20，連線舊新整值遮罩，消費程式與正式來源不足可見 | 待確認：正式安全來源/provider/套用缺證，未宣稱正式有效 |
| arrays-env-override | [來源與五文件](actual/arrays-env-override/)：完整索引0及__映射，Clear→environment→json，fixture值為JSON，沒有假設環境永遠優先 | 待確認：正式artifact/restart/recovery缺證；沒有執行.NET程式 |
| path-and-signoff | [原bytes保全](actual/path-and-signoff/original-preservation.json)：巢狀中文空白cwd取得正確root，../#42\\正式→#42正式，另建_v2，原簽名raw bytes相同，舊連結#編碼 | 待確認：正式工具等缺證。docs目錄外部symlink/junction的agent寫入分支**未測**；具名成品symlink拒絕另有真實unit tests |
| required-review | [來源與五文件](actual/required-review/)：另一步重讀source/四成品完成必要05；04狀態先更新，final source identity逐項等於已審snapshot，寫05不循環失效 | 待確認。review技能不存在／無能力時回退分支**未測**；不是直接交付可上線 |
| review-defects | [第1輪實際阻擋](actual/review-defects/round-1-findings.md)：漏Flags、混合重跑、錯完整鍵、known synthetic秘密原值、查一下無預期、安全DROP六項。修正後第2輪新讀source/全部成品，五文件保存 | 未通過→待確認（可證文書缺陷修正；必要正式證據仍缺，不降為通過）。缺陷原稿安全存档已遮罩，hash記原bytes |
| review-stale-report | [實際失效](actual/review-stale-report/stale-detection.json)：舊PASS刻意無語意證據；實際修改02與working-tree docs/migration.sql，fingerprint及source identity均變，丟棄舊結論，第2輪重新讀 | 待確認：新增INSERT2只在工作區，target仍CREATE，納入與發布方式待補，不直接存新hash成通過 |
| blank-signoff-placeholder | [原占位](actual/blank-signoff-placeholder/original-signoff.md)：人名/時間全空、未執行，先讀後在原資料夾更新且留更新紀錄；無_v2 | 待確認：正式工具等缺證；signed對照由path-and-signoff實際保全驗證 |

全部15案都有實際來源／行為證據或上述明確未測分支。14案各有五份文件，1案停止無文件；沒有「15/15部署通過」結論。未測：正式DB查詢／SQL執行、.NET runtime、實際安裝/更新/移除、遠端Actions/Release、公有目錄上架、獨立無技能／有技能模型對照、三輪仍失敗的上限分支。缺證fixture保持待確認或未通過是預期行為。

## 重現

1. 在新clone或新實驗工作區執行 `python -X utf8 evals/prepare_actual_fixtures.py`，只建立Git來源，拒絕覆寫既有run。新commit SHA可能不同；由invocation重新取參數，不硬編碼已存SHA。
2. 評估agent讀入口/review技能、references、assets，逐案將invocation的repo/cwd/base/target/diff/識別/日期/工作區決策作為任務輸入，完整讀指定revision與相關全樹。敏感來源在本地記憶體讀取後整值遮罩才輸出。
3. 生成新四文件；unknown-base只記輸入請求且不寫文件。簽核案先依original-signoff建立原紀錄，保留原bytes另建_v2；空占位案在原資料夾更新。按review-defects第1輪表注入缺陷，先review拒絕再修正／重新review；stale案保存旧snapshot，再改02與docs/migration.sql，先宣告失效再review。
4. 另一步重讀原始來源與四成品，記語意理由/輪次，不以hash決定狀態。先更04，final source identity與已審snapshot一致才寫05；完成後重算驗證05不使識別變動。匯出安全來源/參數/各輪證據/五輸出與未測界線。

重現需要agent實際執行技能；準備腳本不生成產品文件、不評分、不執行SQL。本次one-shot轉錄/讀取/報告工具只保存在SDD工作區，判讀是本agent的新來源執行，沒有複製task2成品作PASS。
