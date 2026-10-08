# 資料SQL — mixed-transaction

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

SQL-001 同一完整 mixed.sql:1-7，第5行 VALUES 明確一列 Id=1、Note=N'DELETE FROM Users; CREATE TABLE Decoy'；字串不是刪 Users。後查 SELECT Id,Note FROM dbo.Flags WHERE Id=1; 預期一列且Note完整字串一致；維護窗口無併行新增且新表前提下全表COUNT=1。保持 GO(2,7)、XACT_ABORT(1)、BEGIN(3)/COMMIT(6)，不拆DDL/DML、不另外生成SQL。第4行無存在性保護，第5行PK會衝突，不可直接重跑。

## 缺口與失敗處理

正式工具、備份、批次續跑行為缺證。XACT_ABORT與交易不代表跨GO全部自動恢復。失敗停止後續依賴，記已完成批次、查交易狀態後由有證據的恢復流程處理；不承諾安全DROP。

上線唯一執行順序見[04](04_上線指引.md)，混合腳本同一ID只執行一次。

## 更新紀錄

2026-10-08新實際fixture run；沒有執行SQL。
