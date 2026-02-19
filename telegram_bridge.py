#!/usr/bin/env python3
"""
Telegram-Cline Bridge

A Telegram bot that connects to a locally running Cline CLI instance
in interactive mode and allows remote interaction through Telegram messages.
"""

import os
import re
import asyncio
import logging
from typing import Optional

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AUTHORIZED_USER_ID = int(os.getenv("AUTHORIZED_USER_ID", "0"))

# Cline configuration
CLINE_TIMEOUT = int(os.getenv("CLINE_TIMEOUT", "120"))
CLINE_WORKING_DIR = os.getenv("CLINE_WORKING_DIR", os.getcwd())
CLINE_MODEL = os.getenv("CLINE_MODEL", "z-ai/glm-5")
CLINE_YOLO = os.getenv("CLINE_YOLO", "true").lower() == "true"
CLINE_PATH = os.getenv("CLINE_PATH", "cline")  # Full path to cline executable if not in PATH

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class ClineSession:
    """Manages Cline execution in request-response mode."""
    
    def __init__(self, working_dir: str = None, model: str = None):
        self.lock = asyncio.Lock()
        self.working_dir = working_dir or CLINE_WORKING_DIR
        self.model = model or CLINE_MODEL
        self.task_id = None  # For resuming tasks
    
    def is_alive(self) -> bool:
        """Check if Cline is available."""
        # In request-response mode, we spawn fresh each time
        return True
    
    def restart(self) -> str:
        """Reset session state."""
        self.task_id = None
        return "Cline session reset. Next message will start fresh."
    
    @staticmethod
    def clean_output(text: str) -> str:
        """Remove ANSI escape sequences and clean up output."""
        if not text:
            return ""
        
        # Remove ANSI escape sequences
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        text = ansi_escape.sub('', text)
        
        # Remove cursor movement codes
        cursor_codes = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
        text = cursor_codes.sub('', text)
        
        # Remove screen clearing codes
        text = re.sub(r'\x1b\[2J', '', text)
        text = re.sub(r'\x1b\[H', '', text)
        
        # Remove other control characters but keep newlines
        text = re.sub(r'[\x00-\x09\x0b\x0c\x0e-\x1f]', '', text)
        
        # Strip excessive blank lines
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Remove lines that are just UI decorations
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            # Skip lines that are mostly special characters (UI borders)
            stripped = line.strip()
            if stripped and not all(c in '─│┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬─━│┃┄┅┆┇┈┉┊┋' for c in stripped):
                cleaned_lines.append(line)
        
        text = '\n'.join(cleaned_lines)
        
        # Truncate if too long for Telegram (4000 char limit)
        if len(text) > 4000:
            text = text[:3997] + "..."
        
        return text.strip()


class TelegramClineBridge:
    """Bridge between Telegram and Cline."""
    
    def __init__(self):
        self.cline = ClineSession()
    
    async def send_to_cline(self, message: str) -> str:
        """Send a message to Cline and return the response."""
        async with self.cline.lock:
            try:
                import time
                import subprocess
                import json
                
                # Build Cline command
                cmd = [CLINE_PATH]  # Use configured path to cline
                
                if CLINE_YOLO:
                    cmd.append("--yolo")
                
                cmd.extend(["--model", self.cline.model])
                cmd.extend(["--timeout", str(CLINE_TIMEOUT)])
                cmd.extend(["--cwd", self.cline.working_dir])
                cmd.append(message)
                
                logger.info(f"Running Cline: {' '.join(cmd[:4])}... (message)")
                
                # Run Cline and capture output
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.cline.working_dir
                )
                
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=CLINE_TIMEOUT + 10
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    return "⏱️ Cline timed out. Try with a simpler request or increase timeout."
                
                output = stdout.decode('utf-8', errors='replace')
                error = stderr.decode('utf-8', errors='replace')
                
                if process.returncode != 0 and error:
                    logger.error(f"Cline error: {error}")
                    # Still return output if there is any
                
                return self.cline.clean_output(output) or "✅ Cline completed. No text output."
                
            except FileNotFoundError:
                return "❌ Cline CLI not found. Make sure it's installed and in PATH."
            except Exception as e:
                logger.error(f"Error communicating with Cline: {e}")
                return f"Error: {str(e)}"


# Global bridge instance
bridge: Optional[TelegramClineBridge] = None


def is_authorized(user_id: int) -> bool:
    """Check if user is authorized to use the bot."""
    return user_id == AUTHORIZED_USER_ID


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("Unauthorized access.")
        return
    
    await update.message.reply_text(
        "🤖 *Welcome to Cline Bridge!*\n\n"
        "Send any message to interact with Cline.\n\n"
        "*Commands:*\n"
        "/info - Show Cline context (dir, model)\n"
        "/status - Check if Cline is running\n"
        "/reset - Restart Cline session\n"
        "/cd <path> - Change working directory\n"
        "/model <name> - Change AI model\n"
        "/kill - Kill and restart session",
        parse_mode="Markdown"
    )


async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /info command - show current Cline context."""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("Unauthorized access.")
        return
    
    cline = bridge.cline
    status = "🟢 Running" if cline.is_alive() else "🔴 Stopped"
    
    info = (
        f"📊 *Cline Context*\n\n"
        f"*Status:* {status}\n"
        f"*Working Directory:*\n`{cline.working_dir}`\n"
        f"*Model:* `{cline.model}`\n"
        f"*Timeout:* {CLINE_TIMEOUT}s\n"
    )
    
    await update.message.reply_text(info, parse_mode="Markdown")


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /reset command."""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("Unauthorized access.")
        return
    
    result = bridge.cline.restart()
    await update.message.reply_text(result)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command."""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("Unauthorized access.")
        return
    
    status = "alive" if bridge.cline.is_alive() else "dead"
    await update.message.reply_text(f"Cline status: {status}")


async def kill_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /kill command."""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("Unauthorized access.")
        return
    
    result = bridge.cline.restart()
    await update.message.reply_text(f"Session killed and restarted.\n{result}")


async def cd_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cd command - change working directory."""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("Unauthorized access.")
        return
    
    if not context.args:
        await update.message.reply_text(
            f"Current directory: `{bridge.cline.working_dir}`\n"
            f"Usage: /cd <path>",
            parse_mode="Markdown"
        )
        return
    
    new_dir = " ".join(context.args)
    
    # Handle relative paths
    if not os.path.isabs(new_dir):
        new_dir = os.path.abspath(os.path.join(bridge.cline.working_dir, new_dir))
    
    # Validate directory
    if not os.path.isdir(new_dir):
        await update.message.reply_text(f"❌ Directory not found: `{new_dir}`", parse_mode="Markdown")
        return
    
    # Update working directory and restart
    bridge.cline.working_dir = new_dir
    result = bridge.cline.restart()
    
    await update.message.reply_text(
        f"📁 Changed to: `{new_dir}`\n{result}",
        parse_mode="Markdown"
    )


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /model command - change or show model."""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("Unauthorized access.")
        return
    
    if not context.args:
        await update.message.reply_text(
            f"Current model: `{bridge.cline.model}`\n"
            f"Usage: /model <model_name>\n\n"
            f"Common models:\n"
            f"• `claude-3-5-sonnet-20241022`\n"
            f"• `claude-3-opus-20240229`\n"
            f"• `claude-3-haiku-20240307`",
            parse_mode="Markdown"
        )
        return
    
    new_model = " ".join(context.args)
    bridge.cline.model = new_model
    
    await update.message.reply_text(
        f"🧠 Model set to: `{new_model}`\n"
        f"Note: Restart Cline for this to take effect with /reset",
        parse_mode="Markdown"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages."""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("Unauthorized access.")
        return
    
    user_message = update.message.text
    logger.info(f"Message from {user_id}: {user_message[:50]}...")
    
    # Send to Cline and get response
    response = await bridge.send_to_cline(user_message)
    
    # Send response back to user (handle empty response)
    if not response or not response.strip():
        response = "✅ Message sent to Cline. No text output captured (Cline may be processing or waiting for input)."
    
    await update.message.reply_text(response)


def main() -> None:
    """Start the bot."""
    global bridge
    
    # Validate configuration
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set in environment")
        return
    
    if AUTHORIZED_USER_ID == 0:
        logger.error("AUTHORIZED_USER_ID not set in environment")
        return
    
    # Initialize bridge
    bridge = TelegramClineBridge()
    
    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Register handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("info", info_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("kill", kill_command))
    application.add_handler(CommandHandler("cd", cd_command))
    application.add_handler(CommandHandler("model", model_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Start bot
    logger.info("Starting Telegram-Cline Bridge...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()