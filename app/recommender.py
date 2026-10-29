import json
from app.tmdb import search_tmdb
from app.vision import groq_chat

SEARCH_TOOL = {"type": "function", "function": {
    "name": "search_titles",
    "description": "Search TMDB for movies and series whose title contains these words. "
                   "Returns official title, year, type, TMDB rating and synopsis. Matches titles only: "
                   "adding plot words (e.g. 'Remorse FBI') returns nothing, so pass just the title words "
                   "and check the synopses against the other clues yourself.",
    "parameters": {"type": "object", "required": ["query"],
                   "properties": {"query": {"type": "string", "description": "Words from the title"}}},
}}


def search_titles(query: str) -> str:
    lines = []
    for r in search_tmdb(query):
        name = r.get("title") or r.get("name")
        year = (r.get("release_date") or r.get("first_air_date") or "")[:4] or "?"
        rating = f", rated {r['vote_average']:.1f}/10" if r.get("vote_count") else ""
        lines.append(f"{name} ({year}, {r['media_type']}{rating}): {(r.get('overview') or '')[:200]}")
    return "\n".join(lines) or "No matches."


def watchlist_summary(watchlist: list, limit: int = 40) -> str:
    """Compact watchlist for the prompt, most recently touched first. Every token counts against
    Groq's free-tier per-minute cap, so long lists are cut to the latest `limit` titles."""
    recent = sorted(watchlist, key=lambda i: str(i.get("last_updated") or i.get("added_at") or ""), reverse=True)
    lines = []
    for item in recent[:limit]:
        line = f"- {item['title']} ({item['type']}): {item['status']}"
        if item["type"] == "tv" and item.get("episodes_watched"):
            line += f", ep {item['episodes_watched']}"
        lines.append(line)
    if len(watchlist) > limit:
        lines.append(f"(+{len(watchlist) - limit} older titles)")
    return "\n".join(lines) or "Empty watchlist"


def get_recommendation(watchlist: list, user_message: str, history: list = None) -> str:
    if history is None:
        history = []

    system_prompt = f"""You are WatchBot — a fun, casual movie/series recommendation assistant.

User's watchlist:
{watchlist_summary(watchlist)}

Rules:
- When the user wants recommendations, give 2-3 specific ones with a one-line reason each. Never deflect.
- When the user asks about a specific title, answer about that title only. Don't add extra recommendations or bring up their watchlist.
- When the user is trying to identify a title, combine every clue from the conversation. If they remember any word of the title, call search_titles with it and pick the results that fit the other clues. People misremember details, so name the closest 1-3 matches even if one clue doesn't fit. Bold each with its year and a few words from its synopsis, and say plainly which clue doesn't match instead of bending the plot to fit; the app shows each poster so they can confirm. Only ask a question if there's no candidate at all, and never put plot details you're unsure of into a question.
- Only when recommending: if something is in-progress (status: watching), mention it and ask if they want to continue or try something new.
- The app automatically sends a poster, rating, summary, streaming services and IMDb link right after your message for every title you bold. Never say you can't send images, and don't mention posters unless the user asked for one. For "where can I watch X", bold X and say the card below lists where it's streaming.
- For ratings, call search_titles and quote the TMDB rating it returns; never guess a rating.
- Don't state actors, characters, years or plot details unless you are certain.
- Never write URLs or IMDb ids yourself; the app adds the correct IMDb button under each poster.
- Keep it short and fun. No long paragraphs.
- Max one question per response.
- Write every movie/series title in **bold**, using its official title (exactly as search_titles returns it, if you searched). Bold nothing else.
- Use the conversation history to stay in context."""

    messages = [{"role": "system", "content": system_prompt}]
    # Last 6 turns of history for context
    messages.extend(history[-6:])
    messages.append({"role": "user", "content": user_message})

    # Up to 2 search rounds, then force a text answer
    for round_ in range(3):
        response = groq_chat(
            messages=messages,
            max_tokens=800,  # includes reasoning; Groq free tier allows 8000 tokens/min
            temperature=0.4,  # lower = fewer made-up details
            tools=[SEARCH_TOOL],
            tool_choice="auto" if round_ < 2 else "none",
        )
        msg = response.choices[0].message
        if not msg.tool_calls:
            return msg.content
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            query = json.loads(tc.function.arguments or "{}").get("query", "")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": search_titles(query)})
