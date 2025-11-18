from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from serpapi import GoogleSearch
from typing import List, Dict, Any
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


def parse_price_to_number(price_raw: str) -> float:
    """
    Convert price string like '£9.99', '$12.50', '9.99 GBP' into a float.
    """
    m = re.search(r"(\d+(?:\.\d{1,2})?)", price_raw)
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
    in the title or source as 'wholesale-style' offers.
    """
    text = (
        (item.get("title") or "")
        + " "
        + (item.get("source") or "")
        + " "
        + (item.get("snippet") or "")
    ).lower()
    return any(kw in text for kw in WHOLESALE_KEYWORDS)


@app.get("/search")
def search(query: str, country: str = "uk") -> Dict[str, Any]:
    """
    1) Call SerpApi Google Shopping
       - we always append wholesale-related terms to the query
    2) Filter results to those that *look* wholesale/bulk
    3) Pick the cheapest
    """

    if not SERPAPI_KEY:
        return {
            "query": query,
            "message": "missing_serpapi_key",
            "best": None,
            "results": [],
        }

    # Always bias the query towards wholesale-style results
    wholesale_query = f"{query} wholesale bulk trade b2b case pack"

    params = {
        "engine": "google_shopping",
        "q": wholesale_query,
        "api_key": SERPAPI_KEY,
        "gl": country,   # 'uk', 'us', etc.
        "hl": "en",
        "num": 30,
    }

    search = GoogleSearch(params)
    result = search.get_dict()

    if "error" in result:
        return {
            "query": query,
            "message": f"serpapi_error: {result['error']}",
            "best": None,
            "results": [],
            "raw": result,
        }

    shopping: List[Dict[str, Any]] = result.get("shopping_results", []) or []

    if not shopping:
        return {
            "query": query,
            "message": "no_shopping_results",
            "best": None,
            "results": [],
            "raw": result,
        }

    # Add price fields
    for item in shopping:
        price_raw = item.get("price") or item.get("extracted_price") or ""
        item["price_raw"] = str(price_raw)
        item["price_value"] = parse_price_to_number(str(price_raw))

    # Prefer items that look wholesale-style
    wholesale_items = [i for i in shopping if looks_wholesale(i)]

    # If we found any "wholesale-looking" offers, only use those.
    # Otherwise, fall back to all results so you still see something.
    candidates = wholesale_items if wholesale_items else shopping

    # Remove items without numeric price
    candidates = [c for c in candidates if c["price_value"] > 0]

    if not candidates:
        return {
            "query": query,
            "message": "no_price_parsed",
            "best": None,
            "results": [],
        }

    best = min(candidates, key=lambda x: x["price_value"])

    return {
        "query": query,
        "message": "ok",
        "best": best,
        "results": candidates,
    }
