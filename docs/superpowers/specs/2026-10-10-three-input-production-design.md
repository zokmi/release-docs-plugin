# 三項輸入的自動版更產製設計

## 目的與輸入契約

使用者只提供：(1) 正式機 DB 結構基準（schema export／dacpac 等可信副本）、(2) Git diff base→target、(3) 例外排除意圖。repository 從目前工作區解析；provider、migration chain、units、相依、SQL、測試資料、預期結果、驗證證據與文件由插件取得或產製。正式連線不是隱含授權；預設不連線正式 DB。

重用對話中的既有 scope 與排除決策；工作區異動預設排除並清楚回報，需要納入時才確認。實際 DB baseline 與 Git 比較起點分開保存。不得要求使用者替來源加 release-unit 標記、提供整份 metadata、fixture 或四輪預期。

## 根因與改變

現有 collector 僅取得 Git 路徑；analyzer 要求標記或外部 descriptor，並在 blocked 時清空 units；producer 只接受 base/target 中的 SQL bytes。規範雖要求先分析，run 內新產製 SQL 仍無法被消費。修正必須建立 discovery→derivation→analysis→production 的介面，不能只降低 missing_authoritative_sql 關卡。

## 自動流程

1. Pin Git 範圍，保存正式結構副本與 hash。盤點兩端完整 tree、SQL、Database Project、EF package／DbContext／migration／snapshot／history、app consumer、verify 與配置；保留 diff 外相依。
2. 探測 provider、版本、建置／SQL 產製工具與隔離 DB adapter；以來源定位記錄結果、衝突及未知。工具缺失先查既有可信產物，不能直接要求使用者生成 SQL。
3. 建立獨立 candidate inventory 與 dependency graph，從單號／物件／模組解析排除閉包。排除不表示 DROP；既有正式物件保持原定義。跨 included/excluded 不可安全拆分時阻擋相關 artifact，繼續其他來源分析。
4. 可用工具產製正式 baseline→target plan／SQL；target-only project 使用正式基準的隔離模型，不捏造 Git base project。依來源語意生成 descriptor、preconditions、skip／stop、完整定義及 validation；需要 repair 時產製 run 內可審查的衍生來源，不修改原 repo、不自動 commit。
5. 產製合成 fixture、案例 coverage、四輪 expected assertions 與保留資料預期。先固定預期，再實測，禁止由 actual 反填 expected。從配置與消費來源取得參數操作描述並遮罩機密。
6. 分析與安全檢查通過後組裝唯一 SQL，取得隔離四輪實測，再產製含結構／資料異動表的操作文件，執行獨立語意審查与 fingerprint 核對。

## 衍生 SQL 來源契約

保持現有 pinned_git 來源兼容，新增 derived_artifact 來源類型。每個衍生 artifact 綁定原始 scope、正式 baseline hash、完整輸入來源清單（revision/path/hash）、產製方法、工具／版本／參數、轉換 mapping、原始及輸出 bytes hash。工具原始產物與 repair 產物各自不可變保存於 run；來源文字不能改變流程授權。

analyzer 與 producer 依類型驗證：Git source 重新讀取 pinned blob；衍生來源重新讀取受控 run 一般檔案及全部輸入 hash。拒絕外部未綁定 SQL、traversal、symlink/junction/hardlink、來源被修改或 mapping 不完整。不得偽填衍生產物 source_revision，使其看起來存在於 Git。生成 metadata 是候選證據，不自動代表語意 passed。

review fingerprint／lifecycle／semantic review 必須理解衍生来源，完整綁定 baseline、工具產物、repair、descriptors、fixture、預期與 operator 文件；現有報告任何輸入變更即失效。新增 schema 使用明確版本及兼容讀取，未知類型 fail closed。

## SQL 安全與能力界線

衍生來源需保留可核對的轉換及每項修改理由。不得用 regex 刪 GO／COMMIT／RAISERROR、忽略 EXEC 或只包 transaction 來消除 findings。完整定義符合時跳過、缺少時補建、不相容時停止；不能只有名稱存在檢查。SQLPackage 一次性成功不能取代 rerun 收斂。

支援能力以已驗證的 provider／來源操作明列；未支援語法、opaque helper、未知業務規則或不可交易 DDL 不自動猜測。允許產製候選及完整診斷，但不能宣稱合格 SQL。對可自動修正的已支援操作，依 systematic-debugging 保存重現、根因與最小修正，以新 run 重跑；三次失敗檢討編排設計，不堆疊 guard。真正不能推導的資訊才提出具體問題，不能要求使用者重交整份產製輸入。

## 已知來源不相容與處理決策

既有 repository migration 可能是供 SSMS／sqlcmd 直接執行的完整腳本，含 `GO`、unit 內 `BEGIN/COMMIT/ROLLBACK`、動態 `EXEC`、欄位描述 procedure 或 `RAISERROR`。這些 finding 的根因是 execution model 與 plugin contract 不一致，不是 LocalDB、最高權限或單一 session option 故障。LocalDB 通過只能證明該腳本在該 provider 可執行，不能補上 unit mapping、來源 hash、交易邊界或四輪 DATA 預期。

採用「原始來源 + 衍生執行來源」雙層模型：

1. 原始 EF／SQL migration 永遠保留為 pinned source of truth；不因 release 需要而刪除 `GO`、改寫 `RAISERROR`、忽略 `EXEC`、拆除交易或直接修改 repository。
2. provider／repair adapter 只在已核對工具與隔離模型中產生 execution body。每個 body 綁定 baseline hash、輸入 revision/path/hash、工具／版本／命令／參數、轉換 mapping、原始與輸出 hash，保存為 `derived_artifact`，並由 producer／review 重新驗證。
3. `GO`、動態 DDL、metadata procedure、RAISERROR/THROW 與 unit 交易各自形成能力 finding。沒有可審查 provider 的 operation 保留 blocker；不能以補 descriptor 或包一層 transaction 消除 finding。
4. execution artifact 採 `database_tool_minimal` 時，只含基礎 T-SQL、phase/unit 註解與 mapping；connection、最高權限、transaction、模式、錯誤攔截與逐 unit execution evidence 由資料庫工具負責。source unit 的非必要 `SET`、`USE`、SQLCMD directive、`GO`、權限與自有 transaction 在寫檔前阻擋；`SET IDENTITY_INSERT` 僅在有來源證據且成對出現時例外允許。
5. 舊 wrapper 僅作 framework fallback，必須保存 fallback 原因；不能把 wrapper 內的 metadata `SET` 當成 source unit 可以任意使用 session option 的理由。

Metadata operation 若確實屬於本次 release，必須改以明確 descriptor 接入，不得把任意 `EXEC` 放寬為可執行 SQL。descriptor 至少包含 `operation_id`、`provider`、`provider_version`、`object`、`action`（add/update/drop）、`arguments` 的遮罩後摘要、`source_path`／`source_line`、`input_hash`、`output_sql_hash` 與 `reversible`／`transaction_policy`。provider 只能輸出固定、可 fingerprint 的 T-SQL；缺 provider、參數無法核對或 output mapping 不一致時維持 blocker。欄位描述等 metadata 不得因 assembler 不支援而靜默刪除，必須拆成獨立受審核 phase 或保留待確認。

下列 finding 對應的處置固定化：`unmapped_sql`／phase mapping 缺失先建立 execution descriptor；`opaque_execution` 先交給已驗證 provider 或維持 blocker；`batch_separator` 只能由 provider 產出無 batch 的 derived body；`unit_transaction_control` 需選定唯一 transaction owner；`raiserror_without_throw` 只能由保留錯誤碼／訊息的 repair mapping 處理；`missing_data_expectations` 必須自動產生 fixture、seed row 與四輪 before/after assertions。原始來源不具備這些條件時，lifecycle 維持 failed 或待確認，不因文件產出或單次實測轉為合格。

### Provider 與 DATA 證據自動化

`release_unit_generator.py` 讀取 pinned release-unit descriptor 與 repair source，逐 unit 以 SHA-256 驗證輸入，呼叫 `metadata_provider.py` 產生正式 execution body，並輸出含 `sql_hash`、provider kind、input/output hash 與 transformation provenance 的 descriptor。固定文字 metadata、常數 dynamic SQL、已審核的 constraint lookup，以及 literal cursor rows 都必須在 provider 中轉成可審核 SQL；其餘 dynamic execution 維持阻塞。

`data_evidence.py` 要求五個 DATA unit 各自提供 `preserved_data`、`existing_value`、`boundary`、`missing_reference` 四輪實際結果。驗證器缺少任一 round 或 `data_checks` 為空時輸出 `blocked_missing_authoritative_evidence`，不得以推導值或空 assertion 宣稱通過。正式資料庫執行器必須把四輪結果回填後才能將狀態改為 `passed`。

Assembler 的 `database_tool_minimal` profile 依 descriptor 輸入順序執行；phase 僅作 mapping 與查核標記，不重新分組。若 dependency chain 跨越 SCHEMA／REPAIR／DATA，必須保留來源順序、要求 dependency 已在前方出現，並記錄 `original_phase`、`mixed_unit` 與 chain reason。缺 dependency 或嘗試以 unit name 排序時 fail closed；不得因 metadata phase 推導而靜默改寫 migration chain。

## 四輪与交付

同一 immutable SQL：validate_only 完整執行後 rollback；commit 從 fresh baseline／fresh session 執行並提交；rerun 沿用 commit DB 但另開 session驗證收斂；injected_failure 使用 fresh baseline，在 mutation 後／commit 前注入錯誤，驗證 rollback與停止。runner 實際回報 session/database IDs、checks、data_checks 及 preservation；adapter 不可用則部署 not_run，不能捏造通過。

上板文件為 00_上線指引.md、01_部署SQL.sql、適用時02_參數異動.md。00 必含結構異動表、資料異動表、排除摘要與操作查核。完整內部證據留 run；交付資格必須同時符合當前來源語意與所需驗證門檻，不能以 CLI exit 0 代替。

## 驗收與測試

- 僅提供三項輸入的可支援案例能走完 discovery、衍生來源、fixtures、四輪與審查；不需 repo 標記或人工 metadata。
- target-only project、已存在排除物件、diff 外相依、mixed SCHEMA/DATA effects 及 provider／chain 衝突有真實情境測試。
- 修改原始來源、baseline、generated SQL、descriptor 或 fixture 使舊 fingerprint／review 失效；非法路徑與未知來源類型拒絕。
- SQL 缺陷、業務未知、工具缺失與 adapter 未執行分別報告；沒有 adapter 的測試不能宣稱 DB execution 通過。
- 舊 pinned Git 路徑回歸；兩張異動表不漏列／誤列；候選 inventory 不因 analyzer blocked 丟失。

## 不涵蓋

不執行正式部署、不讀取正式資料作 fixture、不自動改 repo／commit、不承諾任意 SQL/provider 全自動修復。實作計畫需明列第一階段支援的來源與操作，以及可重現的工具／DB整合驗證環境。
