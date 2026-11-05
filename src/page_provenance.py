from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import re
from urllib.parse import urlsplit


def normalize_series_url(value):
    if not isinstance(value, str):
        raise ValueError("Expected a NovelUpdates series URL.")
    p = urlsplit(value.strip())
    if (p.scheme not in {"http", "https"}
            or p.netloc not in {"www.novelupdates.com", "novelupdates.com"}
            or not re.fullmatch(r"/series/[^/]+/?", p.path) or p.query or p.fragment):
        raise ValueError("Invalid NovelUpdates series URL.")
    return "https://www.novelupdates.com" + p.path.rstrip("/") + "/"


def content_hash(html):
    return hashlib.sha256(html.encode("utf-8") if isinstance(html, str) else html).hexdigest()


def fetch_time(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("fetched_at must be a timezone-aware timestamp or null.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("fetched_at must include a timezone.")
    return parsed.astimezone(timezone.utc)


def atomic_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(content)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def sidecar_path(path):
    return Path(str(path) + ".meta.json")


def write_cache(path, html, url, fetched_at):
    date = fetch_time(fetched_at)
    if date is None:
        raise ValueError("Live fetches require a fetch timestamp.")
    data = html.encode("utf-8") if isinstance(html, str) else html
    atomic_bytes(path, data)
    metadata = {"version": 1, "url": url, "fetched_at": date.isoformat(), "html_sha256": content_hash(data)}
    # if interrupted between these writes, a stale hash will fail validation.
    atomic_bytes(sidecar_path(path), (json.dumps(metadata, indent=2) + "\n").encode("utf-8"))


def read_cache(path):
    path = Path(path)
    html = path.read_bytes()
    sidecar = sidecar_path(path)
    if not sidecar.exists():
        return html, None, None
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    if metadata.get("version") != 1 or metadata.get("html_sha256") != content_hash(html):
        raise ValueError(f"Cache metadata/hash mismatch: {path}. Do not invent a fetch time; refetch or investigate the cache.")
    date = fetch_time(metadata.get("fetched_at"))
    if date is None:
        raise ValueError(f"Invalid cache fetch timestamp: {sidecar}")
    return html, date.isoformat(), metadata.get("url")


def observation_time(record):
    # deliberately do not fall back to parsed_at for legacy records.
    return fetch_time(record.get("fetched_at"))


def choose_page(previous, incoming):
    """Return (selected, reason). Unknown-age observations cannot replace others.

    Such records remain attachable as a first baseline when no page was retained.
    Same-content re-parses may update parser-derived fields without changing age.
    """
    if previous is None:
        return incoming, "initial_page"
    before, after = observation_time(previous), observation_time(incoming)
    old_hash, new_hash = previous.get("html_sha256"), incoming.get("html_sha256")
    same_content = bool(old_hash and new_hash and old_hash == new_hash)
    if same_content:
        # with equal source content, prefer the current parser only if its version is not older. Retain the latest known observation time independently.
        old_version = previous.get("parser_revision", 0)
        new_version = incoming.get("parser_revision", 0)
        if new_version < old_version:
            return previous, "older_parser_skipped"
        result = dict(incoming)
        date = max([d for d in (before, after) if d is not None], default=None)
        result["fetched_at"] = date.isoformat() if date else None
        result["freshness"] = "known" if date else "unknown"
        # repeated parsing alone should not create database updates.
        comparable_old = {k: v for k, v in previous.items() if k != "parsed_at"}
        comparable_new = {k: v for k, v in result.items() if k != "parsed_at"}
        if comparable_old == comparable_new:
            return previous, "same_content_unchanged"
        return result, "same_content_reparsed"
    if before is None and after is None and not old_hash and new_hash:
        # Migration for old parser outputs: allow newly extracted fields only
        # when every previously populated content field agrees. No fetch date
        # is invented and no existing content value is replaced with a different one.
        fields = ("source_title", "original_language", "authors", "associated_names",
                  "genres", "tags", "synopsis", "novelupdates_rating_count",
                  "novelupdates_reading_list_count", "novelupdates_rating_raw",
                  "original_chapter_status_raw")
        identity_ok = (previous.get("novelupdates_url") == incoming.get("novelupdates_url")
                       and previous.get("source_title") == incoming.get("source_title"))
        agrees = all(previous.get(k) in (None, [], "") or previous.get(k) == incoming.get(k)
                     for k in fields)
        if identity_ok and agrees:
            return incoming, "legacy_missing_fields_enriched"
    if after is None:
        return previous, "unknown_age_page_held"
    if before is None or after > before:
        return incoming, "newer_fetch"
    return previous, "older_or_equal_fetch_held"
