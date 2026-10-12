# appsettings 與實際設定來源

## `02_參數異動.md` 交付結構

確認 pinned codebase diff 有參數異動時，必須產出 `02_參數異動.md`。依序包含：日期／release 與 base/target 來源範圍、安全與套用前提、業務情境與模組對照、參數區塊、部署查核，以及末尾完整脫敏 descriptor JSON array。

業務對照表欄位固定為「參數區塊、使用業務情境、使用模組／功能、主要使用者、異動影響」。各區塊列完整鍵、add/update/remove、前後值、用途與影響、可解析的階層 JSON、適用時的環境變數 `text` 範例、套用位置、reload／重啟與驗證。業務欄位依核對證據填入；未知標待確認。

設定 JSON、表格與 canonical descriptors 從同一批脫敏資料生成。陣列須保留完整 target 元素與實際容器型別，避免複製片段時刪除未變動元素；缺少容器證據時明示索引對照不能整段取代設定。數字 object key 仍是 object key。密鑰與 Bearer credential、已知秘密值均遮罩，遮罩字串不可當正式值。

自動盤點 `appsettings*.json`／`settings*.json`、canonical `Web.config`／`App.config` 與已核對 inventory；其他 `.config` 由 inventory 納入。無法解析的 runtime 設定需保留 unresolved finding，不能聲稱無異動。只有核對 base/target 與 diff 後，才可標 `parameters_applicable=false`。

比較 base/target 的完整配置與消費程式，再查本次環境變數、容器／部署設定、命令列、secret provider、其他配置檔与加载程式。Git 已提交來源与 index／working-tree 分開，刪除讀舊版，rename 保留舊路徑；不得用目前 appsettings 代替指定舊 revision。

## 鍵與差異

- 写來源檔路径、完整键路径、增加／修改／移除、舊值／新值及是否正式待填。以 .NET configuration 举例：`Notify:Enabled`、`Endpoints:0:Url`；数组逐索引保留完整路径，列顺序／長度变化，不能只寫 `Endpoints` 或把索引当物件名。缺键与 `null`、空字串、false、0 区分。
- 同键跨文件变化分别记录来源，不能合并后掩盖删除。移动／重命名键要查程式讀取是否同步，新增未使用键、删仍使用键均記风险与证據。
- 环境变数 `Endpoints__0__Url` 到 `Endpoints:0:Url` 的映射以实际 provider 证明，不假设所有语言都采用双底线。

## 預計調整說明、JSON 範例與位置

每個設定 ID 必須提供參數用途、調整原因與行為影響、預期型別／格式／單位／允許值、預期資料範例，以及實際修改位置；appsettings、環境變數、容器／部署參數、secret provider 與其他配置檔均適用。用途與限制以消費程式、驗證／綁定規則或已確認需求為證據，未知逐項列待確認，不由鍵名猜測。

來源檔案／revision／行號用於追溯，實際修改位置則列環境、專案／服務、部署檔案路徑與完整 JSON 鍵，或平台設定頁／欄位、環境變數名稱、secret 項目及鍵；兩者分列。provider 覆蓋來源檔時須標出真正生效的修改位置及映射依據。缺部署證據不能把 repo 路徑當成正式主機路徑，也不能捏造設定頁。

預期資料範例獨立於舊值／新值與正式預計值，明標「格式示例，非正式值」，型別與結構符合已核對來源；複雜物件／陣列附最小片段，保留必要父層與索引。示例資料可以使用明確標示的虛構非敏感值，但不能捏造允許值或數值限制。敏感欄位遵循下節整值遮罩，只說明類型、位置與安全填入來源，示例及指令不含真實憑證。刪除寫預期不存在及刪除位置，改名列舊／新鍵與兩端位置。範例不能當正式值或已生效的證明。

## 優先順序與套用

讀程式配置注册先后、环境名稱、配置路径、optional/reload、启动参数与实际部署 artifact。不能照框架默认顺序推定项目；后注册 provider 覆盖相同键，但数组合并、绑定与 reload 行为须依实现判读。例：先 Clear，再 AddEnvironmentVariables，再 AddJsonFile，json 对同键覆写环境值。开发 appsettings 值不是正式值；缺正式 artifact／參數／secret provider 时有效值与优先顺序列待確認。

記消費程式與影響功能、重启／reload/滚动切换方式及前后部署相依。`reloadOnChange` 不自动等同消费者实时刷新，查 Options／IOptionsMonitor／缓存／启动读取方式；证據不足不說无需重启。驗證有效鍵／來源与功能行为，通过脱敏状态、测试端点或可审计平台动作检查，不能输出 secrets 证明配置已生效。

## 敏感值

預期資料範例必須直接提供 fenced json 程式碼區塊，包括只有一個純量參數的異動；表格引用對應區塊，不能僅給文字示例。使用已確認的實際鍵、父層、陣列結構與型別。同一修改位置可合併示範，標明設定 ID 與位置；非 JSON provider 以邏輯設定 JSON 示範並另列實際環境變數／平台欄位映射。JSON 必須能解析，不含註解、省略號或模板佔位符；說明放區塊外。安全虛構值明標非正式值；未知結構／型別不得編造。敏感欄位採下述整值遮罩，不可用範例帶出秘密。

密码、token、API key、私钥、凭证、含认证参数的 URL、連線字串及內嵌账号信息都視為敏感。判断兼顾键名、值形態与上下文，不能只依 `password` regex。連線字串／credential URL 整值写 `[已遮罩]`；旧值、新值、删除值、SQL literals、日志与证據摘錄同樣適用，不留下可恢复的前后缀。键可保留，正文写正式「待填（由既有安全設定來源設定）」；不把开发凭證复制到生产。

metadata collector 不輸出值；读取实际来源的工具仍可能留下日志。在本地内存读取完整原文并只返回遮罩摘要，不把含敏感值的原始 diff/show 保存、打印或传给可记录日志的工具。无法安全取得时明确待确认与所需安全来源，不绕过遮罩。產出后检查四文件与报告无原值，也检查代码块／链接／异常文字；这个检查仅证明已知 fixture 敏感值不在文件，不能证明识别了所有未知 secrets。
