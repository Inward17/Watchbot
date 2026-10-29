from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.constants import ChatAction
from telegram.helpers import escape_markdown
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ApplicationHandlerStop,
    CallbackQueryHandler, TypeHandler, PicklePersistence, filters, ContextTypes
)
from groq import RateLimitError
from pymongo.errors import DuplicateKeyError
from app.database import watchlist_collection, watch_log_collection, check_connection
from app.tmdb import search_tmdb, get_details
from app.recommender import get_recommendation
from app import __version__
from dotenv import load_dotenv
from datetime import datetime, timezone
import asyncio
import html
import logging
import os
import re
from app.youtube import extract_video_id, get_video_info, extract_movie_name
from app.instagram import get_reel_info, extract_movie_from_reel
from app.vision import identify_movie_from_image
from app.frame_extractor import extract_frames_with_timeout, identify_movie_from_frames

load_dotenv()

logger = logging.getLogger(__name__)

# Telegram user ids allowed to use the bot, comma-separated. Empty = anyone (and anyone burns your API quotas)
ALLOWED_USERS = {int(u) for u in os.getenv("ALLOWED_USERS", "").replace(" ", "").split(",") if u}
WATCH_REGION = os.getenv("WATCH_REGION", "IN")  # country for "where to watch", ISO 3166-1 code
BUSY_TEXT = "😮‍💨 I'm getting too many requests right now. Give me a minute and try again!"

COMMANDS = [
    ("add", "Search and add a title"),
    ("list", "Show your watchlist"),
    ("watched", "Log episodes: /watched <title> <n>"),
    ("done", "Mark a title completed"),
    ("hold", "Put a title on hold"),
    ("delete", "Remove a title"),
    ("recommend", "Get a recommendation"),
    ("start", "Help"),
]

# ── Helpers ──────────────────────────────────────────────────────────────────

def get_user_id(update: Update) -> int:
    return update.effective_user.id


async def get_watchlist(user_id: int) -> list:
    return await watchlist_collection.find({"user_id": user_id}).to_list(None)


def esc(text) -> str:
    """Escape user/TMDB text for parse_mode="Markdown" — a stray _ or * makes Telegram reject the reply."""
    return escape_markdown(str(text))


GENERIC_REQUEST_WORDS = {
    "recommend", "suggest", "what", "should", "i", "to", "watch", "me", "a", "an", "some", "something",
    "anything", "please", "pls", "can", "could", "you", "u", "movie", "movies", "show", "shows", "series",
    "good", "new", "tonight", "today", "now", "hey", "hi", "bot", "give", "any", "for",
}


def is_open_request(text: str) -> bool:
    """True for "what should I watch?", False once the user names anything specific ("comedy sitcoms")."""
    return all(word in GENERIC_REQUEST_WORDS for word in re.findall(r"[a-z']+", text.lower()))


def md_to_html(text: str) -> str:
    """Render the LLM's **bold** / *italic* as Telegram HTML; everything else is escaped."""
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"<b>_(.+?)_</b>", r"<b><i>\1</i></b>", text)  # **_Title_**
    return re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)


POSTER_URL = "https://image.tmdb.org/t/p/w500"


TYPOGRAPHIC_TO_ASCII = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "’": "'", "‘": "'", "“": '"', "”": '"'})


def titles_in(response: str) -> list:
    """Candidate titles the AI bolded (**Severance**, **Ted Lasso:**), max 8.
    Bold labels like **Why it fits:** come through too; lookup_title drops them (no exact TMDB match)."""
    titles = []
    for t in re.findall(r"\*\*(.+?)\*\*", response):
        t = t.strip(" *_:")  # the AI nests italics (**_Black-ish_**) and bolds colons (**Ted Lasso:**)
        t = t.translate(TYPOGRAPHIC_TO_ASCII)  # "Nine‑Nine" (U+2011), "Schitt’s" → plain text TMDB search finds
        if t and t.lower() not in (s.lower() for s in titles):
            titles.append(t)
    return titles[:8]


def same_title(a: str, b: str) -> bool:
    """Title match ignoring case and punctuation ("Black-ish" == "black-ish", "Spider-Man: X" == "Spider-Man X")."""
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    return norm(a) == norm(b)


def match_items(items: list, query: str) -> list:
    """Watchlist items the user means by `query`. An exact title wins ("dark" is Dark, not The Dark Knight);
    otherwise every title containing the query, so the caller can ask which one."""
    exact = [i for i in items if same_title(i["title"], query)]
    return exact or [i for i in items if query.lower().strip() in i["title"].lower()]


def providers_line(region: dict) -> str:
    """'📺 Netflix, Prime Video' from one country's TMDB watch/providers entry; rent/buy only if nothing streams it."""
    def names(*kinds):
        seen = []
        for kind in kinds:
            for p in region.get(kind, []):
                # Skip variants of a service already listed ("Amazon Prime Video with Ads", "Apple TV Amazon Channel")
                if not any(p["provider_name"].startswith(s) for s in seen):
                    seen.append(p["provider_name"])
        return seen[:3]
    if streaming := names("flatrate", "free", "ads"):
        return "📺 " + ", ".join(streaming)
    if paid := names("rent", "buy"):
        return "💳 Rent/buy: " + ", ".join(paid)
    return ""


def lookup_title(title: str):
    """Exact-name TMDB match that has a poster, plus its IMDb id. None when nothing matches exactly,
    so a wrong show ("A Modern Family") or a bold label never becomes a card. Blocking — run in a thread."""
    # "Get Smart (2008)", "Dark (TV Series)", "Players (2022 TV)": TMDB search needs the bare name
    m = re.fullmatch(r"(.+?)\s*\(([^()]*)\)", title)
    name = m.group(1) if m else title
    year_m = re.search(r"\b(19|20)\d{2}\b", m.group(2)) if m else None
    year = year_m.group(0) if year_m else None
    matches = [
        r for r in search_tmdb(name)
        if r.get("poster_path") and same_title(r.get("title") or r.get("name", ""), name)
    ]
    if year:  # 2008 movie, not the 1965 TV series. ±1: release vs premiere years differ by region
        released = lambda r: (r.get("release_date") or r.get("first_air_date") or "0")[:4]
        matches = [r for r in matches if abs(int(released(r)) - int(year)) <= 1]
    if not matches:
        return None
    r = matches[0]
    details = get_details(r["id"], r["media_type"], append="external_ids,watch/providers")
    region = details.get("watch/providers", {}).get("results", {}).get(WATCH_REGION, {})
    return r, details.get("external_ids", {}).get("imdb_id"), providers_line(region)


async def send_title_cards(message, response: str, watchlist: list):
    """After an AI reply: up to 3 poster cards with Add and IMDb buttons, skipping titles already on the watchlist."""
    try:
        found = await asyncio.gather(
            *(asyncio.to_thread(lookup_title, t) for t in titles_in(response)), return_exceptions=True
        )
        hits = list({f[0]["id"]: f for f in found if isinstance(f, tuple)}.values())  # dedupe by TMDB id
        if len(hits) > 1:  # a list of picks: skip what's already on the watchlist. One title = the user asked about it
            on_list = {item["tmdb_id"] for item in watchlist}
            hits = [h for h in hits if h[0]["id"] not in on_list]
        for r, imdb_id, where in hits[:3]:
            name = r.get("title") or r.get("name", "Unknown")
            year = (r.get("release_date") or r.get("first_air_date") or "")[:4]
            caption = f"<b>{html.escape(name, quote=False)}</b>" + (f" ({year})" if year else "") + f" · {r['media_type'].upper()}"
            if r.get("vote_average"):
                caption += f" · ⭐ {r['vote_average']:.1f}"
            if where:
                caption += f"\n{html.escape(where, quote=False)} <i>(JustWatch)</i>"
            overview = r.get("overview", "")
            if overview:
                caption += "\n\n" + html.escape(overview[:300] + ("…" if len(overview) > 300 else ""), quote=False)
            if imdb_id:
                link_label, link = "IMDb", f"https://www.imdb.com/title/{imdb_id}/"
            else:
                link_label, link = "TMDB", f"https://www.themoviedb.org/{r['media_type']}/{r['id']}"
            buttons = InlineKeyboardMarkup([[
                InlineKeyboardButton("➕ Add", callback_data=f"add_{r['id']}_{r['media_type']}"),
                InlineKeyboardButton(link_label, url=link),
            ]])
            await message.reply_photo(POSTER_URL + r["poster_path"], caption=caption, parse_mode="HTML", reply_markup=buttons)
    except Exception:
        logger.exception("Title cards failed")  # the text reply already went out; cards are a bonus


async def offer_matches(update: Update, context: ContextTypes.DEFAULT_TYPE, movie_name: str):
    await update.message.reply_text(f"🎬 Found: *{esc(movie_name)}*\nSearching TMDB...", parse_mode="Markdown")
    # Let follow-ups ("tell me more", "show the poster") know what this link/image was
    append_history(context, "user", "[sent a video link or image]")
    append_history(context, "assistant", f"That's from **{movie_name}**.")
    query = re.sub(r"\s*\(\d{4}\)$", "", movie_name)  # TMDB finds nothing for "Get Smart (2008)"
    results = await asyncio.to_thread(search_tmdb, query)
    if not results:
        await ask_for_title(update, context, f"Couldn't find '{movie_name}' on TMDB. Type the exact name and I'll search again.")
        return
    await send_pick_list(update, context, results, "Is this what you meant? Pick one to add:")


async def ask_for_title(update: Update, context: ContextTypes.DEFAULT_TYPE, message: str):
    """Identification failed — the user's next text message is treated as the title (see handle_message)."""
    context.user_data["awaiting_title"] = True
    await update.message.reply_text(message)


def match_label(i: int, r: dict) -> str:
    """'2. Players (2022) — TV': same text on the poster album and the pick button, so they line up."""
    title = r.get("title") or r.get("name", "Unknown")
    year = (r.get("release_date") or r.get("first_air_date") or "")[:4]
    return f"{i}. {title}" + (f" ({year})" if year else "") + f" — {r.get('media_type', 'movie').upper()}"


def build_tmdb_keyboard(results: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(match_label(i, r), callback_data=f"add_{r['id']}_{r.get('media_type', 'movie')}")]
        for i, r in enumerate(results, 1)
    ])


async def send_pick_list(update: Update, context: ContextTypes.DEFAULT_TYPE, results: list, text: str):
    """TMDB matches as a numbered poster album, then numbered pick buttons. Same-named titles
    ("Players" x5) are impossible to tell apart from text buttons alone."""
    posters = [
        InputMediaPhoto(POSTER_URL + r["poster_path"], caption=f"{match_label(i, r)}\n{(r.get('overview') or '')[:150]}")
        for i, r in enumerate(results, 1) if r.get("poster_path")
    ]
    try:
        if len(posters) > 1:
            await update.message.reply_media_group(posters)
        elif posters:
            await update.message.reply_photo(posters[0].media, caption=posters[0].caption)
    except Exception:
        logger.exception("Poster album failed")  # the buttons below still work without it
    await update.message.reply_text(text, reply_markup=build_tmdb_keyboard(results))
    # So "which one is it?" / "show me the posters" follow-ups know what the options were
    append_history(context, "assistant", "I showed these options with posters: " + "; ".join(
        match_label(i, r) for i, r in enumerate(results, 1)))


def mood_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔥 Action",   callback_data="mood_Action"),
            InlineKeyboardButton("🔪 Thriller", callback_data="mood_Thriller"),
        ],
        [
            InlineKeyboardButton("💕 Romance",  callback_data="mood_Romance"),
            InlineKeyboardButton("😂 Comedy",   callback_data="mood_Comedy"),
        ],
        [
            InlineKeyboardButton("🚀 Sci-Fi",   callback_data="mood_Sci-Fi"),
            InlineKeyboardButton("😱 Horror",   callback_data="mood_Horror"),
        ],
        [
            InlineKeyboardButton("🎭 Drama",    callback_data="mood_Drama"),
            InlineKeyboardButton("🎲 Surprise me!", callback_data="mood_Any"),
        ],
    ])


async def log_watch_event(user_id: int, tmdb_id: int, title: str, action: str, episodes: int = 0):
    try:
        await watch_log_collection.insert_one({
            "user_id": user_id,
            "tmdb_id": tmdb_id,
            "title": title,
            "action": action,
            "episodes": episodes,
            "timestamp": datetime.now(timezone.utc),
        })
    except Exception:
        logger.exception("Failed to write watch log")  # non-critical, don't fail the command


def append_history(context: ContextTypes.DEFAULT_TYPE, role: str, content: str):
    history = context.user_data.setdefault("history", [])
    history.append({"role": role, "content": content})
    context.user_data["history"] = history[-10:]  # keep last 10 turns


# ── Commands ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 Hey! I'm your personal watchlist bot.\n\n"
        "*Commands:*\n"
        "/add <title> — Add a movie/series\n"
        "/list — View your watchlist\n"
        "/watched <title> <episodes> — Update progress\n"
        "/done <title> — Mark as completed\n"
        "/hold <title> — Put on hold\n"
        "/recommend — Get a recommendation\n"
        "/delete <title> — Remove from list\n\n"
        "*You can also:*\n"
        "📎 Send a YouTube, Shorts or Instagram Reel link\n"
        "📸 Send a screenshot from a movie\n"
        "💬 Just chat: \"something like Dark\", \"where can I watch Severance?\"\n\n"
        f"_WatchBot v{__version__}_",
        parse_mode="Markdown"
    )


async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /add <title>")
        return
    query = " ".join(context.args)
    context.user_data["pending_add_source"] = "command"
    try:
        results = await asyncio.to_thread(search_tmdb, query)
        if not results:
            await update.message.reply_text("Nothing found on TMDB. Try a different title.")
            return
        await send_pick_list(update, context, results, "Which one?")
    except Exception:
        logger.exception("Handler error")
        await update.message.reply_text("⚠️ Couldn't reach TMDB right now. Try again in a moment.")


async def list_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id(update)
    status_emoji = {
        "plan_to_watch": "📌",
        "watching":      "▶️",
        "on_hold":       "⏸️",
        "completed":     "✅",
    }
    try:
        items = await get_watchlist(user_id)
        if not items:
            await update.message.reply_text("Your watchlist is empty. Use /add to get started!")
            return
        text = "🎬 *Your Watchlist:*\n\n"
        for item in items:
            emoji = status_emoji.get(item["status"], "•")
            ep = (
                f" — Ep {item.get('episodes_watched', 0)}/{item.get('total_episodes') or '?'}"
                if item["type"] == "tv" else ""
            )
            text += f"{emoji} *{esc(item['title'])}* ({item['type'].upper()}){ep}\n"
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception:
        logger.exception("Handler error")
        await update.message.reply_text("⚠️ Couldn't fetch your watchlist right now.")


async def apply_action(user_id: int, item: dict, action: str, episodes: int = 0) -> str:
    """Apply a watchlist change, log it, and return the Markdown reply.
    action: "progress" (add `episodes`), "completed", "on_hold" or "removed"."""
    title, now = item["title"], datetime.now(timezone.utc)
    if action == "removed":
        await watchlist_collection.delete_one({"_id": item["_id"]})
        await log_watch_event(user_id, item["tmdb_id"], title, action)
        return f"🗑️ Removed *{esc(title)}* from your watchlist."

    changes = {"last_updated": now}
    if action == "progress":
        new_count = item.get("episodes_watched", 0) + episodes
        status = "completed" if (item.get("total_episodes") and new_count >= item["total_episodes"]) else "watching"
        changes.update(episodes_watched=new_count, status=status)
        if status == "completed":
            changes["completed_at"] = now
        reply = f"✅ Updated! *{esc(title)}* — {new_count} episodes watched. Status: {status}"
    elif action == "completed":
        changes.update(status="completed", completed_at=now)
        reply = f"🎉 Marked *{esc(title)}* as completed!"
    else:
        changes["status"] = "on_hold"
        reply = f"⏸️ Put *{esc(title)}* on hold at episode {item.get('episodes_watched', 0)}. I'll remember where you left off!"
    await watchlist_collection.update_one({"_id": item["_id"]}, {"$set": changes})
    await log_watch_event(user_id, item["tmdb_id"], title, action, episodes)
    return reply


async def act_on_title(message, user_id: int, items: list, query: str, action: str, episodes: int = 0) -> bool:
    """Run `action` on the watchlist title the user named. Several matches → "Which one?" buttons.
    Returns False when nothing matches, so callers can reply or fall through to the AI."""
    matches = match_items(items, query)
    if not matches:
        return False
    if len(matches) > 1:
        await message.reply_text("Which one?", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(i["title"], callback_data=f"act_{action}_{episodes}_{i['tmdb_id']}")]
            for i in matches[:8]
        ]))
        return True
    await message.reply_text(await apply_action(user_id, matches[0], action, episodes), parse_mode="Markdown")
    return True


async def title_command(update: Update, query: str, action: str, episodes: int = 0):
    """Shared body of /watched, /done, /hold and /delete."""
    try:
        user_id = get_user_id(update)
        items = await get_watchlist(user_id)
        if not await act_on_title(update.message, user_id, items, query, action, episodes):
            await update.message.reply_text(f"Couldn't find '{query}' in your watchlist.")
    except Exception:
        logger.exception("Handler error")
        await update.message.reply_text("⚠️ Couldn't update your watchlist. Try again.")


async def watched(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2 or not context.args[-1].isdigit():
        await update.message.reply_text("Usage: /watched <title> <number of episodes>")
        return
    await title_command(update, " ".join(context.args[:-1]), "progress", int(context.args[-1]))


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /done <title>")
        return
    await title_command(update, " ".join(context.args), "completed")


async def hold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /hold <title>")
        return
    await title_command(update, " ".join(context.args), "on_hold")


async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /delete <title>")
        return
    await title_command(update, " ".join(context.args), "removed")


async def recommend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id(update)
    try:
        items = await get_watchlist(user_id)
        in_progress = [i for i in items if i["status"] == "watching"]

        if in_progress:
            keyboard = []
            for show in in_progress[:3]:
                ep = show.get("episodes_watched", 0)
                total = show.get("total_episodes") or "?"
                label = f"▶️ Continue {show['title']} (Ep {ep}/{total})"
                keyboard.append([InlineKeyboardButton(label, callback_data=f"rec_continue_{show['tmdb_id']}")])
            keyboard.append([InlineKeyboardButton("🆕 Something new!", callback_data="rec_new")])

            if len(in_progress) == 1:
                msg = f"You're still watching *{esc(in_progress[0]['title'])}* — continue or try something new?"
            else:
                msg = "You've got shows in progress 👀 — continue one or try something new?"

            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await update.message.reply_text("🎭 What are we feeling today?", reply_markup=mood_keyboard())
    except Exception:
        logger.exception("Handler error")
        await update.message.reply_text("⚠️ Something went wrong. Try again!")


# ── Callback / button handler ─────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    # ── Add item from TMDB results ──
    if data.startswith("add_"):
        _, tmdb_id, media_type = data.split("_", 2)
        on_card = bool(query.message.photo)  # poster card from send_title_cards
        added_from = "recommendation" if on_card else context.user_data.pop("pending_add_source", "command")

        async def say(text):
            # A photo has no text to edit: keep the card and answer underneath it
            if on_card:
                await query.message.reply_text(text)
            else:
                await query.edit_message_text(text)

        try:
            details = await asyncio.to_thread(get_details, int(tmdb_id), media_type)
            title = details.get("title") or details.get("name", "Unknown")
            genres = [g["name"] for g in details.get("genres", [])]
            total_episodes = details.get("number_of_episodes")

            try:
                await watchlist_collection.insert_one({
                    "user_id":          user_id,
                    "tmdb_id":          int(tmdb_id),
                    "title":            title,
                    "type":             media_type,
                    "status":           "plan_to_watch",
                    "episodes_watched": 0,
                    "total_episodes":   total_episodes,
                    "genres":           genres,
                    "added_from":       added_from,
                    "added_at":         datetime.now(timezone.utc),
                })
            except DuplicateKeyError:  # unique (user_id, tmdb_id) index
                await say(f"'{title}' is already in your watchlist!")
                return
            await log_watch_event(user_id, int(tmdb_id), title, "added")
            await say(f"✅ Added '{title}' to your watchlist!")
        except Exception:
            logger.exception("Handler error")
            await say("⚠️ Something went wrong adding that. Try again.")

    # ── "Which one?" pick after an ambiguous /done, /hold, /delete or progress update ──
    elif data.startswith("act_"):
        prefix, episodes, tmdb_id = data.rsplit("_", 2)  # "act_on_hold_0_1234"
        try:
            item = await watchlist_collection.find_one({"user_id": user_id, "tmdb_id": int(tmdb_id)})
            if item:
                await query.edit_message_text(
                    await apply_action(user_id, item, prefix[len("act_"):], int(episodes)), parse_mode="Markdown")
            else:
                await query.edit_message_text("That title isn't in your watchlist anymore.")
        except Exception:
            logger.exception("Handler error")
            await query.edit_message_text("⚠️ Couldn't update your watchlist. Try again.")

    # ── Continue an in-progress show ──
    elif data.startswith("rec_continue_"):
        tmdb_id = int(data.split("_")[2])
        try:
            item = await watchlist_collection.find_one({"user_id": user_id, "tmdb_id": tmdb_id})
            if item:
                ep = item.get("episodes_watched", 0)
                total = item.get("total_episodes") or "?"
                msg = f"🎬 Let's continue *{esc(item['title'])}*!\nYou're on episode {ep}/{total}. Enjoy! 🍿"
                await query.edit_message_text(msg, parse_mode="Markdown")
                append_history(context, "assistant", msg)
            else:
                await query.edit_message_text("Couldn't find that show in your watchlist.")
        except Exception:
            logger.exception("Handler error")
            await query.edit_message_text("⚠️ Something went wrong. Try again.")

    # ── User wants something new → show mood picker ──
    elif data == "rec_new":
        await query.edit_message_text("🎭 What are we feeling today?", reply_markup=mood_keyboard())

    # ── Mood selected → get recommendation ──
    elif data.startswith("mood_"):
        genre = data.split("_", 1)[1]
        mood_msg = f"Surprise me with something great" if genre == "Any" else f"Recommend something in {genre}"
        try:
            items = await get_watchlist(user_id)
            await query.edit_message_text("🤔 Thinking...")
            await query.message.chat.send_action(ChatAction.TYPING)
            history = context.user_data.get("history", [])
            response = await asyncio.to_thread(get_recommendation, items, mood_msg, history)
            append_history(context, "user", mood_msg)
            append_history(context, "assistant", response)
            await query.edit_message_text(md_to_html(response), parse_mode="HTML")
            await send_title_cards(query.message, response, items)
        except RateLimitError:
            await query.edit_message_text(BUSY_TEXT)
        except Exception:
            logger.exception("Handler error")
            await query.edit_message_text("⚠️ AI is having a moment. Try again soon!")


# ── Media / link handlers ─────────────────────────────────────────────────────

async def handle_youtube(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = re.search(r"https?://\S+", update.message.text).group()
    video_id = extract_video_id(url)
    if not video_id:
        await update.message.reply_text("Couldn't parse that YouTube link.")
        return

    context.user_data["pending_add_source"] = "youtube"
    context.user_data.pop("awaiting_title", None)
    await update.message.reply_text("🔍 Checking that link...")
    try:
        video_info = await asyncio.to_thread(get_video_info, video_id)
        if not video_info:
            await update.message.reply_text("Couldn't fetch video info.")
            return

        movie_name = await asyncio.to_thread(extract_movie_name, video_info)

        if movie_name == "UNKNOWN":
            await update.message.reply_text("🎬 Title unclear, analyzing frames... (up to 20s)")
            frames = await extract_frames_with_timeout(url, num_frames=3, timeout=20)
            if frames:
                movie_name = await asyncio.to_thread(identify_movie_from_frames, frames)

        if movie_name == "UNKNOWN":
            await ask_for_title(
                update, context,
                "📹 Couldn't identify a movie/show from this video.\n"
                "What movie/show is it from? Just type the name!"
            )
            return

        await offer_matches(update, context, movie_name)
    except Exception:
        logger.exception("YouTube handler error")
        await update.message.reply_text("⚠️ Something went wrong processing that link. Try again.")


async def handle_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = re.search(r"https?://\S+", update.message.text).group()
    context.user_data["pending_add_source"] = "instagram"
    context.user_data.pop("awaiting_title", None)
    await update.message.reply_text("🔍 Checking that reel...")
    try:
        movie_name = "UNKNOWN"

        # Step 1: try metadata scraping (fast, often blocked by Instagram)
        reel_info = await asyncio.to_thread(get_reel_info, url)
        if reel_info:
            movie_name = await asyncio.to_thread(extract_movie_from_reel, reel_info)

        # Step 2: metadata failed → download reel via yt-dlp and analyze frames
        if movie_name == "UNKNOWN":
            await update.message.reply_text("📸 Caption unclear, analyzing the reel visually... (up to 20s)")
            frames = await extract_frames_with_timeout(url, num_frames=3, timeout=20)
            if frames:
                movie_name = await asyncio.to_thread(identify_movie_from_frames, frames)

        # Step 3: still unknown → ask the user
        if movie_name == "UNKNOWN":
            await ask_for_title(
                update, context,
                "📱 Couldn't identify the movie from this reel.\n"
                "What movie/show is it from? Just type the name!"
            )
            return

        await offer_matches(update, context, movie_name)
    except Exception:
        logger.exception("Instagram handler error")
        await update.message.reply_text("⚠️ Something went wrong. Try again.")


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["pending_add_source"] = "image"
    context.user_data.pop("awaiting_title", None)
    await update.message.reply_text("🔍 Analyzing image...")
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        movie_name = await asyncio.to_thread(identify_movie_from_image, bytes(image_bytes))

        if movie_name == "UNKNOWN":
            await ask_for_title(
                update, context,
                "Couldn't identify a movie/show from this image.\n"
                "What movie is it from? Just type the name!"
            )
            return

        await offer_matches(update, context, movie_name)
    except Exception:
        logger.exception("Image handler error")
        await update.message.reply_text("⚠️ Something went wrong analyzing that image.")


# ── Natural language message handler ─────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    user_id = get_user_id(update)

    try:
        # ── Reply to "Just type the name!" after a failed link/image identification ──
        if context.user_data.pop("awaiting_title", False):
            await offer_matches(update, context, update.message.text.strip())
            return

        items = await get_watchlist(user_id)

        # ── Progress update: "watched 5 episodes of Dark" ──
        patterns = [
            r"watched\s+(\d+)\s+episodes?\s+of\s+(.+)",
            r"watched\s+(.+?)\s+(\d+)\s+episodes?",
            r"(\d+)\s+episodes?\s+of\s+(.+)",
            r"finished\s+(\d+)\s+episodes?\s+of\s+(.+)",
        ]
        for pattern in patterns:
            m = re.search(pattern, text)
            if m:
                g = m.groups()
                if g[0].isdigit():
                    episodes, title_query = int(g[0]), g[1].strip()
                else:
                    title_query, episodes = g[0].strip(), int(g[1])

                if not await act_on_title(update.message, user_id, items, title_query, "progress", episodes):
                    await update.message.reply_text("Couldn't find that title in your watchlist. Use /add to add it first.")
                return

        # ── Mark completed: "finished Dark". No watchlist match → it's chat, let the AI answer ──
        done_m = re.search(r"\b(finished|completed|done watching)\s+(.+)", text)
        if done_m and await act_on_title(update.message, user_id, items, done_m.group(2).strip(), "completed"):
            return

        # ── Put on hold: "hold Dark" / "put Dark on hold" ──
        hold_m = re.search(r"\b(hold|pause|break from|bored of|stop watching)\s+(.+)|\bput\s+(.+?)\s+on\s+hold", text)
        if hold_m and await act_on_title(update.message, user_id, items, (hold_m.group(2) or hold_m.group(3)).strip(), "on_hold"):
            return

        # ── Quick-add: "add Dark" ──
        add_m = re.search(r"^add\s+(.+)", text)
        if add_m:
            title_query = add_m.group(1).strip()
            context.user_data["pending_add_source"] = "command"
            results = await asyncio.to_thread(search_tmdb, title_query)
            if not results:
                await update.message.reply_text("Nothing found on TMDB.")
                return
            await send_pick_list(update, context, results, "Which one?")
            return

        # ── Recommend shortcut: open requests get buttons; specific ones ("comedy sitcoms") fall through to the AI ──
        if any(kw in text for kw in ["recommend", "what to watch", "suggest", "what should i watch"]) and is_open_request(text):
            await recommend(update, context)
            return

        # ── Default: AI conversation with history ──
        await update.message.chat.send_action(ChatAction.TYPING)
        history = context.user_data.get("history", [])
        response = await asyncio.to_thread(get_recommendation, items, update.message.text, history)
        append_history(context, "user", update.message.text)
        append_history(context, "assistant", response)
        await update.message.reply_text(md_to_html(response), parse_mode="HTML")
        await send_title_cards(update.message, response, items)

    except RateLimitError:
        await update.message.reply_text(BUSY_TEXT)
    except Exception:
        logger.exception("Handler error")
        await update.message.reply_text("⚠️ Something went wrong. Try again!")


# ── App setup ─────────────────────────────────────────────────────────────────

async def gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Runs before every handler: drop updates from users not in ALLOWED_USERS."""
    user = update.effective_user
    if not ALLOWED_USERS or (user and user.id in ALLOWED_USERS):
        return
    logger.warning("Blocked user %s (add to ALLOWED_USERS to allow)", user and user.id)
    if update.callback_query:
        await update.callback_query.answer("This bot is private.")
    elif update.effective_message:
        await update.effective_message.reply_text("🔒 This is a private bot.")
    raise ApplicationHandlerStop


async def post_init(app: Application):
    await app.bot.set_my_commands(COMMANDS)  # fills Telegram's "/" menu


def run_bot():
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # PTB logs every poll otherwise
    check_connection()
    if not ALLOWED_USERS:
        logger.warning("ALLOWED_USERS is empty: anyone who finds the bot can use it and your API quotas")
    app = (
        Application.builder()
        .token(os.getenv("TELEGRAM_BOT_TOKEN"))
        .persistence(PicklePersistence(filepath="bot_data.pickle"))  # chat history survives restarts
        .post_init(post_init)
        .build()
    )

    app.add_handler(TypeHandler(Update, gate), group=-1)

    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("add",      add))
    app.add_handler(CommandHandler("list",     list_watchlist))
    app.add_handler(CommandHandler("watched",  watched))
    app.add_handler(CommandHandler("done",     done))
    app.add_handler(CommandHandler("hold",     hold))
    app.add_handler(CommandHandler("delete",   delete))
    app.add_handler(CommandHandler("recommend", recommend))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(
        filters.Regex(r'https?://(www\.)?(youtube\.com|youtu\.be)/\S+'), handle_youtube
    ))
    app.add_handler(MessageHandler(
        filters.Regex(r'https?://(www\.)?instagram\.com/reel/\S+'), handle_instagram
    ))
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print(f"🤖 WatchBot v{__version__} is running...")
    app.run_polling()