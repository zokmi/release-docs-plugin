# Evidence gates 調整與驗證

日期：2026-10-10／Asia/Taipei

## 完成內容

- AnalysisResult 正式保存結構說明、遮罩後參數描述、參數適用性及 Git 比較／工作區決策；未知適用性不轉成無異動。
- 產製協調器集中執行前置資格、來源 revision/hash 核對、排除／相依检查、SQL 組裝、永久輸入保存、可選隔離驗證、渲染與 fingerprint。
- 靜態檢查與 SQL 最終狀態分離；逐 unit 語意紀錄綁定當前 fingerprint。缺紀錄或過期保持待確認。
- 報告 writer 重新核對當前內容，不能沿用過期 fingerprint；fingerprint CLI 保留完整 scope。
- renderer 合併頂層與 unit 內結構說明；保存與渲染共用參數遮罩；路徑 helper 相容沒有 is_junction API 的 runtime。
- 兩份技能新增階段門檻、明確參數適用性、新 run 重試規則、語意紀錄契約及外部 adapter 信任界線。
- CI 與 release workflow 改為完整 pytest suite，避免 unittest discovery 遺漏 pytest-style 測試；發布版本為 0.1.24。

## 驗證

執行環境：Windows、Python 3.13。

```text
python -X utf8 -m pytest tests -q -x --basetemp=.superpowers/verified-gates
479 passed in 896.17s (0:14:56)
```

使用 Python313 的絕對 runtime 路徑執行，測試退出碼 0。最終原始輸出保存於 `.superpowers/sdd/2026-10-10-release-docs-evidence-gates/verified-suite.txt`。

另外通過：

- CI workflow 權限／發布 gate 順序測試：1 passed。
- Claude plugin.json 與 marketplace.json strict validate：success=true，errors/warnings 皆空。
- git diff --check：退出碼 0，僅 Git autocrlf 的 LF/CRLF 提示。
- 獨立程式審查及複審：未發現剩餘 Critical／Important。
- 舊／新提示詞的缺語意紀錄與缺 adapter 情境檢查：修正頂層 conclusion 及參數適用性歧義。

新增測試先確認缺持久化、缺語意門檻、過期 writer、來源 hash 不符及 unit-only 結構描述遺失的失敗，再完成修正。既有 collector 與端到端 fixtures 對齊 source_revision、DATA coverage、排除範圍及 finding code；未放寬安全契約。

## 界線與保留狀態

未執行真實 LocalDB、正式資料庫、Linux 或 Python 3.11／3.12；舊 runtime 路徑 API 透過缺 API 情境測試，完整跨平台矩陣仍由 CI 驗證。外部 executor 回報仍是信任邊界；語意紀錄不能單靠 JSON 證明審查判斷正確。

真實 adapter、多輪審查歷史及以證據驅動的 finalize 維持設計文件的後續範圍。

修改由 `codex/release-evidence-gates` 分支整合，使用 v0.1.24 發布；遠端 CI 與插件安裝結果以發布流程實際結果為準。既有未追蹤 `.pytest-release-*` 及技能 references 保留。
