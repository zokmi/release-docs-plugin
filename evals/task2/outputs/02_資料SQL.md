# 資料 SQL — fixture-task2

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

## 資料異動

SQL-001 与 [01](01_結構SQL.md) 是同一完整 mixed.sql；[04](04_上線指引.md) 只執行一次。新增一筆 dbo.Flags，Id=1，Note 值為字串 `DELETE FROM Users; CREATE TABLE Decoy`（mixed.sql:5）。沒有刪除 Users、沒有建立 Decoy、沒有 UPDATE／DELETE 既有資料。種子一筆與值直接由 VALUES 得知，不推估正式資料總量。

SQL-001 前置為 dbo.Flags 不存在，與建表處於同一交易，不可將 INSERT 單獨再執行。執行後查 `SELECT Id, Note FROM dbo.Flags WHERE Id = 1;`，預期一筆，Note 等於上述完整字串；`SELECT COUNT(*) FROM dbo.Flags;` 預期新建表中的一筆，僅適用無併行新增的本次單位完成後檢查。這些查詢未執行。

直接重跑會因同名表／主鍵衝突，不能宣稱重跑安全。混合單位保留 GO 與交易；失敗時停止 APP-001，查明 COMMIT 是否成功及工具錯誤策略，保留脫敏紀錄。未知恢復流程列待確認；不能猜用 DROP／DELETE 安全回復。

## 缺口與更新

待確認（正式 artifact、備份、恢復與工具策略，README.md:2）。2026-10-08 初次產出；UAT與正式未執行。
