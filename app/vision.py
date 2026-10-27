import requests
import base64
import logging
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
VISION_MODEL = "google/gemma-3-12b-it:free"
# Groq text model for every LLM call. gpt-oss-120b follows the prompt rules and invents fewer facts than
# qwen3.8-27b (tested 2026-10-28). It's a reasoning model and its thinking counts toward max_tokens,
# so callers pass GROQ_REASONING and leave headroom.
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_REASONING = "low"
REFUSAL_PREFIXES = (
    "i cannot", "i can't", "i'm unable", "i am unable", "i'm sorry", "i am sorry",
    "sorry,", "unable to", "cannot ", "not sure", "there is no", "no movie",
)


def clean_title(raw: str) -> str:
    """Normalize an LLM reply to a bare title, or 'UNKNOWN' if it isn't one."""
    lines = (raw or "").strip().splitlines()
    title = lines[0].strip().strip("\"'`*.“”‘’").strip() if lines else ""
    low = title.lower()
    # ponytail: a real title ending in "Unknown" is rejected too; rare enough to accept
    if not title or len(title) > 80 or low.split()[-1] == "unknown" or low.startswith(REFUSAL_PREFIXES):
        return "UNKNOWN"
    return title


def ask_vision(images: list, prompt: str) -> str:
    """Send JPEG images + prompt to the vision model. Returns a clean title or 'UNKNOWN'."""
    content = [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(img).decode()}"}}
        for img in images
    ]
    content.append({"type": "text", "text": prompt})
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json"
            },
            json={"model": VISION_MODEL, "messages": [{"role": "user", "content": content}]},
            timeout=30,
        )
        data = response.json()
        if "error" in data:  # free models return rate limits as an error body
            logger.warning("Vision API error: %s", data["error"])
            return "UNKNOWN"
        return clean_title(data["choices"][0]["message"]["content"])
    except Exception:
        logger.exception("Vision API call failed")
        return "UNKNOWN"


def identify_movie_from_image(image_bytes: bytes) -> str:
    # Telegram re-encodes photos as JPEG
    return ask_vision(
        [image_bytes],
        "Look at this image carefully. Identify any movie or TV series shown or mentioned in it — check the caption, text overlays, description, or visual content. Reply with ONLY the movie/series name. If you cannot identify any, reply UNKNOWN."
    )
