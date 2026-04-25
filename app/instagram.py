import yt_dlp
from groq import Groq
import os
from dotenv import load_dotenv

load_dotenv()

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def extract_reel_id(url: str) -> str:
    import re
    match = re.search(r"/reel/([A-Za-z0-9_-]+)", url)
    return match.group(1) if match else None


def get_reel_info(url: str) -> dict:
    """Extract reel metadata using yt-dlp (no login needed for public reels)."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                "title":       info.get("title", ""),
                "description": info.get("description", ""),
                "uploader":    info.get("uploader", ""),
            }
    except Exception as e:
        print(f"yt-dlp Instagram metadata error: {e}")
        return None


def extract_movie_from_reel(reel_info: dict) -> str:
    title       = reel_info.get("title", "")
    description = reel_info.get("description", "")
    uploader    = reel_info.get("uploader", "")

    prompt = f"""Extract the movie or TV series name from this Instagram reel metadata.

Title: "{title}"
Description: "{description}"
Uploader: "{uploader}"

Reply with ONLY the movie or series name. No explanation. No extra words.
Examples of correct replies: "Reacher", "Interstellar", "Breaking Bad"
If no movie/series found, reply: UNKNOWN"""

    response = groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=50,
    )
    return response.choices[0].message.content.strip()