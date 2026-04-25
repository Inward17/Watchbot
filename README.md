# 🎬 WatchBot — Your Personal Watchlist Telegram Bot

A smart Telegram bot that manages your movie and series watchlist with AI-powered recommendations. Send it a YouTube Short, Instagram Reel, or even a screenshot — it figures out the title and adds it to your list.

---

## ✨ Features

| Feature | Description |
|---|---|
| 📋 **Watchlist management** | Add, list, update progress, mark done, hold, or delete titles |
| 🤖 **AI recommendations** | Conversational recommendations powered by Groq (Llama 3.1) |
| 🎭 **Mood-based flow** | Interactive inline buttons — pick Action, Thriller, Romance, etc. |
| 🧠 **Conversation memory** | Bot remembers context across the conversation (multi-turn) |
| 📎 **YouTube / Shorts** | Send a link → bot extracts the movie name and adds it |
| 📱 **Instagram Reels** | Send a reel link → yt-dlp fetches description → LLM identifies title |
| 📸 **Image recognition** | Send a screenshot → vision AI identifies the movie/show |
| 🎞️ **Frame extraction** | If metadata fails, downloads frames and runs visual AI on them |
| 📊 **Watch log** | Every progress update is logged to MongoDB for history tracking |
| 🗄️ **TMDB integration** | Searches The Movie Database for verified title + episode counts |

---

## 🛠️ Tech Stack

| Layer | Tool |
|---|---|
| Bot | python-telegram-bot |
| AI / LLM | Groq API (Llama 3.1 8B) |
| Vision AI | OpenRouter (Gemma 3) |
| Movie data | TMDB API |
| Video parsing | yt-dlp |
| Database | MongoDB Atlas (Motor async) |
| Runtime | Python 3.11+ |

---

## 🚀 Setup

### 1. Clone the repo

```bash
git clone https://github.com/your-username/watchbot.git
cd watchbot
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Install ffmpeg (required for frame extraction)

- **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH
- **macOS**: `brew install ffmpeg`
- **Linux**: `sudo apt install ffmpeg`

### 5. Configure environment variables

Create a `.env` file in the root directory:

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TMDB_API_KEY=your_tmdb_api_key
GROQ_API_KEY=your_groq_api_key
MONGO_URI=your_mongodb_atlas_connection_string
YOUTUBE_API_KEY=your_youtube_data_api_key
OPENROUTER_API_KEY=your_openrouter_api_key
```

#### Where to get each key

| Key | Source |
|---|---|
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) on Telegram |
| `TMDB_API_KEY` | [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) (free) |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) (free tier) |
| `MONGO_URI` | [MongoDB Atlas](https://www.mongodb.com/cloud/atlas) (free M0 cluster) |
| `YOUTUBE_API_KEY` | [Google Cloud Console](https://console.cloud.google.com) → YouTube Data API v3 |
| `OPENROUTER_API_KEY` | [openrouter.ai](https://openrouter.ai) (free models available) |

### 6. Run the bot

```bash
python main.py
```

---

## 💬 Usage

### Commands

| Command | Description |
|---|---|
| `/start` | Show help |
| `/add <title>` | Search TMDB and add to watchlist |
| `/list` | View your full watchlist with status |
| `/watched <title> <n>` | Log that you watched N episodes |
| `/done <title>` | Mark as completed |
| `/hold <title>` | Put on hold (remembers your episode) |
| `/delete <title>` | Remove from watchlist |
| `/recommend` | Start AI recommendation conversation |

### Natural language

You can also just talk to the bot:

```
"watched 5 episodes of Reacher"
"finished Dark"
"put Peaky Blinders on hold"
"add Interstellar"
"recommend something"
"what should I watch tonight?"
```

### Send links / media

- **YouTube / Shorts link** → auto-identifies movie and adds it
- **Instagram Reel link** → extracts title from description, falls back to visual AI
- **Screenshot / image** → vision AI identifies the movie/show

---

## 🗄️ MongoDB Schema

```
watchlist   → { user_id, tmdb_id, title, type, status, episodes_watched,
                total_episodes, genres, added_from, added_at, completed_at }

watch_log   → { user_id, tmdb_id, title, action, episodes, timestamp }

users       → { telegram_id, preferences }
```

**Status values:** `plan_to_watch` · `watching` · `on_hold` · `completed`  
**added_from values:** `command` · `youtube` · `instagram` · `image`

---

## 📁 Project Structure

```
watchbot/
├── main.py                  # Entry point
├── requirements.txt
├── .env                     # Your secrets (never commit)
└── app/
    ├── bot.py               # All Telegram handlers + conversation logic
    ├── recommender.py       # Groq LLM recommendation engine (multi-turn)
    ├── database.py          # MongoDB Motor async collections
    ├── tmdb.py              # TMDB API search + details
    ├── youtube.py           # YouTube metadata + LLM extraction
    ├── instagram.py         # Instagram reel metadata via yt-dlp
    ├── vision.py            # Image recognition via OpenRouter
    └── frame_extractor.py   # yt-dlp frame extraction + vision fallback
```
