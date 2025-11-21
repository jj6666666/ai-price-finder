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
    Treat results that mention 'wholesale', 'bulk', 'case', etc.
    in the title/source/snippet as 'wholesale-style' offers.
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
    """Single SerpApi call wrapper for google_shopping."""
    params = {
        "engine": "google_shopping",
        "q": query,
        "api_key": SERPAPI_KEY,
        "gl": country,
        "hl": "en",
        "num": 30,
    }
    search = GoogleSearch(params)
    return search.get_dict()


def is_no_results_error(err: str) -> bool:
    """True when SerpApi just says Google returned no results."""
    if not err:
        return False
    return "hasn't returned any results for this query" in err.lower()


@app.get("/search")
def search(query: str, country: str = "uk") -> Dict[str, Any]:
    """
    Behaviour:
    1) Try a wholesale-biased query (add 'wholesale bulk trade b2b case pack').
       - If we find ANY wholesale-looking items → use those.
       - If Google returns 'no results' for that query → treat as 0 items (not fatal).
    2) If we find NO wholesale-looking items at all:
       - Call SerpApi again with the original query (retail).
       - Return all priced results.
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
    err1 = result1.get("error")

    # If it's a true error (invalid key, etc.), surface it.
    if err1 and not is_no_results_error(err1):
        return {
            "query": query,
            "message": f"serpapi_error: {err1}",
            "best": None,
            "results": [],
            "raw": result1,
        }

    # If it's "no results", just treat as 0 shopping results.
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
        return {
            "query": query,
            "message": "ok",
            "best": best,
            "results": wholesale_items,
            "mode": "wholesale_priority",
        }

    # ---------- Second call: original query (retail fallback) ----------
    result2 = call_serpapi(query, country=country)
    err2 = result2.get("error")

    if err2 and not is_no_results_error(err2):
        return {
            "query": query,
            "message": f"serpapi_error: {err2}",
            "best": None,
            "results": [],
            "raw": result2,
        }

    shopping2: List[Dict[str, Any]] = result2.get("shopping_results", []) or []

    if (not shopping2) and is_no_results_error(err2 or ""):
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
