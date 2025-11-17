from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import re
from typing import List, Dict

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------
# 1. SEARCH VIA DUCKDUCKGO HTML
# ------------------------------

def ddg_search(query: str, max_results: int = 5) -> List[str]:
    """
    Use DuckDuckGo's HTML results page to get some URLs.
    This is a very simple HTML search. Check DDG's terms before
    using heavily.
    """
    url = "https://duckduckgo.com/html/"
    params = {"q": query + " buy pet product"}
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    links = []
    for a in soup.select("a.result__a"):
        href = a.get("href")
        if not href:
            continue
        # skip duckduckgo internal links
        if href.startswith("https://duckduckgo.com"):
            continue
        # skip obvious non-product stuff
        if any(bad in href for bad in ["wikipedia.org", "youtube.com"]):
            continue
        links.append(href)
        if len(links) >= max_results:
            break
    return links

# ------------------------------
# 2. SCRAPE A SINGLE PAGE
# ------------------------------

PRICE_RE = re.compile(r"(£|\$|€)\s?(\d+(?:\.\d{1,2})?)")

def scrape_prices_from_url(url: str) -> List[Dict]:
    """
    Fetch a product-like page and extract all currency prices we can see.
    """
    results: List[Dict] = []
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.text.strip() if soup.title else "Unknown product"

        for match in PRICE_RE.findall(r.text):
            currency, amount = match
            try:
                price_val = float(amount)
            except ValueError:
                continue
            results.append(
                {
                    "title": title,
                    "price": price_val,
                    "currency": currency,
                    "url": url,
                }
            )
    except Exception as e:
        print("Error scraping", url, e)

    return results

# ------------------------------
# 3. MAIN SEARCH ENDPOINT
# ------------------------------

@app.get("/search")
def search(query: str):
    """
    1) Search the web for the query
    2) Visit the top few result URLs
    3) Extract any prices we see
    4) Return the cheapest price and all raw hits
    """
    try:
        urls = ddg_search(query)
    except Exception as e:
        return {
            "query": query,
            "message": f"search_failed: {e}",
            "best": None,
            "results": [],
        }

    all_hits: List[Dict] = []
    for u in urls:
        all_hits.extend(scrape_prices_from_url(u))

    if not all_hits:
        return {
            "query": query,
            "message": "no_prices_found",
            "best": None,
            "results": [],
        }

    # pick cheapest
    best = min(all_hits, key=lambda x: x["price"])

    return {
        "query": query,
        "message": "ok",
        "best": best,
        "results": all_hits,
    }
