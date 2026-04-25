from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from app.database import watchlist_collection, watch_log_collection
from app.tmdb import search_tmdb, get_details
from app.recommender import get_recommendation
from dotenv import load_dotenv
from datetime import datetime, timezone
import os
import re
from app.youtube import extract_video_id, get_video_info, extract_movie_name
from app.instagram import get_reel_info, extract_movie_from_reel
from app.vision import identify_movie_from_image
from app.frame_extractor import extract_frames_with_timeout, identify_movie_from_frames

load_dotenv()

# ── Helpers ──────────────────────────────────────────────────────────────────

def get_user_id(update: Update) -> int:
    return update.effective_user.id


def build_tmdb_keyboard(results: list) -> InlineKeyboardMarkup:
    keyboard = []
    for r in results:
        title = r.get("title") or r.get("name", "Unknown")
        year = (r.get("release_date") or r.get("first_air_date", ""))[:4]
        media_type = r.get("media_type", "movie")
        label = f"{title} ({year}) — {media_type.upper()}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"add_{r['id']}_{media_type}")])
    return InlineKeyboardMarkup(keyboard)


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
        pass  # log failures are non-critical


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
        "📎 Send a YouTube / Shorts link\n"
        "📸 Send a screenshot from a movie\n"
        "💬 Just chat naturally!",
        parse_mode="Markdown"
    )


async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /add <title>")
        return
    query = " ".join(context.args)
    context.user_data["pending_add_source"] = "command"
    try:
        results = search_tmdb(query)
        if not results:
            await update.message.reply_text("Nothing found on TMDB. Try a different title.")
            return
        await update.message.reply_text("Which one?", reply_markup=build_tmdb_keyboard(results))
    except Exception:
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
        items = await watchlist_collection.find({"user_id": user_id}).to_list(100)
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
            text += f"{emoji} *{item['title']}* ({item['type'].upper()}){ep}\n"
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("⚠️ Couldn't fetch your watchlist right now.")


async def watched(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /watched <title> <episodes>")
        return
    try:
        episodes = int(context.args[-1])
        title_query = " ".join(context.args[:-1]).lower()
    except ValueError:
        await update.message.reply_text("Usage: /watched <title> <number of episodes>")
        return
    user_id = get_user_id(update)
    try:
        items = await watchlist_collection.find({"user_id": user_id}).to_list(100)
        match = next((i for i in items if title_query in i["title"].lower()), None)
        if not match:
            await update.message.reply_text(f"Couldn't find '{title_query}' in your watchlist.")
            return
        new_count = match.get("episodes_watched", 0) + episodes
        status = "completed" if (match.get("total_episodes") and new_count >= match["total_episodes"]) else "watching"
        await watchlist_collection.update_one(
            {"_id": match["_id"]},
            {"$set": {"episodes_watched": new_count, "status": status, "last_updated": datetime.now(timezone.utc)}}
        )
        await log_watch_event(user_id, match["tmdb_id"], match["title"], "progress", episodes)
        await update.message.reply_text(
            f"✅ Updated! *{match['title']}* — {new_count} episodes watched. Status: {status}",
            parse_mode="Markdown"
        )
    except Exception:
        await update.message.reply_text("⚠️ Couldn't update progress. Try again.")


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /done <title>")
        return
    title_query = " ".join(context.args).lower()
    user_id = get_user_id(update)
    try:
        items = await watchlist_collection.find({"user_id": user_id}).to_list(100)
        match = next((i for i in items if title_query in i["title"].lower()), None)
        if not match:
            await update.message.reply_text(f"Couldn't find '{title_query}' in your watchlist.")
            return
        await watchlist_collection.update_one(
            {"_id": match["_id"]},
            {"$set": {"status": "completed", "completed_at": datetime.now(timezone.utc)}}
        )
        await log_watch_event(user_id, match["tmdb_id"], match["title"], "completed")
        await update.message.reply_text(f"🎉 Marked *{match['title']}* as completed!", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("⚠️ Couldn't update status. Try again.")


async def hold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /hold <title>")
        return
    title_query = " ".join(context.args).lower()
    user_id = get_user_id(update)
    try:
        items = await watchlist_collection.find({"user_id": user_id}).to_list(100)
        match = next((i for i in items if title_query in i["title"].lower()), None)
        if not match:
            await update.message.reply_text(f"Couldn't find '{title_query}' in your watchlist.")
            return
        await watchlist_collection.update_one(
            {"_id": match["_id"]},
            {"$set": {"status": "on_hold"}}
        )
        await log_watch_event(user_id, match["tmdb_id"], match["title"], "on_hold")
        ep = match.get("episodes_watched", 0)
        await update.message.reply_text(
            f"⏸️ Put *{match['title']}* on hold at episode {ep}. I'll remember where you left off!",
            parse_mode="Markdown"
        )
    except Exception:
        await update.message.reply_text("⚠️ Couldn't update status. Try again.")


async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /delete <title>")
        return
    title_query = " ".join(context.args).lower()
    user_id = get_user_id(update)
    try:
        items = await watchlist_collection.find({"user_id": user_id}).to_list(100)
        match = next((i for i in items if title_query in i["title"].lower()), None)
        if not match:
            await update.message.reply_text(f"Couldn't find '{title_query}' in your watchlist.")
            return
        await watchlist_collection.delete_one({"_id": match["_id"]})
        await update.message.reply_text(f"🗑️ Removed *{match['title']}* from your watchlist.", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("⚠️ Couldn't remove from watchlist. Try again.")


async def recommend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id(update)
    try:
        items = await watchlist_collection.find({"user_id": user_id}).to_list(100)
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
                msg = f"You're still watching *{in_progress[0]['title']}* — continue or try something new?"
            else:
                msg = "You've got shows in progress 👀 — continue one or try something new?"

            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await update.message.reply_text("🎭 What are we feeling today?", reply_markup=mood_keyboard())
    except Exception:
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
        added_from = context.user_data.pop("pending_add_source", "command")
        try:
            details = get_details(int(tmdb_id), media_type)
            title = details.get("title") or details.get("name", "Unknown")
            genres = [g["name"] for g in details.get("genres", [])]
            total_episodes = details.get("number_of_episodes")

            existing = await watchlist_collection.find_one({"user_id": user_id, "tmdb_id": int(tmdb_id)})
            if existing:
                await query.edit_message_text(f"'{title}' is already in your watchlist!")
                return

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
            await log_watch_event(user_id, int(tmdb_id), title, "added")
            await query.edit_message_text(f"✅ Added '{title}' to your watchlist!")
        except Exception:
            await query.edit_message_text("⚠️ Something went wrong adding that. Try again.")

    # ── Continue an in-progress show ──
    elif data.startswith("rec_continue_"):
        tmdb_id = int(data.split("_")[2])
        try:
            item = await watchlist_collection.find_one({"user_id": user_id, "tmdb_id": tmdb_id})
            if item:
                ep = item.get("episodes_watched", 0)
                total = item.get("total_episodes") or "?"
                msg = f"🎬 Let's continue *{item['title']}*!\nYou're on episode {ep}/{total}. Enjoy! 🍿"
                await query.edit_message_text(msg, parse_mode="Markdown")
                append_history(context, "assistant", msg)
            else:
                await query.edit_message_text("Couldn't find that show in your watchlist.")
        except Exception:
            await query.edit_message_text("⚠️ Something went wrong. Try again.")

    # ── User wants something new → show mood picker ──
    elif data == "rec_new":
        await query.edit_message_text("🎭 What are we feeling today?", reply_markup=mood_keyboard())

    # ── Mood selected → get recommendation ──
    elif data.startswith("mood_"):
        genre = data.split("_", 1)[1]
        mood_msg = f"Surprise me with something great" if genre == "Any" else f"Recommend something in {genre}"
        try:
            items = await watchlist_collection.find({"user_id": user_id}).to_list(100)
            await query.edit_message_text("🤔 Thinking...")
            history = context.user_data.get("history", [])
            response = get_recommendation(items, mood_msg, history)
            append_history(context, "user", mood_msg)
            append_history(context, "assistant", response)
            await query.edit_message_text(response)
        except Exception:
            await query.edit_message_text("⚠️ AI is having a moment. Try again soon!")


# ── Media / link handlers ─────────────────────────────────────────────────────

async def handle_youtube(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    video_id = extract_video_id(url)
    if not video_id:
        await update.message.reply_text("Couldn't parse that YouTube link.")
        return

    context.user_data["pending_add_source"] = "youtube"
    await update.message.reply_text("🔍 Checking that link...")
    try:
        video_info = get_video_info(video_id)
        if not video_info:
            await update.message.reply_text("Couldn't fetch video info.")
            return

        movie_name = extract_movie_name(video_info)

        if movie_name == "UNKNOWN":
            await update.message.reply_text("🎬 Title unclear, analyzing frames... (up to 20s)")
            frames = extract_frames_with_timeout(url, num_frames=3, timeout=20)
            if frames:
                movie_name = identify_movie_from_frames(frames)

        if movie_name == "UNKNOWN":
            await update.message.reply_text(
                "📹 Couldn't identify a movie/show from this video.\n"
                "What movie/show is it from? Just type the name!"
            )
            context.user_data.pop("pending_add_source", None)
            return

        await update.message.reply_text(f"🎬 Found: *{movie_name}*\nSearching TMDB...", parse_mode="Markdown")
        results = search_tmdb(movie_name)
        if not results:
            await update.message.reply_text(f"Couldn't find '{movie_name}' on TMDB. Try /add manually.")
            return
        await update.message.reply_text("Is this what you meant? Pick one to add:", reply_markup=build_tmdb_keyboard(results))
    except Exception:
        await update.message.reply_text("⚠️ Something went wrong processing that link. Try again.")


async def handle_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    context.user_data["pending_add_source"] = "instagram"
    await update.message.reply_text("🔍 Checking that reel...")
    try:
        movie_name = "UNKNOWN"

        # Step 1: try metadata scraping (fast, often blocked by Instagram)
        reel_info = get_reel_info(url)
        if reel_info:
            movie_name = extract_movie_from_reel(reel_info)

        # Step 2: metadata failed → download reel via yt-dlp and analyze frames
        if movie_name == "UNKNOWN":
            await update.message.reply_text("📸 Caption unclear, analyzing the reel visually... (up to 20s)")
            frames = extract_frames_with_timeout(url, num_frames=3, timeout=20)
            if frames:
                movie_name = identify_movie_from_frames(frames)

        # Step 3: still unknown → ask the user
        if movie_name == "UNKNOWN":
            await update.message.reply_text(
                "📱 Couldn't identify the movie from this reel.\n"
                "What movie/show is it from? Just type the name!"
            )
            context.user_data.pop("pending_add_source", None)
            return

        await update.message.reply_text(f"🎬 Found: *{movie_name}*\nSearching TMDB...", parse_mode="Markdown")
        results = search_tmdb(movie_name)
        if not results:
            await update.message.reply_text(f"Couldn't find '{movie_name}' on TMDB. Try /add manually.")
            return
        await update.message.reply_text("Is this what you meant? Pick one to add:", reply_markup=build_tmdb_keyboard(results))
    except Exception as e:
        print(f"Instagram handler error: {e}")
        await update.message.reply_text("⚠️ Something went wrong. Try again.")


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["pending_add_source"] = "image"
    await update.message.reply_text("🔍 Analyzing image...")
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        movie_name = identify_movie_from_image(bytes(image_bytes))

        if movie_name == "UNKNOWN":
            await update.message.reply_text(
                "Couldn't identify a movie/show from this image.\n"
                "What movie is it from? Just type the name!"
            )
            context.user_data.pop("pending_add_source", None)
            return

        await update.message.reply_text(f"🎬 Found: *{movie_name}*\nSearching TMDB...", parse_mode="Markdown")
        results = search_tmdb(movie_name)
        if not results:
            await update.message.reply_text(f"Couldn't find '{movie_name}' on TMDB. Try /add manually.")
            return
        await update.message.reply_text("Is this what you meant? Pick one to add:", reply_markup=build_tmdb_keyboard(results))
    except Exception:
        await update.message.reply_text("⚠️ Something went wrong analyzing that image.")


# ── Natural language message handler ─────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    user_id = get_user_id(update)

    try:
        items = await watchlist_collection.find({"user_id": user_id}).to_list(100)

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

                db_match = next((i for i in items if title_query in i["title"].lower()), None)
                if db_match:
                    new_count = db_match.get("episodes_watched", 0) + episodes
                    status = "completed" if (db_match.get("total_episodes") and new_count >= db_match["total_episodes"]) else "watching"
                    await watchlist_collection.update_one(
                        {"_id": db_match["_id"]},
                        {"$set": {"episodes_watched": new_count, "status": status, "last_updated": datetime.now(timezone.utc)}}
                    )
                    await log_watch_event(user_id, db_match["tmdb_id"], db_match["title"], "progress", episodes)
                    await update.message.reply_text(
                        f"✅ Got it! *{db_match['title']}* updated — {new_count} episodes watched. Status: {status}",
                        parse_mode="Markdown"
                    )
                else:
                    await update.message.reply_text("Couldn't find that title in your watchlist. Use /add to add it first.")
                return

        # ── Mark completed: "finished Dark" ──
        done_m = re.search(r"(finished|completed|done watching)\s+(.+)", text)
        if done_m:
            title_query = done_m.group(2).strip()
            db_match = next((i for i in items if title_query in i["title"].lower()), None)
            if db_match:
                await watchlist_collection.update_one(
                    {"_id": db_match["_id"]},
                    {"$set": {"status": "completed", "completed_at": datetime.now(timezone.utc)}}
                )
                await log_watch_event(user_id, db_match["tmdb_id"], db_match["title"], "completed")
                await update.message.reply_text(f"🎉 Marked *{db_match['title']}* as completed!", parse_mode="Markdown")
                return

        # ── Put on hold: "hold Dark" / "put Dark on hold" ──
        hold_m = re.search(r"(hold|pause|break|bored|stop watching)\s+(.+)|put\s+(.+?)\s+on\s+hold", text)
        if hold_m:
            title_query = (hold_m.group(2) or hold_m.group(3) or "").strip()
            db_match = next((i for i in items if title_query in i["title"].lower()), None)
            if db_match:
                await watchlist_collection.update_one(
                    {"_id": db_match["_id"]}, {"$set": {"status": "on_hold"}}
                )
                await log_watch_event(user_id, db_match["tmdb_id"], db_match["title"], "on_hold")
                await update.message.reply_text(
                    f"⏸️ Put *{db_match['title']}* on hold. I'll remember where you left off!",
                    parse_mode="Markdown"
                )
                return

        # ── Quick-add: "add Dark" ──
        add_m = re.search(r"^add\s+(.+)", text)
        if add_m:
            title_query = add_m.group(1).strip()
            context.user_data["pending_add_source"] = "command"
            results = search_tmdb(title_query)
            if not results:
                await update.message.reply_text("Nothing found on TMDB.")
                return
            await update.message.reply_text("Which one?", reply_markup=build_tmdb_keyboard(results))
            return

        # ── Recommend shortcut ──
        if any(kw in text for kw in ["recommend", "what to watch", "suggest", "what should i watch"]):
            await recommend(update, context)
            return

        # ── Default: AI conversation with history ──
        history = context.user_data.get("history", [])
        response = get_recommendation(items, update.message.text, history)
        append_history(context, "user", update.message.text)
        append_history(context, "assistant", response)
        await update.message.reply_text(response)

    except Exception:
        await update.message.reply_text("⚠️ Something went wrong. Try again!")


# ── App setup ─────────────────────────────────────────────────────────────────

def run_bot():
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()

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

    print("🤖 WatchBot is running...")
    app.run_polling()