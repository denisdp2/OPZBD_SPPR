"""Нормализация ссылок из выгрузок: Unicode, HTML-сущности и примечания."""

import html
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

import httpx


def normalize_urls(value: str) -> list[str]:
    value = unicodedata.normalize("NFC", html.unescape(value or ""))
    value = value.replace("\u200b", "").replace("\ufeff", "").replace("\\/", "/")
    value = re.sub(r"^(?:https?://)h?(?=https?://)", "", value.strip(), flags=re.I)
    parts = re.split(r"[\r\n]+|\s*[;|]\s*(?=https?://)|\s+(?=https?://)", value)
    result = []
    for part in parts:
        part = re.split(r"\s{2,}(?=\()|\s+(?=\(\*?(?:Раздел|Поставка))", part.strip(), maxsplit=1)[
            0
        ]
        part = part.strip(" \t<>\"'").rstrip(";")
        if part.startswith("www."):
            part = "https://" + part
        try:
            parsed = urlsplit(part)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
                continue
            # httpx кодирует IDN и кириллицу, сохраняя уже закодированные %XX.
            url = str(httpx.URL(urlunsplit(parsed._replace(fragment=""))))
            if url not in result:
                result.append(url)
        except (ValueError, httpx.InvalidURL):
            continue
    return result


def source_url(value: str) -> str | None:
    urls = normalize_urls(value)
    return urls[0] if urls else None


def canonical_links(value: str) -> str:
    return "\n".join(normalize_urls(value)) or value
