from __future__ import annotations

import csv
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from utils import normalize_text

DATA_DIR = Path(__file__).resolve().parent / "data"
DIALECT_PACK = os.environ.get("DIALECT_PACK", "dialect_kangwon")
DIALECT_PACK_DIR = DATA_DIR / "dialect_packs"


def _safe_pack_id(pack_id: str | None) -> str:
    value = str(pack_id or DIALECT_PACK or "dialect_kangwon").strip()
    value = value.removesuffix(".json").removesuffix(".csv")
    if not value or "/" in value or "\\" in value or ".." in value:
        raise RuntimeError(f"Invalid dialect pack id: {pack_id}")
    return value


def _json_path(pack_id: str | None = None) -> Path:
    return DIALECT_PACK_DIR / f"{_safe_pack_id(pack_id)}.json"


def _csv_path(pack_id: str | None = None) -> Path:
    return DIALECT_PACK_DIR / f"{_safe_pack_id(pack_id)}.csv"


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                return list(csv.DictReader(f))
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Failed to read dialect csv {path}: {last_error}")


def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]

    if isinstance(payload, dict):
        for key in ("items", "rows", "data", "entries"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]

    return []


def _first_text(row: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = normalize_text(row.get(key) or "")
        if value:
            return value
    return ""


def _expand_variants(text: str) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []

    variants = {text}

    for match in re.finditer(r"(.+?)\[(.+?)\]", text):
        base = normalize_text(match.group(1))
        inside = normalize_text(match.group(2))
        if base:
            variants.add(base)
        if inside:
            variants.add(inside)

    for part in re.split(r"[,/;·]", text):
        part = normalize_text(part)
        if part:
            variants.add(part)

    return sorted(variants, key=len, reverse=True)


@lru_cache(maxsize=None)
def load_dialect_entries(pack_id: str | None = None) -> list[dict[str, Any]]:
    json_path = _json_path(pack_id)
    csv_path = _csv_path(pack_id)

    if json_path.exists():
        rows = _rows_from_payload(_read_json(json_path))
        source_file = json_path.name
    elif csv_path.exists():
        rows = _read_csv(csv_path)
        source_file = csv_path.name
    else:
        raise FileNotFoundError(f"Dialect pack not found: {json_path} or {csv_path}")

    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for row in rows:
        dialect = _first_text(row, ["방언", "dialect", "source_quote", "local", "dialect_text"])
        standard = _first_text(row, ["표준어", "standard", "standard_text", "normalized", "standard_korean"])
        initial = _first_text(row, ["초성", "initial"])
        registered_at = _first_text(row, ["등록일", "registered_at", "date"])

        if not dialect or not standard:
            continue

        for variant in _expand_variants(dialect):
            key = (variant, standard)
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                {
                    "dialect": variant,
                    "standard": standard,
                    "initial": initial,
                    "registered_at": registered_at,
                    "source_file": source_file,
                }
            )

    return entries
