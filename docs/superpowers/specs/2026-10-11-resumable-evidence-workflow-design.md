# Resumable Evidence Workflow Design

## Goal

讓 release-docs 的證據產製在中斷、命令失敗或外部工具暫時不可用時可以安全恢復，並且只有在所有必要證據原子完成後才產生最終審查通過狀態。

## Context

目前 SQL 靜態審查、validation SQL 與 LocalDB 判定可以正確阻擋證據不足的情況，但完整流程依賴多個人工命令與外部工具。長流程中斷後缺少單一可恢復入口，容易留下半完成的 fixture、local validation、semantic review 或 report，導致人工重跑、狀態混用與中間結果被誤認為完成。

## Scope

本設計涵蓋：

- lifecycle run 的 durable checkpoint 與 resume。
- source、fixture、LocalDB、semantic review、report finalize 的階段狀態。
- DATA fixture／assertion 的完整性 gate。
- 最終報告的 atomic finalize gate。
- command、錯誤摘要與 evidence metadata 的 secret redaction。

本設計不涵蓋：

- 正式資料庫部署或正式業務資料驗收。
- 將 `business_data_validation` 升級為 SQL correctness blocker。
- 自動推導未由 authoritative source 定義的業務規則。
- 以 expected value 取代 runner 實際產生的 before／after 結果。

## Design

### 1. Durable run state

每個 `.release-docs/runs/<run-id>/` 新增機器可讀的 workflow state，至少包含：

- `schema_version`。
- `run_id`。
- `status`: `created`, `running`, `blocked`, `interrupted`, `failed`, `completed`。
- `current_stage`。
- 每個 stage 的 `status`, `attempt`, `started_at`, `completed_at`, `input_fingerprint`, `output_files`, `error_summary`。
- `workflow_fingerprint`，由 source scope、SQL artifact、fixture、manifest 與必要 metadata hash 組成。

State 只能透過 lifecycle store 的受控寫入更新。每次 stage 完成先寫入永久 evidence，再以原子 replace 更新 state；未完成 stage 不得被標示為 passed。

### 2. Stage machine and resume

固定階段順序如下：

```text
created
  -> source_collected
  -> fixture_ready
  -> local_validation_passed
  -> semantic_review_passed
  -> report_finalized
  -> delivery_finalized
```

每個 stage 必須是 idempotent：

- 若輸入 fingerprint 未變且輸出檔案 hash 相符，resume 可重用既有結果。
- 若輸入或輸出不一致，該 stage 與所有 downstream stage 必須 invalidated。
- `resume` 只執行第一個未完成或已 invalidated 的 stage。
- stage 失敗保留錯誤摘要與既有 evidence，不覆寫成通過。

新增的 resume 介面應接受既有 run root，拒絕外部路徑、已 finalized run、缺 lifecycle lock 或 workflow state schema 不相容的 run。

### 3. Fixture and DATA evidence gate

在進入 LocalDB validation 前，協調器必須驗證：

- 每個 included DATA unit 的 `expected_assertions` 完整且唯一。
- 每個 assertion 的 `seed_row_id` 能對應 fixture manifest 中唯一的 seed row。
- 每個 assertion 具有可執行的查核定位或 validation query mapping。
- fixture manifest 的 seed rows 與實際 fixture rows 一致；空 rows 不得宣稱 fixture ready。
- expected before／after 只來自 source analysis；actual before／after 只能由 runner data checks 產生。

缺少上述任一條件時，stage 狀態為 `blocked`，finding domain 為 `sql_correctness`（若缺少 SQL 必要預期）或 `deployment_validation`（若只有執行證據缺少），不得建立完成報告。

### 4. Atomic report finalize

`report_finalized` 必須在單一 finalize gate 內重新檢查：

- current fingerprint 與 semantic review fingerprint 相符。
- source metadata、execution artifact、fixture、manifest、LocalDB evidence 的 hash 相符。
- 四輪 transaction evidence 與必要 data checks 完整。
- finding 分流後，`business_data_validation` 只作非阻塞附加資訊。
- lifecycle receipt 可完整列出永久 evidence 且沒有 temporary／外部路徑。

任何檢查失敗都只更新 workflow state 與 review record，不寫入「SQL 內容審核：通過」的最終報告。

### 5. Secret redaction

所有 command metadata、錯誤摘要與對外 finding 在寫入前經過同一個 redactor：

- 遮罩 connection string 的 password、user credential、token、secret、API key。
- 不保存原始 command line 中的 credential。
- redactor 先於 durable evidence write 執行。
- 偵測到無法可靠遮罩的疑似 secret 時，停止該 stage 並產生非敏感錯誤碼。
- review report 只提供錯誤分類與 remediation，不輸出 SQL literal、連線字串或原始工具錯誤。

## Error handling

- 工具不存在：記錄 capability failure，保留 run 為 blocked，可在工具補齊後 resume。
- 暫時性連線／啟動失敗：在 stage 內採有限次數 retry，超過後進入 failed；resume 可重新嘗試但不重做已完成 upstream。
- 輸入 fingerprint 改變：建立明確 invalidation finding，要求新 evidence，不沿用舊通過結果。
- 使用者中斷：保存目前 stage 為 interrupted／failed，保留 evidence 與 lock cleanup metadata；不得寫完成報告。
- schema 不相容或 evidence 損壞：停止 resume，要求建立新 run。

## Compatibility

- 既有 `schema_version=1` lifecycle metadata 仍可讀取。
- 沒有 workflow state 的舊 run 視為 legacy run，只能 read-only review，不能直接 resume；可由新 run 重建。
- 現有 `validate_release_output.py`、`semantic_review.py` 的 finding domain 定義維持不變。
- 正式資料與 `business_data_validation` 的非阻塞規則維持不變。

## Verification plan

測試必須先建立失敗案例，再實作：

1. 中斷後 resume 只執行未完成 stage。
2. upstream fingerprint 改變會 invalid downstream state。
3. 空 fixture rows 或缺 assertion mapping 不能進入 validation。
4. finalize gate 不會在 report、fingerprint 或 evidence 缺失時產生通過狀態。
5. credential 出現在 command、exception 或 connection string 時不會寫入 durable evidence。
6. `business_data_validation` finding 不會降低 `sql_content_status`。
7. 舊 schema run 維持可讀但不能 resume。

## Success criteria

- 長流程中斷後可用單一 resume 命令恢復，不需人工猜測已完成階段。
- 任一半完成 run 都不能產生最終通過報告。
- evidence 缺口以精確 stage／finding 回報，而非泛化為 opaque 或 semantic pending。
- 全部測試與現有 SQL correctness、validation SQL、LocalDB 四輪契約保持通過。
- 任何 credential 不出現在 lifecycle evidence、review report 或 command log。
