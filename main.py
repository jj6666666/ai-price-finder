from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests, re
from bs4 import BeautifulSoup
from openai import OpenAI

client = OpenAI(api_key="YOUR_OPENAI_KEY")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------
# 1. GLOBAL PRODUCT SCRAPER (Shopify, WooCommerce, HTML)
# -------------------------------------------------------

def extract_prices_from_url(url):
    prices = []
    try:
        r = requests.get(url, timeout=8)
        soup = BeautifulSoup(r.text, "html.parser")

        # Shopify JSON
        if "Product" in r.text:
            json_links = re.findall(r"https://[^\"']+products[^\"']+\.js", r.text)
            for link in json_links[:3]:
                j = requests.get(link).json()
                prices.append({
                    "title": j.get("title"),
                    "price": j.get("price"),
                    "url": url
                })

        # WooCommerce (meta tags)
        for meta in soup.find_all("meta"):
            if meta.get("property") == "product:price:amount":
                prices.append({
                    "title": soup.title.text if soup.title else "Unknown",
                    "price": meta.get("content"),
                    "url": url
                })

        # Raw HTML fallback
        raw_prices = re.findall(r"£\s?\d+\.?\d*", r.text)
        for rp in raw_prices[:5]:
            prices.append({
                "title": soup.title.text if soup.title else "Unknown",
                "price": rp.replace("£",""),
                "url": url
            })

    except:
        pass

    return prices


# -------------------------------------------------------
# 2. GLOBAL SEARCH (Google Search → Real URLs → Scrape)
# -------------------------------------------------------

def google_search(query):
    url = f"https://www.google.com/search?q={query}+buy+wholesale"
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers)
    links = re.findall(r'https://[^\"<>\s]+', r.text)
    clean = [l for l in links if ".jpg" not in l and ".png" not in l]
    return clean[:8]


# -------------------------------------------------------
# 3. AI MATCHING (OpenAI)
# -------------------------------------------------------

def ai_pick_best_match(query, scraped):
    prompt = f"""
You are an AI price finder. Given user query: "{query}", choose the BEST product from below based purely on relevance and cheapest price.

Products:
{scraped}

Return ONLY as JSON: 
{{
 "best_title": "...",
 "best_price": "...",
 "best_url": "..."
}}
"""
    r = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
        max_output_tokens=200
    )
    return r.output[0].content[0].text



# -------------------------------------------------------
# 4. MAIN API ENDPOINT
# -------------------------------------------------------

@app.get("/search")
def search(query: str):
    links = google_search(query)
    results = []

    for link in links:
        prices = extract_prices_from_url(link)
        results.extend(prices)

    if not results:
        return {"error": "No data found"}

    ai_choice = ai_pick_best_match(query, results)
    return {"ai_choice": ai_choice, "all": results}
