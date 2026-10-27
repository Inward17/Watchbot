from googleapiclient.discovery import build
from groq import Groq
import os, re
from dotenv import load_dotenv
from app.vision import clean_title, GROQ_MODEL, GROQ_REASONING

load_dotenv()

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"), timeout=20)

def extract_video_id(url: str) -> str:
    patterns = [
        r"youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})",
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
        r"youtube\.com/shorts/([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_video_info(video_id: str) -> dict:
    youtube = build("youtube", "v3", developerKey=os.getenv("YOUTUBE_API_KEY"))
    response = youtube.videos().list(
        part="snippet",
        id=video_id
    ).execute()
    items = response.get("items", [])
    if not items:
        return None
    snippet = items[0]["snippet"]
    return {
        "title": snippet.get("title", ""),
        "description": snippet.get("description", "")[:500],  # first 500 chars
        "tags": snippet.get("tags", [])[:10],  # first 10 tags
    }

def extract_movie_name(video_info: dict) -> str:
    title = video_info.get("title", "")
    description = video_info.get("description", "")
    tags = ", ".join(video_info.get("tags", []))

    prompt = f"""You are helping identify a movie or TV series from a YouTube video's metadata.

Video title: "{title}"
Video description: "{description}"
Video tags: "{tags}"

Based on ALL of the above information, extract the movie or TV series name being referenced.
Reply with ONLY the movie/series name, nothing else.
If you absolutely cannot identify any specific movie or series, reply with "UNKNOWN"."""

    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        reasoning_effort=GROQ_REASONING,
    )
    return clean_title(response.choices[0].message.content)