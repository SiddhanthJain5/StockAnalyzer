"""FastAPI app for the Finance Analyzer web frontend.

Run locally:
    python3 -m pip install -r requirements.txt
    uvicorn webapp.main:app --reload

Then open http://127.0.0.1:8000
"""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from webapp import pipeline  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Finance Analyzer")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


class AnalyzeRequest(BaseModel):
    type: str  # "stock" | "fund"
    query: str
    market: str = "india"  # "india" | "us" - stocks only
    scheme_code: str | None = None


# --- Simple per-IP rate limit so a public deployment can't hammer
# yfinance/screener.in/mfapi.in (no LLM cost involved - this is just good manners).
RATE_LIMIT_PER_HOUR = int(os.environ.get("RATE_LIMIT_PER_HOUR", "60"))
_request_log: dict[str, deque] = defaultdict(deque)


def _check_rate_limit(ip: str) -> None:
    now = time.time()
    log = _request_log[ip]
    while log and now - log[0] > 3600:
        log.popleft()
    if len(log) >= RATE_LIMIT_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail="Rate limit reached for this address - please try again later.",
        )
    log.append(now)


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest, request: Request) -> dict:
    client_host = request.client.host if request.client else "unknown"
    _check_rate_limit(client_host)

    try:
        if req.type == "stock":
            return pipeline.analyze_stock(req.query, req.market)
        if req.type == "fund":
            return pipeline.analyze_fund(req.query, req.scheme_code)
        raise HTTPException(status_code=400, detail="type must be 'stock' or 'fund'.")
    except pipeline.PipelineError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
