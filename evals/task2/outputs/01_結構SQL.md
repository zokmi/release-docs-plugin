# 結構 SQL — fixture-task2

| 項目 | 內容 |
| --- | --- |
| 產出日期／時區 | 2026-10-08／Asia/Taipei |
| 識別 | fixture-task2 |
| base SHA | 87c3bb769165b55e2884c5027c3fd78bc5f4a8b4 |
| target SHA | a01af9ba4fdf2b148ed61ad77f04c0cfdb86cdbd |
| diff 模式 | direct |
| 工作區範圍 | staged、unstaged、untracked：無；不納入工作區 |
| 來源證據 | target:mixed.sql:1-7；target:README.md:1-3；全部fixture來源完整閱讀 |
| 取代文件 | 無 |

## 結構異動

SQL-001 為 target:mixed.sql 的完整執行單位；新增 dbo.Flags，Id int NOT NULL PRIMARY KEY、Note nvarchar(100) 可為 NULL（mixed.sql:4）。資料說明见 [02](02_資料SQL.md)，唯一執行表见 [04](04_上線指引.md)。字串中的 CREATE TABLE Decoy 不是建表，沒有 Decoy 結構異動。

執行前在既有 SQL Server 工具查 `SELECT OBJECT_ID(N'dbo.Flags', N'U');`，預期 NULL，表示不存在；若非 NULL 停止，核對既有 schema 與來源，不直接重跑。來源無存在性保護；同名物件會衝突。

執行後執行 `SELECT name, TYPE_NAME(user_type_id) AS type_name, is_nullable FROM sys.columns WHERE object_id = OBJECT_ID(N'dbo.Flags', N'U');`，預期 Id/int/0 與 Note/nvarchar/1；另查 `SELECT name FROM sys.key_constraints WHERE parent_object_id = OBJECT_ID(N'dbo.Flags', N'U') AND type = 'PK';`，預期一筆主鍵。查詢是文件建議，未在資料庫執行。

完整來源含 GO、BEGIN TRANSACTION、COMMIT 與 XACT_ABORT ON（1-7）；不拆批次或重新組合。只列一次 SQL-001。未提供工具的錯誤續跑策略與正式資料量，不能推定跨批次全部自動回復、可安全重跑或耗時。失敗即停止後續程式部署，保留訊息与已完成批次，查明交易狀態後再決定恢復；回復流程待確認。

## 缺口與更新

待確認（正式 artifact、備份与錯誤續跑策略未提供，README.md:2）。2026-10-08 初次產出，無執行紀錄。
