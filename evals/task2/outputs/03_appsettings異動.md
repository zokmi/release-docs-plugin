# appsettings 異動 — fixture-task2

| 項目 | 內容 |
| --- | --- |
| 產出日期／時區 | 2026-10-08／Asia/Taipei |
| 識別 | fixture-task2 |
| base SHA | 87c3bb769165b55e2884c5027c3fd78bc5f4a8b4 |
| target SHA | a01af9ba4fdf2b148ed61ad77f04c0cfdb86cdbd |
| diff 模式 | direct |
| 工作區範圍 | staged、unstaged、untracked：無；不納入工作區 |
| 來源證據 | base/target:appsettings.json:1；target:Program.cs:1-5；target:deployment.yaml:1-2；target:README.md:1-3 |
| 取代文件 | 無 |

| 設定 ID | 完整鍵 | 異動 | 舊值 | 新值 | 消費證據 |
| --- | --- | --- | --- | --- | --- |
| CFG-001 | Feature:Old | 移除 | true | 不存在 | 未提供消費處，待確認 |
| CFG-001 | Feature:Enabled | 新增 | 不存在 | true | 未提供消費處，待確認 |
| CFG-001 | Feature:Timeout | 修改 | 10 | 20 | Program.cs:5 |
| CFG-001 | Endpoints:0:Url | 修改 | https://old.example | https://base.example | Program.cs:4 |
| CFG-001 | ConnectionStrings:Db | 修改 | [已遮罩] | [已遮罩] | 未提供消費處，待確認 |

CFG-001 是完整設定來源套用的單位。舊新連線字串整體遮罩，正式憑證待填（由既有安全設定來源設定），不使用開發值；來源 appsettings.json:1。

Program.cs:1-3 清空預設來源，先加入環境變數，再加入 appsettings.json；同鍵後加入 json 覆寫。deployment.yaml:2 的 Endpoints__0__Url 映射 Endpoints:0:Url，本 fixture 有兩個來源，但有效安全值为 https://base.example，不能依默认环境優先推定 https://env.example。實際正式 artifact、來源及環境未知，正式有效值待確認。陣列索引完整保留；沒有其他索引異動可證據。

套用相依：配置與 SQL-001 完成再部署 APP-001（README.md:3）。刷新／重啟方式缺消費實作，待確認，不因 AddJsonFile 推定自動 reload。套用後以脫敏方式核對鍵、有效 provider 與功能；核對安全 Url及Timeout值，不印出 ConnectionStrings:Db。舊鍵刪除／新鍵是否被使用待確認。任何必需鍵缺失或驗證不符停止 APP-001，恢复需既有正式安全来源與相容性證據，不猜還原憑證。

2026-10-08 初次產出，UAT／正式未執行。
