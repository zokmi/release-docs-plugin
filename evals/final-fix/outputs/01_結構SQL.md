# 結構 SQL — AC
- 產出日期／時區：2026-10-08／Asia/Taipei
- 識別：AC（原識別與安全識別相同）
- 範圍類型：commit-list；range base／target／diff_mode 不適用。
- 完整有序 commit_scope（兩份技能傳遞相同 JSON）：

```json
[
  {
    "commit": "b60b8948fdebc17c57520ed2375b4e506228bb17",
    "parent": "38be64ded493bb16e35780d53d7d9aef29493f14"
  },
  {
    "commit": "3d8543e0a460029484e81f01f6758f67900d11a1",
    "parent": "cfe2cc857464524fc9e761d040e56dc436fd8cd5"
  }
]
```

- staged／unstaged／untracked 來源：無；工作區不納入（成品不算部署來源）。
- 完整盤點：README.md:1–6、01_a.sql:1、02_b.sql:1、03_c.sql:1；無 AGENTS.md／CLAUDE.md／應用／ORM／migration／設定。
- 保留既有簽核：本次新目錄，無舊文件、簽名或執行紀錄。

SQL-001：b60b8948fdebc17c57520ed2375b4e506228bb17:01_a.sql:1 新增 public.final_fix_a，id integer PRIMARY KEY（PostgreSQL 主鍵使 id 非 NULL），無 default 或其他欄位。來源完整保留，不產生可執行 SQL。

SQL-002 需要此表，故 SQL-001 先執行。執行前確認表不存在；已存在即停止核對，不能直接重跑。執行後核對 public schema、單一 id integer 欄位、非 NULL、唯一主鍵；預期來自此情境的原始 SQL，不能套用其他 fixture 的 PK／NULL 預期。

只有單行 DDL，沒有 BEGIN／COMMIT；工具 README.md:2 為 psql --set ON_ERROR_STOP=1 --file 01_a.sql。錯誤即停止 SQL-002。資料庫尚未測試；備份、環境形狀及恢復證據待確認。不得猜測 DROP 回復或執行時間。

B=cfe2cc857464524fc9e761d040e56dc436fd8cd5:02_b.sql:1 建立獨立 final_fix_b，為未選中間 commit，不納入 SQL-001 或此次執行。完整 source tree 可見 B，不表示 B 屬選定差異。

更新紀錄：2026-10-08 首次建立，未執行。
