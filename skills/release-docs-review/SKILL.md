---
name: release-docs-review
description: Use when release-docs 已產出必要版更文件，需要必要語意審查、修正複審或確認舊審查報告是否仍有效。
---

# 版更文件必要審查

接收目標 repo、range 的 base／target／diff 模式，或完整有序 commit_scope JSON（每個 commit／選定 direct parent；root 的 parent 為 null），以及未提交內容納入決策與文件資料夾。清單模式逐對重讀選定差異與完整來源，不轉為含未選中間 commit 的 range；merge 必須明確選 direct parent。讀專案 AGENTS.md、CLAUDE.md 與部署慣例。重新讀 Git 實際範圍、完整 SQL／migration、ORM、設定差異與消費程式，以及必要成品；不得只沿用產出摘要或相信舊通過報告。指定 target 的內容用 `git show <解析後 SHA>:<path>`；index／working tree／untracked 分列，不冒充 target。

使用該範本的欄位作為對話審查紀錄，不寫入 05 檔案。每項記錄來源路徑、revision／工作區識別、行號或定位、成品定位、具體缺口與修正。缺少來源是待確認，不能記為「無」。不可將 hash、腳本 exit 0、Markdown 欄位存在當成正確性證明。

## 必檢項

外部排除 manifest（例如 `05_5005_exclusion_manifest.json`）必須保留原檔與原始 hash，驗證後正規化為唯一的 `03_例外排除.json`；審查只接受正規化清單與原檔逐項一致，00／04 不承載排除內容。

審核依 [SQL 判讀規則](../../references/sql-review-rules.md) 的 artifact 契約、轉換分級及三層審核進行，不能以來源／執行 SQL byte-for-byte 不同直接否決，也不能以可重跑直接接受人工改寫。Database Project 的宣告式 schema 與工具產出部署 SQL 分開比對；鎖定工具、兩端 schema、DSP/provider、命令、exit code、hash、來源／執行單位對照與 exclusion manifest 必須完整。工具差異須可解釋；GO／批次分隔不能自動當無語意格式差異。

分別記錄「來源完整性」「語意等價性」「執行安全性」，再回報獨立 SQL 內容與部署驗證狀態。前兩層核對完整 scope、唯一完整單位、受控排除後 target 的全部結構及資料條件；第三層區分靜態安全機制與實際 DB 證據。新增 guard、交易、補欄位或 REPAIR 須正式來源／工具／repair source，未管理人工改寫內容未通過；缺證據待確認。來源缺機制列來源修正待辦；不得在文件補寫後宣稱通過。缺 DB 實測只判部署驗證待確認；產製工具 DSP/provider 不明是內容追溯缺口，與正式主機環境缺口分開。

來源／execution artifact、exclusion manifest、文件任一變更立即失效；重新 fingerprint 及複審。外部／ignored artifact 額外比對實際 hash inventory，不宣稱現有 Git fingerprint 已涵蓋外部檔案。對 release/20261012-no-5005 的使用者提供情境採 reference 案例判定：01 人工包裝及 DATA-003 無正式 repair source 均未通過，排除須完整 manifest，部署驗證待確認；未取得 repo 原檔時標示此為提供事實的適用判定。

每輪語意審查前後都執行 `scripts/validate_release_artifacts.py --documents <release目錄>`。工具只驗證必要／選用文件、artifact class、03 JSON schema、04 設定欄位與結構交叉條件；工具通過不代表 SQL 語意或資料庫部署通過，工具失敗時不得宣稱文件結構完整。

部署驗證是選用項目，只有使用者或專案流程要求時才逐階段核對「舊版本 DB＋測試資料 → 結構 SQL → 資料 SQL → 最終結果查核」的實際證據，詳見 [SQL 判讀規則](../../references/sql-review-rules.md)。要求實測時，確認基準對應此次 base、資料先載入且涵蓋受影響與應保留資料、兩階段在同一隔離 DB 依序執行、失敗停止及最終結果符合 target；空白 DB 或已升級 DB 測試不能代替。未要求或未執行時記「未執行」，不否決 SQL 內容；實測失敗僅在直接證明 SQL 語法、交易或資料邏輯錯誤時影響內容判定。無資料異動須有不適用依據，混合單位不得拆開或重複執行，來源相依衝突須明列。

先確認入口流程已完成範圍核對與文件產出，再做驗證與本輪審核。專案工具新產生或使用者已提供的 SQL／schema／repair artifact 都是必要來源：重讀其完整 artifact，核對來源 revision、base／target schema、provider、工具版本、遮罩命令、exit code、內容 hash 及輸出範圍，確認未混入範圍外異動或與既有 SQL 重複執行。外部 artifact 必須先加入 inventory 再審查，不因檔案不在 repo 就視為不存在；缺 inventory 欄位標待確認，缺 execution artifact 則依來源類型判定阻擋。Database Project schema compare 無 CREATE／ALTER／DROP 時，核對工具成功與 hash 後記錄 schema 無差異，不要求人工補 DDL。正式 repair migration 應標記為 `repair-migration` 類別的獨立來源單位，核對其 ID、source revision、相依、交易、錯誤與重跑設計，02 不得重複內嵌。缺 artifact 時先依入口技能嘗試工具產生，可確認的文件問題先修正再複審。正式資料庫版本、provider／driver、主機或本機基準屬部署驗證資料，不是 SQL 內容審核門檻；仍完成來源與成品審查，收尾分別回報 SQL 內容審核與部署驗證狀態。

1. 完整性：從完整 Git 範圍反查結構、資料、設定每项是否列入；ORM 是否有部署腳本；未提交內容是否有納入決策。
2. 正確性：確認 01／02 為 .sql，說明皆為 SQL 註解，無未填模板、Markdown 圍欄、遮罩佔位語句；完整部署內容須與來源方言及指定工具契約相容，無異動僅含註解，缺 SQL artifact 必須阻擋。結構內容必須回溯 EF model／migration 差異、資料庫專案 schema compare／部署腳本，或專案指定的等價 schema artifact；核對來源 provider、工具版本、revision 與輸出模式。只有 ORM 類別、migration 名稱或人工推導時判為待確認／未通過。刻意不上線的功能可使用受控排除清單；保留未改寫的來源 artifact，並可人工建立本次執行 artifact，但需記錄來源／執行 hash、排除 ID、來源定位、完整執行單位／物件、理由、相依影響、負責人、核准依據與逐單位差異核對。人工處理不得改動納入單位的 SQL、交易或 guard；跨單位刪除、任意 wrapper 或缺證據判未通過。逐項對原始來源核對 SQL 方言、WHERE、完整設定鍵（含陣列索引）、值、程式使用處與實際來源優先順序；遮罩秘密。正式主機、SQL Azure、實際 driver、版本與 collation 不屬內容審核；若另行執行部署驗證，僅記錄結果，不以環境缺口否決 SQL 內容。
3. 相依與執行：根據實際相依核對 SQL／設定／程式的交錯順序；混合 DDL/DML 必須是同一完整執行單位且只執行一次，保留 GO、交易與 migration 工具。
4. 可驗證與可恢復：每步驗證有可查證預期條件；核對停止位置、部分成功、重跑限制、備份與回復條件。Down／交易不是安全回滾證明，不猜測資料量或執行時間。
5. 文件安全與一致性：所有秘密遮罩、文件連結實際可解析、共同範圍及執行 ID 一致；保留已有人工簽名／執行紀錄。只有空白人名、時間、簽核欄與「未執行」的範本列是占位，不算已執行。已有實際紀錄時另建 `_v2`／下一空閒版本並記取代理由。

另必檢 release 日期與容錯：預設目錄日期（包含_v2等版本的日期部分）須對應已確認 release 分支名稱中的有效日期；使用者明確指定其他目錄時核對其指示及路径安全，所有已產出文件標頭一致記錄分支、日期來源與另列產出日期；不得以當天或 commit 日期代替。缺分支／日期依據判待確認，不猜測。

逐完整 SQL 單位依 SQL 判讀規則核對異常中斷容錯及多次重跑設計：表、欄位、索引、約束與表／欄位描述獨立檢查狀態，缺少補建、描述不符更新、正確跳過，不相容或可能損失資料則停止報錯。不能因表存在而跳過未完成項目；資料不得重複新增、累加或破壞應保留值。若物件在受控排除清單中，核對其完整來源定位、排除理由與相依影響，不要求本次執行；未列入排除清單的物件仍須逐物件 guard。內容審核以來源、工具產出、語意等價、交易／錯誤回拋、相依順序與前後只讀查核為必要證據；首次執行、兩次重跑及中斷注入只有在要求部署驗證時才執行。已證實來源缺機制或實測失敗且直接證明內容缺陷，判未通過；缺內容證據判待確認；缺實測只記部署驗證未執行。不得私改 SQL，阻擋未解不得通過。無異動純註解檔附盤點證據可記不適用。

每次建立或更新文件（含修正或 fallback）之前，必須先遵循簽核保留規則選定最終版本目錄，再立即執行共用唯讀 guard：

```text
python <插件根>/skills/release-docs/scripts/validate_output_paths.py --repo <repo> --documents <最終版本目錄>
```

拒絕越界目錄、具名成品 symlink（含 repo 內別名）、非一般檔案、`st_nlink > 1` hard links。失敗只在對話報告並停止寫入，不能寫 05 待確認到被拒絕位置。fingerprint 也使用同一 guard，但不能拿生成後的檢查取代寫入前 preflight。

## 判定與複審

有設定異動時，04 必須直接提供調整後的 fenced json 範例（純量亦適用）；核對可解析性、實際鍵、父層、型別／陣列、對應設定 ID 與修改位置、非正式值標示及敏感值遮罩。只有文字範例或模板示意鍵不能算完成，先修正再複審；來源結構不足則待確認。

04 的每個設定 ID 另核對參數用途與調整原因、預期型別／格式／限制、資料範例及實際修改位置是否齊全並有來源依據。範例須標「格式示例，非正式值」，與正式值分列且無秘密；實際位置須對應有效 provider 的環境、服務、檔案完整鍵或平台／環境變數／secret 鍵，不能只列 repo 來源路徑。刪除／改名需列預期狀態及相應位置。缺可確認欄位先修正再複審；缺必要證據列待確認，不得通過。

第3至5項須核對 00 說明後續檔案用途；若存在 03_例外排除，核對其 `artifact_class=exclusion-manifest`、schema_version、release、exclusions，以及每項 id、type、units、operator_action、reason、dependency_impact、reinstatement_conditions、evidence、approval、review。若存在 04_參數異動，核對 `artifact_class=config-change`、設定鍵、來源、套用方式與驗證欄位。00／03／04 不放執行歷程或重複審查來源；沒有排除時 03 不應存在，沒有參數異動時 04 不應存在。排除缺欄位、重複 ID、納入單位被改寫、artifact／核准／追蹤不一致或 03 與 SQL scope 不一致，判內容未通過或待確認。

SQL 內容審核狀態只用「通過」「待確認」「未通過」；部署驗證另用「通過」「未執行」「待確認」「未通過」，區分尚未要求／尚未執行與實測失敗。漏列 SQL、私改或推導來源、混合腳本重複執行、錯誤鍵／順序／部署／回復指令、交易／錯誤機制不足或敏感值外洩屬內容阻擋，判 SQL 內容未通過；主機、provider／driver、SQL Azure 實測或其他環境證據不足只列部署待辦。未做實測不單獨否決內容。可證實問題先修正再複審受影響文件一致性，最多三輪；文件通過不代表已完成主機部署驗證、人工簽核或已執行。

## 證據失效識別

每輪開始先執行入口技能內的 `scripts/review_fingerprint.py`：

```sh
python <插件根>/skills/release-docs/scripts/review_fingerprint.py --repo <repo> --documents <repo/docs/release-doc/日期> --base <base> --target <target> --diff-mode two-dot
```

range 模式依原輸入選 two-dot 或 three-dot，保持既有 CLI。清單模式改用以下互斥介面，不得同時給 --base、--target 或 --diff-mode：

```text
python <插件根>/skills/release-docs/scripts/review_fingerprint.py --repo <repo> --documents <repo/docs/release-doc/日期> --commit-scope <JSON檔>
```

JSON 檔是非空有序清單，例如 `[{"commit":"<A>","parent":"<A的direct parent>"},{"commit":"<C>","parent":"<C的direct parent>"}]`；root 使用 JSON null。腳本解析全部 revision 為 SHA、验证 direct parent、按順序记录 `commit_scope`，逐對識別前後 source tree、diff status 與 content。清單 snapshot 不含虛構 base／target／diff_mode。A、C 的差異不包括 B；完整樹仍識別其依賴內容。JSON 不含原文。存在的成品 raw bytes 各自 SHA-256；已提交範圍和 staged／unstaged／untracked 分別識別。只排除此資料夾的必要成品及存在的資料 SQL，docs 其他來源仍納入。路徑越界、缺文件或證據不可讀即停止；路徑被 guard 拒絕時只在對話記待確認，不寫報告。

審查完成先再次執行並比較開始 snapshot：若來源識別（range: base、target、diff_mode；清單: commit_scope 的每一對 SHA 與順序；兩者皆比較 committed、working_tree）改變，丟棄本輪結論重新讀來源；成品更改則重新核對更改內容。保存完成語意審查時的 snapshot 作為「已審查 snapshot」。計算最終 snapshot；寫入或接受 05 前，必須再次將最終 snapshot 與已審查 snapshot 的來源識別逐項對比：range 的 base、target、diff_mode，或清單的完整有序 commit_scope；以及 committed、working_tree。任何來源識別不符都丟棄該輪結論並重新審查，不能將新來源 snapshot 直接存成通過證據。這段期間成品只允許已核對的文件內容更新；其他成品變動需重新語意審查。確認一致後才把最終 snapshot 原封不動存入 05。報告本身被排除，寫 05 不會循環失效；必備成品及已存在的資料 SQL 不得是 symlink，包括指向 repo 內其他檔案的報告別名。

交付對話審查結果時，重算同參數 snapshot，比較 `fingerprint`；不符代表舊報告失效，重新語意審查。相符只表示證據內容未變，仍需確認對話回報包含各項審查證據及無未解決事項。摘要同步狀態與阻擋事項。
