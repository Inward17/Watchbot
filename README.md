# WatchBot

A Telegram bot that keeps track of the movies and series you want to watch. Send it a YouTube Short, an Instagram Reel, a screenshot or just a title, and it identifies the show, confirms it against TMDB and adds it to your watchlist. It also tracks episode progress and gives conversational recommendations with posters and IMDb links.

## Features

- **Watchlist management**: add, list, track episodes, complete, pause or remove titles with commands or plain English.
- **Identify from links**: paste a YouTube, YouTube Shorts or Instagram Reel link. WatchBot reads the video's metadata and, if that isn't enough, analyses frames from the video with a vision model.
- **Identify from screenshots**: send an image and a vision model names the movie or series.
- **Visual pick lists**: every search result list comes with a numbered poster album, so titles with the same name ("Players" ×5) are easy to tell apart.
- **AI recommendations**: chat naturally ("recommend some comedy sitcoms") or pick a mood from inline buttons. Answers use your watchlist and the recent conversation as context.
- **Poster cards**: every title the assistant mentions is followed by a card with its poster, year, rating, synopsis, an **Add** button and an **IMDb** link.
- **Progress history**: every add, progress update and status change is logged for later analysis.

## How it works

```
Link / image / text
        │
        ▼
 Identify the title ── YouTube & Instagram metadata (yt-dlp) ──► LLM extracts the title
        │                     │ no title found
        │                     ▼
        │              Download low-res video, grab frames (ffmpeg) ──► vision model
        ▼
 Search TMDB ──► poster album + numbered pick buttons ──► user picks ──► MongoDB
```

All network calls (TMDB, Groq, OpenRouter, yt-dlp, ffmpeg) run off the event loop with timeouts, so one slow video never blocks other users.

## Tech stack

| Layer | Technology |
|---|---|
| Bot framework | [python-telegram-bot](https://python-telegram-bot.org) 22 |
| Language model | [Groq](https://groq.com) API, `openai/gpt-oss-120b` |
| Vision model | [OpenRouter](https://openrouter.ai), `google/gemma-3-12b-it` |
| Movie data and posters | [TMDB](https://www.themoviedb.org) API |
| Video metadata and download | [yt-dlp](https://github.com/yt-dlp/yt-dlp) and ffmpeg |
| Database | MongoDB Atlas, via Motor (async) |
| Runtime | Python 3.11+ |

## Getting started

### Prerequisites

- Python 3.11 or newer
- [ffmpeg](https://ffmpeg.org/download.html) on your `PATH` (used for frame extraction)
  - Windows: download a build from ffmpeg.org and add its `bin` folder to `PATH`
  - macOS: `brew install ffmpeg`
  - Linux: `sudo apt install ffmpeg`
- API keys for the services listed under [Configuration](#configuration)

### Installation

```bash
git clone https://github.com/Inward17/Watchbot.git
cd Watchbot

python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### Configuration

Create a `.env` file in the project root. It is listed in `.gitignore`; never commit it.

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TMDB_API_KEY=your_tmdb_api_key
GROQ_API_KEY=your_groq_api_key
OPENROUTER_API_KEY=your_openrouter_api_key
YOUTUBE_API_KEY=your_youtube_data_api_key
MONGO_URI=your_mongodb_connection_string
```

| Variable | Where to get it |
|---|---|
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) on Telegram |
| `TMDB_API_KEY` | [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) (free) |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) (free tier) |
| `OPENROUTER_API_KEY` | [openrouter.ai](https://openrouter.ai) (free models available) |
| `YOUTUBE_API_KEY` | [Google Cloud Console](https://console.cloud.google.com), YouTube Data API v3 |
| `MONGO_URI` | [MongoDB Atlas](https://www.mongodb.com/cloud/atlas) (a free M0 cluster is enough) |

The model names live in [`app/vision.py`](app/vision.py) (`GROQ_MODEL`, `VISION_MODEL`). Change them there if a provider retires a model.

### Running

```bash
python main.py
```

On startup the bot checks the MongoDB connection and exits with a clear error if the database can't be reached.

## Usage

### Commands

| Command | Description |
|---|---|
| `/start` | Show help |
| `/add <title>` | Search TMDB and add a title |
| `/list` | Show your watchlist with status and episode progress |
| `/watched <title> <n>` | Log `n` more episodes watched |
| `/done <title>` | Mark a title as completed |
| `/hold <title>` | Put a title on hold, keeping your episode count |
| `/delete <title>` | Remove a title |
| `/recommend` | Continue an in-progress show or pick a mood for a recommendation |

### Plain English

```
add Interstellar
watched 5 episodes of Reacher
finished Dark
put Peaky Blinders on hold
recommend some comedy sitcoms
what should I watch tonight?
```

Open-ended requests ("what should I watch?") show mood buttons; specific ones ("comedy sitcoms like The Office") go straight to the assistant.

### Links and images

| Send | What happens |
|---|---|
| YouTube or Shorts link | Title, description and tags are read; frames are analysed if needed |
| Instagram Reel link | Caption is read via yt-dlp; frames are analysed if needed |
| Screenshot | A vision model identifies the movie or series |

If identification fails, the bot asks you to type the name and searches for it.

## Data model

```
watchlist  { user_id, tmdb_id, title, type, status, episodes_watched,
             total_episodes, genres, added_from, added_at, last_updated, completed_at }

watch_log  { user_id, tmdb_id, title, action, episodes, timestamp }
```

- `status`: `plan_to_watch`, `watching`, `on_hold`, `completed`
- `added_from`: `command`, `youtube`, `instagram`, `image`, `recommendation`
- `action`: `added`, `progress`, `on_hold`, `completed`

## Project structure

```
Watchbot/
├── main.py                 # Entry point
├── requirements.txt
├── test_helpers.py         # Checks for the parsing and formatting helpers
└── app/
    ├── bot.py              # Telegram handlers, pick lists, poster cards
    ├── recommender.py      # Conversational recommendations (Groq)
    ├── youtube.py          # YouTube metadata and title extraction
    ├── instagram.py        # Instagram Reel metadata via yt-dlp
    ├── frame_extractor.py  # Video download and frame sampling
    ├── vision.py           # Vision model calls, title cleanup, model settings
    ├── tmdb.py             # TMDB search and details
    └── database.py         # MongoDB collections and startup check
```

## Testing

```bash
python test_helpers.py
```

Runs plain `assert` checks for title cleanup, request routing, Markdown-to-HTML conversion and title extraction. It also works with `pytest`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Instagram links fail with "login required" | Instagram blocks older yt-dlp versions. Update it: `pip install -U yt-dlp` |
| `Can't reach MongoDB` at startup with a DNS error | Some routers can't resolve `mongodb+srv://` addresses. Use the standard `mongodb://host1,host2,host3/?replicaSet=...&tls=true` connection string from Atlas instead |
| `model_not_found` from Groq | The model was retired. Pick a current one from your Groq console and update `GROQ_MODEL` in `app/vision.py` |
| Frame analysis never runs | Make sure `ffmpeg` is installed and on your `PATH` |

## Limitations

- Conversation history is kept in memory, so it resets when the bot restarts.
- The free OpenRouter vision model is rate limited; screenshot identification may occasionally fail.
- Instagram may still block anonymous access for some reels even with an up-to-date yt-dlp.
