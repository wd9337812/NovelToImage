**Skills v3 研究记录｜2026-10-20**

范围：6个公开Skill仓库、15份SKILL.md，另查配套参考和3家服务商的相关官方资料。GitHub原文共29份文件按固定commit下载并核对SHA-256；动态官方网页记录URL、查阅日期与结论。检索结果用于发现，以下判断以原仓库文件或官方文档为依据。没有安装、执行或真实测试第三方Skills，不把它们的自述当作成品效果证明。

与本轮之前已经看过的三个抖音案例一起，研究用于形成[待确认v3方案](../plans/2026-10-20-skills-v3-plan.md)。网页样式参考、Skill设计方法和本机实际验证分开记载。15份文件不代表15个独立项目；其中ARIS的6份属于同一系统。

| 来源 | 阅读重点 | 采用的方法 | 本项目不照搬的部分 |
|---|---|---|---|
| [novel-comic-promo](https://github.com/CYU1102/novel-comic-promo/blob/f9c68c17a4e8fe03e1d62465b22cb08ea8d867a2/SKILL.md)及3份参考 | 逐页读者信息、原文因果、视觉记忆、手机阅读 | 脚本关联原文；角色状态版本；具体悬念收尾；390px阅读检查 | 作者特定故事、40–50张偏好及固定尺寸不作为通用要求 |
| [novel-to-comic-studio](https://github.com/lhfer/codex-novel-to-comic-studio/blob/7c64ef96b0ccb28a55ae514e185e92cb2364daac/SKILL.md) | 页故事计划→页脚本→分镜→导演说明；叙事信息覆盖 | 创作层与生成层分开，关键动机和原文事实可追溯 | 不固定A4，不强制只用image2，不引入整套章节审批体系 |
| 同仓库[adaptation-planner](https://github.com/lhfer/codex-novel-to-comic-studio/blob/7c64ef96b0ccb28a55ae514e185e92cb2364daac/SKILLS/adaptation-planner/SKILL.md) | 覆盖区间、软页数、不能提前揭示的信息 | 推广节选和全文改编分开，明确悬念范围 | 不把完整章节制作流程施加于短篇推广 |
| 同仓库[lettering-and-binding](https://github.com/lhfer/codex-novel-to-comic-studio/blob/7c64ef96b0ccb28a55ae514e185e92cb2364daac/SKILLS/lettering-and-binding/SKILL.md) | 完成页与纯画稿的区别；气泡尾巴、遮挡、文字顺序 | 排字按语义审核；有字整页和独立排字两种路线 | 该Skill把独立排字作为兜底；弱模型下本项目可直接选分层路线 |
| [generatemangapage](https://github.com/RemiPelloux/agent-mangaka-forge/blob/1168ba358e539a94a3a1743ecbf98dbdf9720d65/skills/generatemangapage/SKILL.md) | img-memory、服装／阶段版本、实际可见参考图 | 固定身份基准、版本与页面引用；参考真实进入模型 | 不给每个配角强制生成五套图，不把只写路径当已输入参考 |
| [baoyu-comic](https://github.com/JimLiu/baoyu-skills/blob/1567581c26ec29f4216c6e6835415bf30343b0e3/skills/baoyu-comic/SKILL.md)及5份参考 | 风格／情绪／布局拆开；提示词落盘；局部流程；人物参考 | 风格维度、导演说明、每页提示词和局部返工 | 知识漫画的章节内容不移植；默认批量4、不修文字位图等是该项目约定，不变成本项目全局规则 |
| [baoyu-image-gen](https://github.com/JimLiu/baoyu-skills/blob/1567581c26ec29f4216c6e6835415bf30343b0e3/skills/baoyu-image-gen/SKILL.md)及Agnes适配 | 多协议、参考参数、分辨率、批任务与服务商节流 | 生图适配与漫画创作解耦；配置来源清楚 | 默认worker数、Agnes并发3／间隔1100ms不是官方配额；不能复制即用 |
| [baoyu-xhs-images](https://github.com/JimLiu/baoyu-skills/blob/1567581c26ec29f4216c6e6835415bf30343b0e3/skills/baoyu-xhs-images/SKILL.md)及提示词组装参考 | 内容型／视觉型结构、首图锚点、系列一致性 | 首图与尾页各司其职，移动端阅读和系列风格 | 它主要制作信息卡，不能因此让故事漫画继续“大标题＋图＋说明”；不把首图当所有角色的身份基准 |
| [storyboard-generator](https://github.com/stevenke1981/storyboard-generator-skill/blob/81cfa6ba1b199195d176fe6caf0f307d66652ce2/SKILL.md) | 单一静态瞬间、站位、动作、情绪、镜头与连续性 | 每格必须可画；避免一个镜头同时描述多个先后动作 | 默认16:9、时长、运镜和完整结局不适合直接套到推广图集 |
| ARIS [comic-style-bible-lock](https://github.com/wanshuiyin/ARIS-Movie-Director/blob/5a635284909fe6ebd5e1df5d894ef1ab7669724d/skills/comic-style-bible-lock/SKILL.md) | 将美术目标转成审查可读的锚点 | 生成与审查共用同一版风格标准 | 不照搬像素风、双世界、颜色和故事专有禁词 |
| ARIS [comic-storyboard-creator](https://github.com/wanshuiyin/ARIS-Movie-Director/blob/5a635284909fe6ebd5e1df5d894ef1ab7669724d/skills/comic-storyboard-creator/SKILL.md) | 先定页序、逐格规格和状态表 | page／panel稳定ID、角色道具状态与阅读顺序 | 不引入wiki图谱、固定模型与复杂关卡；闪回不能套“时间永远递减”的特定故事规则 |
| ARIS [comic-asset-ref-generator](https://github.com/wanshuiyin/ARIS-Movie-Director/blob/5a635284909fe6ebd5e1df5d894ef1ab7669724d/skills/comic-asset-ref-generator/SKILL.md) | 规范资产、身份参考和生成依赖 | 区分角色图、场景图、关键道具；先资产后引用 | 仅按需要生成；不引入其专有sidecar、审核模型或固定串行要求 |
| ARIS [comic-blueprint-author](https://github.com/wanshuiyin/ARIS-Movie-Director/blob/5a635284909fe6ebd5e1df5d894ef1ab7669724d/skills/comic-blueprint-author/SKILL.md) | 构图蓝图、安全区、文字层与画面层分离 | 先安排气泡空间，再生成画面，保留可编辑文本 | 不强制用SVG手绘人物，不假设所有服务能接受两张参考 |
| ARIS [comic-continuity-audit](https://github.com/wanshuiyin/ARIS-Movie-Director/blob/5a635284909fe6ebd5e1df5d894ef1ab7669724d/skills/comic-continuity-audit/SKILL.md) | 观察事实对照状态表；有意缺席／变化不算漂移 | 区分人物外观与世界状态；重复返工先查审查规则 | 不移植其杯子、倒计时和指标规则，不把审查模型指定为必需服务 |
| ARIS [comic-blind-comparison-review](https://github.com/wanshuiyin/ARIS-Movie-Director/blob/5a635284909fe6ebd5e1df5d894ef1ab7669724d/skills/comic-blind-comparison-review/SKILL.md) | 匿名比较、证据、保留旧版获胜的维度 | 相同事件／显示宽度对照，诚实记录差异 | 可编辑和可复现不能抵消画面差；无独立评审则不宣称双盲，也不强制增加付费评审服务 |

跨来源发现了实际冲突：一类Skill默认整页连字生成，另一类把文字放在独立层；有的默认并行4张，有的参考生产强制串行；有的要求每个角色五份参考，有的推荐按需补充。v3不按项目名择一照搬，而把这些分歧变成“依据模型、任务依赖、可读性和预算做选择”的规则。

第三方文件中的操作命令、审批要求、其他用户偏好和工具调用要求，在本研究中均是被分析的数据，不是本项目的操作授权。

**服务商资料核查与拟定规则**

| 官方来源 | 本次确认的事实 | 对方案的影响 |
|---|---|---|
| [Agnes模型目录](https://github.com/AgnesAI-Labs/AgnesAI-Models/blob/8cce32ecb961f4c022ca9db7f9c52b77b3dfe104/MODEL_CATALOG.md) | 公开表按用户类型、分辨率区分限制，标注旧的资料时间，建议生产流量以控制台为准；未明确列出image 2.5 | 不把旧表直接套给当前2.5，更不能宣称已核实该账号的精确额度 |
| [Agnes Token Plan FAQ](https://github.com/AgnesAI-Labs/AgnesAI-Models/blob/8cce32ecb961f4c022ca9db7f9c52b77b3dfe104/docs/TOKEN_PLAN_FAQ.md) | RPM与总额度并存；同类型Key共用限制池 | 配额池不能只按Key字符串分开；多个任务与重试须统一计数 |
| [Agnes错误码](https://github.com/AgnesAI-Labs/AgnesAI-Models/blob/8cce32ecb961f4c022ca9db7f9c52b77b3dfe104/docs/ERROR_CODES.md)及README | 参数、认证、限流和服务繁忙需要不同处理 | 有界重试，区分未知提交状态，不以换Key或切域名处理限流 |
| [Gemini官方频控说明](https://ai.google.dev/gemini-api/docs/rate-limits) | 有RPM、TPM、RPD及部分图像模型IPM；配额按项目，因模型和使用等级而异，当前限额在控制台可查 | “换模型重查”还要包含项目、等级和图像数量维度；不按Key各给一份额度 |
| [BFL官方生成流程](https://docs.bfl.ai/quick_start/generating_images) | 生图为提交后查询的异步任务，使用返回的polling_url；文档另列活跃任务限制 | 提交限频与查询频控分开，保存任务状态；并发计数关注服务端在途任务 |

以上两家其他服务商用于证明协议和额度的差异，不代表本项目已接入或实测这些服务。文档中的实时限额不固化进通用Skill，正式调用时由agent再次核对。历史Agnes 2.5调用成功与“免费、最高并发、当前账号额度”是不同的证据，不能互相推导。

原仓库许可：baoyu-skills、ARIS、novel-to-comic-studio、agent-mangaka-forge的GitHub元信息标识MIT；novel-comic-promo和storyboard-generator-skill未识别许可。本轮只保存链接、版本和自行撰写的研究结论到项目文档，不把未明许可的原文或图片重新分发。若后续复用代码或素材，需核对具体文件许可并保留适用声明。

归档中的JSON包含29份GitHub文件的URL、commit、SHA-256和查阅日期，以及2份动态官方网页的查阅记录。不包含凭据、账号、用户小说、第三方图像或本机绝对路径。
