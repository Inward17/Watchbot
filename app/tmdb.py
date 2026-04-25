import requests
import os
from dotenv import load_dotenv

load_dotenv()

TMDB_KEY = os.getenv("TMDB_API_KEY")
BASE_URL = "https://api.themoviedb.org/3"

def search_tmdb(query: str):
    url = f"{BASE_URL}/search/multi"
    params = {"api_key": TMDB_KEY, "query": query}
    res = requests.get(url, params=params).json()
    results = res.get("results", [])
    filtered = [r for r in results if r.get("media_type") in ("movie", "tv")][:5]
    return filtered

def get_details(tmdb_id: int, media_type: str):
    url = f"{BASE_URL}/{media_type}/{tmdb_id}"
    params = {"api_key": TMDB_KEY}
    return requests.get(url, params=params).json()