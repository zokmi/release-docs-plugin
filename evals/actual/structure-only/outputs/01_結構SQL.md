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

## 方言確認後可使用的只讀結構檢查（未執行）

```sql
SELECT OBJECT_ID(N'dbo.Flags', N'U');
SELECT name, TYPE_NAME(user_type_id) AS type_name, max_length, is_nullable FROM sys.columns WHERE object_id=OBJECT_ID(N'dbo.Flags', N'U');
SELECT c.name, ic.key_ordinal FROM sys.key_constraints k JOIN sys.index_columns ic ON ic.object_id=k.parent_object_id AND ic.index_id=k.unique_index_id JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE k.parent_object_id=OBJECT_ID(N'dbo.Flags', N'U') AND k.type='PK';
```

上述查詢僅適用SQL Server；工具與引擎需補證才使用。预期值见異動說明。Flags(review-defects)與OldVersion來源沒有PK，PK查詢預期0；其餘來源有PK預期Id/key_ordinal1。
