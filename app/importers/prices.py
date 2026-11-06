"""Эвристический разбор стоимости: сумма — подсказка для администратора, не тариф."""

import asyncio
import io
import ipaddress
import json
import os
import re
import socket
import ssl
import zipfile
from typing import Literal
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

import httpx
import pdfplumber
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from app.importers.urls import normalize_urls

MAX_BYTES = 5_000_000
PARSER_VERSION = 2
NUMBER = (
    r"(?<![\w.,])(?P<number>\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)"
    r"(?:[.,](?P<decimal>\d{1,2}))?(?!\d)"
)
PRICE = re.compile(
    NUMBER + r"\s*(?P<thousands>тыс\.?\s*)?(?P<currency>руб(?:л(?:ь|я|ей))?\.?|₽|rub|р\.?)(?!\w)",
    re.I,
)
CONTEXT = re.compile(r"лиценз|стоимост|цена|прайс|тариф|подписк|price", re.I)
FREE = re.compile(
    r"(?:лицензи[яю]|программ\w*|ПО)\s+(?:предоставля\w*\s+|распространя\w*\s+)?бесплатно|бесплатная\s+лицензия|безвозмездн",
    re.I,
)


def tls_context() -> ssl.SSLContext:
    # Дополнительный доверенный CA можно задать явно; проверка TLS всегда включена.
    context = ssl.create_default_context()
    if os.environ.get("SZI_CA_BUNDLE"):
        context.load_verify_locations(os.environ["SZI_CA_BUNDLE"])
    return context


class PriceCandidate(BaseModel):
    amount: float = Field(ge=0, allow_inf_nan=False)
    context: str


class PriceResult(BaseModel):
    status: Literal["ok", "free", "scan", "js", "no_price", "other", "error"]
    value: float | None = Field(None, ge=0, allow_inf_nan=False)
    note: str = ""
    candidates: list[PriceCandidate] = Field(default_factory=list)
    parser_version: int = 1
    source_url: str | None = None


def extract_text(content: bytes) -> tuple[str, str]:
    if content.startswith(b"%PDF"):
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return "pdf", "\n".join(page.extract_text() or "" for page in pdf.pages[:30])
    if content.startswith(b"PK"):
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            try:
                info = archive.getinfo("word/document.xml")
            except KeyError:
                return "other", ""
            if info.file_size > MAX_BYTES:
                raise ValueError("Слишком большой документ")
            root = ElementTree.fromstring(archive.read(info))
            return "docx", " ".join(root.itertext())
    if b"\x00" in content[:512]:
        return "other", ""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1251", errors="replace")
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside"]):
        tag.decompose()
    return "html", soup.get_text(" ")


def find_prices(text: str) -> list[PriceCandidate]:
    found = []
    for match in PRICE.finditer(text):
        after = text[match.end() :]
        # «15 р.м.» — количество рабочих мест, не сумма в рублях.
        if match["currency"].lower().startswith("р") and not match["currency"].lower().startswith(
            "руб"
        ):
            if re.match(r"\s*\.?\s*м(?:\.|\b)", after, re.I):
                continue
        if re.match(
            r"\s*(?:/|за)\s*(?:1\s+)?(?:ролик|запрос|проверк|сообщен|операци|минут|ГБ|МБ)",
            after,
            re.I,
        ):
            continue
        amount = float(re.sub(r"\D", "", match["number"]) + "." + (match["decimal"] or "0"))
        if match["thousands"]:
            amount *= 1000
        context = " ".join(text[max(0, match.start() - 80) : match.end() + 60].split())
        found.append(PriceCandidate(amount=amount, context=context))
    return found


def product_prices(content: bytes) -> list[PriceCandidate]:
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["del", "s"]):
        tag.decompose()
    candidates = []
    # Явные блоки цены текущего товара предпочтительнее случайных сумм в описании.
    for tag in soup.select(".product-price, [itemprop='price'], .product__price, .product_price"):
        container = tag.parent
        if container and container.select_one("[itemprop='priceCurrency']"):
            currency = container.select_one("[itemprop='priceCurrency']").get("content", "RUB")
            if currency.upper() not in {"RUB", "RUR"}:
                continue
        text = str(tag.get("content") or tag.get_text(" ", strip=True))
        matches = find_prices(text)
        if not matches and re.fullmatch(r"[\d \u00a0\u202f.,]+", text):
            matches = find_prices(text + " руб.")
        candidates.extend(matches)
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        objects = data if isinstance(data, list) else [data]
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            offers = obj.get("offers", [])
            for offer in offers if isinstance(offers, list) else [offers]:
                if isinstance(offer, dict) and offer.get("priceCurrency", "").upper() in {
                    "RUB",
                    "RUR",
                }:
                    candidates.extend(find_prices(str(offer.get("price", "")) + " руб."))
    return candidates


def result(**kwargs) -> PriceResult:
    return PriceResult(parser_version=PARSER_VERSION, **kwargs)


def classify(content: bytes) -> PriceResult:
    try:
        kind, text = extract_text(content)
        if kind == "other":
            return result(status="other", note="Формат не поддерживается")
        found = product_prices(content) if kind == "html" else []
        if not found:
            found = find_prices(text)
        positive = [candidate for candidate in found if candidate.amount > 0]
        good = [candidate for candidate in positive if CONTEXT.search(candidate.context)]
        if positive:
            value = min(candidate.amount for candidate in (good or positive))
            return result(status="ok", value=value, note=kind, candidates=found[:30])
        if found:
            return result(status="free", value=0, note=kind, candidates=found[:30])
        if FREE.search(text):
            return result(status="free", value=0, note=kind)
        if len(text.strip()) < 30:
            return result(
                status="scan" if kind == "pdf" else "js", note="Нужен OCR или проверка в браузере"
            )
        return result(status="no_price", note=kind)
    except Exception as exc:
        return result(status="error", note=str(exc)[:200])


async def validate_url(url: str) -> None:
    """Выгрузка содержит внешние ссылки: локальные адреса загружать нельзя."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ValueError("Допустимы только внешние HTTP(S) ссылки без авторизации")
    addresses = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, parsed.port or 443)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError("Локальные и служебные адреса запрещены")


async def download(client: httpx.AsyncClient, url: str) -> bytes:
    for _ in range(6):
        await validate_url(url)
        async with client.stream("GET", url) as response:
            if response.is_redirect:
                url = str(response.url.join(response.headers["location"]))
                continue
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > MAX_BYTES:
                    raise ValueError("Файл превышает 5 МБ")
            return bytes(content)
    raise ValueError("Слишком много перенаправлений")


async def collect_price(client: httpx.AsyncClient, url: str) -> PriceResult:
    errors = []
    fallback = None
    candidates = normalize_urls(url)[:3]
    for candidate in candidates:
        try:
            content = await asyncio.wait_for(download(client, candidate), timeout=30)
            parsed = await asyncio.to_thread(classify, content)
            if parsed.status in {"no_price", "js"}:
                soup = BeautifulSoup(content, "html.parser")
                links = []
                for anchor in soup.find_all("a", href=True):
                    href = anchor["href"]
                    label = anchor.get_text(" ", strip=True)
                    if re.search(r"\.(pdf|docx)(?:[?#]|$)", href, re.I) and re.search(
                        r"цен|стоим|прайс|тариф|price|cost", href + " " + label, re.I
                    ):
                        links.append(urljoin(candidate, href))
                for link in list(dict.fromkeys(links))[:3]:
                    try:
                        document = await asyncio.wait_for(download(client, link), timeout=25)
                        price = await asyncio.to_thread(classify, document)
                        if price.status in {"ok", "free"}:
                            return price.model_copy(update={"source_url": link})
                    except (httpx.HTTPError, ValueError, asyncio.TimeoutError):
                        continue
            if parsed.status in {"ok", "free"}:
                return parsed.model_copy(update={"source_url": candidate})
            fallback = parsed
        except httpx.HTTPStatusError as exc:
            errors.append(f"HTTP {exc.response.status_code}: {candidate}")
            if candidate.startswith("http://") and exc.response.status_code in {403, 426}:
                https = "https://" + candidate.removeprefix("http://")
                if https not in candidates:
                    candidates.append(https)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    return fallback or result(status="error", note="; ".join(errors)[:500] or "Некорректная ссылка")
