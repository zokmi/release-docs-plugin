---
name: release-docs-review
description: Use when release-docs 已產出必要版更文件，需要必要語意審查、修正複審或確認舊審查報告是否仍有效。
---

# 版更文件必要審查

接收目標 repo、range 的 base／target／diff 模式，或完整有序 commit_scope JSON（每個 commit／選定 direct parent；root 的 parent 為 null），以及未提交內容納入決策與文件資料夾。清單模式逐對重讀選定差異與完整來源，不轉為含未選中間 commit 的 range；merge 必須明確選 direct parent。讀專案 AGENTS.md、CLAUDE.md 與部署慣例。重新讀 Git 實際範圍、完整 SQL／migration、ORM、設定差異與消費程式，以及必要成品；不得只沿用產出摘要或相信舊通過報告。指定 target 的內容用 `git show <解析後 SHA>:<path>`；index／working tree／untracked 分列，不冒充 target。

使用該範本的欄位作為對話審查紀錄，不寫入 05 檔案。每項記錄來源路徑、revision／工作區識別、行號或定位、成品定位、具體缺口與修正。缺少來源是待確認，不能記為「無」。不可將 hash、腳本 exit 0、Markdown 欄位存在當成正確性證明。

## 必檢項

先確認入口流程已完成範圍核對與文件產出，再做驗證與本輪審核。專案工具新產生的 SQL 也是必要來源：重讀其完整 artifact，核對来源 revision、migration 起訖／schema 基準、provider、工具版本、命令及輸出內容識別，確認未混入範圍外異動或與既有 SQL 重複執行。缺 artifact 時先依入口技能嘗試工具產生，可確認的文件問題先修正再複審。正式資料庫版本或本機基準不足只暫停 SQL 執行驗證，仍完成其他來源與成品審查；收尾分別回報文件產出、來源審查、本機執行驗證及最終審核狀態，缺必要證據不得通過。

1. 完整性：從完整 Git 範圍反查結構、資料、設定每项是否列入；ORM 是否有部署腳本；未提交內容是否有納入決策。
2. 正確性：確認 01／02 為 .sql，說明皆為 SQL 註解，無未填模板、Markdown 圍欄、遮罩佔位語句；完整部署內容須與指定引擎及工具相容，無異動僅含註解，缺 SQL artifact 必須阻擋。結構內容必須回溯 EF model／migration 差異、資料庫專案 schema compare／部署腳本，或專案指定的等價 schema artifact；核對 provider、工具版本、revision 與輸出模式。只有 ORM 類別、migration 名稱或人工推導時判為待確認／未通過。逐項對原始來源核對 SQL 方言、WHERE、完整設定鍵（含陣列索引）、值、程式使用處與實際來源優先順序；遮罩秘密。並核對每個 SQL 檔是否在與正式機資料庫引擎、主要版本及 provider 完全一致的隔離本機資料庫完成「建立／還原基準、執行完整 SQL、驗證 schema／資料／history」。正式機版本不明時必須先向使用者索取版本，暫停 SQL 執行驗證並繼續其他來源與成品審查；不能以正式資料庫執行、近似版本、lint、parser 或 dry-run 取代，缺少版本確認、執行紀錄、執行錯誤或驗證不完整時不得判定通過。
3. 相依與執行：根據實際相依核對 SQL／設定／程式的交錯順序；混合 DDL/DML 必須是同一完整執行單位且只執行一次，保留 GO、交易與 migration 工具。
4. 可驗證與可恢復：每步驗證有可查證預期條件；核對停止位置、部分成功、重跑限制、備份與回復條件。Down／交易不是安全回滾證明，不猜測資料量或執行時間。
5. 文件安全與一致性：所有秘密遮罩、文件連結實際可解析、共同範圍及執行 ID 一致；保留已有人工簽名／執行紀錄。只有空白人名、時間、簽核欄與「未執行」的範本列是占位，不算已執行。已有實際紀錄時另建 `_v2`／下一空閒版本並記取代理由。

每次建立或更新必要文件（含修正、04 狀態或 fallback）之前，必須先遵循簽核保留規則選定最終版本目錄，再立即執行共用唯讀 guard：

```text
python <插件根>/skills/release-docs/scripts/validate_output_paths.py --repo <repo> --documents <最終版本目錄>
```

拒絕越界目錄、具名成品 symlink（含 repo 內別名）、非一般檔案、`st_nlink > 1` hard links。失敗只在對話報告並停止寫入，不能寫 05 待確認到被拒絕位置。fingerprint 也使用同一 guard，但不能拿生成後的檢查取代寫入前 preflight。

## 判定與複審

有設定異動時，03 必須直接提供調整後的 fenced json 範例（純量亦適用）；核對可解析性、實際鍵、父層、型別／陣列、對應設定 ID 與修改位置、非正式值標示及敏感值遮罩。只有文字範例或模板示意鍵不能算完成，先修正再複審；來源結構不足則待確認。

03 的每個設定 ID 另核對參數用途與調整原因、預期型別／格式／限制、資料範例及實際修改位置是否齊全並有來源依據。範例須標「格式示例，非正式值」，與正式值分列且無秘密；實際位置須對應有效 provider 的環境、服務、檔案完整鍵或平台／環境變數／secret 鍵，不能只列 repo 來源路徑。刪除／改名需列預期狀態及相應位置。缺可確認欄位先修正再複審；缺必要證據列待確認，不得通過。

第3至5項亦須核對04的簡潔分支收尾欄位：部署 SHA 驗證、回合併／PR 條件、tag 對應 SHA、分支保留／清理條件、來源與負責人。逐步比對專案慣例；不得猜分支名稱或合併策略，不得將未執行記為完成。

狀態只用「通過」「待確認」「未通過」。漏必跑 SQL、混合腳本重複執行、錯誤鍵／順序／部署／回復指令、敏感值外洩屬阻擋，判未通過；必要正式值或來源不足判待確認。必檢完成且無未解決事項才可通過。可證實問題先修正再複審受影響項及四份文件一致性，最多三輪；仍有缺口就交付明確缺口和所需資訊，不降低標準。文件通過不代表資料庫測試、正式驗證、人工簽核或已執行。

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

審查完成先再次執行並比較開始 snapshot：若來源識別（range: base、target、diff_mode；清單: commit_scope 的每一對 SHA 與順序；兩者皆比較 committed、working_tree）改變，丟棄本輪结論重新讀來源；成品更改則重新核對更改內容。保存完成語意審查時的 snapshot 作為「已審查 snapshot」。先把最終審查狀態與報告連結寫入 04，再計算最終 snapshot；寫入或接受 05 前，必須再次將最終 snapshot 與已審查 snapshot 的來源識別逐項對比：range 的 base、target、diff_mode，或清單的完整有序 commit_scope；以及 committed、working_tree。任何來源識別不符都丟棄該輪結論並重新審查，不能將新來源 snapshot 直接存成通過證據。這段期間成品只允許已核對的 04 狀態／報告連結更新；其他成品變動需重新語意審查。確認一致後才把最終 snapshot 原封不動存入 05。報告本身被排除，寫 05 不會循環失效；必備成品及已存在的資料 SQL 不得是 symlink，包括指向 repo 內其他檔案的報告別名。

交付對話審查結果時，重算同參數 snapshot，比較 `fingerprint`；不符代表舊報告失效，重新語意審查。相符只表示證據內容未變，仍需確認對話回報包含各項審查證據及無未解決事項。摘要同步狀態與阻擋事項。
