# 資料SQL — #42正式

| 項目 | 內容 |
| --- | --- |
| 日期／時區 | 2026-10-08／Asia/Taipei |
| 識別 | ../#42\正式 → #42正式 |
| base SHA | 8aa4c34e7481ba39378b1865e306a0d43b829477 |
| target SHA | e13ca05bede101459bd9fb38988038042cd3480e |
| diff 模式 | direct（fingerprint two-dot） |
| 工作區 | staged/unstaged/untracked無額外部署來源；生成的精確五份成品排除，legacy簽核保留（如有） |
| 來源 | e13ca05bede101459bd9fb38988038042cd3480e:docs/migration.sql:完整閱讀；base/target全樹完整盤點 |
| 取代文件 | ../2026-10-08_#42正式/04_上線指引.md（保留實際簽名；原識別../#42\正式→#42正式） |

## 異動、執行單位與檢查

無（完整docs/migration.sql僅CREATE與AGENTS.md盤點，没有其他資料來源）。

## 缺口與失敗處理

正式工具/方言、備份、artifact与恢复方案缺證；停止實際部署，不猜安全DROP。

上線唯一執行順序見[04](04_上線指引.md)，混合腳本同一ID只執行一次。

## 更新紀錄

2026-10-08新實際fixture run；沒有執行SQL。
