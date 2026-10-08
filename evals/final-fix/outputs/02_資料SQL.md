# 資料 SQL — AC
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

SQL-002：3d8543e0a460029484e81f01f6758f67900d11a1:03_c.sql:1，完整單行 INSERT INTO public.final_fix_a (id) VALUES (7)。固定新增一列 id=7，未修改或刪除既有列；id 唯一性由 SQL-001 保證，不影響 B 表。

前置為 SQL-001 表就緒且 id=7 不存在，已有此列即停止，不把它視為已部署。執行後核對恰一列 id=7；這是此情境 seed 的預期，無通用筆數假設。無明確交易或可重跑保護，重跑會碰主鍵；錯誤停止，不自動 DELETE 或假設回滾。工具 README.md:2 為 psql --set ON_ERROR_STOP=1 --file 03_c.sql。

正式資料／併行寫入／備份恢復／UAT 尚未確認。没有拆分來源或執行資料庫 SQL。

更新紀錄：2026-10-08 首次建立，未執行。
