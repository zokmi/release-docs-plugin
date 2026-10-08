---
name: release-docs-review
description: Use when release-docs 已產出四份版更文件，需要必要語意審查、修正複審或確認舊審查報告是否仍有效。
---

# 版更文件必要審查

接收目標 repo、range 的 base／target／diff 模式，或完整有序 commit_scope JSON（每個 commit／選定 direct parent；root 的 parent 為 null），以及未提交內容納入決策與文件資料夾。清單模式逐對重讀選定差異與完整來源，不轉為含未選中間 commit 的 range；merge 必須明確選 direct parent。讀專案 AGENTS.md、CLAUDE.md 與部署慣例。重新讀 Git 實際範圍、完整 SQL／migration、ORM、設定差異與消費程式，以及四份成品；不得只沿用產出摘要或相信舊通過報告。指定 target 的內容用 `git show <解析後 SHA>:<path>`；index／working tree／untracked 分列，不冒充 target。

使用 [審查報告範本](../../assets/05_版更審查報告.md)。每項記錄來源路徑、revision／工作區識別、行號或定位、成品定位、具體缺口與修正。缺少來源是待確認，不能記為「無」。不可將 hash、腳本 exit 0、Markdown 欄位存在當成正確性證明。

## 必檢項

1. 完整性：從完整 Git 範圍反查結構、資料、設定每项是否列入；ORM 是否有部署腳本；未提交內容是否有納入決策。
2. 正確性：逐項對原始來源核對 SQL 方言、WHERE、完整設定鍵（含陣列索引）、值、程式使用處與實際來源優先順序；遮罩秘密。
3. 相依與執行：根據實際相依核對 SQL／設定／程式的交錯順序；混合 DDL/DML 必須是同一完整執行單位且只執行一次，保留 GO、交易與 migration 工具。
4. 可驗證與可恢復：每步驗證有可查證預期條件；核對停止位置、部分成功、重跑限制、備份與回復條件。Down／交易不是安全回滾證明，不猜測資料量或執行時間。
5. 文件安全與一致性：所有秘密遮罩、文件連結實際可解析、共同範圍及執行 ID 一致；保留已有人工簽名／執行紀錄。只有空白人名、時間、簽核欄與「未執行」的範本列是占位，不算已執行。已有實際紀錄時另建 `_v2`／下一空閒版本並記取代理由。

每次建立或更新四份文件及第五報告（含修正、04 狀態或 fallback）之前，必須先遵循簽核保留規則選定最終版本目錄，再立即執行共用唯讀 guard：

```text
python <插件根>/skills/release-docs/scripts/validate_output_paths.py --repo <repo> --documents <最終版本目錄>
```

拒絕越界目錄、具名成品 symlink（含 repo 內別名）、非一般檔案、`st_nlink > 1` hard links。失敗只在對話報告並停止寫入，不能寫 05 待確認到被拒絕位置。fingerprint 也使用同一 guard，但不能拿生成後的檢查取代寫入前 preflight。

## 判定與複審

狀態只用「通過」「待確認」「未通過」。漏必跑 SQL、混合腳本重複執行、錯誤鍵／順序／部署／回復指令、敏感值外洩屬阻擋，判未通過；必要正式值或來源不足判待確認。必檢完成且無未解決事項才可通過。可證實問題先修正再複審受影響項及四份文件一致性，最多三輪；仍有缺口就交付明確缺口和所需資訊，不降低標準。文件通過不代表資料庫測試、正式驗證、人工簽核或已執行。

## 證據失效識別

每輪開始先執行入口技能內的 `scripts/review_fingerprint.py`：

```sh
python <插件根>/skills/release-docs/scripts/review_fingerprint.py --repo <repo> --documents <repo/docs/日期_識別> --base <base> --target <target> --diff-mode two-dot
```

range 模式依原輸入選 two-dot 或 three-dot，保持既有 CLI。清單模式改用以下互斥介面，不得同時給 --base、--target 或 --diff-mode：

```text
python <插件根>/skills/release-docs/scripts/review_fingerprint.py --repo <repo> --documents <repo/docs/日期_識別> --commit-scope <JSON檔>
```

JSON 檔是非空有序清單，例如 `[{"commit":"<A>","parent":"<A的direct parent>"},{"commit":"<C>","parent":"<C的direct parent>"}]`；root 使用 JSON null。腳本解析全部 revision 為 SHA、验证 direct parent、按順序记录 `commit_scope`，逐對識別前後 source tree、diff status 與 content。清單 snapshot 不含虛構 base／target／diff_mode。A、C 的差異不包括 B；完整樹仍識別其依賴內容。JSON 不含原文。四份文件 raw bytes 各自 SHA-256；已提交範圍和 staged／unstaged／untracked 分別識別。只排除此資料夾的精確五份成品，docs 其他來源仍納入。路徑越界、缺文件或證據不可讀即停止；路徑被 guard 拒絕時只在對話記待確認，不寫報告。

審查完成先再次執行並比較開始 snapshot：若來源識別（range: base、target、diff_mode；清單: commit_scope 的每一對 SHA 與順序；兩者皆比較 committed、working_tree）改變，丟棄本輪结論重新讀來源；成品更改則重新核對更改內容。保存完成語意審查時的 snapshot 作為「已審查 snapshot」。先把最終審查狀態與報告連結寫入 04，再計算最終 snapshot；寫入或接受 05 前，必須再次將最終 snapshot 與已審查 snapshot 的來源識別逐項對比：range 的 base、target、diff_mode，或清單的完整有序 commit_scope；以及 committed、working_tree。任何來源識別不符都丟棄該輪結論並重新審查，不能將新來源 snapshot 直接存成通過證據。這段期間成品只允許已核對的 04 狀態／報告連結更新；其他成品變動需重新語意審查。確認一致後才把最終 snapshot 原封不動存入 05。報告本身被排除，寫 05 不會循環失效；五個具名成品不得是 symlink，包括指向 repo 內其他檔案的報告別名。

交付或再次使用通過報告時，重算同參數 snapshot，比較 `fingerprint`；不符代表舊報告失效，重新語意審查。相符只表示證據內容未變，仍需確認報告確有五項審查證據及無未解決事項。摘要同步狀態與阻擋事項。
