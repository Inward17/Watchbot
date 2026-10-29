# Changelog

All notable changes to WatchBot are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/):

- **Major** (2.0.0): breaking changes, such as a new database layout or a required new environment variable
- **Minor** (1.1.0): new features that keep existing setups working
- **Patch** (1.0.1): bug fixes only

## [1.1.0] - 2026-10-29

### Added
- Grounded answers: the assistant searches TMDB before naming a half-remembered title or quoting a rating, instead of guessing.
- Where to watch: poster cards show the streaming services in your country (JustWatch data via TMDB). Set the country with `WATCH_REGION`.
- Private mode: `ALLOWED_USERS` limits the bot to listed Telegram user ids.
- "Which one?" buttons when `/done`, `/hold`, `/watched` or `/delete` matches several titles.
- Command menu in Telegram's `/` button, typing indicator while the AI works.
- Chat history survives restarts (`bot_data.pickle`).
- Fallback Groq model (`openai/gpt-oss-20b`) when the main model hits its rate limit, and a "busy" message when both are capped.
- Version number in `/start` and the startup log.

### Changed
- The AI sees your full watchlist as a compact summary, most recent first.
- Exact title matches win over partial ones ("dark" picks *Dark*, not *The Dark Knight*).
- YouTube and Instagram title extraction share one Groq client.

### Fixed
- Adding a title failed on dropped TMDB connections; requests now retry.
- The same title could be added twice; a unique database index now prevents it.
- Watchlists longer than 100 titles were cut off.
- "Removed" actions are now logged to the history.

## [1.0.0] - 2026-10-28

### Added
- Add titles from YouTube, Shorts and Instagram Reel links, screenshots or plain text.
- Watchlist commands: `/add`, `/list`, `/watched`, `/done`, `/hold`, `/delete`, `/recommend`.
- Plain-English commands and conversational recommendations with poster cards and IMDb links.
- Numbered poster albums for picking between search results.
- MongoDB storage with a startup connection check.

[1.1.0]: https://github.com/Inward17/Watchbot/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Inward17/Watchbot/releases/tag/v1.0.0
