# External Setup Guide

Everything in this file requires manual action on your phone, browser, or a third-party service. None of it can be automated from inside the project.

---

## 1. Telegram Bot

### 1.1 Create the bot and get the token

1. Open Telegram and search for **@BotFather**.
2. Send `/newbot`.
3. Choose a name (e.g. `OpenClaw`) and a username (e.g. `openclaw_bot` — must end in `bot`).
4. BotFather replies with a token like `123456789:AAF...`. Copy it.
5. In your `.env` file set:
   ```
   TELEGRAM_BOT_TOKEN=123456789:AAF...
   ```

### 1.2 Get your personal chat ID

1. Search for **@userinfobot** in Telegram and start it.
2. It replies immediately with your user ID (a number like `987654321`).
3. In your `.env` file set:
   ```
   TELEGRAM_CHAT_ID=987654321
   TELEGRAM_ALLOWED_USER_IDS=987654321
   ```
   `TELEGRAM_CHAT_ID` is where alerts are sent. `TELEGRAM_ALLOWED_USER_IDS` is the allowlist for callback button actions (approve/reject/draft). Set both to your own ID.

### 1.3 Start the bot for the first time

1. In Telegram, search for your bot by username and press **Start**.
   The bot must receive at least one message from you before it can initiate conversations.

### 1.4 Test the token

```bash
curl "https://api.telegram.org/bot<YOUR_TOKEN>/getMe"
```

Expected: a JSON response with `"ok": true` and your bot's name.

---

## 2. AI API (free — Google Gemini)

OpenClaw uses an AI API only for proposal drafting (Phase 4 — not built yet). Until then, you do not need this at all. When you get there, use **Google Gemini** — it is completely free via Google AI Studio with no credit card required.

### 2.1 Get a free Gemini API key

1. Go to **[aistudio.google.com](https://aistudio.google.com)** and sign in with any Google account.
2. Click **Get API key** (top left) → **Create API key**.
3. Copy the key (starts with `AIza...`).
4. In your `.env` file set:
   ```
   OPENAI_API_KEY=AIza...
   ```
   The variable is still named `OPENAI_API_KEY` because the code uses the OpenAI SDK — Gemini supports the same API format.

### 2.2 Choose models

Set these in `.env`:

```
OPENAI_MODEL=gemini-2.0-flash
OPENAI_EMBEDDINGS_MODEL=text-embedding-004
```

- `gemini-2.0-flash` is the recommended free model — fast, handles French business language well, and has a large context window.
- `text-embedding-004` is Google's free embeddings model, sufficient for proposal retrieval.

### 2.3 Point the SDK at Google's endpoint

Gemini exposes an OpenAI-compatible endpoint. Add this line to your `.env`:

```
OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
```

The OpenAI Python SDK will automatically use this base URL instead of OpenAI's servers. No code changes needed.

### 2.4 Free tier limits (as of 2026)

| Model | Requests per minute | Requests per day |
|---|---|---|
| gemini-2.0-flash | 15 | 1,500 |
| text-embedding-004 | 1,500 | Unlimited |

For personal freelance use (a few proposals per day) this is more than enough. No credit card, no billing, no usage caps to worry about.

### 2.5 Test it works

Once `.env` is filled in and the code is built, test with:

```bash
curl "https://generativelanguage.googleapis.com/v1beta/models?key=YOUR_API_KEY"
```

Expected: a JSON list of available models including `gemini-2.0-flash`.

---

## 3. Docker (via WSL)

You run Docker directly inside WSL — no Docker Desktop needed. All commands below run inside your WSL terminal.

### 3.1 Install Docker Engine inside WSL

```bash
# Update apt
sudo apt update && sudo apt upgrade -y

# Install prerequisites
sudo apt install -y ca-certificates curl gnupg lsb-release

# Add Docker's official GPG key
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Add the Docker apt repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine + Compose plugin
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### 3.2 Allow running Docker without sudo

```bash
sudo usermod -aG docker $USER
# Then close and reopen your WSL terminal for this to take effect
```

### 3.3 Start the Docker daemon

WSL does not start services automatically on launch. Run this once per WSL session (or add it to your `~/.bashrc`):

```bash
sudo service docker start
```

To avoid typing this every time, add it to `~/.bashrc`:

```bash
echo 'sudo service docker start > /dev/null 2>&1' >> ~/.bashrc
```

### 3.4 Verify

```bash
docker --version
docker compose version
docker run hello-world
```

All three should succeed without `sudo`.

### 3.5 Run the project database

From inside the project directory in WSL:

```bash
make db-up
docker ps   # should show openclaw-postgres as healthy after ~10 seconds
```

---

## 4. Python 3.12 (inside WSL)

### 4.1 Install via deadsnakes PPA

Ubuntu's default apt repository often ships an older Python. Use the deadsnakes PPA to get 3.12:

```bash
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev
```

### 4.2 Verify

```bash
python3.12 --version
# Should print: Python 3.12.x
```

### 4.3 Use it with make

The Makefile uses `python3` by default. If your WSL distro has multiple Python versions, override it:

```bash
make bootstrap PYTHON=python3.12
```

Or set it permanently in your shell:

```bash
echo 'alias python3=python3.12' >> ~/.bashrc
source ~/.bashrc
```

---

## 5. Playwright OS dependencies (required on WSL)

Chromium needs several system libraries that are not installed by default in WSL. Run these **after** `make playwright-install` (or `make bootstrap`):

```bash
.venv/bin/playwright install-deps chromium
```

This installs libglib, libnss, libatk, libxcomposite, libxdamage, and other libraries Chromium depends on. Without this step the scraper fails immediately with a missing shared library error.

If `install-deps` itself fails with permission errors:

```bash
sudo .venv/bin/playwright install-deps chromium
```

### Headful mode on WSL

Running `--headful` (visible browser window) requires a display. On WSL2 with **Windows 11**, this works automatically via WSLg. On WSL2 with **Windows 10**, you need an X server (e.g. VcXsrv) running on Windows and `DISPLAY=:0` set in your shell.

For scraping purposes, headless mode (the default) works fine on WSL without any display setup.

---

## 6. Free-Work account (optional but recommended)

Free-Work shows more missions and avoids rate limiting when you are logged in.

1. Create an account at [free-work.com](https://www.free-work.com).
2. Run the scraper in headful mode the first time to log in manually inside the browser window:
   ```bash
   make freework-smoke ARGS="--headful --user-data-dir data/playwright/freework --slow-mo 300"
   ```
3. Log in inside the browser that opens. Once logged in the session is saved to `data/playwright/freework/`.
4. Subsequent runs reuse the saved session and do not require login.

---

## Summary checklist

| Item | Required for | Done? |
|---|---|---|
| Telegram bot token | Alerts + callback buttons | |
| Telegram chat ID | Knowing where to send alerts | |
| Telegram user ID | Allowlist for approve/reject | |
| Start the bot (send /start) | Bot can message you | |
| Gemini API key (free, aistudio.google.com) | Proposal generation (Phase 4) | |
| Docker Engine installed in WSL | Database | |
| Docker daemon started (`sudo service docker start`) | Database | |
| Python 3.12 installed via deadsnakes | Everything | |
| Playwright OS deps installed (`playwright install-deps chromium`) | Scraper | |
| Free-Work login saved | Better scraper results | |
