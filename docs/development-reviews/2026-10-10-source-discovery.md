# 來源取得流程修正紀錄

## 證據與根因

依使用者分享對話 https://chatgpt.com/s/cx_6aca21c7050c8191b5871a5e058ab840 的可見正文：已確認 scope、正式 schema baseline，且盤點出 20 SQL／7 verify／target-only Database Project；代理在 analyzer 阻擋後只新增 analysis 與 remediation 文件，仍要求補 metadata／四輪預期。這是分享中的回報，未在原專案重現 SQL 執行。

本機程式核對：collect_release_evidence 只取得 Git 路徑證據；analyze_release_units 接受 execution_units descriptor 或 release-unit 標記，blocked 時清空 units；produce_release 核對 source_path 的 pinned Git bytes，未接受任意 run 內產製 SQL。

根因是缺少來源分析到工具輸入的必要步驟；原有輸入驗證被誤用為停止資訊取得的理由。SQL 本身交易衝突與產物輸入介面限制是另外的 blocker，不能靠 metadata 修補。

## 修正與驗證

- 新增 source-discovery.md：決策重用、工具探測、target-only baseline 路徑、external descriptors、fixture／預期／參數推導、重跑資格檢查及最小缺失回報。
- 產製與審查技能均引用該流程，保留來源／排除／交易／四輪證據門檻。
- RED：獨立壓力測試指出舊規範仍允許只寫報告後要求使用者補 metadata。
- GREEN：同場景要求實際建立工具輸入與重跑；target-only、hazard 與 pinned source 限制未繞過，未發現重要漏洞。
- 套件檢查、相對連結檢查與 git diff --check 通過。純規範修改未重跑 Python 全套；未執行原專案 DB 測試。

這是代理執行流程規範，未新增 SSDT 建置 adapter 或自動 SQL 語意解析器；run 產製 SQL 直接接入 pinned source 的介面仍需另行設計。未發布或更新已安裝插件。
