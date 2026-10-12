# 自動產製參數異動文件設計

## 目標

當 pinned base/target Git diff 確認包含設定參數異動時，自動產製 `02_參數異動.md`，文件須符合既有參數異動範本的操作結構，同時提供人員可讀的異動說明與可直接複製的脫敏 JSON。不得因上游 descriptor 漏傳而靜默省略文件。

## 範圍

納入下列來源的參數異動分析：

- `appsettings*.json`、`settings*.json` 與其他已確認的 JSON 設定檔
- `Web.config`／`App.config` 與 inventory 已核對的其他 `.config` 設定檔；套件清單與無關 `.config` 不自動視為 runtime 參數來源
- deployment manifest／設定來源中的環境變數映射，例如 `Foo__Bar`
- 既有 source discovery 已核對的 consumer、provider 順序與部署說明

只讀取 pinned base/target revision；不以 working tree 或目前檔案內容取代 revision source。

## 資料契約

每個已確認參數異動產生一個 descriptor，至少包含：

- `environment`
- `service`
- `key`：完整設定鍵，陣列保留索引，例如 `Endpoints:0:Url`
- `change`：`add`、`update` 或 `remove`
- `old_value`、`new_value`：只留在受控 lifecycle evidence，文件輸出前脫敏
- `format_example`
- `apply`
- `reload`
- `validation`
- `source_reference`
- `parameter_group`
- `business_context`
- `module`
- `users`
- `impact`

`environment`、`service`、`key` 缺任一項，視為不完整 descriptor 並阻擋產製。無法確認參數適用性時維持 `parameters_applicable=null`，不得當作無異動。

## 文件結構規範

結構來源：`C:/Users/kenny/Documents/bsaila/docs/release-doc/2026-10-12_v3/02_參數異動.md`。沿用其來源說明、業務對照、分組範例與部署查核順序；實際值與業務說明仍須依本次 pinned source 證據建立。

`02_參數異動.md` 必須依下列順序產出：

1. 標題與來源範圍：日期／release 識別、base/target diff 或 revision、設定來源清單。
2. 安全與套用前提：說明正式密鑰、連線字串、JWT secret、SFTP 密碼、私鑰路徑等不得提交 Git，應由部署平台環境變數或 Application Settings 注入。
3. 業務情境與模組對照表，欄位固定包含：`參數區塊`、`使用業務情境`、`使用模組／功能`、`主要使用者`、`異動影響`。
4. 依參數區塊分節；每節至少包含：異動摘要、完整設定鍵、用途／行為影響、可複製 JSON 設定範例、環境變數或部署平台覆寫範例（適用時）、reload／重啟要求與驗證方式。
5. 參數部署查核：以編號清單列出部署後逐項驗證、敏感值來源與未核准時的安全預設值。

每個參數分節的 JSON 必須保留實際設定階層，例如 `PlatformStatsSettings.FixedValues.TotalMatches` 不得攤平成無法直接套用的欄位。JSON block 必須是合法 JSON；環境變數範例使用 `text` block，不得把 secret 偽裝成 JSON 正式值。

陣列範例須保留 pinned target 的完整元素與原始容器型別，包含未變動元素；數字命名的 object key 不得轉成陣列。缺少容器證據的舊 descriptors 只能呈現索引對照並明示不得整段取代設定。production 必須核對每個設定來源在 base／target tree 實際存在的角色，不接受僅有 target 的 update 證據。呼叫端提供的已知 secrets 與 Bearer credential 同樣適用於所有文件投影。

業務情境、模組、主要使用者與影響只能來自已核對的 consumer／部署／需求證據；無法取得時明確填 `待確認` 並保留 finding，不得由設定鍵名稱猜測。`parameter_group` 用於合併同一設定區塊的分節，不得以秘密值或不穩定的原始值命名。

## 產製規則

1. source discovery 從 base/target diff、consumer 與 deployment source 建立 `parameter_changes`。
2. 有一筆以上已確認 parameter descriptor 時，`parameters_applicable` 必須是 `true`，且產出 `02_參數異動.md`。
3. `02_參數異動.md` 必須包含範本結構中的業務情境表、參數分節與部署查核，並另外包含機器可驗證的異動摘要：
   - Markdown table：環境、服務、完整設定鍵、異動類型、前值→後值、套用、reload、驗證、來源。
   - fenced `json` block：每個參數分節的可套用設定範例，與該分節的異動 descriptor 對應。
   - fenced `json` block：在文件末尾提供完整脫敏 descriptor array，供工具或審查流程複製解析。
4. 敏感 key、URL credential、secret assignment 與已知 secret 一律遮罩；不得將 raw old/new value 寫入 operator document。
   明確 `sensitive=true` 的值包含複合型別時，對應完整 `target_config` 值也必須遮罩；邏輯設定鍵的字面冒號、巢狀與混合表示須全部遮罩，保留非敏感鄰近設定與原始來源不變。
5. 確認無參數異動時不產出 `02_參數異動.md`，但 lifecycle metadata 必須保存已檢查範圍與 `parameters_applicable=false`。
6. 若 diff 顯示設定異動但無法建立完整 descriptor，產製必須失敗並回報缺少欄位或來源，不得產出只有 SQL 的不完整交付物。

## JSON 契約

文件末尾的 canonical JSON 是合法 JSON array；每個元素至少包含：

```json
{
  "environment": "Production",
  "service": "CustomerAPI",
  "key": "Cache:TTL",
  "change": "update",
  "old_value": 60,
  "new_value": 120,
  "format_example": "整數，例如 120",
  "apply": "更新正式設定來源",
  "reload": "重新啟動服務",
  "validation": "確認健康檢查與快取期限",
  "source_reference": "target:appsettings.json:12"
}
```

實際輸出必須使用脫敏值；若值為敏感資料，使用 `[REDACTED]` 或安全來源提示，不輸出正式 secret。

分節中的設定 JSON 是可直接套用的 configuration shape，不得包含 raw secret；敏感欄位使用空字串、`[REDACTED]` 或「由密鑰管理服務提供」等安全提示。分節 JSON、Markdown table 與 canonical descriptor array 必須由同一批 sanitized descriptors／設定投影產生，不得各自手寫造成不一致。

## 驗證與錯誤處理

### 來源契約與支援邊界

- 同一 base 或 target 角色不得包含重複的設定來源 path，即使值相同也須阻擋，不能用最後一筆來源覆蓋前面的證據。Compose `extends`（包括空值）同樣屬未解析繼承來源，必須阻擋，不能把本機 environment 當成完整設定。

- `key` 是 consumer 的邏輯設定鍵；`key_segments` 是來源的實體路徑，字串表示 object key、整數表示 array index。字面 `A:B` 不得誤讀為 `A`／`B` 巢狀物件；邏輯鍵大小寫或冒號映射衝突必須阻擋，不能覆寫後宣稱無異動。
- JSON 與標準 XML `.config` 可從 pinned base／target 發現異動。XML 僅支援本機 `appSettings`、`connectionStrings` 的 `add`；connection string 的 `providerName` 也屬異動。`clear`／`remove` 因無法核對繼承設定而不支援；自訂 section、外部設定、DTD／entity 同樣必須明確回報 unresolved，不得只比對本機 dictionary 後宣稱無異動。
- 部署來源僅支援 literal dotenv、JSON 變數映射及有明確服務／容器歸屬的 JSON Compose／Kubernetes environment。YAML、插值、`env_file`／`envFrom`、外部 secret／`valueFrom` 與無法辨識 provider 的來源不得猜測；即使本機 environment 為空，也不得將未知外部來源當成空集合。
- 部署來源需提供環境、服務與已審查的 provider precedence 證據；引用的 consumer 程式碼需以 target revision、path、source hash 核對。只填 `true` 不構成 precedence 證據，也不由鍵名自動推論 provider 優先序。
- 產製 preflight 必須重新核對來源引用與實體路徑，不接受竄改的 path、revision、hash、line 或缺少的 base／target role。資料值相同不表示追溯契約相同。
- 同環境、同服務、同參數群組但不同來源的設定片段須分節，不得合併後互相覆蓋。XML／環境變數附的 JSON 僅為邏輯設定範例，必須標示不得直接取代原格式。
- 共用完整陣列／物件片段的 descriptors 必須套用同來源所有 sensitive paths 的遮罩；不得讓相鄰非敏感 descriptor 恢復敏感的數字、布林、null 或複合值。遮罩不得改動原始來源，也不得跨來源遮罩相同路徑的公開值。

- appsettings 新增、修改、刪除均須有測試。
- nested key 與 array index 必須保留完整路徑。
- environment variable mapping 必須測試雙底線映射。
- table 與 JSON 必須由同一組 sanitized descriptors 產出，避免內容分歧。
- JSON 必須可被標準 parser 解析。
- 範本業務情境表、參數分節、設定 JSON、環境變數覆寫範例與部署查核清單必須在正確順序出現。
- 每個參數分節至少有一個合法 JSON 設定範例；有 provider override 時另有 `text` 環境變數範例。
- 有參數異動但 descriptor 不完整時，測試必須確認產製被阻擋且不留下部分 operator output。
- 無參數異動時，測試必須確認不產出 `02_參數異動.md`。

## 非目標

- 不推導正式環境實際值或正式業務結果。
- 不修改部署 SQL。
- 不把未核對的設定檔或 working-tree 內容視為參數異動證據。
- 不自動決定缺少來源證據的 environment、service、reload 或 validation；這些情況必須待確認或阻擋。
