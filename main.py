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
    in the title or source/snippet as 'wholesale-style' offers.
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
    params = {
        "engine": "google_shopping",
        "q": query,
        "api_key": SERPAPI_KEY,
        "gl": country,   # 'uk', 'us', etc.
        "hl": "en",
        "num": 30,
    }
    search = GoogleSearch(params)
    return search.get_dict()


@app.get("/search")
def search(query: str, country: str = "uk") -> Dict[str, Any]:
    """
    Behaviour:
    1) Try a wholesale-biased query (add "wholesale bulk trade b2b case pack").
       - If we find ANY wholesale-looking items → use those.
    2) If we find NO wholesale-looking items at all →
       - Call SerpApi again with the original query (no extra keywords)
       - Return all results (retail included).
    """

    if not SERPAPI_KEY:
        return {
            "query": query,
            "message": "missing_serpapi_key",
            "best": None,
            "results": [],
        }

    # ---------- First call: wholesale-biased query ----------
    wholesale_query = f"{query} wholesale bulk trade b2b case pack"
    result1 = call_serpapi(wholesale_query, country=country)

    # Handle possible error from SerpApi
    if "error" in result1:
        return {
            "query": query,
            "message": f"serpapi_error: {result1['error']}",
            "best": None,
            "results": [],
            "raw": result1,
        }

    shopping1: List[Dict[str, Any]] = result1.get("shopping_results", []) or []

    # Attach price fields
    for item in shopping1:
        price_raw = item.get("price") or item.get("extracted_price") or ""
        item["price_raw"] = str(price_raw)
        item["price_value"] = parse_price_to_number(price_raw)

    # Wholesale-looking subset from first call
    wholesale_items = [i for i in shopping1 if looks_wholesale(i) and i["price_value"] > 0]

    # If we have any wholesale-looking items, use ONLY those
    if wholesale_items:
        best = min(wholesale_items, key=lambda x: x["price_value"])
        return {
            "query": query,
            "message": "ok",
            "best": best,
            "results": wholesale_items,
            "mode": "wholesale_priority",
        }

    # ---------- Second call: original query (retail fallback) ----------
    result2 = call_serpapi(query, country=country)

    if "error" in result2:
        return {
            "query": query,
            "message": f"serpapi_error: {result2['error']}",
            "best": None,
            "results": [],
            "raw": result2,
        }

    shopping2: List[Dict[str, Any]] = result2.get("shopping_results", []) or []

    if not shopping2:
        return {
            "query": query,
            "message": "no_shopping_results",
            "best": None,
            "results": [],
            "raw": result2,
        }

    for item in shopping2:
        price_raw = item.get("price") or item.get("extracted_price") or ""
        item["price_raw"] = str(price_raw)
        item["price_value"] = parse_price_to_number(price_raw)

    priced = [i for i in shopping2 if i["price_value"] > 0]

    if not priced:
        return {
            "query": query,
            "message": "no_price_parsed",
            "best": None,
            "results": shopping2,
            "mode": "retail_fallback",
        }

    best = min(priced, key=lambda x: x["price_value"])

    return {
        "query": query,
        "message": "ok",
        "best": best,
        "results": priced,
        "mode": "retail_fallback",
    }
