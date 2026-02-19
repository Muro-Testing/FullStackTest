# Objective

Build a Telegram bot that connects to a locally running **Cline CLI** instance in interactive mode and allows remote interaction through Telegram messages.

The system must:

1. Maintain a persistent interactive Cline session.
2. Forward Telegram messages into the active Cline session.
3. Capture Cline's output.
4. Return the output back to the Telegram user.
5. Support multi-turn planning interactions.
6. Restrict access to authorized Telegram user IDs.
7. Recover automatically if Cline crashes.

---

# System Architecture

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

---

# Technical Requirements

## Language

Python 3.10+

## Required Packages

```
python-telegram-bot==20.*
pexpect
asyncio
```

---

# Process Requirements

## 1. Cline Must Run In Interactive Mode

Use:

```
pexpect.spawn("cline", encoding="utf-8", timeout=120)
```

NOT headless mode.

We require a persistent interactive session.

---

## 2. Session Behavior

The system must:

* Start Cline once at bot startup.
* Keep the process alive.
* Send user messages via `sendline()`.
* Capture output until:

  * Prompt reappears
  * Or timeout
* Return only relevant response (strip terminal control codes).

---

## 3. Output Handling

The bridge must:

* Remove ANSI escape sequences.
* Remove cursor movement codes.
* Strip excessive blank lines.
* Truncate messages > 4000 characters (Telegram limit).

---

## 4. Security

Must include:

```
ALLOWED_USERS = [YOUR_TELEGRAM_USER_ID]
```

Reject any message from non-authorized users.

---

## 5. Crash Recovery

If Cline process exits:

* Automatically restart it.
* Notify user: "Cline restarted."

---

## 6. Concurrency Rule

Only ONE message may be processed at a time.

Implement an async lock:

```
asyncio.Lock()
```

to prevent overlapping Cline writes.

---

# Required File Structure

```
project/
│
├── telegram_bridge.py
├── .env
├── TELEGRAM_CLINE_BRIDGE_SPEC.md
└── requirements.txt
```

---

# .env File

```
TELEGRAM_BOT_TOKEN=YOUR_TOKEN
AUTHORIZED_USER_ID=123456789
```

---

# Core Implementation Specification

## telegram_bridge.py Must:

### 1. Load environment variables

### 2. Initialize Telegram bot

### 3. Spawn Cline using pexpect

### 4. Register text message handler

### 5. Acquire async lock

### 6. Send user text to Cline

### 7. Read output until prompt detected

### 8. Clean output

### 9. Send response

### 10. Release lock

---

# Prompt Detection Strategy

Cline interactive session typically ends responses with:

```
>
```

OR similar shell prompt.

Agent must:

* Wait until prompt pattern appears
* Or use small delay and collect buffered output

Implementation suggestion:

```
cline.expect(r"\n>")
```

Prompt pattern must be configurable.

---

# Error Handling

If:

* Timeout occurs → respond with partial output.
* Exception occurs → restart Cline and notify user.

---

# Optional Features (Nice to Have)

* `/reset` command → restart Cline session
* `/status` → check if Cline alive
* `/kill` → kill and restart session
* Logging to file
* Rate limiting

---

# Performance Requirements

* Response latency < 2 seconds (excluding Cline compute time).
* No memory leaks.
* Cline process must not duplicate.

---

# Do NOT

* Do not spawn a new Cline per message.
* Do not use blocking I/O without asyncio.
* Do not allow multiple simultaneous Cline sessions.
* Do not allow public bot access.

---

# Acceptance Criteria

System is considered working when:

1. Telegram user sends: "Plan a REST API"
2. Cline responds with planning questions.
3. User replies.
4. Cline continues conversation in same context.
5. No duplicate sessions created.
6. Restart works via `/reset`.

---

# Deployment Instructions

Run with:

```
pip install -r requirements.txt
python telegram_bridge.py
```

---

# Expected Behavior Example

Telegram:

```
Build me a SaaS architecture.
```

Bot response:

```
To design this, I need:
1. Target users?
2. Expected traffic?
...
```

User:

```
Small B2B SaaS.
```

Bot continues without losing context.

---

# End of Specification
