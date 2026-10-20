**模型发现与调度｜v3**

首次使用、换模型／服务商／端点／分辨率／限额池时，由agent查当前资料，生成本机provider profile；用户无需猜并发或手填限频。复制技能内`provider-profile.template.json`到被忽略的本机配置，不能直接运行模板。

先读取用户已有配置和凭据环境变量名，确认实际服务商。查询官方模型文档、接口示例、当前套餐／项目限额及可读取的响应头。代理服务使用自己的配额。第三方Skill只能提示需要核实的字段，不能证明本账号有相同额度。没有账号控制台信息时，明确记为未知；不要求用户为普通制作先查一遍技术参数。

记录精确模型ID、同步或异步、端点、ratio与size规则、参考参数和编辑能力、返回字段、费用权限、限额池作用域、RPM／图片数／日额度／在途上限。资料有日期、链接、具体支持的设置、未知项和选择理由，设置合理复核日。价格或免费权限不明且用户限定免费时，停止消耗而不是换付费服务。

`research.applies_to`必须逐字匹配profile中的`provider/model/base_url/resolution/quota_pool`。改变这些字段后旧研究不能通过校验，需重新查阅并写入适用对象。`checked_on`、`recheck_after`使用记录的时区偏移；字段变化、400不兼容、429或权限变化应提前复核。

```powershell
python <技能绝对路径>/scripts/comic.py v3 profile-check provider-profile.local.json
```

该命令只校验资料完整性，不会上网替agent搜索，也不证明配额、免费权限或视觉能力已实测。查阅与选择由agent完成，脚本执行已经确定的配置。

当前实现支持：Agnes同步协议、可配置Images兼容JSON协议、multipart文件编辑、配置式异步提交／查询。其他多模态聊天或厂商专有协议应按官方说明增加适配，并以模拟响应和获授权实测验证；不能只改模型名字就宣布支持。

同步Agnes使用`size`档位＋`ratio`，参考图放到`extra_body.image`；不能把它的字段规则施加于所有兼容接口。compatible协议用`capabilities.size_by_ratio`写明已核实的尺寸映射，返回字段路径可配置。异步协议配置`task_id_path/poll_url_path/status_path/success_states/failure_states/poll_hosts`与图像返回路径；查询凭据只发到核验过的域名，图片下载不携带API认证。

兼容JSON编辑协议可配置`protocol.edit_path`，有参考图时发送到同服务该端点；无参考资产生成仍走`submit_path`。`reference_field`指定字段，`reference_format`可选`data_uri_list`或`url_object_list`，后者将每张本地PNG编码为`{"url":"data:image/png;base64,..."}`。必须实测服务是否接受Data URI；只接受公网URL或multipart的服务需另外适配，不能因模型在列表里就宣称已验证参考图编辑。真实502应记录为接口失败，不能凭营销目录声称已支持。

`url_object_list`可用`reference_object_field:image_url`指定对象字段；`image_url_parts`编码为标准type/image_url嵌套对象，仍需核验真实协议。使用`encoding:multipart_edit`时，应配`reference_format:data_uri_list`与顶层`reference_field:image`，执行器将记录的PNG转为文件上传，`multipart_image_field`默认`image[]`。其他参数为表单字段，禁止自行写Content-Type丢失boundary。无参考的资产生成仍发送JSON。island的本次gpt-image-2.5实测JSON编辑返回400，最简文生图与multipart参考编辑成功；并非所有兼容服务都支持同样格式。

串行／并行和请求间隔分别设置。调度器同时约束滚动RPM、起始间隔、在途数、每日提交预算。日界支持明确的UTC小时；需要夏令时或其他日界语义的服务，应先扩展适配，不能误用UTC表。每次生成一个输出，所有失败和重试均计入图片提交预算，查询次数单独记录。

使用共同的`runtime.state_file`共享同一额度池，默认`runs/.cache/v3-scheduler.sqlite3`。同一账号／项目的多个Key或同服务官方备用域名如共享限额，使用同一`quota_pool`。本机SQLite事务控制跨进程并发；其他设备的流量仍需依赖服务响应和账号信息，不声称本地记录等于全账号实时余额。

人物参考是角色画面的强制输入：先生成或导入已有图，实际看图，写`asset-review.json`绑定SHA后才制作依赖画面。每个角色版本绑定资产，执行器逐请求附带并记录实际摘要。模型资料未核验参考能力时，在消耗生成预算前停止。并发只用于已满足参考依赖的任务。

429区分RPM和总配额，遵守Retry-After；503降低负载并有界重试；401/403/402停止。提交途中的超时／断开保留unknown状态并阻止同池继续提交；已返回任务ID的异步作业续跑只查询；成功响应已保存时，下载失败也不重生图片。unknown或进程中断的sending状态应先查服务端／日志，不能为“恢复”直接删除状态库。

需要人工核查未知任务时，可在技能入口要求agent检查本机SQLite记录与控制台。当前没有一键强制清空命令，以免误释放仍在服务端执行的生成。确认任务确实终止，或取回已有图片后，才能明确记录abandoned或恢复结果，保留原提交计数。

参考图API不可用时记录错误，核验参数、认证和官方服务状态，在既定预算内排查／重试；仍失败就停止当前制作，不生成无参考替代图。首次生成错误后不再分发未启动任务；已经在途的任务保留结果。模型或服务商切换须有授权并重新核查资料。

Agnes核查入口：[国际站image2.5](https://wiki.agnes-ai.com/en/docs/agnes-image-25-flash)。2026-10-20该页面标明当前输出及参考免费；精确账号并发不能从营销页推导。本案例的串行60秒是同一配置的保守客户端策略，不是其他模型的默认值。换模型必须重查。
