# appsettings異動 — config-add-change-delete

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

CFG-001，base/target:appsettings.json:1：Feature:Old 移除（true→不存在）、Feature:Enabled 新增（不存在→true）、Feature:Timeout 修改（10→20）、ConnectionStrings:Db 修改（舊新整值[已遮罩]）。不存在與false/null不同。沒有消費程式、provider順序或正式artifact，正式值待填（由既有安全設定來源提供）、有效值與刪键相容性待確認。核對正式安全來源、完整鍵後，從脫敏狀態/功能行為驗證Timeout與Enabled，不輸出連線憑證；重啟/reload需消費方式證據，不能稱正式已生效。

## 缺口與失敗處理

消費程式、配置來源順序、正式安全來源、套用與回復方案缺證；停止正式設定變更至補齊。

上線唯一執行順序見[04](04_上線指引.md)，混合腳本同一ID只執行一次。

## 更新紀錄

2026-10-08新實際fixture run；沒有執行SQL。
