# v3.4：社媒首张与连续前三张

在事实表之后、全套分镜之前读本文。适用于社媒故事推广；Q版与非Q版采用相同叙事要求。技术试样和全文改编不自动变成同一种开场。45–85字、两至三格是试排起点，不是平台规则或留存保证。

## 工作卡：一次只完成一个判断

1. **选事件。**“只根据事实表写三个文字开场候选，分别尝试关系反差、证据揭露、直接冲突；素材不支持时换一种。每个写原文短引、观众会知道的新事实、为什么值得翻页、第二张如何承接。不要生图，不虚构反转，不提前揭谜底。”
2. **选开场。**“比较候选的原文依据、可画性、情绪和承接。选一个并具体解释取舍。可以冷开场，但必须说明回溯与泄底风险。前三张先兑现故事，不放强CTA。”
3. **写首张。**“把处境或关系、具体异常或冲突、反应或选择组织成第一页。优先两至三格，按镜头关系选择布局。每格只画一个瞬间；让动作、证据、表情讲故事。不要用立绘配一句人设介绍当完整开场。”
4. **接两张。**“第2张立刻回应第1张的事件并给新事实或后果，第3张让人物行动或代价更清楚。不要反复介绍同一人设。写出每页新增事实、可见证据、未解问题、下一页如何承接，并逐一附原文依据。”
5. **校对。**“只看前三张草稿，陌生观众能否知道处境、具体矛盾和继续阅读的理由？每句和每个画面是否有原文依据？画出的预言是否被误当事实？下一页是否重复或断开？指出具体页／格并修改。”

不要为完成三个候选付费生三套图。首张不是插在正文前的纯海报，不默认额外生成封面。明确要求独立封面时，记录用户原话，单独处理展示用途，不假称通过故事开场验收。

## 选择格数和文字

两至三格通常足以表现关系→证据→反应；剧情与手机阅读空间支持时可用四格。不要把此建议变为每页固定三格，也不固定上下二格。单格须写`single_panel_reason`：画面如何同时表达关系、冲突和行动。理由不能代替实际看图；只有背景介绍时应重写。

首张约45–85个非空白正文字符为试排起点，程序按所有非keyword文字统计（含标点），不将字数当质量分。画面已提供信息时可短于45字；超过85字先检查冗余和气泡空间，不缩字号。沿用简化入口单格文字限制；放不下时改镜头或转完整分镜。

把冲突画出来：手机截图、被推开的手、被改动的物件、人物迟疑等必须与原文一致。截图／信纸上的关键文字用本地排字，完整故事中记录说话者；画稿不要依赖模型拼写中文。每个动作、证据状态和表演都须可回查。

## 可运行示例与字段

示例使用本项目原创《雨夜来信》，只演示三张开场，不冒充60–100张成品：

```powershell
python <技能目录>/scripts/comic.py v3 compile --brief <技能目录>/references/opening-brief.example.json --beats <技能目录>/references/opening-beats.example.json --story <仓库>/examples/story.txt --out runs/opening-demo/plan.json
python <技能目录>/scripts/comic.py v3 opening-check --plan runs/opening-demo/plan.json --story <仓库>/examples/story.txt --out runs/opening-demo/opening-report.json
python <技能目录>/scripts/comic.py v3 layout --plan runs/opening-demo/plan.json --story <仓库>/examples/story.txt --out runs/opening-demo/layouts
```

正式任务仍使用`promotion_excerpt`及用户张数；示例为`style_pilot`。不要把示例剧情搬到用户故事。

在`brief.local.json`放`opening`，编译器原样保留；直接写完整计划时设置`authoring_version:"3.4"`并填写同一结构。完整字段见[示例简报](opening-brief.example.json)：

- `version:1`、`scope:"social_story"`。
- `candidates`恰好三个文字候选，字段`id/approach/summary/source_quote/next_page`。
- `selected`为候选ID；`selection_reason`写具体理由。
- `pages`依次对应最终前三张ID；字段`page_id/beat/new_fact/visible_evidence/unresolved/next_page_bridge/source_quote`。`beat`为`conflict/evidence/reaction/decision/setup_only`，首张不能是`setup_only`。
- 单格首张额外写`single_panel_reason`。每条`source_quote`均须能在原文找到。

`v3 init`为新推广任务创建待填写开场结构；新`compile`产物记录v3.4，新推广不能缺省策略。分批写作时先草拟前三张和开场策略，再分批写其余页；只处理后续批次时可保留beats，合并全套后编译，不把第11张误当首张。

仅当用户明确要求独立封面或非社媒用途时，将scope分别设为`user_requested_cover/not_social`并记录`reason/user_instruction`；不能自行豁免以绕过开场要求。`style_pilot/full_adaptation`未显式选择social_story时不强制开场合同。

## 内部试制与继续

先完成整套分镜与布局检查，生成并实际审阅人物参考，然后只用`--pages`指定实际前三张ID内部试制。模型调用、人物参考与频控仍按当前服务资料配置；不因本升级修改并发或放宽限额。

原尺寸与约390px宽都打开检查前三张，再完成正常的六项逐页验收和本专项验收。后续页生成前，执行器会检查专项记录与真实图片是否匹配；未通过就先修相关文字／镜头，不等待用户确认样图，也不无限重试。先重排文字、再局部改图，沿用本次预算上限。

`opening-report.json`记录结构、警告和`plan_hash`；它不是通过证明。Agent实际审图后在输出目录写`opening-review.json`：

```json
{
  "plan_hash": "从本次opening-report.json复制的摘要",
  "page_hashes": {"page-001": "实际成品摘要", "page-002": "实际成品摘要", "page-003": "实际成品摘要"},
  "reviewer": "实际阅读原文和看图的审阅者",
  "verdict": "needs_revision",
  "checks": {
    "context_clear": false, "conflict_visible": false, "information_progress": false,
    "page_two_payoff": false, "mobile_readability": false, "source_fidelity": false
  },
  "observations": {
    "context_clear": "具体描述人物关系或处境通过哪一格表达",
    "conflict_visible": "具体看到的冲突、证据或动作，不能只复述策略标签",
    "information_progress": "首张新增事实以及保留的具体问题",
    "page_two_payoff": "第二张如何接住首张，第三张新增什么",
    "mobile_readability": "原尺寸与390px宽实际检查了哪些文字、表情、格序和遮挡",
    "source_fidelity": "原文依据、时间关系、动机、预言与泄底的核对结果"
  },
  "blocking_issues": ["填写实际问题；示例状态不允许导出成品"]
}
```

图片摘要从`production.json`复制并对真实文件核验；页ID按项目实际值填写。只有全部实际通过才改为`accepted`、相应布尔值为true、`blocking_issues:[]`。代码只能检查完整性与摘要，无法证明观察诚实或图片有吸引力。

后续页用相同计划续跑；完成全套后严格导出。开场分镜、策略或前三张图片变化，会使旧专项审查失效；只修改后续页不必重复审核未变的开场。审查与报告进入制作资料ZIP，纯图片ZIP保持只有图片。

旧计划用`opening-check`只作诊断，明确标`legacy_not_assessed`；不自动补字段、追认、修改图片或产生调用。重新按v3.4制作时显式编写新策略并重新审查，保留原成果。MOCK、REVIEW和短试样仍明确标注，不冒充已审长集。
