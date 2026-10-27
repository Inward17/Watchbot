from groq import Groq
from app.tmdb import search_tmdb, get_details
from app.vision import GROQ_MODEL, GROQ_REASONING
import os
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"), timeout=20)


def get_ratings(titles: list) -> str:
    ratings_text = ""
    for title in titles:
        results = search_tmdb(title)
        if results:
            r = results[0]
            details = get_details(r["id"], r.get("media_type", "movie"))
            rating = details.get("vote_average", "N/A")
            vote_count = details.get("vote_count", 0)
            ratings_text += f"• {title}: ⭐ {rating}/10 ({vote_count} votes)\n"
        else:
            ratings_text += f"• {title}: Rating not found\n"
    return ratings_text or "No ratings found."


def get_recommendation(watchlist: list, user_message: str, history: list = None) -> str:
    if history is None:
        history = []

    watchlist_text = "\n".join([
        f"- {item['title']} ({item['type']}) | Status: {item['status']} | Episodes watched: {item.get('episodes_watched', 'N/A')}"
        for item in watchlist
    ]) or "Empty watchlist"

    # Ratings shortcut
    msg_lower = user_message.lower()
    if any(word in msg_lower for word in ["rating", "imdb", "score", "rated"]):
        ratings = get_ratings([item["title"] for item in watchlist])
        return f"Here are the TMDB ratings:\n\n{ratings}"

    system_prompt = f"""You are WatchBot — a fun, casual movie/series recommendation assistant.

User's watchlist:
{watchlist_text}

Rules:
- When the user wants recommendations, give 2-3 specific ones with a one-line reason each. Never deflect.
- When the user asks about or is trying to identify a specific title, answer about that title only. Don't add extra recommendations or bring up their watchlist.
- Only when recommending: if something is in-progress (status: watching), mention it and ask if they want to continue or try something new.
- The app automatically sends a poster, summary and IMDb link right after your message for every title you bold. If the user asks for an image or picture, bold the title and say the poster is right below. Never say you can't send images.
- Don't name actors, characters or plot details unless you are certain; if unsure, point to the IMDb link instead.
- Never write URLs or IMDb ids yourself; the app adds the correct IMDb button under each poster.
- Keep it short and fun. No long paragraphs.
- Max one question per response.
- Write every movie/series title in **bold**, using its official title. Bold nothing else.
- Use the conversation history to stay in context."""

    messages = [{"role": "system", "content": system_prompt}]
    # Last 6 turns of history for context
    messages.extend(history[-6:])
    messages.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        max_tokens=600,
        reasoning_effort=GROQ_REASONING,
    )
    return response.choices[0].message.content