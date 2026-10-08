# appsettings異動 — arrays-env-override

| 項目 | 內容 |
| --- | --- |
| 日期／時區 | 2026-10-08／Asia/Taipei |
| 識別 | arrays-env-override → arrays-env-override |
| base SHA | 36a96cd3c131e13f3d19d46a3e37ca6ac37e5c77 |
| target SHA | 0639e627d41d512895b24a64d4d3385b0d4de9ac |
| diff 模式 | direct（fingerprint two-dot） |
| 工作區 | staged/unstaged/untracked無額外部署來源；生成的精確五份成品排除，legacy簽核保留（如有） |
| 來源 | 0639e627d41d512895b24a64d4d3385b0d4de9ac:Program.cs:完整閱讀; 0639e627d41d512895b24a64d4d3385b0d4de9ac:appsettings.json:完整閱讀; 0639e627d41d512895b24a64d4d3385b0d4de9ac:deployment.yaml:完整閱讀；base/target全樹完整盤點 |
| 取代文件 | 無 |

## 異動、執行單位與檢查

CFG-001 target:appsettings.json:1 新Endpoints:0:Url=https://base.example與Notify:Enabled=true；base未有配置，不宣稱未改索引刪除，只有索引0且長度1。target:deployment.yaml:1 Endpoints__0__Url=https://env.example，.NET AddEnvironmentVariables把雙底線映射Endpoints:0:Url。target:Program.cs:1 Clear→AddEnvironmentVariables→AddJsonFile(optional:false)，JSON最後加入覆盖同鍵，fixture啟動讀取的Endpoints:0:Url為https://base.example。程式直接讀取並非IOptionsMonitor，无reloadOnChange參數，不能稱無需重啟。正式環境範圍與artifact缺證；套用前核對實際環境與配置位置，後檢脫敏來源順序與Url功能；正式有效值待確認。

## 缺口與失敗處理

正式artifact/環境與服務重啟/回復流程未提供，fixture來源順序可證，不把fixture值冒充正式值。

上線唯一執行順序見[04](04_上線指引.md)，混合腳本同一ID只執行一次。

## 更新紀錄

2026-10-08新實際fixture run；沒有執行SQL。
