from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from serpapi import GoogleSearch
from typing import List, Dict
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# TODO: put your SerpApi key here or in an env var on Render
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "YOUR_SERPAPI_KEY_HERE")


def search_serpapi_google_shopping(query: str, country: str = "uk") -> List[Dict]:
    """
    Use SerpApi's Google Shopping engine to search for products.
    Returns a list of simplified product dicts.
    """
    params = {
        "engine": "google_shopping",
        "q": query,
        "api_key": SERPAPI_KEY,
        "gl": country,   # country code (uk/us/de etc.)
        "hl": "en",      # language
        "num": 20,       # number of results
    }

    search = GoogleSearch(params)
    result = search.get_dict()

    products = []

    # SerpApi returns results under "shopping_results"
    for item in result.get("shopping_results", []):
        title = item.get("title")
        price = item.get("price")
        source = item.get("source")
        link = item.get("link")
        # Some results have "product_id" and "currency", but "price" is enough for now
        if not title or not price or not link:
            continue

        # price is a string like "£9.99" or "$12.50"
        products.append(
            {
                "title": title,
                "price_raw": price,
                "source": source,
                "link": link,
            }
        )

    return products


def parse_price_to_number(price_raw: str) -> float:
    """
    Convert price string like '£9.99', '$12.50', '9.99 USD' into a float.
    Very simple parser – good enough for MVP.
    """
    import re

    match = re.search(r"(\d+(?:\.\d{1,2})?)", price_raw)
    if not match:
        return 0.0
    return float(match.group(1))


@app.get("/search")
def search(query: str, country: str = "uk"):
    """
    Main search endpoint used by your frontend.
    1) Calls SerpApi Google Shopping
    2) Normalises prices
    3) Picks the cheapest
    """
    if not SERPAPI_KEY or SERPAPI_KEY == "YOUR_SERPAPI_KEY_HERE":
        return {
            "query": query,
            "message": "missing_serpapi_key",
            "best": None,
            "results": [],
        }

    products = search_serpapi_google_shopping(query, country=country)

    if not products:
        return {
            "query": query,
            "message": "no_results",
            "best": None,
            "results": [],
        }

    # add numeric price field for sorting
    for p in products:
        p["price_value"] = parse_price_to_number(p["price_raw"])

    # filter out zero prices just in case
    products = [p for p in products if p["price_value"] > 0]

    if not products:
        return {
            "query": query,
            "message": "no_price_parsed",
            "best": None,
            "results": [],
        }

    # pick cheapest
    best = min(products, key=lambda x: x["price_value"])

    return {
        "query": query,
        "message": "ok",
        "best": best,
        "results": products,
    }
