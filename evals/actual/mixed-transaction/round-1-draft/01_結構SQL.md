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
