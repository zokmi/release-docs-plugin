# Release 穩定性與速度修正

## 範圍與限制

基準為 `434bb2d`，作業分支 `codex/release-speed-hardening`。修正 SHA 誤判與工具探測失敗處理；CI／Release 保留 Linux／Windows × Python 3.11／3.12／3.13 六組完整測試，以及 tag、main、版本、資源與發布相依 gate。沒有復用其他 CI 的成功結果，也不覆寫 v0.1.35 tag。插件程式仍只需標準函式庫；pytest／xdist 只屬測試相依。

原 v0.1.35 Release run `38237179288` 因 Windows 3.13 的 `dotnet --version` 超過 10 秒而失敗，release job skipped；同 SHA 的 main CI run `38237111622` 因 Git SHA 偶然含 `999` 被整份文件字串 assertion 誤判。這些失敗不能視為已發布。

## 修正與測試

- 工具探測預設不可用；缺工具、timeout、啟動錯誤、非零退出均保存明確 probe status，保留來源清單。只有成功且非空版本回應才標示 probe verified，不代表 SQL 執行能力或正式部署通過。
- unknown-tool 單元測試指定未知工具，不依賴 runner 安裝的真實 SDK；另有實際 Python version subprocess 與故障邊界測試。
- Git SHA 含 `999` 的 fixture 以真實 commit object 重現，tree／parent 保留；不偽造來源 SHA。文件驗證改為比對設定 JSON、descriptor 及 target revision，而不是禁止整份文件出現 `999`。
- 工具故障回歸先 RED 3 failed；SHA marker 回歸先 RED 3 failed。修正後 SHA 六項 add／update／remove 通過；限定範圍四-worker 回歸 36 passed、11 subtests passed，沒有 skipped。
- 獨立唯讀審查沒有 Critical／Important；timeout/error 診斷預期值的 Minor 已補精確比對並複審關閉。

## 同範圍效能比較

環境：Windows、Python 3.12.14、pytest 9.1.1、pytest-xdist 3.8.0。相依安裝在專屬暫存 venv，未變更全域 Python。以下均使用相同 13 項 Git-heavy 案例、相同程式與相依版本，分開執行避免競爭：

| 模式 | 結果 | 耗時 |
| --- | --- | --- |
| `-n 0` | 13 passed | 27.68 秒 |
| `-n 4 --dist worksteal` | 13 passed | 23.22 秒 |
| `-n 2 --dist worksteal` | 13 passed | 14.50 秒 |

兩 worker 對此範圍減少約 47.6% elapsed time，因此先採 Windows 2-worker、Linux `-n 0`。這是單次、限定範圍的本機比較，不能冒稱 GitHub 完整發布已降到 3–5 分鐘。CI／Release 另輸出最慢 30 項耗時與各 matrix 的 JUnit artifact，供後續整體量測。

## 最終驗證

完整 `tests` 收集 **1091 tests**。完整兩-worker 回歸實際 **1091 passed、15 subtests passed**，exit code 0，耗時 **874.27 秒（14 分 34 秒）**。JUnit 包含 1091 個主案例與 15 個 subtests，共 **1106**，`failures=0`、`errors=0`、`skipped=0`。不沿用前一版本通過報告，也不修改使用者原有兩份未提交報告。

另以與 CI 相同的 `PYTEST_ADDOPTS='-n 2 --dist worksteal'` 注入方式驗證工具探測與發布／套件 gates：**19 passed、11 subtests passed**，3.45 秒。六組遠端 matrix 的新速度尚未量測，不能用本機資料宣稱 GitHub 發布成功或已達特定分鐘數。`git diff --check` 通過；獨立複審所有 finding 已關閉。

最慢案例集中於 resumable workflow 與多輪 Git／文件證據處理；後续若要優化 fixture 共用，必須另驗證每個 case 的可修改資料仍完全隔離，不能把本輪平行化視為可共用 repo／DB 的授權。

```powershell
python -m pip install -r requirements-test.txt
python -X utf8 -m pytest tests -q -n 2 --dist worksteal --durations=30 --junitxml=test-results.xml
```
