# 知乎故事 CPA 漫画图集 Skills v3.3

输入准确推广关键词和小说／推文，agent完成改编、分镜、模型资料核验、生图、气泡排字和实际看图验收，输出按顺序上传的漫画图片ZIP。

v3.3新增Q版／非Q版选择，首次制作询问缺少的风格、API连接地址、模型名和Key配置，已有信息不重复索取；凭据只留本机。移除了正文提示词中写死的Q版比例，人物参考与正文共享选择。新增[分步工作卡与任务提示](skills/zhihu-comic-cpa/references/agent-workflow-v33.md)和简化分镜编译器：agent每批只写最多10页剧情、人物和对白，程序补齐ID、人物参考绑定、布局和保护区初稿，减轻结构化输出负担。实际看图仍是必需步骤，不保证所有模型达到相同画质。

社媒推广采用[长图集阅读规划](skills/zhihu-comic-cpa/references/reading-pacing.md)：默认60–100张，正文足够时优先100张，按原文、用户数量和当前渠道限制调整。已通过浏览器翻页计数核实用户提供的三个参考案例均100张，见[案例记录](docs/research/2026-10-21-douyin-long-album.md)；CTA位置受登录弹窗影响未核实。`v3 pacing --plan plan.json --out pacing-report.json`记录张数、字数、格数、速度假设和首个强CTA前时长；估算不代表留存或转化，不用复制内容凑数。

v3.1强制角色参考图实际入参，agent内部审阅后自动完成整套，不等待试样风格确认。每页格数、面积与阅读顺序按分镜决定，提供生图前布局预览；示例为1、3、4格，不把任何一种布局作为全局默认。三条生成路线继续可选：完整漫画页、无字整页后排字、独立分格后排字。[本轮修订与流程图](docs/plans/2026-10-20-skills-v3.1-plan.md)记录需求、实现与验证边界。

## 在 Codex 中使用

将 `skills/zhihu-comic-cpa` 整个目录放入 `~/.codex/skills/` 或项目的 `.agents/skills/`。在用户选择的Python环境安装该目录的 `requirements.txt`。Windows自动寻找微软雅黑，Linux可安装Noto Sans CJK；也可设置 `COMIC_FONT`。

> 使用 $zhihu-comic-cpa。关键词：雨夜来信。正文：……。使用我配置的生图模型，制作小红书故事漫画，给我图片ZIP。

agent通读故事并编写分镜；独立脚本接收其已完成的计划。只给标题和正文的自然语言流程由agent完成，不要求用户手写JSON。技能入口：[SKILL.md](skills/zhihu-comic-cpa/SKILL.md)。

风格、连接和凭据的询问规则见[输入与风格](skills/zhihu-comic-cpa/references/intake-style.md)。离线初始化示例（地址和模型需替换为用户实际选择，不把Key作为命令参数）：

```powershell
python skills/zhihu-comic-cpa/scripts/comic.py v3 styles
python skills/zhihu-comic-cpa/scripts/comic.py v3 init --title "准确标题" --style standard --base-url https://provider.example/v1 --model EXACT_MODEL_ID --out runs/new-story
```

`standard`为非Q版、`chibi`为Q版，`custom`需同时给`--style-prompt`。初始化只产生待填写简报和待核验模型档案，不联网、不保存Key、不覆盖已有目录。简化编译的3页原创技术示例可直接检查：

```powershell
python skills/zhihu-comic-cpa/scripts/comic.py v3 compile --brief skills/zhihu-comic-cpa/references/authoring-brief.example.json --beats skills/zhihu-comic-cpa/references/authoring-beats.example.json --story examples/story.txt --out runs/authoring-demo/plan.json
```

示例是`style_pilot`，不是60–100张推广成品。正式任务按工作卡在独立故事目录编写简报与分批分镜，导入参考时把计划放在简报同目录。

## 更换模型，由 agent 查资料

没有适用于所有服务的默认并发数。先查实际服务商的当前官方文档、可读取的账号／项目限额及响应信息，再填写本机 `provider-profile.local.json`。模板位于 [provider-profile.template.json](skills/zhihu-comic-cpa/provider-profile.template.json)，不能原样运行。

资料记录精确模型、端点、分辨率、同步／异步协议、参考参数、返回字段、费用权限、共享限额池、并发、起始间隔、RPM与日额度，以及来源、查阅和复核日期。改变模型、端点、分辨率或限额池后，旧资料绑定不能通过校验。细节见 [模型发现与调度](skills/zhihu-comic-cpa/references/model-discovery.md)。

Agnes 2.5本次真实试样按用户要求串行，读取等待240秒、总等待上限360秒。约60秒起始间隔是该次任务的保守策略，不是其他模型的全局默认。当前免费价格以[国际站模型文档](https://wiki.agnes-ai.com/en/docs/agnes-image-25-flash)和实际账号为准；不自动订阅或切付费服务。

## 制作和导出

```powershell
python -m pip install -r requirements.txt
python skills/zhihu-comic-cpa/scripts/comic.py v3 schema
python skills/zhihu-comic-cpa/scripts/comic.py v3 profile-check provider-profile.local.json
python skills/zhihu-comic-cpa/scripts/comic.py v3 layout --story story.txt --plan plan.json --out runs/story-v3/layouts
python skills/zhihu-comic-cpa/scripts/comic.py v3 run --story story.txt --plan plan.json --profile provider-profile.local.json --out runs/story-v3 --stage assets --max-attempts 12
python skills/zhihu-comic-cpa/scripts/comic.py v3 run --story story.txt --plan plan.json --profile provider-profile.local.json --out runs/story-v3 --max-attempts 12
```

真实Key仅从环境变量或本机 `.env` 读取。12是试样的提交次数示例预算，包含参考、失败和重试；大图集按实际规模设置。默认共享本机SQLite状态库，串并行、起始间隔、滚动RPM和在途任务分别控制；调度库与成功响应跨重启保留。不要删除未知提交记录来绕过等待。

每个出镜角色版本必须绑定 `reference_assets`，执行器自动将对应参考附带到该角色出镜的每次请求。先运行 `--stage assets`，agent实际看图后保存绑定SHA的资产审查并自动续作，无需用户确认。支持导入已有 `local_path`；参考不支持、未审阅或通道失败时停止，禁止无参考降级。`--pages page-a,page-b`只处理指定页；纯排字修订复用原画，改变模型、画幅、提示或参考图则使用新缓存。

每页提供 `layout.rationale/reading_order`，先检查布局预览再生成；执行器拒绝分格重叠和无理由重复整套几何。布局多样性服从剧情，不要求每套都包含1、3、4格，也不强行排除两格。

逐页检查剧情、角色、表演、准确台词、气泡指向和手机可读性，按 [制作与验收](skills/zhihu-comic-cpa/references/production-v3.md) 保存 `visual-review.json`。修改图片后旧验收失效。页面缺失或未审时，不能导出成已验收图集。

```powershell
python skills/zhihu-comic-cpa/scripts/comic.py v3 export runs/story-v3
```

导出还核对实际参考数量、角色版本与资产摘要；`--review-copy`也不能绕过人物参考要求。输出纯图片ZIP与独立制作资料ZIP，后者包含实际参考图及可移植分镜。固定白名单排除原文全文、凭据、模型配置、调度库、缓存和本机绝对参考路径。MOCK／REVIEW／试制包明确标识，不冒充完整已审图集。

## 离线验证与旧版兼容

```powershell
python skills/zhihu-comic-cpa/scripts/comic.py v3 run --story examples/story.txt --plan skills/zhihu-comic-cpa/references/plan-v3.example.json --profile examples/offline-profile.json --out runs/offline-v3 --mock
python -m unittest discover -s tests -v
```

MOCK只检查排版、顺序与打包，图像和包名显式标注，不会在远程接口失败后自动启用。图像语义质量必须实际看图，不能由测试通过代替。

旧版入口仅保留历史兼容，不能用来绕过当前人物参考与分镜要求。`v3 migrate-plan --plan old.json --story story.txt --out migrated.json`会建立待生成人物参考任务，agent仍需重新导演。v3.0无参考试样不能作为v3.1成品，需要补参考绑定并重做角色画面。

## 研究与版本

[方案与研究归档](docs/README.md)保存v3提案和原始来源。参考包括novel-comic-promo、baoyu-skills、Novel-to-Comic Studio、Agent Mangaka Forge、storyboard-generator及ARIS。设计方法经筛选重新实现；没有直接复制其故事或图片。其他协议仅在完成适配并验证后宣称支持；模拟异步测试不代表已实测第二家生图模型。

本项目代码和原创示例采用MIT许可证。用户小说、第三方图片和平台素材保留原权利。真实小说及试样默认仅保存在本机，不提交公共仓库。只使用有权改编的素材，准确关键词和推广入口以实际任务为准；图集制作不自动登录右豹、领取任务或发帖，不承诺流量和佣金。
