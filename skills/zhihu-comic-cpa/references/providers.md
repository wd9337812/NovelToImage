# 模型接入

## Agnes 默认

官方资料：[模型目录](https://github.com/AgnesAI-Labs/AgnesAI-Models)、[图像模型](https://agnes-ai.com/doc/agnes-image-21-flash)。上线和配额以账号实测为准，仓库不承诺永久免费。

- Base URL：`https://apihub.agnes-ai.com/v1`
- 文本：`agnes-2.5-flash`，`POST /chat/completions`
- 图片：`agnes-image-2.1-flash`，`POST /images/generations`
- Bearer Key：环境变量 `AGNES_API_KEY`
- 返回 `data[0].b64_json` 或 `data[0].url`。默认请求 `return_base64: true`。
- 角色参考使用顶层 `image` 数组（Data URI），`reference_field` 可按供应商文档改成 `extra_body.image`。角色参考先生成一张，后续各格均引用同一张，不逐格引用上一张以免漂移累积。

## 换 OpenAI 兼容生图服务

复制配置为仓库根的 `config.local.json`，改 image：

```json
{
  "image": {
    "provider": "openai",
    "base_url": "https://your-provider.example/v1",
    "api_key_env": "COMIC_API_KEY",
    "model": "YOUR_IMAGE_MODEL",
    "size": "1024x1024",
    "supports_reference": false,
    "extra": {"response_format": "b64_json"}
  }
}
```

配置会递归覆盖默认值；`extra` 是完整替换，避免把 Agnes 专属参数发给其他服务。同一 Key 同时服务文本和图片时指向同一环境变量；也可以分开配置。`provider: openai` 指 **Images Generations 兼容协议**，不意味着所有型号都支持相同参数。模型如只支持 multipart edits、异步任务轮询、ComfyUI 或 Stability 专有协议，需要扩展适配器，不冒充已经支持。支持 image 数组的兼容服务可启用参考；不支持时关闭。`extra` 不允许覆盖模型、提示词、尺寸、认证和参考图字段。

`text.extra` 也是完整替换，可去掉不被文本模型支持的 `temperature` / `max_tokens` 参数。正文超过 60,000 字符时不会截断，请选定适合推广的连续片段，或在 Codex 中完整阅读后通过 `--plan` 提供人工复核的分镜。

## 网络与失败

默认遵循系统代理。失效代理可在本机配置 `"network": {"trust_env": false}`，该设置仅对本工具本次进程生效。自定义 URL 默认必须使用 HTTPS；仅允许 localhost/127.0.0.1/::1 使用 HTTP，供本地服务开发。TLS 校验始终开启。远程返回的图片使用独立无认证下载请求，不把 API Key 发往图片 CDN；拒绝 URL 认证信息及 localhost、私有和保留 IP 的远程下载。

401/403、额度不足和参数错误停止；429 与临时 5xx 最多重试两次，遵循 Retry-After（最长 60 秒）。请求超时有可能已在服务端计费，重试有可能重复消耗；可将 `retries` 设为 0。成功原画以提示词、模型、参数、参考图片摘要作为缓存键；失败不记作成功，也不以离线图自动替代。
