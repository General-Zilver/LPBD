import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .worker import get_or_build_pack

# matching module lives one level up from worker_service/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from matching.controller import (
    get_status, run_single_page, update_match_status,
)

app = FastAPI(title="LPBD Worker")


# One page entry from the client request, including optional prior validators.
class PageIn(BaseModel):
    url: str
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    last_text_hash: Optional[str] = None
    last_checked: Optional[float] = None


# Request body for building or retrieving a weekly shared pack.
class ScrapeRequest(BaseModel):
    domain: str
    pages: List[PageIn]
    mode: str = "fetch_if_changed"
    options: Dict[str, Any] = Field(default_factory=dict)


# A page that was fetched and included in the returned pack payload.
class ChangedPage(BaseModel):
    url: str
    title: str
    normalized_text: str
    text_hash: str
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    fetched_at: float


# Endpoint response with cache status, page data, and any fetch errors.
class ScrapeResponse(BaseModel):
    domain: str
    checked_at: float
    cache_hit: bool
    unchanged_urls: List[str]
    changed_pages: List[ChangedPage]
    errors: List[Dict[str, str]]


@app.post("/scrape", response_model=ScrapeResponse)
# API entrypoint that delegates scraping/cache logic to the worker layer.
def scrape(req: ScrapeRequest) -> ScrapeResponse:
    rate_limit_ms = int(req.options.get("rate_limit_ms", 0) or 0)
    timeout_s = int(req.options.get("timeout_s", 30) or 30)
    force_refresh = bool(req.options.get("force_refresh", False))
    client_has_pack = bool(req.options.get("client_has_pack", False))

    cache_hit, pack_pages, unchanged_urls, errors = get_or_build_pack(
        req.domain,
        [p.model_dump() for p in req.pages],
        rate_limit_ms=rate_limit_ms,
        timeout_s=timeout_s,
        force_refresh=force_refresh,
        client_has_pack=client_has_pack,
    )

    return ScrapeResponse(
        domain=req.domain,
        checked_at=time.time(),
        cache_hit=cache_hit,
        unchanged_urls=unchanged_urls,
        changed_pages=[ChangedPage(**p) for p in pack_pages],
        errors=errors,
    )


# -- matching endpoints ----------------------------------------------------

# Request body for single-page real-time matching.
class RealtimeMatchRequest(BaseModel):
    user: str
    url: str
    model: str = "phi3:mini"


# Request body for updating a match's status.
class StatusUpdateRequest(BaseModel):
    status: str  # new | seen | dismissed | saved


@app.get("/matching/status/{user}")
# Returns the full results envelope for a user.
def matching_status(user: str):
    return get_status(user)


@app.patch("/matching/results/{match_id}")
# Updates a single match result's status.
def matching_update(match_id: str, req: StatusUpdateRequest):
    try:
        found = update_match_status(match_id, req.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not found:
        raise HTTPException(status_code=404, detail=f"Match '{match_id}' not found")
    return {"match_id": match_id, "status": req.status}


@app.post("/matching/realtime")
# Fetches a single URL, matches it against the user's profile, and
# returns the match results immediately.
def matching_realtime(req: RealtimeMatchRequest):
    try:
        results = run_single_page(req.user, req.url, model=req.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {
        "url": req.url,
        "results": [r.to_dict() for r in results],
        "count": len(results),
    }
