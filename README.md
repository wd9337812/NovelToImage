# 知乎故事 CPA 漫画图集 Skills v3

输入准确推广关键词和小说／推文，agent完成改编、分镜、模型资料核验、生图、气泡排字和实际看图验收，输出按顺序上传的漫画图片ZIP。

v3采用三条可选路线：完整漫画页、无字整页后排字、独立分格后排字。由模型能力与实际试样决定，避免把所有模型固定在“两格插画＋下方字幕”的模板里。当前实现包括可追溯分镜、角色状态、可编辑气泡、局部缓存、持久频控、同步／配置式异步续作，以及与技术校验分开的视觉验收。

## 在 Codex 中使用

将 `skills/zhihu-comic-cpa` 整个目录放入 `~/.codex/skills/` 或项目的 `.agents/skills/`。在用户选择的Python环境安装该目录的 `requirements.txt`。Windows自动寻找微软雅黑，Linux可安装Noto Sans CJK；也可设置 `COMIC_FONT`。

> 使用 $zhihu-comic-cpa。关键词：雨夜来信。正文：……。使用我配置的生图模型，制作小红书故事漫画，给我图片ZIP。

agent通读故事并编写分镜；独立脚本接收其已完成的计划。只给标题和正文的自然语言流程由agent完成，不要求用户手写JSON。技能入口：[SKILL.md](skills/zhihu-comic-cpa/SKILL.md)。

## 更换模型，由 agent 查资料

没有适用于所有服务的默认并发数。先查实际服务商的当前官方文档、可读取的账号／项目限额及响应信息，再填写本机 `provider-profile.local.json`。模板位于 [provider-profile.template.json](skills/zhihu-comic-cpa/provider-profile.template.json)，不能原样运行。

资料记录精确模型、端点、分辨率、同步／异步协议、参考参数、返回字段、费用权限、共享限额池、并发、起始间隔、RPM与日额度，以及来源、查阅和复核日期。改变模型、端点、分辨率或限额池后，旧资料绑定不能通过校验。细节见 [模型发现与调度](skills/zhihu-comic-cpa/references/model-discovery.md)。

Agnes 2.5本次真实试样按用户要求串行，读取等待240秒、总等待上限360秒。约60秒起始间隔是该次任务的保守策略，不是其他模型的全局默认。当前免费价格以[国际站模型文档](https://wiki.agnes-ai.com/en/docs/agnes-image-25-flash)和实际账号为准；不自动订阅或切付费服务。

## 制作和导出

```powershell
python -m pip install -r requirements.txt
python skills/zhihu-comic-cpa/scripts/comic.py v3 schema
python skills/zhihu-comic-cpa/scripts/comic.py v3 profile-check provider-profile.local.json
python skills/zhihu-comic-cpa/scripts/comic.py v3 run --story story.txt --plan plan.json --profile provider-profile.local.json --out runs/story-v3 --max-attempts 12
```

真实Key仅从环境变量或本机 `.env` 读取。12是试样的提交次数示例预算，包含参考、失败和重试；大图集按实际规模设置。默认共享本机SQLite状态库，串并行、起始间隔、滚动RPM和在途任务分别控制；调度库与成功响应跨重启保留。不要删除未知提交记录来绕过等待。

有角色参考时先运行 `--stage assets`，实际看图后保存绑定SHA的资产审查，再制作依赖页面。`--pages page-a,page-b`只处理指定稳定ID；改字体或台词排版可以复用无字原画。改变原画提示词、模型、画幅或实际参考图会得到新的缓存。

逐页检查剧情、角色、表演、准确台词、气泡指向和手机可读性，按 [制作与验收](skills/zhihu-comic-cpa/references/production-v3.md) 保存 `visual-review.json`。修改图片后旧验收失效。页面缺失或未审时，不能导出成已验收图集。

```powershell
python skills/zhihu-comic-cpa/scripts/comic.py v3 export runs/story-v3
```

输出纯图片ZIP与独立制作资料ZIP。`style_pilot`明确标为试样；待审导出需显式 `--review-copy`，文件带REVIEW前缀。固定白名单排除原文、凭据、模型配置、调度库和缓存。

## 离线验证与旧版兼容

```powershell
python skills/zhihu-comic-cpa/scripts/comic.py v3 run --story examples/story.txt --plan skills/zhihu-comic-cpa/references/plan-v3.example.json --profile examples/offline-profile.json --out runs/offline-v3 --mock
python -m unittest discover -s tests -v
```

MOCK只检查排版、顺序与打包，图像和包名显式标注，不会在远程接口失败后自动启用。图像语义质量必须实际看图，不能由测试通过代替。

旧版 `comic.py run --title ... --story ...`、version1计划和旧配置继续可用，历史两格字幕样式保留兼容。`v3 migrate-plan --plan old.json --story story.txt --out migrated.json`可以迁移数据；该步骤不等于已重新导演和提升画质。

## 研究与版本

[方案与研究归档](docs/README.md)保存v3提案和原始来源。参考包括novel-comic-promo、baoyu-skills、Novel-to-Comic Studio、Agent Mangaka Forge、storyboard-generator及ARIS。设计方法经筛选重新实现；没有直接复制其故事或图片。其他协议仅在完成适配并验证后宣称支持；模拟异步测试不代表已实测第二家生图模型。

本项目代码和原创示例采用MIT许可证。用户小说、第三方图片和平台素材保留原权利。真实小说及试样默认仅保存在本机，不提交公共仓库。只使用有权改编的素材，准确关键词和推广入口以实际任务为准；图集制作不自动登录右豹、领取任务或发帖，不承诺流量和佣金。
