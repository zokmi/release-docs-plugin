# 參數文件審查修正紀錄

## 範圍

修正獨立審查指出的敏感片段洩漏、邏輯設定鍵碰撞、實體 JSON 路徑誤判、來源追溯未納入 preflight 比對，以及 XML／部署參數缺少受控成功路徑。不修改部署 SQL，不代表正式部署或業務資料驗收通過。使用者後續明確要求合併與發布，目標版本 v0.1.35；實際發布狀態以 GitHub Release workflow 與 Release 為準。

## 已驗證

- 共用完整陣列片段的敏感值須在同來源各 descriptor 遮罩，原始來源不變；來源與 provider 不同不得互相覆蓋。
- 祖先 descriptor 的自由格式範例可能序列化敏感子值，整段遮罩，不猜測編碼或全域替換數字。
- canonical projection 保留實體 `key_segments`、provider 與 precedence metadata；XML／環境變數 JSON 明示為邏輯設定，不可直接取代來源格式。
- renderer：新增回歸測試先實際失敗；最後完整 `tests/test_release_documents.py` 為 **89 passed，0 skipped**（`.tmp-review-renderer-reviewed-green`）。獨立複審未發現新的 Critical／Important；複審另做 6 組記憶體內重現，未冒稱重新執行整套測試。
- 套件必要資源包含兩個參數發現模組：回歸先失敗，完整 `tests/test_release.py` 為 **5 passed**（`.tmp-review-package-green`）。
- 發現層複審新增外部部署來源／XML 繼承語意的 Important：Compose `env_file`、Kubernetes `envFrom`（包括空值）與 XML `clear`／`remove` 改為明確拒絕。新增測試 RED 17 failed，修正後主流程重跑三個 discovery／deployment／source 測試檔 **97 passed，0 skipped**（`.tmp-review-discovery-reviewed-final`）。此紀錄是限定範圍驗證，非整個插件結果；解析器修正仍在獨立複審。

## 最後修正回合

- 重複 base／target 來源：不再使用最後一筆覆蓋證據，回傳 blocking 與 applicability `None`；兩角色、兩排列皆有測試。
- Compose `extends`（包括空值）明確拒絕；不將外部繼承設定視為完整 literal map。以上新增案例 RED **7 failed**，修正後納入最後整體回歸。
- XML namespace 邊界：新增回歸先 RED，改為拒絕 qualified tags；標準 XML 正向 fixture 同步改為無 namespace，保留獨立拒絕案例。
- 整合限定範圍曾為 **191 passed／1 failed**：環境 provider 正向 fixture 使用 Windows 工作區 bytes 的 hash，與 Git 換行正規化後的 pinned bytes 不符。正式驗證正確阻擋；修正 fixture 改用 `git show` 的原始 bytes，未放寬 hash 規則。XML／environment 正向產製重跑 **2 passed**。
- 最後獨立審查未發現可重現 Critical／Important；Minor namespace 邊界已採納，補充唯讀複審也確認可關閉。完整回歸分為四組、各自 basetemp；已核對全部 **30 個測試檔**恰好涵蓋一次，無遺漏或重複。先前中止的單程序／第三組試跑不列為通過。

## 最終驗證結果

第一組 **99 passed**、第二組 **89 passed**、第三組 **240 passed**、第四組 **656 passed**，四組 exit code 全為 0；合計 **1084 passed、0 failed、0 skipped**，與完整 collect-only 的 **1084 tests** 一致。最後一組耗時 1593.02 秒。這是本次修正後的實測，不沿用先前版本的 961 passed。獨立複審沒有未解決的 Critical／Important／Minor。

v0.1.35 僅再調整三份 manifest 與 README 版本資訊，`tests/test_release.py`／`tests/test_packaging.py` 另重跑 **13 passed**，套件資源／版本檢查通過。提交與快轉合併不得混入使用者原有不相關變更；遠端發布仍需 release workflow 的六組平台／Python matrix 通過。

## 重跑方式與驗證範圍

以下四組合計涵蓋所有 `tests/test_*.py`，每組使用不同暫存目錄，可並行執行。所有組別完成後才計算整體結果。

```powershell
pytest tests/test_analysis_metadata.py tests/test_artifact_lifecycle.py tests/test_atomic_finalize.py tests/test_authenticated_preservation.py tests/test_change_tables.py tests/test_source_discovery.py -q --basetemp=.tmp-review-remediation-final-part1
pytest tests/test_collect_release_evidence.py tests/test_derived_sources.py tests/test_entity_framework_detection.py tests/test_evidence.py tests/test_evidence_redaction.py tests/test_evaluation_fixture.py tests/test_final_fix.py tests/test_packaging.py -q --basetemp=.tmp-review-remediation-final-part2
pytest tests/test_deployment_parameters.py tests/test_parameter_discovery.py tests/test_produce_release.py tests/test_release_unit_generator.py tests/test_release_units.py tests/test_metadata_provider.py tests/test_release.py -q --basetemp=.tmp-review-remediation-final-part3b
pytest tests/test_end_to_end.py tests/test_local_validation.py tests/test_release_documents.py tests/test_release_review.py tests/test_review_fingerprint.py tests/test_resumable_workflow.py tests/test_semantic_review.py tests/test_sql_assembler.py tests/test_workflow_state.py -q --basetemp=.tmp-review-remediation-final-part4
```

套件資源／版本唯讀檢查通過（`check_package(Path.cwd(), 'v0.1.35')`）。`git diff --check` 通過，只有既有 LF／CRLF 提示。修正基準 HEAD 為 `2dabf81b55b3f977638d6546be714078dc831085`。不修改或清理使用者既有不相關變更與測試證據。阻擋 fetch 的全空字元 ref `main.broken` 已移至 `.git/main.broken.recovery-20261012` 保存，未刪除任何有效分支。
