# 實際必要審查：第1輪

狀態：未通過。Task4 agent 已重新讀取原始 target:schema.sql:1、target:appsettings.json:1 與四份文件，不採信04舊通過標示。具體 SHA 見 invocation.json／round-1-read-log.json，原稿bytes的hash見 round-1-reviewed.json。round-1-inspected 的秘密已遮罩，不能把安全存档誤認原稿沒有洩漏；原稿曾含known synthetic fixture值，僅在本地記憶體確認，不將原值印入工具輸出。

| 必檢項 | 來源／成品定位 | 實際問題 | 等級／處置 |
| --- | --- | --- | --- |
| 完整性 | schema.sql:1；01:1 | 原始CREATE dbo.Flags，01卻寫無任何新增表；漏必跑結構 | 阻擋，補完整Flags欄位及唯一SQL-001 |
| 正確性 | appsettings.json:1；03:1 | 來源Notify:Enabled，成品Notify:Enable；並含來源ApiKey原值 | 阻擋，改完整鍵，整值遮罩，正式安全來源待補 |
| 相依與執行 | schema.sql:1；04:2-3 | CREATE與INSERT同支混合腳本卻兩列重跑；第二次CREATE同名衝突，不能拆分類重跑 | 阻擋，完整單位只一列 |
| 可驗證與可恢復 | schema.sql:1；04:4 | 「查一下」無可操作預期；直接DROP保證安全沒有備份、相容或資料保全證據 | 阻擋，前後只讀檢查明確預期，失敗停止，回復缺證保持待確認 |
| 安全與一致性 | appsettings.json:1；03:1／04:1 | 秘密外洩與無有效來源snapshot的舊通過狀態 | 阻擋，遮罩並重新review，不能以hash或旧狀態通過 |

本輪未執行SQL。修正原始證據能確認的六項缺陷後，再重新讀来源與四份文件。正式工具/方言、設定消費程式、安全來源、artifact與恢復仍缺證，所以複審最多可為待確認。
