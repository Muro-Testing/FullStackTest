# Telegram-Cline Bridge

A Telegram bot that connects to a locally running Cline CLI instance in interactive mode, allowing remote interaction through Telegram messages.

## Features

- Maintains a persistent interactive Cline session
- Forwards Telegram messages to Cline
- Returns Cline output back to Telegram
- Multi-turn conversation support
- User authorization (restricted access)
- Automatic crash recovery

## Prerequisites

- Python 3.10+
- Cline CLI installed and accessible in PATH
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))

## Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/Muro-Testing/FullStackTest.git
   cd FullStackTest
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` with your credentials:
   ```
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   AUTHORIZED_USER_ID=your_telegram_user_id
   ```

   To get your Telegram user ID, message [@userinfobot](https://t.me/userinfobot).

5. **Run the bot**
   ```bash
   python telegram_bridge.py
   ```

## Available Commands

| Command | Description |
|---------|-------------|
| `/start` | Start the bot and see available commands |
| `/info` | Show Cline context (working directory, model, status) |
| `/status` | Check if Cline is running |
| `/reset` | Restart the Cline session |
| `/cd <path>` | Change working directory and restart Cline |
| `/model <name>` | Set AI model (requires /reset to apply) |
| `/kill` | Kill and restart the session |

## Configuration

Environment variables can be customized:

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Required | Your Telegram bot token |
| `AUTHORIZED_USER_ID` | Required | Your Telegram user ID |
| `CLINE_WORKING_DIR` | Current directory | Working directory for Cline |
| `CLINE_MODEL` | `claude-3-5-sonnet-20241022` | AI model for Cline |
| `CLINE_PROMPT_PATTERN` | `\n>` | Regex pattern to detect Cline prompt |
| `CLINE_TIMEOUT` | `120` | Timeout in seconds for Cline responses |

## Viewing Cline Context

Use `/info` from Telegram to see:
- 🟢/🔴 Status (running/stopped)
- 📁 Working directory
- 🧠 AI model
- ⏱️ Timeout setting

This helps you understand:
- **Which folder** Cline is working in
- **Which model** is being used
- **If Cline is alive** and ready

## Architecture

```
Telegram User
    ↓
Telegram Bot API
    ↓
Python Bridge Service
    ↓
Persistent Cline Interactive Process (PTY)
    ↑
Captured stdout
    ↑
Telegram response
```

## Security

- Only authorized Telegram user IDs can interact with the bot
- Never share your `.env` file or bot token
- Keep your Telegram user ID private

## License

MIT