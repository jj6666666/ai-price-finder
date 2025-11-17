from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import re
from bs4 import BeautifulSoup
from typing import List, Dict

app = FastAPI()

# Allow browser calls from anywhere (Netlify etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------- helper functions ----------

def google_search(query: str) -> List[str]:
    """Very simple Google search → list of external URLs."""
    params = {"q": f"{query} pet product buy", "num": "5"}
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get("https://www.google.com/search", params=params, headers=headers, timeout=8)

    # crude URL extraction
    links = re.findall(r'https://[^\"<>\s]+', r.text)
    cleaned = []
    for l in links:
        if any(bad in l for bad in ["google.com", "webcache.googleusercontent.com", "policies.google.com"]):
            continue
        if any(ext in l for ext in [".jpg", ".jpeg", ".png", ".webp", ".svg"]):
            continue
        cleaned.append(l)
    # just the first few
    return cleaned[:5]


def extract_prices_from_url(url: str) -> List[Dict]:
    """Fetch a page, try to pull out title + any £xx.xx prices."""
    results: List[Dict] = []
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=8)
        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.text.strip() if soup.title else "Unknown product"

        # find patterns like £12.34 or £ 9.99
        matches = re.findall(r"£\s?(\d+(?:\.\d{1,2})?)", r.text)
        for m in matches:
            try:
                price_val = float(m)
                results.append({
                    "title": title,
                    "price": price_val,
                    "currency": "GBP",
                    "url": url,
                })
            except ValueError:
                continue
    except Exception as e:
        print("Error scraping", url, e)

    return results

# --------- main endpoint ----------

@app.get("/search")
def search(query: str):
    links = google_search(query)
    all_results: List[Dict] = []
    for link in links:
        all_results.extend(extract_prices_from_url(link))

    if not all_results:
        return {
            "query": query,
            "message": "No prices found",
            "best": None,
            "results": [],
        }

    # pick cheapest price
    best = min(all_results, key=lambda x: x["price"])

    return {
        "query": query,
        "message": "ok",
        "best": best,
        "results": all_results,
    }
