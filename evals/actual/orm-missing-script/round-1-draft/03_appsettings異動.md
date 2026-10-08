# appsettings異動 — orm-missing-script

| 項目 | 內容 |
| --- | --- |
| 日期／時區 | 2026-10-08／Asia/Taipei |
| 識別 | orm-missing-script → orm-missing-script |
| base SHA | 0c6810829285b6d6f1b55d0d8c50633934544bae |
| target SHA | 13b547b87b8db9731650fc35ca5621a0acc63238 |
| diff 模式 | direct（fingerprint two-dot） |
| 工作區 | staged/unstaged/untracked無額外部署來源；生成的精確五份成品排除，legacy簽核保留（如有） |
| 來源 | 13b547b87b8db9731650fc35ca5621a0acc63238:Context.cs:完整閱讀; 13b547b87b8db9731650fc35ca5621a0acc63238:Models/Invoice.cs:完整閱讀；base/target全樹完整盤點 |
| 取代文件 | 無 |

## 異動、執行單位與檢查

無設定異動（全樹三檔完整讀取，沒有配置與消費處）。

## 缺口與失敗處理

阻擋：ORM新增但無migration/既有schema證據。停止相關部署，要求對映、migration或已部署schema，禁止自行生成SQL補洞。

上線唯一執行順序見[04](04_上線指引.md)，混合腳本同一ID只執行一次。

## 更新紀錄

2026-10-08新實際fixture run；沒有執行SQL。
