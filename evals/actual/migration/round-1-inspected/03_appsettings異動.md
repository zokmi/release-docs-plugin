# appsettings異動 — migration

| 項目 | 內容 |
| --- | --- |
| 日期／時區 | 2026-10-08／Asia/Taipei |
| 識別 | migration → migration |
| base SHA | b633e44e7dddf1f64c9fcde8b4a4841c6e531876 |
| target SHA | febd8e919834735bf35196d39328002638df5d66 |
| diff 模式 | direct（fingerprint two-dot） |
| 工作區 | staged/unstaged/untracked無額外部署來源；生成的精確五份成品排除，legacy簽核保留（如有） |
| 來源 | febd8e919834735bf35196d39328002638df5d66:Migrations/20261008_AddEnabled.cs:完整閱讀; febd8e919834735bf35196d39328002638df5d66:deploy.md:完整閱讀；base/target全樹完整盤點 |
| 取代文件 | 無 |

## 異動、執行單位與檢查

無設定異動，已讀AGENTS.md、migration及deploy.md全樹。

## 缺口與失敗處理

正式bundle artifact、EF/provider版本、history目前版本、備份缺證。禁止直接Down作安全回復，需資料保全與相容方案。

上線唯一執行順序見[04](04_上線指引.md)，混合腳本同一ID只執行一次。

## 更新紀錄

2026-10-08新實際fixture run；沒有執行SQL。
