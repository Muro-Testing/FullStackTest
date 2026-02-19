# 🧠 Cline Memory

## Session Context
This file persists memory across sessions. Read this at the start of each conversation.

## User Preferences
- User likes fast, efficient responses
- User prefers bidirectional control (Telegram + Terminal)
- User wants to see live progress

## Project Information
- **Project**: Telegram-Cline Bridge
- **Purpose**: Remote control of Cline AI via Telegram
- **Features**: Live streaming, file handling, bidirectional terminal

## Recent Activity
### 2026-02-19
- Created Telegram-Cline bridge bot
- Added live message streaming (edits message in real-time)
- Added terminal input mode (type in terminal to control Cline)
- Created file auto-detection and sending
- Added /files and /get commands

## Technical Details
- **Bot Token**: From .env file
- **Authorized User**: From .env file
- **Model**: z-ai/glm-5 (configurable)
- **Timeout**: 120 seconds (configurable)

## Important Files
- `telegram_bridge.py` - Main bot code
- `CLINE_AGENTS.md` - Agent personality and rules
- `CLINE_MEMORY.md` - This file (persistent memory)
- `.env` - Configuration (not in git)

## Notes
- Always read this file first to restore context
- Update this file when important things happen
- Keep entries concise but informative