# 結構SQL — review-stale-report

| 項目 | 內容 |
| --- | --- |
| 日期／時區 | 2026-10-08／Asia/Taipei |
| 識別 | review-stale-report → review-stale-report |
| base SHA | 28ffb8a6846bd39fd8956c7c907c5220e84514cf |
| target SHA | 3f5cdab3683de2a4e3518b422ed457aefe58b050 |
| diff 模式 | direct（fingerprint two-dot） |
| 工作區 | staged/unstaged/untracked無額外部署來源；生成的精確五份成品排除，legacy簽核保留（如有） |
| 來源 | 3f5cdab3683de2a4e3518b422ed457aefe58b050:docs/migration.sql:完整閱讀；base/target全樹完整盤點 |
| 取代文件 | 無 |

## 異動、執行單位與檢查

SQL-001 target:docs/migration.sql:1 新dbo.EvalMarker (Id int NOT NULL PRIMARY KEY)。docs底下的migration來源仍屬審查範圍，不能排除整個docs。執行前OBJECT_ID應NULL；執行後Id/int/4/非NULL，主鍵Id一列，既有工具/方言待確認。保持完整腳本，直接重跑同名衝突。

## 缺口與失敗處理

正式工具/方言、備份、artifact与恢复方案缺證；停止實際部署，不猜安全DROP。

上線唯一執行順序見[04](04_上線指引.md)，混合腳本同一ID只執行一次。

## 更新紀錄

2026-10-08新實際fixture run；沒有執行SQL。

## 方言確認後可使用的只讀結構檢查（未執行）

```sql
SELECT OBJECT_ID(N'dbo.EvalMarker', N'U');
SELECT name, TYPE_NAME(user_type_id) AS type_name, max_length, is_nullable FROM sys.columns WHERE object_id=OBJECT_ID(N'dbo.EvalMarker', N'U');
SELECT c.name, ic.key_ordinal FROM sys.key_constraints k JOIN sys.index_columns ic ON ic.object_id=k.parent_object_id AND ic.index_id=k.unique_index_id JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE k.parent_object_id=OBJECT_ID(N'dbo.EvalMarker', N'U') AND k.type='PK';
```

上述查詢僅適用SQL Server；工具與引擎需補證才使用。预期值见異動說明。Flags(review-defects)與OldVersion來源沒有PK，PK查詢預期0；其餘來源有PK預期Id/key_ordinal1。
