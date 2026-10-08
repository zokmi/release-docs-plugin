# 資料SQL — config-add-change-delete

| 項目 | 內容 |
| --- | --- |
| 日期／時區 | 2026-10-08／Asia/Taipei |
| 識別 | config-add-change-delete → config-add-change-delete |
| base SHA | 523654cc315c485a9e87766763e42b7000d25c78 |
| target SHA | ab771e6cfb4e6e104e67c9387693f9fb91a8d3fa |
| diff 模式 | direct（fingerprint two-dot） |
| 工作區 | staged/unstaged/untracked無額外部署來源；生成的精確五份成品排除，legacy簽核保留（如有） |
| 來源 | ab771e6cfb4e6e104e67c9387693f9fb91a8d3fa:appsettings.json:完整閱讀；base/target全樹完整盤點 |
| 取代文件 | 無 |

## 異動、執行單位與檢查

無資料異動（同完整盤點，不把連線設定當DML）。

## 缺口與失敗處理

消費程式、配置來源順序、正式安全來源、套用與回復方案缺證；停止正式設定變更至補齊。

上線唯一執行順序見[04](04_上線指引.md)，混合腳本同一ID只執行一次。

## 更新紀錄

2026-10-08新實際fixture run；沒有執行SQL。
