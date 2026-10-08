# appsettings 與實際設定來源

比較 base/target 的完整配置與消費程式，再查本次環境變數、容器／部署設定、命令列、secret provider、其他配置檔与加载程式。Git 已提交來源与 index／working-tree 分開，刪除讀舊版，rename 保留舊路徑；不得用目前 appsettings 代替指定舊 revision。

## 鍵與差異

- 写來源檔路径、完整键路径、增加／修改／移除、舊值／新值及是否正式待填。以 .NET configuration 举例：`Notify:Enabled`、`Endpoints:0:Url`；数组逐索引保留完整路径，列顺序／長度变化，不能只寫 `Endpoints` 或把索引当物件名。缺键与 `null`、空字串、false、0 区分。
- 同键跨文件变化分别记录来源，不能合并后掩盖删除。移动／重命名键要查程式讀取是否同步，新增未使用键、删仍使用键均記风险与证據。
- 环境变数 `Endpoints__0__Url` 到 `Endpoints:0:Url` 的映射以实际 provider 证明，不假设所有语言都采用双底线。

## 優先順序與套用

讀程式配置注册先后、环境名稱、配置路径、optional/reload、启动参数与实际部署 artifact。不能照框架默认顺序推定项目；后注册 provider 覆盖相同键，但数组合并、绑定与 reload 行为须依实现判读。例：先 Clear，再 AddEnvironmentVariables，再 AddJsonFile，json 对同键覆写环境值。开发 appsettings 值不是正式值；缺正式 artifact／參數／secret provider 时有效值与优先顺序列待確認。

記消費程式與影響功能、重启／reload/滚动切换方式及前后部署相依。`reloadOnChange` 不自动等同消费者实时刷新，查 Options／IOptionsMonitor／缓存／启动读取方式；证據不足不說无需重启。驗證有效鍵／來源与功能行为，通过脱敏状态、测试端点或可审计平台动作检查，不能输出 secrets 证明配置已生效。

## 敏感值

密码、token、API key、私钥、凭证、含认证参数的 URL、連線字串及內嵌账号信息都視為敏感。判断兼顾键名、值形態与上下文，不能只依 `password` regex。連線字串／credential URL 整值写 `[已遮罩]`；旧值、新值、删除值、SQL literals、日志与证據摘錄同樣適用，不留下可恢复的前后缀。键可保留，正文写正式「待填（由既有安全設定來源設定）」；不把开发凭證复制到生产。

metadata collector 不輸出值；读取实际来源的工具仍可能留下日志。在本地内存读取完整原文并只返回遮罩摘要，不把含敏感值的原始 diff/show 保存、打印或传给可记录日志的工具。无法安全取得时明确待确认与所需安全来源，不绕过遮罩。產出后检查四文件与报告无原值，也检查代码块／链接／异常文字；这个检查仅证明已知 fixture 敏感值不在文件，不能证明识别了所有未知 secrets。
