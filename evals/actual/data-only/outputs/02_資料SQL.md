# 資料SQL — data-only

| 項目 | 內容 |
| --- | --- |
| 日期／時區 | 2026-10-08／Asia/Taipei |
| 識別 | data-only → data-only |
| base SHA | 44fc7c16036942b2f19d8662dd387a1c810b9adf |
| target SHA | d779beec679978f36ee9f29d2bf460aa0f7c73a9 |
| diff 模式 | direct（fingerprint two-dot） |
| 工作區 | staged/unstaged/untracked無額外部署來源；生成的精確五份成品排除，legacy簽核保留（如有） |
| 來源 | d779beec679978f36ee9f29d2bf460aa0f7c73a9:data.sql:完整閱讀；base/target全樹完整盤點 |
| 取代文件 | 無 |

## 異動、執行單位與檢查

SQL-001，target:data.sql:1：僅 WHERE Enabled IS NULL 的 dbo.Users 列回填 Enabled=1，非 NULL 的人工值保留。影響筆數待確認，不捏造。維護窗口排除並行寫入後，SELECT COUNT(*) FROM dbo.Users WHERE Enabled IS NULL; 預期0；執行前先取同條件數量並核對欄位可接受1，這是驗證設計未執行。資料庫方言、型別、備份、trigger及交易工具未知，所以此查詢需補方言/schema 證據後採用，不能先稱已驗證。重跑只處理仍NULL的列，仍需確認併行與trigger副作用。

## 缺口與失敗處理

資料庫方言、既有欄位與正式工具／備份缺證。失敗先停止後續作業，保留脫敏結果及已提交範圍，恢復待確認。

上線唯一執行順序見[04](04_上線指引.md)，混合腳本同一ID只執行一次。

## 更新紀錄

2026-10-08新實際fixture run；沒有執行SQL。
