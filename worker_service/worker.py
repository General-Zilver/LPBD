import hashlib
import json
import time
from typing import Any, Dict, List, Tuple

import requests
from bs4 import BeautifulSoup

from .metadata_store import get_page_metadata, upsert_page_metadata
from .pack_store import (
    acquire_domain_lock,
    get_pack,
    next_sunday_235959_timestamp,
    purge_expired_packs,
    release_domain_lock,
    save_pack,
)


# Normalize HTML into stable plain text so hash comparisons are reliable.
def _normalize_text(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())


# Pull the page title safely; return empty string when missing.
def _page_title(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return ""


# Shared SHA-256 helper used for page-level and pack-level fingerprints.
def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


# Build conditional request headers from merged metadata/client validators.
def _headers_from_validators(
    etag: str | None,
    last_modified: str | None,
) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    return headers


# Merge client-provided validators with server-side metadata.
def _merge_validators(meta: Dict[str, Any] | None, page_in: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "etag": page_in.get("etag") or (meta.get("etag") if meta else None),
        "last_modified": page_in.get("last_modified") or (meta.get("last_modified") if meta else None),
        "text_hash": page_in.get("last_text_hash") or (meta.get("text_hash") if meta else None),
    }


# Compute a stable pack hash that ignores volatile fields like fetched_at.
def _stable_pack_hash(pack_pages: List[Dict[str, Any]]) -> str:
    stable_rows = sorted((p["url"], p["text_hash"]) for p in pack_pages)
    return _sha256(json.dumps(stable_rows, ensure_ascii=True))


# Return cached pack when valid, otherwise rebuild and refresh stores.
def get_or_build_pack(
    domain: str,
    pages: List[Dict[str, Any]],
    *,
    rate_limit_ms: int = 0,
    timeout_s: int = 30,
    force_refresh: bool = False,
    client_has_pack: bool = False,
) -> Tuple[bool, List[Dict[str, Any]], List[str], List[Dict[str, str]]]:
    now = time.time()
    purge_expired_packs(now)

    if not force_refresh:
        cached = get_pack(domain)
        if cached:
            return True, cached["pack"], [], []

    if not acquire_domain_lock(domain):
        return False, [], [], [{"url": domain, "error": "Timed out waiting for domain rebuild lock"}]

    unchanged_urls: List[str] = []
    errors: List[Dict[str, str]] = []
    pack_pages: List[Dict[str, Any]] = []
    should_save_pack = not client_has_pack

    try:
        # Another request may have rebuilt while we waited for lock.
        if not force_refresh:
            cached = get_pack(domain)
            if cached:
                return True, cached["pack"], [], []

        for idx, page_in in enumerate(pages):
            url = page_in["url"]
            if idx > 0 and rate_limit_ms > 0:
                time.sleep(rate_limit_ms / 1000.0)

            meta = get_page_metadata(domain, url)
            merged = _merge_validators(meta, page_in)
            headers = _headers_from_validators(
                merged.get("etag"),
                merged.get("last_modified"),
            )

            try:
                response = requests.get(url, headers=headers, timeout=timeout_s)
            except requests.RequestException as exc:
                errors.append({"url": url, "error": str(exc)})
                continue

            if response.status_code == 304:
                unchanged_urls.append(url)
                upsert_page_metadata(
                    domain,
                    url,
                    pack_hash=meta.get("pack_hash") if meta else None,
                    etag=merged.get("etag"),
                    last_modified=merged.get("last_modified"),
                    text_hash=merged.get("text_hash"),
                    last_checked_at=now,
                )
                # Existing clients can skip full rebuild when origin confirms unchanged.
                if client_has_pack:
                    should_save_pack = False
                    continue
                # New clients still need content when shared weekly pack is missing.
                try:
                    response = requests.get(url, timeout=timeout_s)
                except requests.RequestException as exc:
                    errors.append({"url": url, "error": str(exc)})
                    continue

            if response.status_code >= 400:
                errors.append({"url": url, "error": f"HTTP {response.status_code}"})
                continue

            title = _page_title(response.text)
            normalized_text = _normalize_text(response.text)
            text_hash = _sha256(normalized_text)
            fetched_at = time.time()

            prior_text_hash = merged.get("text_hash")
            if prior_text_hash == text_hash:
                unchanged_urls.append(url)

            pack_pages.append(
                {
                    "url": url,
                    "title": title,
                    "normalized_text": normalized_text,
                    "text_hash": text_hash,
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "fetched_at": fetched_at,
                }
            )

        pack_hash = _stable_pack_hash(pack_pages)
        expires_at = next_sunday_235959_timestamp(now)

        for page in pack_pages:
            upsert_page_metadata(
                domain,
                page["url"],
                pack_hash=pack_hash,
                etag=page.get("etag"),
                last_modified=page.get("last_modified"),
                text_hash=page.get("text_hash"),
                last_checked_at=now,
            )

        if should_save_pack and pack_pages:
            save_pack(domain, pack_pages, pack_hash, now, expires_at)

        return False, pack_pages, unchanged_urls, errors
    finally:
        release_domain_lock(domain)
