# 結構SQL — mixed-transaction

| 項目 | 內容 |
| --- | --- |
| 日期／時區 | 2026-10-08／Asia/Taipei |
| 識別 | mixed-transaction → mixed-transaction |
| base SHA | 86a6b2a0f4f626a7326bb65e7c2080fc646c0a16 |
| target SHA | 158d4cd7084e1a7e440e7ee21ee343686683f100 |
| diff 模式 | direct（fingerprint two-dot） |
| 工作區 | staged/unstaged/untracked無額外部署來源；生成的精確五份成品排除，legacy簽核保留（如有） |
| 來源 | 158d4cd7084e1a7e440e7ee21ee343686683f100:mixed.sql:完整閱讀；base/target全樹完整盤點 |
| 取代文件 | 無 |

## 異動、執行單位與檢查

SQL-001，target:mixed.sql:1-7 完整單位。第4行建立 dbo.Flags，Id int NOT NULL PRIMARY KEY，Note nvarchar(100) nullable。第5行 N字串中的 CREATE TABLE Decoy 不建表，沒有 Decoy 異動。前檢 SELECT OBJECT_ID(N'dbo.Flags',N'U'); 預期NULL，否则停止。後檢 sys.columns 預期 Id/int/max_length4/is_nullable0、Note/nvarchar/max_length200/is_nullable1；PK join index_columns/columns 僅 Id/key_ordinal1。nvarchar(100) 的 max_length 以bytes為200。驗證設計未執行。

## 缺口與失敗處理

正式工具、備份、批次續跑行為缺證。XACT_ABORT與交易不代表跨GO全部自動恢復。失敗停止後續依賴，記已完成批次、查交易狀態後由有證據的恢復流程處理；不承諾安全DROP。

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
