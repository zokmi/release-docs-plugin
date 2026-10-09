# SQL／migration 判讀規則

完整讀來源，再對照資料庫方言、schema、消費程式與部署慣例。來源引用採 `revision:path:行號`（刪除檔用 base；工作區用 index／working-tree 標識與內容識別），注明讀取範圍；檔名、commit 標題與關鍵字候選只幫助定位，不是可靠 SQL parser。

## 執行單位與分類

| 類別 | 必寫事實 |
| --- | --- |
| 結構 | 表、欄位／型別／NULL／預設、主鍵、索引／唯一、約束／外鍵、view、procedure 等實際異動與相依 |
| 資料 | seed 值及可證筆數、UPDATE/DELETE/回填/遷移條件、既有資料受影響與不受影響範圍 |
| migration | ID、工具與版本、Up/Down 行為、history／目前版本、既有 artifact 與指令來源 |

每支腳本或 migration 一個執行 ID（例如 SQL-001），记录来源 revision 與完整路徑。混合腳本在 01、02 同 ID 說明；保持完整交易、`GO`、delimiter、工作階段與相依，不剪出 DDL/DML 重跑，將已核對來源完整保存為可執行 .sql；說明使用 SQL 註解，混合內容僅保存一次。字串、註解、動態 SQL 與 stored procedure 內語句須辨別真正執行時機：`N'DELETE FROM Users'` 是值；動態執行與 procedure 修改則讀调用處確認。

交付的 01／02 必須是可直接交給 SSMS、sqlcmd 或專案指定 SQL 工具執行的完整 deployment artifact；不能要求上板人員先啟動 ORM runtime、手動補 SQL 或依賴未交付的隱含步驟。每個執行單位必須定義「正常首次執行、已提交後中斷再執行、正常重複執行」三種狀態收斂規則：已完成項目無動作，未完成項目自動補完，資料不重複／累加／覆寫，不相容狀態停止並回報。這是靜態內容要求；實際 DB 測試仍屬選用部署驗證。

migration 按原工具單位執行，不將 Up/Down 變成手工部署 SQL。來源只有 UAT 命令而正式用 bundle 时，不能把 UAT 命令當成正式命令；缺正式 artifact、provider 或版本則待確認。ORM 新實體／欄位／DbSet 若缺 migration／腳本或已有 schema 證據，列部署缺口并停止相关部署，不能寫「無資料庫異動」。

## 結構內容驗證來源

DB-first repo 若存在 Database.sqlproj，結構來源優先使用 Database Project；dbo/Tables/*.sql 的 CREATE TABLE、索引、約束及 extended properties 是宣告式 schema source，不是可直接上板的增量腳本。EF Sql/*.sql 另依資料／migration／混合單位盤點，不得與 schema source 重複部署。

## 來源與執行 artifact 契約

來源 artifact 原檔逐位元保存，執行 artifact 另存；兩者不要求 byte-for-byte 相同。工具轉換必須由專案鎖定的 SSDT Database Project publish/deployment、EF 官方 script/bundle 或正式 schema compare 工具產出。完整證據具備後才進入語意等價審核，工具成功或可重跑本身不代表內容通過。

artifact metadata 必須包含：base／target SHA 與 schema artifact hash、來源 revision／路徑／定位、provider（Database Project 包含 DSP）、工具版本、遮罩後完整命令、exit code、輸出 dacpac／deployment script／execution artifact hash、來源與執行單位一對一對照、轉換規則及逐單位差異解釋。不同物件可同屬一個完整工具交易／批次，以子項定位作一對一追溯，不能為湊對照拆交易；無法定位即待確認。保存原始工具輸出與最終執行檔，確認沒有範圍外異動、重複單位或無法解釋的差異。

| 差異類型 | 內容判定 |
| --- | --- |
| 鎖定工具產出且完整證據 | 可進入語意等價審核；仍須核對 target schema／資料行為 |
| 格式、註解、GO 或批次分隔 | 記錄轉換規則並證明語意未變；GO 可能影響編譯、變數作用域、交易及工具停止行為，不自動視為無害 |
| 納入單位新增 guard、交易、欄位補建、資料修復或錯誤處理 | 語意轉換；須由正式來源、產製工具或可追溯 repair source 支持，不能只靠人工說明通過 |
| 已證實未經來源管理的人工改寫 | SQL 內容未通過；不得標記完整来源複製 |
| 完整單位受控排除 | 可衍生 execution artifact，須完整 exclusion manifest；不能改寫其他納入單位 |
| 來源本身缺安全重跑機制 | 列來源修正待辦，先修正式來源／工具模式或建立正式 repair migration；不得在 release 文件私補 |

exclusion manifest 每项保存排除 ID、來源 revision／路徑／定位、完整物件或執行單位、來源 artifact hash、execution artifact hash、理由、相依影響、負責人、核准及追蹤依據、逐單位差異核對。若待排除物件與納入物件共用不可分割交易／批次，不能直接刪語句；應在受控 schema／產製設定中表達排除並重新由工具生成，保存完整轉換證據。排除通過不等於整體 SQL 通過。

03_例外排除若產出，只保存受控排除的結構化證據，不改寫納入 SQL；04_參數異動若產出，只保存參數套用與驗證資訊。兩者均不取代來源 artifact 或審查 metadata。

## Database Project 標準產製流程

1. 取得此次 base 與 target revision 的完整 schema source（含 sqlproj、引用與產製設定），在隔離工作副本使用專案鎖定工具分別建置 schema artifact／dacpac。
2. 以 base schema 作比較基準、target schema 作目標，產出 deployment script 或 dacpac publish script；採離線模式，需連線比較時只可使用已確認隔離本機基準，禁止連正式資料庫。
3. 保存兩端 SHA、schema artifact hash、dacpac／deployment script hash、DSP/provider、工具版本、遮罩後命令及 exit code。不得將整個 target CREATE TABLE 清單人工包裝成增量部署 SQL。
4. 套用完整受控排除清單及相依分析，建立 exclusion manifest；重新核對工具輸出及來源／執行單位對照，不混入未選 commit 或排除物件，也不能誤刪未排除物件。
5. 將已核對 execution artifact 交付至 01_結構SQL.sql，來源 artifact 及原始工具輸出另存，完整追溯放 artifact metadata／審查輸入。

工具不可用或 schema／產製證據不足時標記「待確認（缺少 Database Project 工具／schema artifact／產出證據）」，停止受影響單位交付，不自行把 CREATE TABLE 或 ORM model 改寫成部署 SQL。

## 資料與混合單位的 repair source

每個資料來源單位必須標記一個 `artifact class`：`data-migration`（一般資料 migration／seed／回填）、`repair-migration`（為修復既有資料庫物件或資料狀態而建立的正式 migration）或 `mixed-ddl-dml`（同一完整單位同時含 DDL 與 DML）。自定義檔案如 `2026_10_12_ScheduleDrawRepair.sql` 應使用 `repair-migration`，並在檔頭或 artifact metadata 提供唯一 ID、source revision、完整執行單位與相依順序；檔名本身不能作為分類證據。

EF SQL、migration、混合 DDL/DML 不得在 01／02 追加未受來源管理的 REPAIR。來源缺安全重跑機制時，優先修正式來源或建立獨立、可追溯且納入此次 Git scope 的 repair migration；本插件只列來源修正待辦，不擅自新增範圍外 migration。

repair source 必須有唯一 ID、source revision、完整執行單位、相依順序、交易與錯誤處理、來源及 execution artifact hash；若要求部署實測，再保存首次執行、正常重跑至少兩次與新還原基準中斷後重跑的證據。未要求實測不影響內容審核，但必須核對 repair 的靜態冪等設計與來源追溯；已證實 repair 沒有正式來源則內容未通過，來源是否存在尚不能確認則待確認。修正正式來源後重新確認 Git scope、產出並複審，不能私補後宣稱通過。

## 三層審核與狀態

1. **來源完整性**：此次 Git scope 全覆蓋、來源單位唯一且完整，沒有漏列、重複、範圍外異動；排除證據完整。
2. **語意等價性**：結構逐項核對表、欄位、型別、NULL、default、index、PK、UQ、FK、CHECK 及描述；資料／migration 核對條件、WHERE、seed、回填、刪除及資料保留。工具差異可追溯；人工 guard／repair／交易／資料邏輯有正式來源。比較目標是 manifest 說明的受控排除後 target schema，仍保存原 target 與差異，不能偽稱完全等於未排除 target。
3. **執行安全性**：靜態核對交易、错误回拋與停止機制；實測必須完成舊版 DB＋測試資料 → 結構 SQL → 資料 SQL → 最終查核、首次成功、至少兩次正常重跑及新還原基準注入 SQL 錯誤／連線中止後重跑，核對部分提交、資料保留、索引／約束／描述與 history。

SQL 內容審核与部署驗證各自只用「通過／待確認／未通過」。已證實來源 artifact 缺失、未管理人工改寫、工具產製不符或 repair 無正式來源，內容未通過；來源存在性或工具證據不足而未能確定違規，內容待確認。正式主機、部署 provider／driver、DB 版本或隔離 DB 未提供只影響部署驗證，不單獨否決內容；產製工具 DSP/provider 與 schema 證據缺失仍屬內容追溯缺口。缺實際 DB 證據，部署驗證待確認，不能宣稱通過。

來源／執行 artifact、exclusion manifest 或文件任一變更，舊審查立即失效；重新 fingerprint 與語意複審。證據檔保存在 repo 內可由 fingerprint 識別的位置；外部或 ignored artifact 另保存本輪實際 hash inventory，開始／完成／交付逐項重算比對，不得只用 Git fingerprint 假定外部證據未變。

## 案例：release/20261012-no-5005

以下依使用者提供事實判定，非本插件已讀取該專案檔案或完成 DB 實測。範圍 master → release/20261012-no-5005、two-dot；日期 20261012 解析為 2026-10-12，目錄 docs/release-doc/2026-10-12。SQL-001／SQL-002 是交付檔 ID，STRUCT-001～054／DATA-003 是內部單位 ID，不能因檔案合併失去追溯。

- 目前 01_結構SQL.sql：SQL 內容未通過，STRUCT-001～054 人工包裝／改寫，缺 Database Project 工具產出證據。先由 Project/backend/Database/Database.sqlproj 的兩端 schema 重新產製 SQL-001。
- 目前 02_資料SQL.sql：SQL 內容未通過，DATA-003 的 REPAIR 未成正式可追溯來源。先修 Project/backend/EventPlatform.EF/Sql/*.sql 的正式來源或建立正式 repair source，再產出 SQL-002。
- #5005：dbo.tblAdminRoles、dbo.tblFunction、dbo.tblFunctionOnRole、dbo.tblAdminAccounts.cRoleId、FK_tblAdminAccounts_Role、cRoleId 描述。理由是 PM 尚未完成測試、雲端更版文件未列本次 release；這些理由不是核准證據。只有完整 exclusion manifest 才算排除證據通過，不能推論 SQL 整體通過。
- 部署驗證待確認：尚未完成完整舊版 DB 順序驗證與中斷後重跑。
- 修正順序：Database Project／SSDT 重產 SQL-001 → 修 DATA-003 正式來源／repair source → 重產 SQL-002 → 重做來源完整性及語意等價性審核 → 隔離 DB 部署驗證。

若後續已取得完整修正證據，入口應改走「外部產物輸入」分支：Visual Studio／SSDT 建置成功且 SqlPackage schema compare script hash 已保存時，SQL-001 以該 execution artifact 為來源；產物只有訊息或交易包裝、沒有 CREATE／ALTER／DROP 時，結論為「schema 無差異」，不得人工補 DDL。DATA-003 改由正式 repair migration 提供來源時，SQL-002 只引用該 migration，核對唯一 ID、source revision、交易、錯誤與重跑設計，不得再保留內嵌 REPAIR。#5005 的完整 manifest 應輸入非必要 `03_例外排除.json`，由 review 以 ID、完整單位、artifact hash、相依、核准與追蹤欄位驗證；00／03／04 不複製排除內容。完成這些來源與 artifact 審查後，01／02 可進入內容審核；隔離 DB 實測仍維持選用部署驗證。

範圍確認後先完成 diff 分析、執行單位分類、重複／替代核對與相依排序，再產出文件及驗證審核。缺既有 SQL artifact 時，依入口技能「專案工具產生 SQL」使用已確認的 EF／Database Project／schema compare 工具在隔離副本補產，保存來源 SHA、起訖基準、provider、工具版本、命令、artifact 內容識別及結果，核對後作為完整來源使用。只有 ORM 或工具失敗時保留缺口，不手寫推測 SQL。正式版本未知只暫停依賴該版本的步驟，繼續其他分析、產出與來源審查；產生 artifact 不算資料庫執行驗證。

結構 SQL 的內容優先以可重現的 schema 差異來源驗證，依序採用：

1. EF Core／EF migration 的 model snapshot 與 migration 差異，以及該專案產出的正式 migration script 或 bundle。
2. Database project（例如 SQL Database Project／SSDT）專案 schema 與產出的 publish／deployment script 或 schema compare 結果。
3. 專案明確指定的其他 schema compare 工具與其輸出 artifact。

上述來源必須能對應到此次 Git 範圍與目標資料庫 provider／版本，並保存來源路徑、revision、工具版本與產出模式。人工閱讀 ORM 類別、migration 名稱或 commit 訊息只能定位，不能單獨證明欄位、索引、約束或 DROP／ALTER 內容正確。沒有 EF 差異、資料庫專案差異或其他可核對 schema artifact 時，不能自行推導或改寫可執行結構 SQL；應在 SQL 註解、04 與對話審查回報列為待確認／阻擋。

## 本機執行驗證

### 可選的舊版升級部署驗證順序

只有使用者或專案流程要求部署實測時，才依「舊版本 DB＋測試資料 → 結構 SQL → 資料 SQL → 最終結果查核」完成；這是部署信心檢查，不是 SQL 內容審核的必要條件。要求實測時不能以空白 DB 或已升級的目標版本 DB 取代。

1. 在隔離本機建立或還原此次 base 對應的舊版本 DB，核對 schema 與 migration history；先載入符合舊版結構的測試資料並確認成功。資料須涵蓋此次受影響的既有資料、回填／遷移／修正條件及應保留不變的資料，依來源納入 NULL、預設值、唯一鍵與外鍵等適用邊界。保存基準與測試資料來源、版本／內容識別、載入命令及執行前筆數／關鍵值。
2. 在同一 DB 執行本次完整結構 SQL，成功後核對表、欄位、索引、約束、描述與 history，並確認既有測試資料符合預期；失敗即停止，不得繼續資料 SQL。
3. 接著在同一 DB 執行本次完整資料 SQL，核對 seed、回填、遷移、修正或刪除的預期筆數／值、未對應列及應保留資料。無資料異動時附盤點證據並記此階段不適用，不建立假資料 SQL。
4. 比對最終 schema、描述、資料及 history 與此次 target 預期；若本次要求重跑／中斷測試，再從新基準執行下節測試。每個獨立情境重新還原「舊版本 DB＋測試資料」，不得沿用其他情境已升級的 DB 當作首次執行基準。

要求實測時，各階段保存 artifact 內容識別、命令、時間、exit code、錯誤輸出及前後查核結果；未要求或未執行時標「未執行」，不影響獨立的 SQL 內容審核結論。只做 parser、lint、dry-run、產生 script 或空白 DB 建置不能標為部署實測完成，但可作為內容審核的輔助證據。

保持完整 SQL／migration 執行單位、交易及來源相依。混合 DDL/DML 單位只執行一次，不為分階段驗證拆開或重複執行，記錄對應階段與前後檢查。來源相依要求交錯執行而無法遵循上述順序時，明列衝突與來源依據，部署驗證維持待確認，不得私改順序或宣稱符合流程。

每個產出的 SQL 檔若執行隔離的本機資料庫，只作部署驗證，不得連線或執行正式資料庫。SQL 內容審核不要求主機、SQL Azure、版本、provider／driver、collation 或部署工具完全一致；這些屬部署環境待辦。若執行部署驗證，應記錄環境與結果；使用 EF migration bundle 或 Database Project 時，仍應對可用的隔離資料庫執行，而不是把只產生 script 當成已驗證。只有當環境錯誤直接證明 SQL 語法、交易或異常機制有缺陷時，才回到 SQL 內容審核。

驗證流程必須是「建立或還原本機基準 → 執行完整 SQL／migration → 驗證執行結果」：記錄正式機版本依據、本機版本、工具版本、連線目標識別、執行命令、開始／結束時間、exit code、錯誤輸出，以及執行後 schema、索引／約束、資料筆數／值與 migration history 結果。敏感連線資訊不得寫入紀錄。只做 parser、lint、`--dry-run` 或產生 script 不算執行成功。

驗證失敗、只完成部分交易、正式機與本機引擎／版本／provider 不一致，或本機沒有可用資料庫時，狀態必須為待確認或未通過，並停止宣稱 SQL 可上線。不得為了通過驗證修改來源 SQL、跳過錯誤、猜測正式機版本、改用不同方言或連線正式資料庫。

## 順序與檢查

- B 引用 A 的表／欄位／seed／外鍵目標时 A 先 B；啟動即用新 schema 的程式必須在 schema 就緒後。破壞性改動需確認舊程式相容、停止／切換時機。
- 多腳本改同表時反查「前面的回填是否漏掉後面才插入的列」，從条件與消費程式判斷预期；不能只检查物件相依。每個順序结论附來源，未知列待確認。
- 每個新表在執行前查不存在或確認既存表形狀与預期一致；`IF OBJECT_ID`／`IF NOT EXISTS` 只保護存在性，可能靜默跳過不相容結構，不代表全部可重跑。
- 逐單位記交易、COMMIT／批次、錯誤處理與部分成功。SQL Server `SET XACT_ABORT ON`、交易及 `GO` 不足以證明跨批次／工具全部回復；依引擎、工具与來源判斷。回滚／還原指令必须已有证據，不能猜可安全删除已建立物件。
- 記鎖表、索引／大量 UPDATE、資料覆寫、約束驗證的風險；沒有資料量与環境測量不估時間或影響筆數。未提交来源标「尚未進版控」与是否纳入、发布取得方式。
- SQL Server severity 10 `RAISERROR` 或 PostgreSQL `RAISE NOTICE` 通常不中断；確認實際控制流程，列警告意义、驗證與停止動作。字串比對／JOIN 無對應可能靜默漏遷移，補可操作的未對應列檢查。

## 驗證與失敗處理

每項檢查寫方言正確的只讀查詢或工具动作、预期結果与依据。精确筆數可從固定 seed 算出，但既有資料 UPDATE 不捏造筆數；验证「仍有符合條件的列為 0」需交代并行写入／维护窗口。连「大于 0」也必須有来源保障，不能把它当万能预期值。無 schema／方言／环境證据時写「待確認（缺哪個資訊）」，不要放不能貼上執行的佔位 SQL 并稱可用。

逐單位回答失败位置、已提交部分、停止后续依赖、能否直接重跑及前置条件、需留證的日志、数据库备份恢复與程式版本相容性；未知即禁止直接重跑並待確認。Down／DROP／DELETE 可能失去資料，不能等同回復。SQL Server filtered index／computed column 的工作階段選項与專案型别／時間函式等代码问题记录开发者待办与阻擋证据，不能在文件里悄悄修 SQL。

## 異常中斷與重複執行的內容要求及選用實測

每個可執行單位的設計必須定義正常重跑與異常中斷後重跑應收斂的結構、描述及資料狀態；實際執行這些情境屬選用部署驗證。

- 表、欄位、索引與約束分別核對存在性及完整定義；表已存在不能跳過後續未完成步驟。已正確者跳過、缺少者補建；有來源依據且可證安全的差異才自動修正，不相容或可能損失資料時停止並報錯。
- 表／欄位描述獨立於建表／加欄位執行，檢查存在性及內容；缺少新增、不符更新、相同無動作。描述新增或更新中斷後也須能重跑補完。
- 資料依穩定鍵與預期狀態檢查，避免重複 INSERT、累加或覆寫應保留值；不相容資料不得靜默略過。migration history 不得在完整單位成功前標記完成，也不能代替單位內狀態檢查。
- 依來源引擎及部署工具核對交易、錯誤回拋、停止後續相依、非交易 DDL 與跨批次部分提交。TRY/CATCH、XACT_ABORT 或 IF NOT EXISTS 單獨不足以證明容錯；禁止吞錯續跑。

內容審核以 guard、狀態檢查、交易、錯誤回拋、停止後續相依、資料冪等性及可恢復限制的靜態設計判斷，不因尚未在 DB 執行而自動不通過。若使用者或專案要求部署實測，才在相容性證據足夠的隔離本機引擎／版本／provider／driver／工具與基準先首次執行成功，再至少重跑兩次，核對結構、描述、資料及 history 不重複、不累加，並從新還原基準依提交邊界注入中斷。記錄中斷位置、已提交狀態、停止結果、同一 artifact 重跑命令及最終比對；不能改 SQL 製造假通過。實測失敗若直接證明 SQL 內容或異常機制缺陷，內容未通過；單純環境不相容列部署待辦。

缺機制或來源不安全列來源修正待辦並判文件未通過；未要求或未執行 DB 實測記「部署驗證未執行」，不改變內容審核結論。要求實測但缺環境／provider／driver 證據判部署驗證待確認；先嘗試專案工具可追溯的可重跑輸出，不能解決時不得私改來源交付。修正來源或工具 artifact 後重新核對範圍並複審。無異動純註解檔為無動作，重跑測試不適用並附盤點證據。

## 「無」的證據

只有指定範圍、工作區決策及相關 SQL／migration／ORM／內嵌 SQL／部署來源已盤點才寫無；未讀、权限不足或没有脚本但 ORM 有变化时寫待確認。文件審查核對執行紀錄；符合條件的隔離本機 SQL 執行由產出後的驗證階段完成，UAT與正式驗證欄保持未执行直到取得真实紀錄。
