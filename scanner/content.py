"""解析二维码内容：判断内容类型、拆出字段、套用复制模板。"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable
from urllib.parse import parse_qsl, unquote, urlsplit

TYPE_LABELS = {
    "url": "链接",
    "wifi": "WiFi",
    "vcard": "名片",
    "email": "邮件",
    "phone": "电话",
    "sms": "短信",
    "geo": "位置",
    "gs1": "GS1",
    "otpauth": "动态口令",
    "text": "文本",
}

TEMPLATES = {
    "仅内容": "{text}",
    "内容+来源": "{source}: {text}",
    "TSV": "{time}\t{source}\t{type}\t{format}\t{text}",
    "JSON": "",
}

VCARD_LABELS = {
    "FN": "姓名",
    "N": "姓名",
    "ORG": "公司",
    "TITLE": "职位",
    "TEL": "电话",
    "EMAIL": "邮箱",
    "ADR": "地址",
    "URL": "网址",
    "NOTE": "备注",
}

GS1_LABELS = {
    "00": "SSCC",
    "01": "GTIN",
    "02": "内容码",
    "10": "批号",
    "11": "生产日期",
    "15": "保质期",
    "17": "有效期",
    "21": "序列号",
    "30": "数量",
    "37": "数量",
    "400": "订单号",
    "410": "收货方",
}

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_DOMAIN_RE = re.compile(r"^(?:www\.)?[\w-]+(?:\.[\w-]+)+(?:/\S*)?$")
_GS1_BRACKET_RE = re.compile(r"^\(\d{2,4}\)")
_GS1_PAIRS_RE = re.compile(r"\((\d{2,4})\)([^(]*)")
_GS1_RAW = (
    ("01", 14),
    ("02", 14),
    ("11", 6),
    ("15", 6),
    ("17", 6),
    ("10", None),
    ("21", None),
)


def classify(text: str) -> str:
    value = text.strip()
    lowered = value.lower()
    if lowered.startswith("wifi:"):
        return "wifi"
    if lowered.startswith("begin:vcard"):
        return "vcard"
    if lowered.startswith("mailto:") or _EMAIL_RE.fullmatch(value):
        return "email"
    if lowered.startswith("tel:"):
        return "phone"
    if lowered.startswith(("smsto:", "sms:")):
        return "sms"
    if lowered.startswith("geo:"):
        return "geo"
    if lowered.startswith("otpauth:"):
        return "otpauth"
    if _GS1_BRACKET_RE.match(value) or value[:2] in {"01", "00"} and value[2:].isdigit():
        return "gs1"
    if lowered.startswith(("http://", "https://", "ftp://")) or _DOMAIN_RE.match(value):
        return "url"
    return "text"


def type_label(kind: str) -> str:
    return TYPE_LABELS.get(kind, TYPE_LABELS["text"])


def _query_fields(query: str) -> list[tuple[str, str]]:
    return [(unquote(key), unquote(value)) for key, value in parse_qsl(query, keep_blank_values=True)]


def _fields_url(text: str) -> list[tuple[str, str]]:
    parts = urlsplit(text)
    fields: list[tuple[str, str]] = []
    if parts.scheme:
        fields.append(("协议", parts.scheme))
    if parts.netloc:
        fields.append(("地址", parts.netloc))
    if parts.path and parts.path != "/":
        fields.append(("路径", unquote(parts.path)))
    fields.extend(_query_fields(parts.query))
    return fields or [("内容", text)]


def _fields_wifi(text: str) -> list[tuple[str, str]]:
    body = text.split(":", 1)[1] if ":" in text else text
    names = {"T": "加密方式", "S": "名称", "P": "密码", "H": "隐藏网络"}
    fields: list[tuple[str, str]] = []
    for item in body.strip(";").split(";"):
        if ":" not in item:
            continue
        key, _, value = item.partition(":")
        fields.append((names.get(key.upper(), key), unquote(value)))
    return fields or [("内容", text)]


def _fields_vcard(text: str) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.split(";")[0].upper()
        if key in {"BEGIN", "END", "VERSION"} or not value.strip():
            continue
        fields.append((VCARD_LABELS.get(key, key), unquote(value.strip())))
    return fields or [("内容", text)]


def _fields_email(text: str) -> list[tuple[str, str]]:
    body = text[len("mailto:"):] if text.lower().startswith("mailto:") else text
    address, _, query = body.partition("?")
    fields = [("收件人", unquote(address))]
    for key, value in _query_fields(query):
        fields.append(({"subject": "主题", "body": "正文", "cc": "抄送"}.get(key.lower(), key), value))
    return fields


def _fields_phone(text: str) -> list[tuple[str, str]]:
    return [("号码", text.split(":", 1)[-1])]


def _fields_sms(text: str) -> list[tuple[str, str]]:
    body = text.split(":", 1)[-1]
    if text.lower().startswith("smsto:"):
        number, _, message = body.partition(":")
        return [("号码", number), ("内容", message)]
    number, _, query = body.partition("?")
    fields = [("号码", number)]
    fields.extend(({"body": "内容"}.get(key.lower(), key), value) for key, value in _query_fields(query))
    return fields


def _fields_geo(text: str) -> list[tuple[str, str]]:
    body = text.split(":", 1)[-1]
    coords, _, query = body.partition("?")
    latitude, _, longitude = coords.partition(",")
    fields = [("纬度", latitude), ("经度", longitude.split(",")[0])]
    fields.extend(_query_fields(query))
    return [item for item in fields if item[1]]


def _fields_otpauth(text: str) -> list[tuple[str, str]]:
    parts = urlsplit(text)
    label = unquote(parts.path.lstrip("/"))
    issuer, _, account = label.partition(":")
    fields = [
        ("类型", parts.netloc.upper()),
        ("发行方", issuer),
        ("账户", account or label),
    ]
    names = {"secret": "密钥", "digits": "位数", "period": "周期", "algorithm": "算法", "counter": "计数"}
    fields.extend((names.get(key.lower(), key), value) for key, value in _query_fields(parts.query))
    return [item for item in fields if item[1]]


def _fields_gs1(text: str) -> list[tuple[str, str]]:
    value = text.strip()
    fields: list[tuple[str, str]] = []
    if _GS1_BRACKET_RE.match(value):
        for ai, content in _GS1_PAIRS_RE.findall(value):
            fields.append((GS1_LABELS.get(ai, f"AI {ai}"), content.strip()))
        return fields or [("内容", text)]
    index = 0
    while index < len(value):
        matched = False
        for ai, length in _GS1_RAW:
            if not value.startswith(ai, index):
                continue
            start = index + len(ai)
            if length is None:
                rest = value[start:]
                content = rest.split("\x1d", 1)[0]
            else:
                content = value[start:start + length]
            if not content:
                continue
            fields.append((GS1_LABELS.get(ai, f"AI {ai}"), content.strip()))
            index = start + len(content)
            matched = True
            break
        if not matched:
            break
    return fields or [("内容", text)]


def extract_fields(text: str) -> list[tuple[str, str]]:
    kind = classify(text)
    handlers = {
        "url": _fields_url,
        "wifi": _fields_wifi,
        "vcard": _fields_vcard,
        "email": _fields_email,
        "phone": _fields_phone,
        "sms": _fields_sms,
        "geo": _fields_geo,
        "otpauth": _fields_otpauth,
        "gs1": _fields_gs1,
    }
    handler = handlers.get(kind)
    if handler is None:
        return [("内容", text)]
    try:
        return handler(text)
    except Exception:  # noqa: BLE001 - 解析失败就退回原始内容
        return [("内容", text)]


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def format_row(row: dict[str, Any], template: str) -> str:
    values: dict[str, Any] = {key: row.get(key, "") for key in ("time", "source", "type", "format", "text")}
    fields = row.get("fields") or []
    values["fields"] = "；".join(f"{name}={value}" for name, value in fields)
    for name, value in fields:
        values.setdefault(name, value)
    try:
        return template.format_map(_SafeDict(values))
    except (IndexError, ValueError):
        return str(row.get("text", ""))


def row_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "time": row.get("time", ""),
        "source": row.get("source", ""),
        "type": row.get("type", ""),
        "format": row.get("format", ""),
        "text": row.get("text", ""),
        "fields": {name: value for name, value in row.get("fields") or []},
    }


def render_copy(rows: Iterable[dict[str, Any]], template_name: str = "仅内容", custom: str = "") -> str:
    rows = list(rows)
    if template_name == "JSON":
        return json.dumps([row_dict(row) for row in rows], ensure_ascii=False, indent=2)
    template = custom if template_name == "自定义" else TEMPLATES.get(template_name, "{text}")
    return "\n".join(format_row(row, template) for row in rows)
