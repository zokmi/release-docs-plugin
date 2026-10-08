# 結構SQL — blank-signoff-placeholder

| 項目 | 內容 |
| --- | --- |
| 日期／時區 | 2026-10-08／Asia/Taipei |
| 識別 | blank-signoff-placeholder → blank-signoff-placeholder |
| base SHA | f0c08b482da1575af7e23c3838513d55f39173c4 |
| target SHA | 046c9f13261c201203771f11e6c6438acec6db6c |
| diff 模式 | direct（fingerprint two-dot） |
| 工作區 | staged/unstaged/untracked無額外部署來源；生成的精確五份成品排除，legacy簽核保留（如有） |
| 來源 | 046c9f13261c201203771f11e6c6438acec6db6c:docs/migration.sql:完整閱讀；base/target全樹完整盤點 |
| 取代文件 | 無 |

## 異動、執行單位與檢查

SQL-001 target:docs/migration.sql:1 新dbo.EvalMarker (Id int NOT NULL PRIMARY KEY)。docs底下的migration來源仍屬審查範圍，不能排除整個docs。執行前OBJECT_ID應NULL；執行後Id/int/4/非NULL，主鍵Id一列，既有工具/方言待確認。保持完整腳本，直接重跑同名衝突。

## 缺口與失敗處理

正式工具/方言、備份、artifact与恢复方案缺證；停止實際部署，不猜安全DROP。

上線唯一執行順序見[04](04_上線指引.md)，混合腳本同一ID只執行一次。

## 更新紀錄

2026-10-08新實際fixture run；沒有執行SQL。
