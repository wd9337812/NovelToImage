from __future__ import annotations

import base64
import copy
from datetime import date, datetime, timezone, timedelta
import io
import json
import os
from pathlib import Path
import queue
import threading
import time
from urllib.parse import urlsplit

import requests
from PIL import Image

from .core import ProductionError, require, https_url, fingerprint
from .scheduler import retry_after, CachedSubmission


def validate_profile(profile, today=None):
    today = today or datetime.now(timezone(timedelta(hours=profile.get("research", {}).get("timezone_offset_hours", 0)))).date()
    require(profile.get("version") == 1, "模型资料档案需version: 1。")
    for key in ("provider", "model", "api_key_env", "quota_pool", "research"):
        require(bool(profile.get(key)), f"模型资料缺少{key}。")
    https_url(profile["base_url"])
    research = profile["research"]
    applies = {k: profile[k] for k in ("provider", "model", "base_url", "resolution", "quota_pool")}
    require(research.get("applies_to") == applies, "模型、端点、分辨率或限额池改变了：agent需重新查资料并绑定新的配置对象。")
    try:
        checked = date.fromisoformat(research["checked_on"])
        expires = date.fromisoformat(research["recheck_after"])
    except (KeyError, ValueError):
        raise ProductionError("模型资料需有查阅日和下次复核日。") from None
    require(checked <= today <= expires, "模型资料需要重新查阅；请核验官方说明后更新档案。")
    require(research.get("decision") and research.get("sources"), "不能用无依据的并发／频控默认值。")
    for source in research["sources"]:
        https_url(source["url"], allow_query=True)
        require(source.get("supports"), "来源需说明支持了哪个设置。")
    limits = profile.get("limits", {})
    require(isinstance(limits.get("max_inflight"), int) and 1 <= limits["max_inflight"] <= 64, "需设置有依据的最大在途任务数。")
    require(isinstance(limits.get("start_interval_seconds"), (int, float)) and limits["start_interval_seconds"] >= 0, "需独立设置请求起始间隔。")
    for field in ("requests_per_minute", "images_per_day", "poll_requests_per_minute"):
        value = limits.get(field)
        require(value is None or isinstance(value, int) and value > 0, f"{field}需为正整数或null（未知）。")
    require(0 <= limits.get("day_boundary_utc_hour", 0) < 24, "日额度重置时间无效。")
    protocol = profile.get("protocol", {})
    require(protocol.get("mode") in {"sync", "async"}, "模型协议需声明sync或async。")
    require(protocol.get("dialect") in {"agnes", "compatible"}, "当前适配支持Agnes与可配置Images Generations协议。")
    require(protocol.get('reference_format', 'data_uri_list') in {'data_uri_list', 'url_object_list', 'image_url_parts'}, '未知参考图编码方式。')
    require(protocol.get('reference_object_field', 'url') in {'url', 'image_url'}, '参考图对象字段需为url或image_url。')
    require(protocol.get('encoding', 'json') in {'json', 'multipart_edit'}, '未知图片请求编码。')
    if protocol.get('encoding') == 'multipart_edit':
        require(protocol.get('dialect') == 'compatible' and '.' not in protocol.get('reference_field', 'image'), 'multipart编辑需使用兼容协议与顶层参考字段。')
    for endpoint_key in ('edit_path',):
        if protocol.get(endpoint_key):
            require(protocol[endpoint_key].startswith('/') and not protocol[endpoint_key].startswith('//'), '编辑端点需为同服务相对路径。')
    require(str(protocol.get("submit_path", "/images/generations")).startswith("/") and not str(protocol.get("submit_path", "")).startswith("//"), "提交端点应为同一服务的相对路径。")
    require(not set(protocol.get("extra", {})) & {"model", "prompt", "image", "size", "ratio"}, "协议extra不能覆盖核心生成参数或注入未记录参考图。")
    require("image" not in protocol.get("extra", {}).get("extra_body", {}), "参考图只能由已记录的reference输入传入。")
    require(isinstance(profile.get("max_retries", 1), int) and 0 <= profile.get("max_retries", 1) <= 3, "重试次数需为0–3。")
    for timeout in ("read_timeout_seconds", "deadline_seconds", "poll_deadline_seconds"):
        require(0 < profile.get(timeout, 360) <= 3600, "请求与轮询等待上限需为1–3600秒。")
    constraints = research.get("user_constraints", {})
    if constraints.get("request_mode") == "serial":
        require(limits["max_inflight"] == 1, "本任务已要求串行请求，不能增加并发。")
    if constraints.get("timeout_range_seconds"):
        low, high = constraints["timeout_range_seconds"]
        require(all(low <= profile.get(k, 240 if k == "read_timeout_seconds" else 360) <= high
                    for k in ("read_timeout_seconds", "deadline_seconds")), "超时设置不符合本任务确认的范围。")
    if protocol["mode"] == "async":
        require(protocol.get("poll_hosts") and protocol.get("task_id_path") and protocol.get("poll_url_path"), "异步接口需明确任务ID、查询地址字段和可发送认证的查询域名。")
    require(profile.get("cost", {}).get("status") in {"free_confirmed", "authorized_paid", "unknown"}, "需记录费用权限状态。")
    # Only environment-variable names are accepted, never credential values in JSON.
    def check(value):
        if isinstance(value, dict):
            require(not {str(k).lower() for k in value} & {"api_key", "authorization", "password", "token", "headers"}, "资料档案不能保存认证凭据或自定义认证头。")
            for item in value.values():
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)
    check(profile)
    return profile


def field(payload, path, default=None):
    try:
        for segment in path.split("."):
            payload = payload[int(segment)] if isinstance(payload, list) else payload[segment]
        return payload
    except (KeyError, IndexError, TypeError, ValueError):
        return default


def assign(payload, path, value):
    keys = path.split(".")
    for key in keys[:-1]:
        payload = payload.setdefault(key, {})
    payload[keys[-1]] = value


class ImageProvider:
    def __init__(self, profile, scheduler, legacy, references_root=None, transport=None):
        self.profile = validate_profile(profile)
        self.scheduler = scheduler
        self.legacy = legacy
        self.references_root = references_root
        self.transport = transport
        self.session = requests.Session()
        self.session.trust_env = profile.get("trust_env", True)
        download_cfg = legacy.load_config()
        download_cfg["network"]["trust_env"] = self.session.trust_env
        self.downloader = legacy.Client(download_cfg)

    def request(self, method, url, body=None):
        token = os.environ.get(self.profile["api_key_env"], "")
        require(bool(token), "未设置模型所需的环境变量；没有发起请求。")
        if self.transport:
            return self.transport(method, url, body)
        kwargs = {'json': body}
        spec = self.profile['protocol']
        ref_key = spec.get('reference_field', 'image')
        if spec.get('encoding') == 'multipart_edit' and method == 'POST' and body and body.get(ref_key):
            form = copy.deepcopy(body)
            refs = form.pop(ref_key)
            parts = []
            for index, value in enumerate(refs):
                require(isinstance(value, str) and value.startswith('data:image/png;base64,'), 'multipart参考需为已记录的本地PNG输入。')
                raw = base64.b64decode(value.split(',', 1)[1], validate=True)
                parts.append((spec.get('multipart_image_field', 'image[]'), (f'reference-{index+1}.png', raw, 'image/png')))
            kwargs = {'data': {k: str(v) for k, v in form.items()}, 'files': parts}
        result = queue.Queue(maxsize=1)
        def send():
            try:
                response = self.session.request(method, url, **kwargs,
                    headers={"Authorization": "Bearer " + token},
                    timeout=(15, self.profile.get("read_timeout_seconds", 240)), allow_redirects=False)
                result.put((True, response))
            except Exception as exc:
                result.put((False, exc))
        threading.Thread(target=send, daemon=True).start()
        try:
            ok, value = result.get(timeout=self.profile.get("deadline_seconds", 360))
        except queue.Empty:
            raise requests.Timeout("Overall deadline") from None
        if not ok:
            raise value
        return value

    def body(self, prompt, ratio, references):
        spec = self.profile["protocol"]
        body = copy.deepcopy(spec.get("extra", {}))
        body.update(model=self.profile["model"], prompt=prompt)
        if spec["dialect"] == "agnes":
            body.update(size=self.profile.get("resolution", "1K"), ratio=ratio)
            body.setdefault("extra_body", {})["response_format"] = "b64_json"
        else:
            mapping = self.profile["capabilities"].get("size_by_ratio", {})
            require(ratio in mapping, "当前模型尚未核验此画幅的size映射，请查资料配置。")
            body["size"] = mapping[ratio]
        if references:
            require(self.profile["capabilities"].get("references"), "该模型档案未启用参考图，不能假装已传入。")
            images = ["data:image/png;base64," + base64.b64encode(Path(p).read_bytes()).decode() for p in references]
            if spec.get('reference_format') == 'url_object_list':
                images = [{spec.get('reference_object_field', 'url'): value} for value in images]
            elif spec.get('reference_format') == 'image_url_parts':
                images = [{'type': 'image_url', 'image_url': {'url': value}} for value in images]
            assign(body, spec.get("reference_field", "extra_body.image"), images)
        return body

    def decode(self, payload):
        spec = self.profile["protocol"]
        encoded = field(payload, spec.get("base64_path", "data.0.b64_json"))
        if encoded:
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError):
                raise ProductionError("图片Base64响应无效。") from None
        else:
            url = field(payload, spec.get("image_url_path", "data.0.url"))
            require(isinstance(url, str), "模型没有返回已配置的图像字段；响应已隐藏。")
            raw = self.downloader.download(url)
        return self.legacy.normalize_image(raw)

    def generate(self, job, prompt, ratio, references):
        require(not self.profile.get("offline_only"), "该资料仅供MOCK排版，不能请求真实服务。")
        require(self.profile["cost"]["status"] != "unknown" or self.profile["cost"].get("allow_unknown", False), "当前服务费用权限未核验，没有自动提交。")
        completed = self.scheduler.completed(job)
        if completed:
            saved = json.loads(completed["task_json"])
            if saved.get("response"):
                return self.decode(saved["response"])
        pending = self.scheduler.pending(job)
        if pending:
            if pending["status"] == "submitted" and pending["task_json"]:
                return self.poll(pending["id"], json.loads(pending["task_json"]), job)
            raise ProductionError("该任务提交状态未确认，已保留记录；请先恢复／核查，未重复提交。")
        body = self.body(prompt, ratio, references)
        spec = self.profile['protocol']
        submit_path = spec.get('edit_path') if references else None
        endpoint = self.profile["base_url"].rstrip("/") + (submit_path or spec.get("submit_path", "/images/generations"))
        require(bool(os.environ.get(self.profile["api_key_env"])), "未设置模型所需的环境变量；没有发起或登记图片请求。")
        for attempt in range(self.profile.get("max_retries", 1)+1):
            try:
                ticket = self.scheduler.acquire(job)
            except CachedSubmission as cached:
                require(bool(cached.data.get("response")), "已有提交结果需恢复，请检查任务记录。")
                return self.decode(cached.data["response"])
            try:
                response = self.request("POST", endpoint, body)
            except requests.ConnectTimeout:
                self.scheduler.finish(ticket, "failed")
                if attempt < self.profile.get("max_retries", 1):
                    self.scheduler.backoff(10 * 2**attempt)
                    continue
                raise ProductionError("建立连接超时，已记录失败；没有更换服务。") from None
            except requests.RequestException:
                self.scheduler.finish(ticket, "unknown")
                raise ProductionError("提交途中断开或超过总等待时间，服务端可能仍在生成；已停止重复提交。") from None
            if 200 <= response.status_code < 300:
                try:
                    payload = response.json()
                except ValueError:
                    self.scheduler.finish(ticket, "unknown")
                    raise ProductionError("成功状态返回非JSON，结果未知；未重复提交。") from None
                if self.profile["protocol"]["mode"] == "async":
                    proto = self.profile["protocol"]
                    task = {"id": field(payload, proto["task_id_path"]), "url": field(payload, proto["poll_url_path"])}
                    if not task["id"] or not task["url"]:
                        self.scheduler.finish(ticket, "unknown")
                        raise ProductionError("异步提交未返回已配置的任务信息；未重复提交。")
                    self.scheduler.finish(ticket, "submitted", task)
                    return self.poll(ticket, task, job)
                self.scheduler.finish(ticket, "done", {"response": payload})
                return self.decode(payload)
            code = response.status_code
            self.scheduler.finish(ticket, "failed")
            # Do not persist provider response bodies, which may echo credentials.
            if code in {429, 500, 502, 503, 504, 520} and attempt < self.profile.get("max_retries", 1):
                # A daily/account quota rejection must not be confused with a short RPM burst.
                if code == 429 and any(x in response.text.lower() for x in ("quota", "balance", "daily", "insufficient", "额度", "余额")):
                    raise ProductionError("HTTP429显示总额度或账号配额不足，已停止重试。")
                seconds = retry_after(response.headers.get("Retry-After"), time.time(), 15*2**attempt)
                self.scheduler.backoff(seconds)
                print(f"服务返回HTTP{code}，已降低负载，按频控有界重试。", flush=True)
                continue
            raise ProductionError(f"图片请求HTTP{code}，已保留成功缓存；响应正文和认证信息未写入日志。")
        raise ProductionError("图片请求失败。")

    def poll(self, ticket, task, job):
        proto = self.profile["protocol"]
        url = https_url(task["url"], allow_query=True)
        require(urlsplit(url).hostname in proto["poll_hosts"], "异步查询域名未核验，不向未知地址发送凭据。")
        deadline = time.monotonic() + self.profile.get("poll_deadline_seconds", 600)
        while time.monotonic() < deadline:
            t = self.scheduler.acquire(job, "poll")
            try:
                response = self.request("GET", url)
            except requests.RequestException:
                self.scheduler.finish(t, "failed")
                raise ProductionError("异步查询失败；原任务已保存，可续作查询，无需重新生成。") from None
            self.scheduler.finish(t, "done" if response.status_code == 200 else "failed")
            if response.status_code != 200:
                raise ProductionError(f"异步查询HTTP{response.status_code}，原任务未重新提交。")
            payload = response.json()
            state = field(payload, proto.get("status_path", "status"))
            if state in proto.get("success_states", ["Ready", "completed"]):
                self.scheduler.finish(ticket, "done", {**task, "response": payload})
                return self.decode(payload)
            if state in proto.get("failure_states", ["Failed", "Error", "failed"]):
                self.scheduler.finish(ticket, "failed", task)
                raise ProductionError("异步任务明确失败，已保留任务信息。")
        raise ProductionError("异步查询达到等待上限；任务仍保留，可续作，不重复提交。")
