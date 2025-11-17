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


@app.get("/search")
def search(query: str, country: str = "uk") -> Dict[str, Any]:
    """
    1) Call SerpApi Google Shopping with the SAME params as your manual test
    2) Return all shopping_results + the cheapest one as 'best'
    """

    if not SERPAPI_KEY:
        return {
            "query": query,
            "message": "missing_serpapi_key",
            "best": None,
            "results": [],
        }

    params = {
        "engine": "google_shopping",
        "q": query,
        "api_key": SERPAPI_KEY,
        "gl": country,   # 'uk', 'us', etc.
        "hl": "en",
        "num": 20,
    }

    search = GoogleSearch(params)
    result = search.get_dict()

    # If SerpApi returned an error, show it directly
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

    # Add numeric price for sorting
    for item in shopping:
        price_raw = item.get("price") or item.get("extracted_price") or ""
        item["price_raw"] = price_raw
        item["price_value"] = parse_price_to_number(str(price_raw))

    # Filter out items with no numeric price
    priced = [i for i in shopping if i["price_value"] > 0]

    best = min(priced, key=lambda x: x["price_value"]) if priced else None

    return {
        "query": query,
        "message": "ok",
        "best": best,
        "results": shopping,
    }
