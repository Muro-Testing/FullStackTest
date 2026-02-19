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

import pexpect
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AUTHORIZED_USER_ID = int(os.getenv("AUTHORIZED_USER_ID", "0"))

# Prompt pattern to detect Cline's response end
CLINE_PROMPT_PATTERN = os.getenv("CLINE_PROMPT_PATTERN", r"\n>")
CLINE_TIMEOUT = int(os.getenv("CLINE_TIMEOUT", "120"))

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class ClineSession:
    """Manages the persistent Cline interactive session."""
    
    def __init__(self):
        self.process: Optional[pexpect.spawn] = None
        self.lock = asyncio.Lock()
        self._start_session()
    
    def _start_session(self) -> None:
        """Start a new Cline interactive session."""
        try:
            logger.info("Starting Cline interactive session...")
            self.process = pexpect.spawn(
                "cline",
                encoding="utf-8",
                timeout=CLINE_TIMEOUT
            )
            # Wait for initial prompt
            self.process.expect(CLINE_PROMPT_PATTERN, timeout=30)
            logger.info("Cline session started successfully")
        except Exception as e:
            logger.error(f"Failed to start Cline session: {e}")
            self.process = None
    
    def is_alive(self) -> bool:
        """Check if Cline process is still running."""
        return self.process is not None and self.process.isalive()
    
    def restart(self) -> str:
        """Restart the Cline session."""
        if self.process:
            try:
                self.process.close(force=True)
            except Exception:
                pass
        self._start_session()
        return "Cline restarted." if self.is_alive() else "Failed to restart Cline."
    
    @staticmethod
    def clean_output(text: str) -> str:
        """Remove ANSI escape sequences and clean up output."""
        # Remove ANSI escape sequences
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        text = ansi_escape.sub('', text)
        
        # Remove cursor movement codes
        cursor_codes = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
        text = cursor_codes.sub('', text)
        
        # Strip excessive blank lines
        text = re.sub(r'\n{3,}', '\n\n', text)
        
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
            if not self.cline.is_alive():
                logger.warning("Cline process died, restarting...")
                self.cline.restart()
                if not self.cline.is_alive():
                    return "Error: Cline is not available. Please try again later."
            
            try:
                # Send message to Cline
                self.cline.process.sendline(message)
                
                # Wait for response (prompt pattern indicates end)
                self.cline.process.expect(CLINE_PROMPT_PATTERN, timeout=CLINE_TIMEOUT)
                
                # Get the output
                output = self.cline.process.before or ""
                
                return self.cline.clean_output(output)
                
            except pexpect.TIMEOUT:
                # Return partial output on timeout
                output = self.cline.process.before or ""
                if output:
                    return self.cline.clean_output(output) + "\n\n[Response timed out]"
                return "Error: Cline response timed out."
                
            except pexpect.EOF:
                logger.error("Cline process ended unexpectedly")
                self.cline.restart()
                return "Cline process ended unexpectedly. Restarting..."
                
            except Exception as e:
                logger.error(f"Error communicating with Cline: {e}")
                self.cline.restart()
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
        "Welcome to Cline Bridge!\n\n"
        "Send any message to interact with Cline.\n\n"
        "Commands:\n"
        "/reset - Restart Cline session\n"
        "/status - Check Cline status\n"
        "/kill - Kill and restart session"
    )


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
    
    # Send response back to user
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
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("kill", kill_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Start bot
    logger.info("Starting Telegram-Cline Bridge...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()