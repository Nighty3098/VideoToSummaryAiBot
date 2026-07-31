# AI Video Summary Bot

<br />

<div align="center">
  <img src="./imgs/1.png" width="45%" />
  <img src="./imgs/2.png" width="45%" />
</div>

<br />

A Telegram bot that transcribes video/audio and generates structured Markdown summaries via AI.

## Features

- **YouTube links** — downloads audio, extracts subtitles (ru/en), transcribes via Whisper
- **File uploads** — accepts video/audio files from Telegram (mp4, webm, mkv, mov, avi, mp3, m4a, wav, ogg, flac)
- **Transcription** — faster-whisper large-v3 on GPU (CUDA) with timestamps
- **Structured summary** — generated via Qwen AI (chat.qwen.ai) with emoji headers, Obsidian callouts, tables, checklists, code blocks
- **Smart caching** — downloaded audio, transcriptions, and subtitles are cached by video ID; repeated requests skip download and transcription
- **Whitelist** — only authorized users can access the bot
- **Admin panel** — statistics, user management, logs, cache clearing, stats reset
- **Proxy support** — MTProxy for Telegram, SOCKS5 for yt-dlp with health check and automatic fallback

## Installation

### Prerequisites

- Python 3.10+
- CUDA 12.x + cuDNN (required for GPU transcription)
- FFmpeg (for audio conversion)

### Quick install

```bash
git clone https://github.com/Nighty3098/VideoToSummaryAiBot && cd VideoToSummaryAiBot
bash install.sh
```

The script creates a venv, installs pip dependencies, and downloads Playwright Chromium.

### Manual install

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### Configuration

```bash
cp .env.example .env
# fill in BOT_TOKEN, API_ID, API_HASH
```

#### Environment variables

| Variable            | Required | Description                    |
| ------------------- | -------- | ------------------------------ |
| `BOT_TOKEN`         | yes      | Bot token from @BotFather      |
| `API_ID`            | yes      | API ID from my.telegram.org    |
| `API_HASH`          | yes      | API Hash from my.telegram.org  |
| `ADMIN_ID`          | yes      | Telegram ID of the admin       |
| `USE_PROXY`         | no       | MTProxy for Telegram (1/0)     |
| `PROXY_URL`         | no       | `tg://proxy?server=...`        |
| `USE_SOCKS5`        | no       | SOCKS5 for yt-dlp (1/0)        |
| `SOCKS5_PROXY`      | no       | `socks5://user:pass@host:port` |
| `WHISPER_CACHE_DIR` | no       | Whisper model cache directory  |

## Usage

### For users

1. Send the bot a **YouTube link** or a **video/audio file**
2. The bot downloads media → transcribes via Whisper → generates a structured summary via Qwen AI
3. Receive a `.md` file with the formatted summary

Repeated requests for the same YouTube video use cached audio and transcription — only the AI summary is regenerated.

### Admin panel

Command `/admin_p`:

| Button         | Action                                |
| -------------- | ------------------------------------- |
| 📊 Statistics  | Request statistics                    |
| 👥 Users       | User list, removal                    |
| ➕ Add User    | Add user (by ID or forwarded message) |
| 📋 Logs        | Last 200 lines of today's log         |
| 🧹 Clear Cache | Clears `temp/` and `logs/`            |
| 🔄 Reset Stats | Resets all request statistics         |

## Caching

```
cache/
  yt_{video_id}/
    meta.json            — {title, transcription: true, audio: true}
    audio.mp3            — downloaded audio
    subtitles.txt        — subtitles (if available)
    transcription.txt    — Whisper transcription
```

The cache is checked at each stage of the pipeline:

1. **Transcription cached** → skip download, transcription, go straight to AI summary
2. **Audio cached** → skip download, run Whisper + AI, cache transcription
3. **Nothing cached** → full pipeline, all results cached

## Troubleshooting

### Whisper not using GPU

```bash
# find libcublas.so.12
sudo find / -name libcublas.so.12 -type f 2>/dev/null

# add to LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/path/to/cuda_v12:$LD_LIBRARY_PATH
```

The bot auto-detects the library in common paths (Ollama, LM Studio, CUDA 12.x).

### Playwright: Chromium not found

```bash
source venv/bin/activate && playwright install chromium
```

### yt-dlp: 429 Too Many Requests

- Wait 15-30 minutes
- Configure SOCKS5 proxy in `.env`
- Subtitle errors are non-fatal — the pipeline continues

### Bot not responding

- Check `BOT_TOKEN`, `API_ID`, `API_HASH` in `.env`
- Verify the user is whitelisted (`/admin_p` → Add User)
- Check logs: `tail -f logs/bot_$(date +%Y-%m-%d).log`

### Formatting lost in summary

The bot uses `html2text` to convert Qwen's rendered HTML back to Markdown. If formatting issues persist, check that the Qwen AI is following the prompt instructions.

## Logging

```
logs/bot_YYYY-MM-DD.log
```
