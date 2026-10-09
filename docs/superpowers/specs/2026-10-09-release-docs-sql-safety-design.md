# release-docs SQL 防錯與 EF 分析架構

日期：2026-10-09
狀態：設計已確認，待實作規劃

## 目標

使用者提供舊版資料庫結構、Git codebase diff 範圍與排除意圖後，插件以 Entity Framework 為主要資料庫異動來源，自動分析單一 SQL Server 資料庫的完整異動範圍，產出可追溯且適合人工執行的上線套件。

插件負責分析、產製、審核與隔離驗證；正式資料庫不由插件連線或修改。正式 SQL 由上板人員在 SSMS 或相容資料庫工具中，以新 connection／session 手動執行。

## 首版範圍與限制

- 只處理單一 SQL Server 資料庫，最低支援 SQL Server 2016，以便使用 `SESSION_CONTEXT` 傳入執行模式。
- EF6 與 EF Core 由插件自動偵測，不要求使用者先指定版本。
- 多個 `DbContext` 只有在能證明指向同一資料庫時才合併分析；無法確認時阻擋。
- 不可納入 release-level transaction 的 SQL 操作首版直接阻擋，不產出受控非交易 unit。
- 模型變更缺少可重建的 migration、migration chain 不完整、provider 不明或 baseline 無法對應時阻擋。
- 不直接修改正式資料庫、不把 repair source 寫回原始 Database Project 或 EF source。

## 最終輸出契約

交付目錄只包含：

```text
00_上線指引.md
01_部署SQL.sql
02_參數異動.md        # 僅有參數異動時產出
```

`01_部署SQL.sql` 是唯一人工執行 SQL，依序包含 `SCHEMA`、`REPAIR`、`DATA`、`VALIDATION` 四個區段。每個 unit 帶有唯一 ID、來源路徑、revision、source hash、SQL hash、source line、artifact line range 與 dependency mapping。

`lifecycle_exclusion_manifest.json`、完整 source metadata、原始 EF 工具輸出、repair source、LocalDB 證據與審核輸入只保存於 `.release-docs/runs/<run-id>/`，不進入上板目錄，也不要求人工執行或修改。

`00_上線指引.md` 說明結構異動、參數異動、排除摘要、備份、維護窗口、單一 session 執行方式、失敗處理與部署後查核。排除摘要是 lifecycle manifest 的人工可讀投影，不是排除真相。

## 架構元件

### EF 偵測器

從專案檔、套件鎖定檔、provider 參照、`DbContext`、migration、model snapshot 與可用工具資訊辨識 EF6／EF Core、版本、provider、context 與 migration chain。每個判定保存來源路徑、revision、hash 與偵測結果。

偵測器必須將版本衝突、provider 不明、context 與資料庫對應不明及缺少 migration chain 視為阻擋條件，不以檔名或 migration history 單獨猜測。

### 來源與差異分析器

固定 Git 根目錄、base／target revision、diff mode、工作區是否納入，以及舊版 DB schema 的來源與 hash。從 base revision 取得 baseline，從 target revision 取得 migration、model snapshot、migration 內原始 SQL、SQL 檔案與設定消費端；工作區異動與已提交異動分開記錄。

分析器以 EF migration operation 與模型差異為主要來源，migration history 僅作輔助證據，仍須核對實際 table、column、index、FK、constraint 與 extended property 定義。模型有變更但沒有完整 migration 時阻擋。

### Unit 規劃器

將完整異動拆成 `SCHEMA`、`REPAIR`、`DATA`、`VALIDATION` unit，為每個 unit 建立：

- 完整物件定義與受影響物件。
- 前置條件、dependency 與執行順序。
- 已存在且定義正確時的跳過條件。
- 缺少時的補建行為。
- 定義不相容、可能遺失資料或無法判定時的停止條件。
- 驗證查詢與預期結果。
- source revision、source path、source hash、source line 與 SQL hash。

`complete` 必須由分析證據支持，不能只相信來源檔案中的宣告。無法建立完整 unit 時保留診斷資料並阻擋產製。

### 排除分析器

使用者輸入是排除意圖，不是完整 manifest。分析器將意圖對應到完整 migration operation／unit、物件與 dependency，建立 `lifecycle_exclusion_manifest.json`。每項 exclusion 必須記錄唯一 ID、完整 unit、source provenance、operator action、理由、dependency impact、reinstatement conditions、authorization、review 與 evidence。

同一 migration 混合多個功能時，只有能證明完整切分且不破壞 dependency 才允許排除；否則阻擋。被排除 unit 不得進入 `01_部署SQL.sql`，也不得產生對應 DROP、DELETE 或欄位補建。

### SQL 產製器

EF 工具產出的 SQL 與 execution artifact 分開保存。需要補強前置條件、完整定義檢查、repair 或安全重跑行為時，建立可追溯 repair source，不直接修改 EF 原始產物。

產製器在組裝前執行 source provenance、dependency、unit order、hash、敏感資訊與危險語法檢查。來源內不透明的 `EXEC`、未受控 dynamic SQL、batch-only DDL、資料庫切換、transaction control、不可交易 DDL、`GO` 或不完整 SQL 均阻擋。產製器自行建立的受控 unit execution wrapper 必須能與來源內不透明執行區分。

## SQL 交易與人工執行契約

`01_部署SQL.sql` 必須是可直接在 SSMS 執行的純 T-SQL，不依賴 `:setvar`、`:r` 或 sqlcmd 專用語法，也不使用需要人工拆批的 `GO`。整份檔案必須在同一個新 connection／session 一次執行。

檔案使用單一 release-level transaction、`SET XACT_ABORT ON`、`TRY/CATCH` 與原始 `THROW`。unit 不得自行 commit、rollback、切換 database 或修改保留執行 context。每個 unit 執行前設定 phase、unit ID、source path、revision 與 line，失敗後輸出結構化 context、rollback 狀態並停止後續 unit。

執行模式由 session context 控制，且預設為安全的 ValidateOnly：

```sql
DECLARE @RawValidateOnly sql_variant =
    SESSION_CONTEXT(N'ReleaseDocs.ValidateOnly');

IF @RawValidateOnly IS NOT NULL
   AND (TRY_CONVERT(tinyint, @RawValidateOnly) IS NULL
        OR TRY_CONVERT(tinyint, @RawValidateOnly) NOT IN (0, 1))
    THROW 51002, N'ValidateOnly must be 0 or 1.', 1;

DECLARE @ValidateOnly bit =
    COALESCE(CONVERT(bit, TRY_CONVERT(tinyint, @RawValidateOnly)), 1);
```

未設定時採用安全預設 `1`；明確設定但不是 0／1 時必須停止。`ValidateOnly=1` 完整執行並驗證後 rollback；只有上板人員在同一新 session 明確設定 `0` 才允許 commit：

```sql
EXEC sys.sp_set_session_context
    @key = N'ReleaseDocs.ValidateOnly',
    @value = 0;
```

設定後在同一視窗執行整份 SQL。`sp_set_session_context`、執行 context 或 `@ValidateOnly` 的來源內修改均列為危險語法。正式執行前，`00_上線指引.md` 必須要求唯讀 preflight、備份／快照與維護窗口確認。

錯誤輸出至少包含 release ID、database、server、ValidateOnly、phase、unit ID、source path、source revision、source line、SQL Server error metadata、`XACT_STATE()`、`@@TRANCOUNT` 與 transaction action；敏感訊息必須遮罩。連線中斷或無法取得 CATCH 證據時，結果只能標示為待確認，不能自動判定失敗或成功。

## LocalDB 與正式執行證據

LocalDB 驗證是隔離的部署信心檢查，不取代正式 provider、版本、權限與維護窗口確認。若有 disposable runner，必須從 fresh baseline 執行四輪：

1. ValidateOnly 完整執行後 rollback。
2. Fresh baseline 以 ValidateOnly=0 執行並 commit。
3. 在已 commit 的資料庫以新 session 重跑，確認結果收斂。
4. 注入可預期 unit failure，確認 rollback、`THROW` 與後續 unit 未執行。

每輪保存 server、database、provider／tool version、baseline、fixture、command、exit code、checks、error summary 與 artifact hash。沒有必要 runner、baseline、fixture 或版本證據時狀態只能是 `未執行` 或 `待確認`。

正式環境執行證據由上板人員提供，至少包含實際 artifact hash、server/database、執行模式、session、開始／結束時間、結果查核、錯誤輸出與停止原因。插件不把人工回報直接視為已驗證；證據不完整時維持 `待確認`。

## Lifecycle、fingerprint 與審核

每次產製建立不可覆寫的 `.release-docs/runs/<run-id>/`。永久 evidence 與可清除 temporary 分開保存：成功交付後只清除明確標記的 temporary；失敗或中斷 run 保留七天供診斷，過期後只清除受控 temporary，不刪除永久 manifest、review record 或 execution evidence。

審核分開回報：

- SQL 內容審核：來源、unit mapping、交易契約、ValidateOnly、錯誤處理、重跑條件與 fingerprint。
- 部署驗證：LocalDB 四輪或正式人工執行證據；沒有證據不得宣稱通過。

審核機必須比對 `lifecycle_exclusion_manifest.json`、`01_部署SQL.sql` 與 `00_上線指引.md` 的排除摘要。找不到 lifecycle manifest、來源 revision、execution artifact 或必要 hash 時，排除範圍與審核均為待確認或未通過。

fingerprint 至少涵蓋 `00_上線指引.md`、`01_部署SQL.sql`、適用的 `02_參數異動.md`、lifecycle exclusion、source revision、source／execution artifact hash 與 baseline hash。任何來源、排除、SQL、repair 或參數異動都使既有審核失效。

審核狀態採用 `通過`、`待確認`、`未通過`；文件審核通過不代表正式資料庫已執行。

## 風險控制與優化

- 每個 unit 增加分析 confidence 與阻擋原因，讓使用者只需補充具體歧義。
- 預設 ValidateOnly=1，降低人工忘記設定時誤提交的風險。
- 產製前檢查資料量、長交易、lock／blocking 與 log 風險；不在部署 SQL 內自動 retry。
- 動態 SQL、編譯錯誤與 wrapper 的 artifact line range 必須可對回原始 migration source。
- 不以 LocalDB 結果推論正式 provider 結果。
- 所有來源與 evidence 以 revision／hash 固定，避免使用工作區內容冒充指定版本。
- 人工執行證據使用明確的 `未執行`、`人工回報`、`證據完整`、`待確認` 狀態，避免把審核結果誤稱為部署成功。

## 首版驗收

1. 能自動辨識 EF6／EF Core、版本、provider、單一資料庫與 `DbContext` 對應；無法確認時阻擋。
2. 能從 EF migration、model snapshot 與 baseline 產生完整 unit；缺 migration 或結構不一致時阻擋。
3. 能產出唯一 `01_部署SQL.sql`，且排除 unit 不會進入 SQL。
4. SQL 能在新 SSMS session 以 ValidateOnly=1 執行後 rollback，明確設定 0 才 commit。
5. 已 commit 後重跑不產生重複欄位、index、constraint 或資料。
6. 注入錯誤時能 rollback、`THROW`、停止後續 unit，並輸出可定位的錯誤 context。
7. LocalDB 證據與 SQL 內容審核分開保存；沒有 runner 或證據時不宣稱通過。
8. lifecycle manifest、source metadata、artifact hash、review record 與永久 execution evidence 可重建且不可靜默覆寫。
9. 交付目錄只包含定義的 `00`、`01` 與適用的 `02`。

## 不在本次範圍

- 多資料庫或跨資料庫 migration。
- 支援不可交易 DDL 的自動補償流程。
- 插件直接連線或修改正式資料庫。
- 將人工修正寫回 EF migration、Database Project 或原始 codebase。
- 以 LocalDB 取代正式 provider／版本／權限／維護窗口驗證。
