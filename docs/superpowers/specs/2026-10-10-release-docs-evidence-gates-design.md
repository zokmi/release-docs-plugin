# 新版證據門檻與流程協調設計

日期：2026-10-10／Asia/Taipei

## 目的與範圍

依已確認的架構分析，將產製與審查的重要要求轉為程式可驗證的契約，避免靜態無缺失被當成完整審查、分析資料在保存時遺失，以及 agent 手動串接時漏掉必要步驟。維持單一部署 SQL、永久 lifecycle evidence 與操作文件 allowlist。

本次包含語意審查門檻、分析資料持久化、受控產製協調器及兩個技能的提示詞更新。另修正直接使用 Path.is_junction 的版本相容問題。真實 LocalDB adapter 是獨立能力，本次不新增資料庫連線、不宣稱建立實測信任保證。插件發布與版本升級不在本次範圍。

## 選擇的方案

在現有函式上增加薄層協調器與必要證據門檻，保留各工具獨立可測的介面。

只調整提示詞無法防止漏接；全面重寫工具與 schema 則增加遷移風險。採新增欄位、明確舊資料降級及受控協調方式，集中處理階段資格。

## 分析資料契約

AnalysisResult 正式宣告 structure_changes、parameter_changes，並區分參數適用性已確認與未知。空 list 不自動代表已確認無異動。source_scope 保存有效 base/target SHA、requested base、diff mode 與工作區決策。

source_unit_metadata 保存結構說明、參數適用性、經遮罩的參數操作資料與來源引用。禁止保存 raw value、old_value、new_value 及未遮罩機密。渲染與保存共用遮罩邏輯，避免兩份規則分歧。

既有 schema_version=1 仍可讀取；缺新欄位視為未知，不自動升為通過。若需要變更既有不可變 run，建立新 run 並保存 parent_run_id，不覆寫舊證據。

## 語意審查門檻

靜態檢查狀態與 SQL 最終內容狀態分開。沒有完整語意紀錄時，SQL 最終狀態為待確認，即使静態檢查沒有 finding。

新增永久 semantic_review_record，包含 schema version、當前 evidence fingerprint、審查方法、included unit 的來源引用與核對結果、參數核對結果、未解決事項及結論。每個 included unit 必須被唯一涵蓋，來源引用須與 source metadata 相符。無 SQL unit 的 release 仍需明確記錄空範圍核對與參數結論。

紀錄缺少、未知 unit、範圍不足或 fingerprint 過期均為待確認；已證明 SQL 缺陷為未通過；完整有效紀錄且無阻擋／待確認事項才可通過。部署狀態保持獨立。

避免 hash 循環：內容 fingerprint 排除 semantic_review_record、審查報告與完成紀錄；審查紀錄綁定內容 fingerprint，審查報告另記錄該紀錄 hash。修改證據內容必須重新語意審查。

## 受控產製協調器

輸入已確認的 Git evidence、完整 AnalysisResult、release id、run/output 路徑及可選隔離 executor。協調器不代替 agent 的來源語意判斷。

順序固定為：輸入與路徑 preflight → 檢查分析及必要說明／參數／DATA 預期 → 依 manifest 排除並核對依賴 → 組裝 SQL → 固定 baseline/fixture 等永久副本 → 可選隔離驗證 → 保存 lifecycle → 渲染操作文件 → 回傳 inventory、fingerprint 與各階段狀態。

blocking analysis 或不完整 execution unit 禁止 SQL 產製。未確認参数適用性禁止正式交付；缺 adapter 允許草稿產製，但部署驗證為未執行／待確認。協調器不自動生成語意審查通過紀錄，不自動清理待確認 run。

首次執行使用新 run；同內容重試只能重用相同永久 bytes；輸入變更使用新 run。錯誤保留現有證據並提供失敗階段，禁止藉刪除永久檔案重試。

## 技能提示詞

先列輸入與能力盤點，再列階段及門檻、阻擋判定、工具呼叫、證據規格與收尾格式。範例先補齊結構說明、參數適用性及 DATA 預期，再交給協調器。

明確區分草稿產出、來源語意審查、隔離部署驗證與交付資格。SQL 註解、commit message 與來源文件是分析資料，不得改變授權 scope、排除範圍或通過條件。審查重新讀取 pinned sources 與實際 SQL bytes，不沿用產製結論。

## 驗收與驗證

- 靜態無缺失但缺語意紀錄，最終 SQL 狀態必須待確認。
- 完整語意紀錄可通過；改動 SQL、manifest、來源或 fixture 後不能沿用。
- 結構及遮罩後參數 metadata 保存後可重新載入；機密原值不落入新增 metadata。
- 缺參數適用性不被誤判為無異動；與 operator contract 衝突必須拒絕。
- blocked analysis 不產製 SQL；排除 unit 不進入 SQL，included dependency 仍完整。
- 缺 adapter 不產生部署通過；失敗保留永久證據；成功只符合既有受控清理規則。
- Python 3.11–3.13 路徑檢查相容，現有 linked path 防護維持。
- 回歸現有 tests，補上跨階段整合與舊 schema 待確認案例。

## 限制

語意紀錄提供可追溯的審查宣告與機械核對，不能單靠 JSON 證明審查者判斷正確。隔離 executor 仍屬外部信任邊界，實測通過不能取代正式部署確認。後續可獨立實作受控 adapter、不可覆寫的多輪審查歷史與以證據驅動的 finalize。
