# 分镜格式与制作取舍

`--pages` 是成品总图数，含一张封面和一张关键词尾页。`plan.pages` 只放中间正文，因此长度应为 `--pages - 2`。每页 `panels` 长度等于配置的 `render.panels_per_page`（2 或 3）。封面、尾页和角标由排版程序统一生成。

```json
{
  "version": 1,
  "title": "雨夜来信",
  "hook": "母亲去世三年后，我收到她的来信",
  "characters": [
    {"id": "lin", "name": "林宁", "appearance": "adult East Asian woman, short black bob, round glasses, mustard cardigan, navy trousers"}
  ],
  "cover_scene": "Lin stands inside a warm old house, holding an unopened faded envelope, rainy window behind her, astonished face, medium shot",
  "pages": [
    {"panels": [
      {"characters": ["lin"], "scene": "Lin holds a faded envelope at the open doorway, rain outside, medium shot", "source_quote": "门缝里塞进一封泛黄的信", "texts": [{"type": "narration", "text": "母亲去世三年后，我收到了一封信。"}]},
      {"characters": ["lin"], "scene": "Lin stares at the back of a closed envelope, hands trembling, close-up on face", "source_quote": "背面是母亲熟悉的字迹", "texts": [{"type": "dialogue", "speaker": "林宁", "text": "这字迹……是妈妈的。"}]}
    ]}
  ],
  "cliffhanger": "她让我在午夜前打开地下室的门。",
  "post": {"title": "去世三年的母亲给我寄了一封信", "body": "一封迟到的来信，让我重新走进那间旧屋。", "tags": ["故事漫画", "悬疑故事"]}
}
```

以上仅示意一页，不可据此省略实际指定的页数。人物 id 只用于数据关联；画面提示词会自动注入对应外观。原文引句必须是原文连续子串，用来核对情节锚点；不要求每句改编台词逐字抄原文。每页选新事件，不能用重复反应镜头凑数。剧情过短无法承载指定张数时，减少图数或明确询问用户是否接受扩写，不擅自增加关键情节。

- 前两张即交代人物和核心冲突；尽量一格一事件。
- `scene` 只描述画面、动作、表情、景别，不包含台词，不让模型画字。英文短句通常更便于弱模型遵循。
- `texts` 1–2 项，每项不超过 46 个汉字/字符，单格合计不超过 72。旁白用 `narration`，对白用 `dialogue` 并给 `speaker`。程序在画面下方排可靠文字卡，不让气泡遮挡脸和手。
- 人物不超过两个；通过独立单人反应镜头表达多人争执。手持小物、复杂手势、群像和繁复建筑先简化。
- 角色参考图能辅助统一，但不能保证脸部完全一致。所有画面坚持同一发型、衣服颜色和风格提示。
- 结尾停在原文真实悬念。推广词使用真实任务关键词，避免“免费全集”“保证收益”等未经核实的话术。

文字排版失败会报错，不静默缩成难读小字、不丢字。原图、提示词和缓存保存在本机运行目录，允许修改后重做；提交公共仓库前排除输入原文、推广任务私有资料和运行产物。
