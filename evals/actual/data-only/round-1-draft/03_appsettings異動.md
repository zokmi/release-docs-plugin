# appsettings異動 — data-only

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

無設定異動（全樹 AGENTS.md、data.sql 完整閱讀）。

## 缺口與失敗處理

資料庫方言、既有欄位與正式工具／備份缺證。失敗先停止後續作業，保留脫敏結果及已提交範圍，恢復待確認。

上線唯一執行順序見[04](04_上線指引.md)，混合腳本同一ID只執行一次。

## 更新紀錄

2026-10-08新實際fixture run；沒有執行SQL。
