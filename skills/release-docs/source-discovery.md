# 自動取得來源與補齊產製輸入

在 Git evidence 收集後、正式 unit analysis／produce_release 前執行本流程。這是代理利用現有工具執行的工作規範，不代表 collector 已實作 SSDT deployment、SQL parser 或業務規則推導。所有結果留在本次 run，正式 DB 不連線；不執行 repository 中未核對的命令。

## 1. 重用決策，探測能力

- 從本次對話取回已確認 repo、base/target、diff mode、工作區政策、baseline 與排除意圖；不要重新詢問同一決策。分別記錄 Git diff baseline 與已確認的實際 DB baseline，不以 HEAD 或 Git base 覆蓋附件。
- Windows 先以 `Get-Command git,dotnet,MSBuild,SqlPackage,sqlcmd,SqlLocalDB -ErrorAction SilentlyContinue` 探測，其他平台使用相應命令查找；再核對工具版本、專案 SDK／provider、已知官方安裝位置及專案的 tool manifest。PATH 未找到不等於工具未安裝；不得遞迴掃描無關使用者資料或輸出機密。缺 adapter 不妨礙來源盤點與預期推導。
- 用 Git tree／pinned blob 盤點兩端來源；`rg --files` 只用於已物化且 revision 已核對的目錄。搜尋 sqlproj、publish profile、pre/post deployment、dacpac、migration、SQL、verify、app consumer 與設定 key；查既有 run 產物時核對來源與 hash，不照用舊通過結論。

## 2. 取得 baseline→target artifact

兩端都有 Database Project：在受控來源副本以專案已核對的建置方式產製模型；記錄 revisions、project references、工具設定、變數來源與 hash。target-only project：明確記錄 base 沒有 project，改用使用者已確認的舊版／正式 schema SQL。在已授權的 disposable DB 路徑物化該 SQL並由可用工具取得模型，再比較 target；未授權本機 DB 執行時完成離線分析，列明所需能力。不得為了湊 base project 合成未核對結構。

使用已確認工具產製 deployment plan／script，不使用 Publish 對正式環境寫入；工具參數以實際 help 與專案設定為準。比對 excluded objects 的現有定義與 target 定義，避免 schema compare 將排除物件當作待 DROP。需要排除 target 模型時只能在隔離來源副本作可追溯變換並保存 mapping，不修改原始專案、不用字串刪 SQL；排除無法安全隔離即阻擋該產物。target 建庫 script、一次性 deployment script 與本插件要求的可重跑 unit 分別審核；工具成功產製不代表符合交易／rerun 契約。

## 3. 從分析結果建立工具輸入

讀 `scripts/analyze_release_units.py` 的 descriptor 契約，從完整 SQL 與驗證來源建立機器可讀的 `evidence["execution_units"]`，不要求使用者先替來源加 `-- release-unit:`。既有 SQL 無標記可用 external descriptor；source_path 必須指向核對過的 pinned SQL，SQL bytes 由 analyzer 讀取，descriptor 的 target_definition.sql 必須精確相符。

逐 unit 產製 unit_id、phase、objects、issues、depends_on、preconditions、target_definition、skip_condition、stop_condition、validation_queries 及必要 covers；query/expected 使用現有 schema。來源 revision/hash/line 由工具重新核對；將每個條件的推導依據保存於來源分析紀錄。verify script 可提供查核語意，仍須核對是否能證明該 unit，不能只因副檔名直接採信。前置／skip／stop 要驗完整定義，不能只看物件存在、填恆真查詢或先寫 complete=true 來通過檢查。SQL 檔案數不是 unit 數：完整邊界不可安全拆分時保留 blocker。

建立單號→來源→物件→unit mapping 與相依閉包，含 diff 外前置物件；同時列出不受影響與無法解析的來源，不用全 repo 檔案數當 SQL 範圍，也不改變 Git scope。#5005 等排除依已授權意圖解析成完整 units，不能照抄案例的六項物件或以相依自動擴大授權。

使用 `scripts/derived_sources.py` 的 `derived_artifact` 來源契約接入 run 內新產製的 deployment／repair bytes；`pinned_git` 仍核對 base/target blob。兩者都要保存 scope、baseline、完整輸入 hash、工具／版本、mapping 與輸出 hash。禁止偽填 source_revision/hash、假稱產物已在 target、只靠 covers 將 sqlproj 當 execution SQL，或私自 commit／更換 scope。未知來源類型與任一 hash／mapping 不符均拒絕；此限制不能成為不生成其他可取得 descriptors 的理由。

## 4. 自動建立 fixture、預期與設定說明

依主技能四輪推導契約，先解析 DATA predicates、轉換與保留規則，產生 fixture SQL、seed rows、coverage、expected_assertions 與 expected_preserved_data_summary。每個適用 case 對應明確 seed_row_id；不適用有來源理由，未知不能填不適用。物化 fixture 前先核對 baseline constraints、FK 順序、必填值與唯一性，使用合成資料，不複製正式資料或機密。先固定預期，再取得實測；不是只產出 remediation-plan.md。

從設定 diff、consumer 與部署文件推導 parameter_changes／parameters_applicable、服務、環境與 reload／validation。檢查到無異動可附查核範圍與理由明確記錄 false；未檢查或無法判定維持未知。讀取時避免輸出 secret 原值，描述依現有遮罩契約保存。交易模式遵循插件契約，不把固定安全機制重新當成待使用者選擇的資料。

## 5. 重跑資格檢查，持續完成可做部分

保存候選 descriptors、來源 mapping、推導依據與未解析清單後重新呼叫 analyzer。`missing_authoritative_sql`、units=0 不代表無 DB 異動；analyzer 在 blocked 時會清空 units，因此候選盤點另存，避免丟失已完成分析。缺 metadata 先自動補 metadata；來源 SQL 的 GO、獨立 COMMIT、opaque EXEC、RAISERROR 或非冪等轉換則是另類問題，不能補欄位掩蓋、刪字或直接包 transaction。

來源分析完成後，產製器預設選用 `database_tool_minimal` SQL profile：工具探測結果需包含可建立 fresh connection／transaction、執行完整 artifact、取得逐 unit 結果與 rollback／commit evidence 的能力。若只能使用舊 framework wrapper，保存 `sql_profile=framework`、工具限制與 fallback 原因；不得因工具具最高權限而把 session `SET`、權限或 transaction 控制塞回 source unit。

若已授權來源修正，依 systematic-debugging 保存重現、根因與最小修正，在可追溯 repair／source 修正後建立新 pinned evidence 與新 run，重跑受影響檢查及四輪；不得修改交付 SQL後沿用舊 hash。沒有來源修正授權時保留精確修復位置，但繼續完成其他 units／fixture／參數分析。不得用「首次成功、正式只跑一次」取代 rerun 門檻。三次修正仍失敗時停下檢討來源／編排設計，不繼續症狀式補 guard。

資格滿足才呼叫 produce_release、獨立語意審查、真實 adapter 四輪與最終 fingerprint。每次回報區分已分析、已生成工具輸入、已產製 artifact、已執行與已審查。使用者要求「補齊」或「繼續」時應執行已授權且可安全完成的取得與補齊步驟，不以新增計畫文件作為完成；僅對不可推導的業務規則、未授權來源變更或實際能力缺口提出最小問題。
