from __future__ import annotations

import asyncio
import base64
import json
import math
import time
import uuid
from collections import deque
from typing import Any, Deque

from fastapi import Body, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

TOTAL_ORDERS = 41
RATE_LIMIT = 16
RATE_WINDOW_SECONDS = 10.0

app = FastAPI(title="Orders API", version="1.0.0")
# Fixed catalog with IDs 1..41. Paging reads this catalog; it never mutates it.
CATALOG: list[dict[str, Any]] = [
    {"id": order_id, "description": f"Catalog order {order_id}"}
    for order_id in range(1, TOTAL_ORDERS + 1)
]

# In-process state is sufficient for a single Render instance/process.
# The API is intentionally started with one Uvicorn worker.
_idempotency: dict[str, dict[str, Any]] = {}
_rate_buckets: dict[str, Deque[float]] = {}
_state_lock = asyncio.Lock()


def _encode_cursor(offset: int) -> str:
    raw = str(offset).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> int:
    try:
        padded = cursor + ("=" * (-len(cursor) % 4))
        offset = int(base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii"))
        if offset < 0 or offset > TOTAL_ORDERS:
            raise ValueError("cursor out of range")
        return offset
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc


@app.middleware("http")
async def per_client_rate_limit(request: Request, call_next):
    # OPTIONS requests are browser CORS preflights, not counted as API calls.
    if request.method == "OPTIONS":
        return await call_next(request)

    client_id = (request.headers.get("X-Client-Id") or "anonymous").strip() or "anonymous"
    now = time.monotonic()
    async with _state_lock:
        bucket = _rate_buckets.setdefault(client_id, deque())
        while bucket and now - bucket[0] >= RATE_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT:
            wait_seconds = max(1, math.ceil(RATE_WINDOW_SECONDS - (now - bucket[0])))
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(wait_seconds)},
            )
        bucket.append(now)

    return await call_next(request)


# Keep CORS outermost so even middleware-generated 429 responses have CORS
# headers. Otherwise browsers report them as generic "Failed to fetch" errors.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)


@app.get("/")
async def root():
    return {"status": "ok", "service": "orders-api", "total_orders": TOTAL_ORDERS}


@app.post("/orders", status_code=201)
async def create_order(
    payload: dict[str, Any] = Body(default={}),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required")

    key = idempotency_key.strip()
    async with _state_lock:
        existing = _idempotency.get(key)
        if existing is not None:
            return JSONResponse(status_code=201, content=existing)

        # The submitted payload is retained for this created order, while its ID
        # is generated once and reused for every replay of the same key.
        order = {
            "id": str(uuid.uuid4()),
            "status": "created",
            "order": payload,
        }
        _idempotency[key] = order
        return JSONResponse(status_code=201, content=order)


@app.get("/orders")
async def list_orders(
    limit: int = Query(default=10, ge=1, le=100),
    cursor: str | None = Query(default=None),
):
    offset = _decode_cursor(cursor) if cursor else 0
    page = CATALOG[offset : offset + limit]
    next_offset = offset + len(page)
    next_cursor = _encode_cursor(next_offset) if next_offset < TOTAL_ORDERS else None
    return {"items": page, "next_cursor": next_cursor}


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
