from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from serpapi import GoogleSearch
from typing import List, Dict, Any
from collections import deque
from datetime import datetime
import os
import re

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SERPAPI_KEY = os.getenv("SERPAPI_KEY")

# -------- Price history (in-memory, last 200 searches globally) --------

HISTORY_LIMIT = 200
price_history: deque = deque(maxlen=HISTORY_LIMIT)


def record_history(
    query: str,
    country: str,
    mode: str,
    best: Dict[str, Any],
) -> None:
    """Store a compact record in the global history deque."""
    try:
        entry = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "query": query,
            "country": country,
            "mode": mode,
            "title": best.get("title") or "",
            "price_value": best.get("price_value"),
            "price_raw": best.get("price_raw") or best.get("price") or "",
            "source": best.get("source") or best.get("store") or "",
        }
        price_history.append(entry)
    except Exception:
        # history is best-effort only; ignore any errors
        pass


# -------- Search helpers --------

def parse_price_to_number(price_raw: str) -> float:
    """Convert price string like '£9.99', '$12.50', '9.99 GBP' into a float."""
    m = re.search(r"(\d+(?:\.\d{1,2})?)", str(price_raw))
    if not m:
        return 0.0
    return float(m.group(1))


WHOLESALE_KEYWORDS = [
    "wholesale",
    "bulk",
    "case of",
    "case",
    "carton",
    "box of",
    "pack of",
    "trade",
    "b2b",
    "pack x",
    "x10",
    "x12",
    "x24",
    "x48",
]


def looks_wholesale(item: Dict[str, Any]) -> bool:
    """
    Heuristic: treat results that mention 'wholesale', 'bulk', 'case', etc.
    """
    text = (
        (item.get("title") or "")
        + " "
        + (item.get("source") or "")
        + " "
        + (item.get("snippet") or "")
    ).lower()
    return any(kw in text for kw in WHOLESALE_KEYWORDS)


def call_serpapi(query: str, country: str = "uk") -> Dict[str, Any]:
    """Single SerpApi call wrapper."""
    if not SERPAPI_KEY:
        return {"error": "missing_serpapi_key"}

    # Map UI country to SerpApi `gl` code
    gl_map = {
        "uk": "uk",
        "us": "us",
        "eu": "de",   # use Germany as EU proxy
        "au": "au",
    }
    gl = gl_map.get(country.lower(), "uk")

    params = {
        "engine": "google_shopping",
        "q": query,
        "api_key": SERPAPI_KEY,
        "gl": gl,
        "hl": "en",
        "num": 30,
    }
    search = GoogleSearch(params)
    return search.get_dict()


# -------- Main search endpoint --------

@app.get("/search")
def search(query: str, country: str = "uk") -> Dict[str, Any]:
    """
    Behaviour:
    1) First call: wholesale-biased query (add 'wholesale bulk trade b2b case pack')
       - If any wholesale-looking items → return those (mode: wholesale_priority)
    2) Otherwise, second call: original query
       - Return all reasonably-priced results (mode: retail_fallback)
    3) Record best result into global price history
    """

    if not SERPAPI_KEY:
        return {
            "query": query,
            "country": country,
            "message": "missing_serpapi_key",
            "best": None,
            "results": [],
        }

    # ----- First call: wholesale-biased -----
    wholesale_query = f"{query} wholesale bulk trade b2b case pack"
    result1 = call_serpapi(wholesale_query, country=country)

    if "error" in result1:
        return {
            "query": query,
            "country": country,
            "message": f"serpapi_error: {result1['error']}",
            "best": None,
            "results": [],
        }

    shopping1: List[Dict[str, Any]] = result1.get("shopping_results", []) or []
    for item in shopping1:
        price_raw = item.get("price") or item.get("extracted_price") or ""
        item["price_raw"] = str(price_raw)
        item["price_value"] = parse_price_to_number(price_raw)

    wholesale_items = [
        i for i in shopping1 if looks_wholesale(i) and i["price_value"] > 0
    ]

    if wholesale_items:
        best = min(wholesale_items, key=lambda x: x["price_value"])
        record_history(query, country, "wholesale_priority", best)
        return {
            "query": query,
            "country": country,
            "message": "ok",
            "best": best,
            "results": wholesale_items,
            "mode": "wholesale_priority",
        }

    # ----- Second call: retail fallback -----
    result2 = call_serpapi(query, country=country)

    if "error" in result2:
        return {
            "query": query,
            "country": country,
            "message": f"serpapi_error: {result2['error']}",
            "best": None,
            "results": [],
        }

    shopping2: List[Dict[str, Any]] = result2.get("shopping_results", []) or []

    if not shopping2:
        return {
            "query": query,
            "country": country,
            "message": "no_shopping_results",
            "best": None,
            "results": [],
        }

    for item in shopping2:
        price_raw = item.get("price") or item.get("extracted_price") or ""
        item["price_raw"] = str(price_raw)
        item["price_value"] = parse_price_to_number(price_raw)

    priced = [i for i in shopping2 if i["price_value"] > 0]

    if not priced:
        return {
            "query": query,
            "country": country,
            "message": "no_price_parsed",
            "best": None,
            "results": shopping2,
            "mode": "retail_fallback",
        }

    best = min(priced, key=lambda x: x["price_value"])
    record_history(query, country, "retail_fallback", best)

    return {
        "query": query,
        "country": country,
        "message": "ok",
        "best": best,
        "results": priced,
        "mode": "retail_fallback",
    }


# -------- Price history endpoint --------

@app.get("/history")
def get_history(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Return latest global price checks (newest first).
    """
    limit = max(1, min(limit, HISTORY_LIMIT))
    # deque is oldest→newest; we want newest first
    latest = list(price_history)[-limit:][::-1]
    return latest
