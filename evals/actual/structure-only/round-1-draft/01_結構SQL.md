# 結構SQL — structure-only

| 項目 | 內容 |
| --- | --- |
| 日期／時區 | 2026-10-08／Asia/Taipei |
| 識別 | structure-only → structure-only |
| base SHA | 531c6e8fdf96f6e6d25051d0f9389d60044902c7 |
| target SHA | e9ef25d82126c9fecf45ed3c42a82e2ae1f63bbc |
| diff 模式 | direct（fingerprint two-dot） |
| 工作區 | staged/unstaged/untracked無額外部署來源；生成的精確五份成品排除，legacy簽核保留（如有） |
| 來源 | e9ef25d82126c9fecf45ed3c42a82e2ae1f63bbc:schema.sql:完整閱讀；base/target全樹完整盤點 |
| 取代文件 | 無 |

## 異動、執行單位與檢查

SQL-001，target:schema.sql:1 新建 dbo.Flags：Id int NOT NULL PRIMARY KEY、Enabled bit NOT NULL。執行前 SELECT OBJECT_ID(N'dbo.Flags',N'U'); 預期 NULL；不為 NULL 停止核對既有結構。執行後查 sys.columns 的 name、TYPE_NAME(user_type_id)、max_length、is_nullable，預期 Id/int/4/0、Enabled/bit/1/0；查 sys.key_constraints JOIN sys.index_columns JOIN sys.columns，Flags 的 PK 僅 Id、key_ordinal=1。此為 SQL Server 型別判讀，部署工具及環境未提供，查詢未執行。無存在性保護，直接重跑同名物件衝突。

## 缺口與失敗處理

正式工具、artifact、維護窗口、備份與恢复流程未提供；停止部署直到補證，不能猜安全 DROP 或時間。

上線唯一執行順序見[04](04_上線指引.md)，混合腳本同一ID只執行一次。

## 更新紀錄

2026-10-08新實際fixture run；沒有執行SQL。
