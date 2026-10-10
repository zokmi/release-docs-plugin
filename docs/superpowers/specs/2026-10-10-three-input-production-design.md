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
