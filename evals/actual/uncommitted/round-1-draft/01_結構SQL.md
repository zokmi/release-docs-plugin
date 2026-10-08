# 結構SQL — uncommitted

| 項目 | 內容 |
| --- | --- |
| 日期／時區 | 2026-10-08／Asia/Taipei |
| 識別 | uncommitted → uncommitted |
| base SHA | 37d881982a4ba7733ace4ffb0fd9c4bb7799367b |
| target SHA | 0110e36a8a8f82ab3031e03ddb166b31d8a17b46 |
| diff 模式 | direct（fingerprint two-dot） |
| 工作區 | staged:index schema.sql=StagedVersion；unstaged:working-tree schema.sql=WorkVersion；untracked:new.sql全表UPDATE；納入決策未提供，不納入已提交步驟；HEAD LaterHead不屬target |
| 來源 | 0110e36a8a8f82ab3031e03ddb166b31d8a17b46:schema.sql:完整閱讀；base/target全樹完整盤點 |
| 取代文件 | 無 |

## 異動、執行單位與檢查

SQL-001 僅 target:schema.sql:1 建 dbo.OldVersion (Id int nullable)。HEAD另有LaterHead，不在指定target；index為StagedVersion、working-tree為WorkVersion，不能替代OldVersion。前檢物件不存在，後檢Id/int/nullable；工具/方言待證，不稱已驗證。

## 缺口與失敗處理

待確認：請決定staged、unstaged、untracked是否納入本次部署；沒有答案不混入步驟。若納入需提交或發布取得方式與內容識別。正式工具、schema、備份缺證。

上線唯一執行順序見[04](04_上線指引.md)，混合腳本同一ID只執行一次。

## 更新紀錄

2026-10-08新實際fixture run；沒有執行SQL。
