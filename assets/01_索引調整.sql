-- # 索引調整 SQL — {{識別}}
--
-- 本檔只在索引名稱可能因環境差異而無法直接由 01_結構SQL.sql 安全執行時產生。
-- 一般工具產出的確定索引異動仍放在 01_結構SQL.sql，不得重複執行。
-- artifact class: index-adjustment
--
-- | 項目 | 內容 |
-- | --- | --- |
-- | 索引調整 ID | {{IDX-001}} |
-- | 來源與 execution artifact | {{revision:path:定位、source hash、execution hash}} |
-- | 目標物件 | {{schema.table}} |
-- | 預期索引定義 | {{key columns／順序、included columns、unique、filter、clustered}} |
-- | 名稱差異處理 | {{唯一符合者 rename／跳過；找不到或多個符合者停止}} |
-- | 與 01 相依 | {{欄位／表／約束／索引相依 ID 與執行順序}} |
-- | 人工處置 | {{僅在明確停止條件下依 metadata 選擇；不得猜名稱或直接 DROP}} |
--
-- 執行契約：同一 connection/session 內完成完整查詢、異動與驗證。
-- ValidateOnly=1：執行後 ROLLBACK；ValidateOnly=0：執行後 COMMIT。
-- 禁止第一次保留未提交 transaction，再由第二次獨立執行接續 COMMIT。

SET XACT_ABORT ON;
SET NOCOUNT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    -- 1. 以 schema/table 與完整索引定義查詢 sys.indexes、sys.index_columns、sys.columns。
    -- 2. 只允許找到唯一符合的現有索引；找不到或多個符合時 THROW。
    -- 3. 只執行已由來源與 artifact 證據支持的 rename／create／drop-create。
    -- 4. 執行後重新查核 key、include、unique、filter、clustered 與名稱。
    -- TODO: 填入來源提供的完整可執行 SQL；不可保留模板或人工猜測。

    IF EXISTS (SELECT 1 FROM dbo.__ReleaseIndexValidationErrors)
        THROW 50021, N'索引定義或名稱驗證失敗', 1;

    IF @ValidateOnly = 1
        ROLLBACK TRANSACTION;
    ELSE
        COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
