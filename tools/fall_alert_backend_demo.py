#!/usr/bin/env python3
"""HTTP backend for the WS63 fall-alert Wi-Fi gateway.

Default mode is safe for demos: it receives Board B alerts, rate-limits them,
prints the payload, and dry-runs notifications. Real SMS/voice sending is
enabled only through environment variables.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_list(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


@dataclass
class BackendConfig:
    token: str = os.getenv("FALL_BACKEND_TOKEN", "change-me-demo-token")
    rate_limit_seconds: int = int(os.getenv("FALL_RATE_LIMIT_SECONDS", "60"))
    notify_provider: str = os.getenv("FALL_NOTIFY_PROVIDER", "dryrun").strip().lower()
    dry_run: bool = env_bool("FALL_NOTIFY_DRY_RUN", True)
    channels: list[str] = None  # type: ignore[assignment]
    contacts: list[str] = None  # type: ignore[assignment]

    @classmethod
    def load(cls) -> "BackendConfig":
        cfg = cls()
        cfg.channels = env_list("FALL_NOTIFY_CHANNELS") or ["sms", "voice"]
        cfg.contacts = env_list("FALL_CONTACTS")
        return cfg


class NotificationError(RuntimeError):
    pass


class Notifier:
    def send(self, alert: dict[str, Any]) -> None:
        raise NotImplementedError


class DryRunNotifier(Notifier):
    def __init__(self, config: BackendConfig) -> None:
        self.config = config

    def send(self, alert: dict[str, Any]) -> None:
        print("[NOTIFY] dry-run enabled; no SMS/voice request sent.")
        print(f"[NOTIFY] contacts={self.config.contacts or ['<not configured>']}")
        print(f"[NOTIFY] message={build_alert_text(alert)}")


class TencentNotifier(Notifier):
    """Tencent Cloud SMS + VMS notifier.

    Install dependency:
        pip install tencentcloud-sdk-python

    Required environment:
        TENCENT_SECRET_ID
        TENCENT_SECRET_KEY
        TENCENT_SMS_REGION
        TENCENT_SMS_SDK_APP_ID
        TENCENT_SMS_SIGN_NAME
        TENCENT_SMS_TEMPLATE_ID
        TENCENT_VMS_REGION
        TENCENT_VMS_SDK_APP_ID
        TENCENT_VMS_TEMPLATE_ID
    """

    def __init__(self, config: BackendConfig) -> None:
        self.config = config
        self.secret_id = require_env("TENCENT_SECRET_ID")
        self.secret_key = require_env("TENCENT_SECRET_KEY")
        self.sms_region = os.getenv("TENCENT_SMS_REGION", "ap-guangzhou")
        self.sms_sdk_app_id = require_env("TENCENT_SMS_SDK_APP_ID")
        self.sms_sign_name = require_env("TENCENT_SMS_SIGN_NAME")
        self.sms_template_id = require_env("TENCENT_SMS_TEMPLATE_ID")
        if "voice" in self.config.channels:
            self.vms_region = os.getenv("TENCENT_VMS_REGION", "ap-guangzhou")
            self.vms_sdk_app_id = require_env("TENCENT_VMS_SDK_APP_ID")
            self.vms_template_id = require_env("TENCENT_VMS_TEMPLATE_ID")

    def send(self, alert: dict[str, Any]) -> None:
        if not self.config.contacts:
            raise NotificationError("FALL_CONTACTS is empty")
        if "sms" in self.config.channels:
            self._send_sms(alert)
        if "voice" in self.config.channels:
            self._send_voice(alert)

    def _credential(self):
        from tencentcloud.common import credential

        return credential.Credential(self.secret_id, self.secret_key)

    def _send_sms(self, alert: dict[str, Any]) -> None:
        from tencentcloud.sms.v20210111 import models, sms_client

        req = models.SendSmsRequest()
        req.SmsSdkAppId = self.sms_sdk_app_id
        req.SignName = self.sms_sign_name
        req.TemplateId = self.sms_template_id
        req.TemplateParamSet = build_template_params(alert)
        req.PhoneNumberSet = self.config.contacts

        client = sms_client.SmsClient(self._credential(), self.sms_region)
        resp = client.SendSms(req)
        print(f"[NOTIFY] Tencent SMS response: {resp.to_json_string()}")

    def _send_voice(self, alert: dict[str, Any]) -> None:
        from tencentcloud.vms.v20200902 import models, vms_client

        client = vms_client.VmsClient(self._credential(), self.vms_region)
        for phone in self.config.contacts:
            req = models.SendTtsVoiceRequest()
            req.TemplateId = self.vms_template_id
            req.TemplateParamSet = build_template_params(alert)
            req.CalledNumber = phone
            req.VoiceSdkAppid = self.vms_sdk_app_id
            req.PlayTimes = 2
            resp = client.SendTtsVoice(req)
            print(f"[NOTIFY] Tencent voice response for {phone}: {resp.to_json_string()}")


class PushPlusNotifier(Notifier):
    """Personal WeChat push via PushPlus.

    Required environment:
        PUSHPLUS_TOKEN

    Optional:
        PUSHPLUS_TOPIC
        PUSHPLUS_CHANNEL
    """

    def __init__(self, config: BackendConfig) -> None:
        self.config = config
        self.token = require_env("PUSHPLUS_TOKEN")
        self.topic = os.getenv("PUSHPLUS_TOPIC", "").strip()
        self.channel = os.getenv("PUSHPLUS_CHANNEL", "wechat").strip()

    def send(self, alert: dict[str, Any]) -> None:
        payload = {
            "token": self.token,
            "title": "跌倒报警",
            "content": build_pushplus_markdown(alert),
            "template": "markdown",
            "channel": self.channel,
        }
        if self.topic:
            payload["topic"] = self.topic

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            "https://www.pushplus.plus/send",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            raise NotificationError(f"PushPlus request failed: {exc}") from exc

        print(f"[NOTIFY] PushPlus response: {text}")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise NotificationError("PushPlus response is not JSON")
        if data.get("code") != 200:
            raise NotificationError(f"PushPlus returned error: {text}")


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise NotificationError(f"missing environment variable: {name}")
    return value


def build_template_params(alert: dict[str, Any]) -> list[str]:
    device_id = str(alert.get("device_id", "unknown"))
    event_count = str(alert.get("event_count", "1"))
    now_text = time.strftime("%Y-%m-%d %H:%M:%S")
    return [device_id, now_text, event_count]


def build_alert_text(alert: dict[str, Any]) -> str:
    device_id, now_text, event_count = build_template_params(alert)
    return f"检测到跌倒报警，设备 {device_id}，时间 {now_text}，事件序号 {event_count}。"


def build_pushplus_markdown(alert: dict[str, Any]) -> str:
    device_id, now_text, event_count = build_template_params(alert)
    payload = alert.get("payload", "")
    return (
        "## 跌倒报警\n\n"
        f"- 设备：{device_id}\n"
        f"- 时间：{now_text}\n"
        f"- 事件序号：{event_count}\n"
        f"- 原始载荷：{payload}\n\n"
        "**请立即查看老人/被监护人状态。**"
    )


def make_notifier(config: BackendConfig) -> Notifier:
    if config.dry_run or config.notify_provider in {"", "dryrun", "none"}:
        return DryRunNotifier(config)
    if config.notify_provider == "tencent":
        return TencentNotifier(config)
    if config.notify_provider == "pushplus":
        return PushPlusNotifier(config)
    raise NotificationError(f"unsupported FALL_NOTIFY_PROVIDER={config.notify_provider}")


class AlertState:
    def __init__(self, config: BackendConfig) -> None:
        self.config = config
        self.notifier = make_notifier(config)
        self.last_notify_time = 0.0

    def handle_alert(self, alert: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        elapsed = now - self.last_notify_time
        if self.last_notify_time > 0 and elapsed < self.config.rate_limit_seconds:
            wait = int(self.config.rate_limit_seconds - elapsed)
            print(f"[RATE] skipped duplicate alert, wait {wait}s.")
            return {"ok": True, "notified": False, "reason": "rate_limited", "wait_seconds": wait}

        self.notifier.send(alert)
        self.last_notify_time = now
        return {"ok": True, "notified": True}


class FallAlertHandler(BaseHTTPRequestHandler):
    server_version = "FallAlertBackend/1.1"

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/fall-alert":
            self.send_error(404, "not found")
            return

        if not self._check_token():
            self.send_error(401, "invalid token")
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(400, "invalid json")
            return

        print("=" * 72)
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] FALL ALERT")
        print(json.dumps(data, ensure_ascii=False, indent=2))

        try:
            result = self.server.alert_state.handle_alert(data)  # type: ignore[attr-defined]
            self._send_json(200, result)
        except Exception as exc:  # Keep backend alive during contest demos.
            print(f"[ERROR] notification failed: {exc}")
            self._send_json(500, {"ok": False, "error": str(exc)})

    def _check_token(self) -> bool:
        expected = self.server.alert_state.config.token  # type: ignore[attr-defined]
        got = self.headers.get("Authorization", "")
        return got == f"Bearer {expected}"

    def _send_json(self, status: int, data: dict[str, Any]) -> None:
        body = (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[HTTP] {self.address_string()} - {fmt % args}")


class FallAlertServer(ThreadingHTTPServer):
    def __init__(self, addr: tuple[str, int], handler, config: BackendConfig) -> None:
        super().__init__(addr, handler)
        self.alert_state = AlertState(config)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    config = BackendConfig.load()
    print(f"Notify provider: {config.notify_provider}, dry_run={config.dry_run}")
    print(f"Rate limit: {config.rate_limit_seconds}s")
    print(f"Contacts: {config.contacts or ['<not configured>']}")

    server = FallAlertServer((args.host, args.port), FallAlertHandler, config)
    print(f"Listening on http://{args.host}:{args.port}/api/fall-alert")
    server.serve_forever()


if __name__ == "__main__":
    main()
