---
name: release-docs
description: 當使用者要先確認 Git 差異範圍，再以舊版資料庫來源與排除意圖產製上線 SQL、參數與操作文件時使用；不執行正式部署。
---

# Release Docs

## 輸入與證據

先從已提供內容取得 repository、base／target 或明確 commit 範圍、diff mode、工作區是否納入、舊版 DB 結構來源、release 識別與排除意圖。缺少影響範圍的必要資訊時標示待確認；不得自行將 HEAD 或工作區異動視為本次 scope。

執行唯讀工具（SCRIPT_DIR 為此技能的 scripts 目錄）：

```text
python SCRIPT_DIR/collect_release_evidence.py --repo PATH --base REV --target REV --diff-mode direct
```

完成審查與交付後才呼叫 `finalize_lifecycle_run(run_root, review_status="success", delivery_status="success")`；它只清除該 run 下的暫存目錄，保留 manifest、審查報告與 execution evidence。每次新 run 建立時會先掃描並清除已到期的暫存資料。

選擇 `merge-base` 時以共同祖先作為實際比較起點。讀取 JSON 的完整 SHA、Git 根目錄與 A/M/D/R 等路徑證據；將 staged、unstaged、untracked 與 committed changes 分開。工具不輸出內容，後續 source 分析必須再取得對應 revision 的來源，不可從檔名或 commit 標題猜測 SQL。

## 產製與審查邊界

先收集 Git 證據，再分析完整 execution units、保存 lifecycle 證據、組裝 SQL，最後渲染上板操作文件。以下工具負責產製；SQL 內容審核與 LocalDB／disposable runner 驗證須另行取得證據。缺少必要能力或證據時標示待確認，不得宣稱已完成審查或部署驗證。

完整工作流需依 Database Project／dacpac／migration／SQL 與 codebase 的實際消費，建立可追溯的 SCHEMA、REPAIR、DATA、VALIDATION execution units。不得從 ORM Up/Down 自行猜出 SQL。排除意圖須分析完整 unit 與 dependency impact，無法安全切出單位時阻擋產出。

上板檔案固定為 `00_上線指引.md`、唯一人工 SQL `01_部署SQL.sql`，以及有參數異動時的 `02_參數異動.md`。source、工具輸出、完整 mapping 與排除真相 `lifecycle_exclusion_manifest.json` 保存在 `.release-docs/runs/<run-id>/`，不得交給上板人員操作、不得放入 release 目錄或版控，也不得寫入 `docs/release-artifacts`。`00` 的排除摘要由 lifecycle 真相投影，不反向改寫排除範圍。

單一 release-level transaction 必須完整執行與驗證後，在 ValidateOnly=1 rollback，在 ValidateOnly=0 從 fresh baseline／fresh session 重新執行後 commit；rerun 使用已 commit 的資料庫，以 fresh session 驗證收斂，不重置 baseline。任何錯誤 rollback、THROW 並停止；不可交易 DDL 需受控分類，不能宣稱外層 transaction 可回復。不得直接連線或修改正式資料庫。

分開回報 SQL 內容審核與部署驗證狀態。證據不足用「待確認」，不得以文件存在或 Git 收集成功代替 SQL／部署驗證。

## 產製器串接

從 scripts 目錄載入 Python 函式，依序呼叫：

```python
ef = detect_entity_framework(repo, evidence["source_scope"])
analysis = analyze_release_units(repo, evidence, baseline_schema, exclusion_intent, ef_detection=ef)
# 不將排除單位交給 assembler；manifest 是排除真相。
excluded_ids = {uid for exclusion in analysis.exclusions for uid in exclusion["unit_ids"]}
included_units = [unit for unit in analysis.units if unit["unit_id"] not in excluded_ids]
artifact = assemble_deployment_sql(included_units, run_root / "01_部署SQL.sql", {
    "release_id": release_id,  # runtime_mode 為 session_context；不可傳入 validate_only
})
localdb_evidence = run_local_validation(
    artifact.path, server="(localdb)\\MSSQLLocalDB", database=release_id,
    baseline_source=str(run_root / "baseline.sql"), fixture_source=str(run_root / "fixture.sql"),
    fixture_manifest=run_root / "fixture.json",
    data_units=[unit for unit in included_units if unit["phase"] == "DATA"],
    # 未提供 executor 時只記錄 not_run；真實隔離 adapter 另提供版本、command、provenance。
)
manifest_path = write_lifecycle_run(
    run_root, analysis,
    localdb_validation=localdb_evidence,
    execution_artifact={"path": str(artifact.path), "sha256": artifact.sha256},
    operator_contract={"parameters_applicable": bool(getattr(analysis, "parameter_changes", []))},
)
inventory = render_release_documents(analysis, artifact, manifest_path, output_dir)
```

遇到 blocking findings 即停止產製。`run_root` 必須是 `.release-docs/runs/<run-id>`。execution artifact、baseline 與 fixture 的不可變副本保存於 `run_root`；最終 output 另選受控目錄；不得使用 `docs/release-artifacts`。renderer 接受 `write_lifecycle_run` 回傳的 manifest Path 或其 run directory，從檔案讀取排除證據，核對 SQL SHA-256 及 included unit mapping；只逐 byte 複製已組裝 SQL，不重建或修改 SQL 語意。`OutputInventory.output_dir` 為絕對路徑，`files` 為交付檔名到 SHA-256 的 mapping，供後續 fingerprint 使用。

renderer 寫入前檢查全部輸入與輸出，拒絕 traversal、symlink、junction、hardlink、未宣告的檔案／子目錄、legacy artifact 路徑與 lifecycle 目錄。既有檔案只接受完全相同內容；存在過期參數文件或內容衝突時，換新的交付目錄。不得把 lifecycle JSON、完整來源 hash、內部 dependency graph 或工具紀錄放進操作文件。

## 結構與參數文件

產製文件前，根據已確認的來源語意補充 `analysis.structure_changes`，每項包含 `kind`（table、column、index、fk、constraint、extended_property）、`name`、`description`、`impact`，並以必填 `unit_id` 關聯有效 included source unit。renderer 會移除排除單位的描述；缺少或未知單位的 top-level 描述會省略且標待確認，不能將其物件寫入結構異動範圍。也可在 `units[].structure_changes` 提供同格式資訊，其來源 ID 繼承包含它的 unit，只有 included units 會被讀取。列出實際異動物件、目的與影響；不得憑 SQL 關鍵字、檔名或 commit 標題猜測說明。沒有說明時 `00` 會顯示「結構異動說明待確認」，必須補齊後再交付。排除摘要只投影 lifecycle 的 issue、理由、物件範圍、保留操作與重新納入條件。

有參數異動時提供 `analysis.parameter_changes` list；每項含 `environment`、`service`、完整 `key`，以及 `format_example`、`apply`、`reload`、`validation`。缺必要環境／服務／完整 key 即阻擋；操作細節缺值顯示待確認。敏感 key 或 `sensitive=True` 的格式範例固定遮罩，raw value／old_value／new_value 不輸出，且其已知機密值會從操作描述移除。一般範例中的 URL 帳密與機密 assignment 也遮罩；機密原值留在受控機密儲存。沒有參數異動時不產出 `02_參數異動.md`。

`00` 包含 release/source、六類結構範圍及說明、排除摘要、備份/preflight、ValidateOnly=1 完整 rollback 後以 fresh baseline／新 session 執行 ValidateOnly=0 commit、錯誤停止、結構化錯誤欄位與部署後查核。LocalDB 預設「未執行」，SQL 內容審核預設「待確認」，兩者不互相取代。

若 lifecycle metadata 有 `localdb_validation`，renderer 可讀取 `status`（not_run／failed／passed）。passed 必須有相符 `artifact_sha256` 及 `rounds`：validate_only、commit、rerun、injected_failure；每輪需 status=passed、exit_code=0 與 server、database、provider_version、tool_version、baseline_source、fixture_source、command、checks，以及必填字串 `error_output_summary`。正常成功輪可明確記錄空摘要，injected_failure 輪需非空預期錯誤摘要。注入錯誤輪的 exit_code=0 指 runner 成功驗證預期錯誤、rollback 與停止，並非 SQL 無錯誤。證據不完整或 artifact 不符只顯示「待確認」。這是讀取既有證據的介面，renderer 不執行資料庫測試。


## Session context 與四輪證據

SQL Server 2016 以上支援此契約。assembler 的 transaction_mode 只接受可選 release_id，產物 runtime_mode 為 session_context。每次在同一 connection/session 一次執行整份 SQL；預設 ValidateOnly=1 完整 rollback。正式執行前由人員在同一新 session 設定 `EXEC sys.sp_set_session_context @key=N'ReleaseDocs.ValidateOnly', @value=0;` 才允許 ValidateOnly=0 commit。禁止第一次留下未提交交易，再由第二次獨立 connection 接續 commit；不得將執行模式寫死在產製參數。不可交易 DDL 直接阻擋。

DATA units 的 expected_assertions 必須在保存 lifecycle 前由已核對來源與 fixture 補齊：每項有唯一 id、case、seed_row_id，以及 validate_only／commit／rerun／injected_failure 的 expected_by_round.before／after。fixture manifest 保存 usage、seed_rows 的 unit_id／row_id／purpose、expected_preserved_data_summary；assertions 可由 manifest 或 data_units 提供，避免重複。資料來源需涵蓋既有值、保留值、NULL、重複候選、邊界、空集合與筆數。無法安全定義預期值時阻擋內容審查。

runner 每輪保存 artifact_sha256、baseline_sha256、fixture_sha256、fixture_manifest_sha256、database_id、session_id、committed_state、distinct checks、data_checks 與 adapter 實際回報的 preserved_data_summary。保留資料實測摘要不可由預期摘要代填。ValidateOnly、commit、failure 使用不同 fresh baseline database；rerun 保留 commit 的 database_id／committed_state 並使用不同 session_id。fixture、baseline、manifest 與 execution artifact 需留在 lifecycle 永久區，不得放 temporary。缺 runner 時未執行；缺必要證據、相同 checks 或保留資料摘要不符時待確認。四輪隔離結果不代表正式部署成功。

目前 EF 自動 guarded SQL 僅接受可完整比對定義的簡單 CreateTable（int／bigint／bit／nvarchar(max)、單欄 PK）及單欄非唯一 CreateIndex；其他欄位或 operation shape 會阻擋，須提供經核對的可追溯完整 SQL／repair source。不得將 metadata 的 skip_condition 當成 SQL 已具備重跑保護。
