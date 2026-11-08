from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable

import requests
import yaml
from dotenv import load_dotenv


class CollectionError(RuntimeError):
    """Raised when a source cannot be collected safely."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stable_id(*parts: str) -> str:
    raw = "|".join(str(part).strip() for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def clean_html_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def load_settings(root: Path) -> dict[str, Any]:
    load_dotenv(root / ".env")
    config_path = root / "config" / "settings.yaml"
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def build_session() -> requests.Session:
    contact = os.getenv("CONTACT_EMAIL", "").strip()
    if not contact or "@" not in contact or "your_email" in contact.lower():
        raise CollectionError(
            "CONTACT_EMAIL chưa được cấu hình. Sao chép .env.example thành .env "
            "và thay bằng email liên hệ thật trước khi gọi Wikimedia API."
        )
    app_name = os.getenv("APP_NAME", "VietnamFilmNetworkCollector").strip()
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": f"{app_name}/0.1 ({contact})",
            "Accept": "application/json, application/sparql-results+json;q=0.9, */*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        }
    )
    return session


def _retry_after_seconds(response: requests.Response | None, fallback: float) -> float:
    if response is None:
        return fallback
    raw = response.headers.get("Retry-After")
    if not raw:
        return fallback
    try:
        return max(1.0, float(raw))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(raw)
            return max(1.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            return fallback


def request_json(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any],
    timeout: int,
    max_retries: int,
    delay_seconds: float,
    source_name: str,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        response: requests.Response | None = None
        try:
            response = session.get(url, params=params, timeout=timeout)
            if response.status_code == 429 or response.status_code in {502, 503, 504}:
                if attempt >= max_retries:
                    response.raise_for_status()
                wait = _retry_after_seconds(response, min(60.0, 2.0 ** attempt))
                logging.warning("%s trả HTTP %s; chờ %.1f giây", source_name, response.status_code, wait)
                time.sleep(wait)
                continue
            response.raise_for_status()
            payload = response.json()
            api_error = payload.get("error") if isinstance(payload, dict) else None
            if api_error:
                code = str(api_error.get("code", "unknown"))
                info = str(api_error.get("info", ""))
                if code in {"maxlag", "ratelimited", "readonly", "Timeout"} and attempt < max_retries:
                    wait = min(60.0, 2.0 ** (attempt + 1))
                    logging.warning("%s API error %s; chờ %.1f giây (%s)", source_name, code, wait, info[:160])
                    time.sleep(wait)
                    continue
                raise CollectionError(f"{source_name} API error {code}: {info}")
            time.sleep(delay_seconds)
            return payload
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            wait = _retry_after_seconds(response, min(60.0, 2.0 ** attempt))
            logging.warning("Lỗi gọi %s (%s); thử lại sau %.1f giây", source_name, exc, wait)
            time.sleep(wait)
    raise CollectionError(f"Không thể truy cập {source_name} sau {max_retries + 1} lần: {last_error}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise CollectionError(f"JSONL lỗi tại {path}:{line_number}: {exc}") from exc
    return rows


def append_jsonl_unique(path: Path, records: Iterable[dict[str, Any]], key_fields: tuple[str, ...]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: set[tuple[str, ...]] = set()
    if path.exists():
        for row in read_jsonl(path):
            existing.add(tuple(str(row.get(field, "")) for field in key_fields))
    added = 0
    with path.open("a", encoding="utf-8") as handle:
        for row in records:
            key = tuple(str(row.get(field, "")) for field in key_fields)
            if key in existing:
                continue
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            existing.add(key)
            added += 1
    return added


class Checkpoint:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.data = {"completed_tasks": {}, "updated_at": utc_now()}

    def is_completed(self, task: str) -> bool:
        return bool(self.data.get("completed_tasks", {}).get(task))

    def mark_completed(self, task: str) -> None:
        self.data.setdefault("completed_tasks", {})[task] = True
        self.data["updated_at"] = utc_now()
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")


def setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )
