import requests
import base64
import os
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")

def identify_movie_from_image(image_bytes: bytes) -> str:
    img_data = base64.b64encode(image_bytes).decode()
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "google/gemma-3-12b-it:free",
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_data}"}},
                {"type": "text", "text": "Look at this image carefully. Identify any movie or TV series shown or mentioned in it — check the caption, text overlays, description, or visual content. Reply with ONLY the movie/series name. If you cannot identify any, reply UNKNOWN."}
            ]}]
        }
    )
    result = response.json()["choices"][0]["message"]["content"].strip()
    return result