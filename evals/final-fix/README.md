# Final fix scoped actual evidence

2026-10-08／Asia/Taipei。這是新證據，不修改 `evals/actual/`、先前 task2 或其 snapshot。由本輪 implementer 實際依更新後兩份技能在新 Git fixture 生成／另輪重讀審查；沒有 subagent、安裝、部署、SQL 執行或外部服務。這是窄範圍實作端演練，不宣稱獨立評審。

`sources/` 是實際 Git fixture 的完整四個來源檔；`source-identities.json` 記錄 baseline、A、B、C 與原始有序選定 pairs。A 新增表，B 新增獨立表但不選，C insert A 的表。每份 `outputs/01–04` 都保存相同有序 pairs，沒有假造 range。05 逐項重讀語意證據，正式環境／備份恢復／UAT 未驗證，所以正確保持「待確認」。PK／NULL 與 seed 7 的預期只依本情境來源；先前 archived Minor PK prose 保留為誠實證據，不拿它作通用預期。

实际命令（Python 使用本機 bundled runtime）：

```text
python skills/release-docs/scripts/validate_output_paths.py --repo .superpowers/final-fix-run/source-repo --documents .superpowers/final-fix-run/source-repo/docs/2026-10-08_AC
python skills/release-docs/scripts/review_fingerprint.py --repo .superpowers/final-fix-run/source-repo --documents .superpowers/final-fix-run/source-repo/docs/2026-10-08_AC --commit-scope .superpowers/final-fix-run/scope.json
```

首次建立與每次寫入／04 狀態／05 保存前均執行 guard。`preflight-actual.json` 保存內部／外部 01 symlink、05 fallback alias，以及四份已存在時第五報告 update alias 的實際 exit 2 和未變來源／成品 hash；拒絕後沒有草稿、狀態或 fallback 寫入，阻擋只回報對話。測試設置與清除 symlink 只是 fixture 操作，不是技能修復原檔。

`review-start.json` 和 `reviewed.json` 完全相等；只更新已核對的 04 最終狀態後，`final-snapshot.json` 的 `commit_scope`、`committed`、`working_tree` 與受審識別逐項相等。chosen diff `changed_paths` 僅 `01_a.sql`、`03_c.sql`，B 未混入差異（完整 source tree 仍含 B 的來源內容，這是相依內容識別）。05 原樣保存 CLI snapshot，寫 05 後重算仍相同。

自動真實 Git 回歸：`python -X utf8 -m unittest discover -s tests -p test_final_fix.py -v`。另測 order／merge parent identity、root/null、無效非 direct parent、revision→SHA、mutual exclusion、安全新目錄／越界／非一般檔案。此 Windows sandbox 建 hard link 發生 WinError 5，實際 hard-link case 明確 skipped；並非宣稱已測 hard-link filesystem 行為。

重現來源時使用新的 Git 臨時目錄，依 source-identities 所列拓撲先 commit README，然後依序新增 `01_a.sql`、`02_b.sql`、`03_c.sql`；生成的 SHA 會不同，需記錄新的有序 A/baseline、C/B pairs。不可改此 archive 的既有 SHA／fingerprint。
