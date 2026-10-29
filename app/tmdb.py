import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import os
from dotenv import load_dotenv

load_dotenv()

TMDB_KEY = os.getenv("TMDB_API_KEY")
BASE_URL = "https://api.themoviedb.org/3"

# TMDB connections sometimes get reset mid-handshake; retry instead of failing the user's action
session = requests.Session()
session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=5, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504))))

def search_tmdb(query: str):
    url = f"{BASE_URL}/search/multi"
    params = {"api_key": TMDB_KEY, "query": query}
    res = session.get(url, params=params, timeout=10)
    res.raise_for_status()
    results = res.json().get("results", [])
    filtered = [r for r in results if r.get("media_type") in ("movie", "tv")][:5]
    return filtered

def get_details(tmdb_id: int, media_type: str, append: str = None):
    url = f"{BASE_URL}/{media_type}/{tmdb_id}"
    params = {"api_key": TMDB_KEY}
    if append:  # e.g. "external_ids" adds the IMDb id in the same request
        params["append_to_response"] = append
    res = session.get(url, params=params, timeout=10)
    res.raise_for_status()
    return res.json()