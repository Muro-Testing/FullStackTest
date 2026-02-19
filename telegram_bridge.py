#!/usr/bin/env python3
"""
Telegram-Cline Bridge

A Telegram bot that connects to a locally running Cline CLI instance
in interactive mode and allows remote interaction through Telegram messages.

Features:
- Bidirectional: Control from both Telegram AND terminal
- Live streaming: See Cline output in real-time in both places
- File handling: Auto-sends created files via Telegram
"""

import os
import re
import asyncio
import logging
import glob
import sys
import threading
from typing import Optional, List
from pathlib import Path
from queue import Queue

from dotenv import load_dotenv
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Load environment variables
load_dotenv()

# Global message queue for terminal input
terminal_input_queue = Queue()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AUTHORIZED_USER_ID = int(os.getenv("AUTHORIZED_USER_ID", "0"))

# Cline configuration
CLINE_TIMEOUT = int(os.getenv("CLINE_TIMEOUT", "120"))
CLINE_WORKING_DIR = os.getenv("CLINE_WORKING_DIR", os.getcwd())
CLINE_MODEL = os.getenv("CLINE_MODEL", "z-ai/glm-5")
CLINE_YOLO = os.getenv("CLINE_YOLO", "true").lower() == "true"
CLINE_PATH = os.getenv("CLINE_PATH", "cline")  # Full path to cline executable if not in PATH

# Logging setup - reduce noise from httpx
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Silence httpx INFO logs (they're very verbose)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.Application").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.Updater").setLevel(logging.WARNING)


class ClineSession:
    """Manages Cline execution with persistent session support."""
    
    def __init__(self, working_dir: str = None, model: str = None):
        self.lock = asyncio.Lock()
        self.working_dir = working_dir or CLINE_WORKING_DIR
        self.model = model or CLINE_MODEL
        self.task_id = None  # For resuming tasks
        self.process = None  # Persistent Cline process
        self.reader_task = None
        self.output_buffer = ""
        self.session_active = False
        self.total_tokens = 0
        self.messages_sent = 0
        self.session_start_time = None
    
    def is_alive(self) -> bool:
        """Check if Cline process is running."""
        return self.process is not None and self.process.returncode is None
    
    def get_stats(self) -> dict:
        """Get session statistics."""
        import time
        uptime = 0
        if self.session_start_time:
            uptime = int(time.time() - self.session_start_time)
        
        return {
            "active": self.is_alive(),
            "task_id": self.task_id,
            "tokens": self.total_tokens,
            "messages": self.messages_sent,
            "uptime_seconds": uptime,
            "model": self.model,
            "working_dir": self.working_dir
        }
    
    async def start_interactive(self) -> bool:
        """Start Cline in interactive mode for persistent session."""
        try:
            cmd = [CLINE_PATH]
            if CLINE_YOLO:
                cmd.append("--yolo")
            cmd.extend(["--model", self.model])
            cmd.extend(["--cwd", self.working_dir])
            
            logger.info(f"Starting Cline interactive: {' '.join(cmd[:4])}")
            
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.working_dir
            )
            self.session_active = True
            self.session_start_time = time.time() if 'time' in dir() else 0
            import time
            self.session_start_time = time.time()
            
            logger.info("Cline interactive session started")
            return True
        except Exception as e:
            logger.error(f"Failed to start Cline: {e}")
            return False
    
    async def stop(self):
        """Stop the Cline process."""
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except:
                try:
                    self.process.kill()
                except:
                    pass
        self.process = None
        self.session_active = False
    
    def restart(self) -> str:
        """Reset session state."""
        self.task_id = None
        self.total_tokens = 0
        self.messages_sent = 0
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
        self.tracked_files: set = set()  # Track files before/after
    
    def scan_files(self, extensions: List[str] = None) -> List[str]:
        """Scan working directory for files."""
        if extensions is None:
            extensions = ['.html', '.css', '.js', '.py', '.json', '.md', '.txt', '.png', '.jpg', '.gif']
        
        files = []
        for ext in extensions:
            pattern = os.path.join(self.cline.working_dir, f'**/*{ext}')
            files.extend(glob.glob(pattern, recursive=True))
        
        return sorted(files)
    
    def get_new_files(self, extensions: List[str] = None) -> List[str]:
        """Find files that were created since last check."""
        current = set(self.scan_files(extensions))
        new = current - self.tracked_files
        self.tracked_files = current
        return sorted(list(new))
    
    def track_current_files(self):
        """Remember current files to detect new ones later."""
        self.tracked_files = set(self.scan_files())
    
    async def send_to_cline(self, message: str, chat_id: int = None, context = None, stream_message_id: int = None) -> tuple:
        """Send a message to Cline and return (response, task_id, message_id).
        
        Streams output in real-time by editing a Telegram message.
        """
        async with self.cline.lock:
            try:
                import time
                
                # Read memory files for context
                context_preamble = ""
                memory_file = os.path.join(self.cline.working_dir, "CLINE_MEMORY.md")
                agents_file = os.path.join(self.cline.working_dir, "CLINE_AGENTS.md")
                
                if os.path.exists(memory_file):
                    try:
                        with open(memory_file, 'r') as f:
                            context_preamble += f"\n\n[MEMORY CONTEXT - Read this first:]\n{f.read()[:2000]}"
                    except:
                        pass
                
                if os.path.exists(agents_file):
                    try:
                        with open(agents_file, 'r') as f:
                            context_preamble += f"\n\n[AGENT INSTRUCTIONS:]\n{f.read()[:1500]}"
                    except:
                        pass
                
                # Build Cline command with context
                cmd = [CLINE_PATH]  # Use configured path to cline
                
                if CLINE_YOLO:
                    cmd.append("--yolo")
                
                # Resume existing task if available
                if self.cline.task_id:
                    cmd.extend(["--taskId", self.cline.task_id])
                    logger.info(f"Resuming task: {self.cline.task_id}")
                else:
                    cmd.extend(["--model", self.cline.model])
                
                cmd.extend(["--timeout", str(CLINE_TIMEOUT)])
                cmd.extend(["--cwd", self.cline.working_dir])
                
                # Prepend context if available
                if context_preamble:
                    cmd.append(f"Context:{context_preamble}\n\nUser message: {message}")
                else:
                    cmd.append(message)
                
                logger.info(f"Running Cline: {' '.join(cmd[:4])}... (message)")
                
                # Create initial streaming message if we have context
                stream_msg_id = stream_message_id
                if context and chat_id and not stream_msg_id:
                    try:
                        msg = await context.bot.send_message(
                            chat_id=chat_id,
                            text="🔄 *Cline is working...*\n\n`Starting...`",
                            parse_mode="Markdown"
                        )
                        stream_msg_id = msg.message_id
                    except Exception as e:
                        logger.warning(f"Could not create stream message: {e}")
                
                # Run Cline and capture output in real-time
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.cline.working_dir
                )
                
                # Collect output in real-time with live updates
                output = ""
                last_edit_time = 0
                last_edit_text = ""
                task_id = None
                edit_interval = 1.5  # Edit message every 1.5 seconds max
                
                while True:
                    try:
                        # Read a chunk of output
                        chunk = await asyncio.wait_for(
                            process.stdout.read(512),
                            timeout=0.5
                        )
                        
                        if chunk:
                            chunk_str = chunk.decode('utf-8', errors='replace')
                            output += chunk_str
                            
                            # Log to terminal prominently
                            if chunk_str.strip():
                                # Clean and print to terminal for visibility
                                clean_chunk = self.cline.clean_output(chunk_str)
                                if clean_chunk:
                                    print("\n" + "="*60)
                                    print("🤖 CLINE OUTPUT:")
                                    print("-"*60)
                                    print(clean_chunk[:500])
                                    print("="*60 + "\n")
                                    logger.info(f"Cline: {clean_chunk[:100]}...")
                            
                            # Try to extract task ID
                            if not task_id:
                                task_match = re.search(r'Task started:\s*(\d+)', output)
                                if task_match:
                                    task_id = task_match.group(1)
                                    logger.info(f"Task ID: {task_id}")
                            
                            # Edit the streaming message periodically
                            current_time = time.time()
                            if context and chat_id and stream_msg_id and (current_time - last_edit_time) > edit_interval:
                                # Prepare preview text
                                preview = self.cline.clean_output(output)
                                if preview and preview != last_edit_text:
                                    # Add status header
                                    status_text = f"🔄 *Cline working...*\n\n```\n{preview[:3500]}\n```"
                                    try:
                                        await context.bot.edit_message_text(
                                            chat_id=chat_id,
                                            message_id=stream_msg_id,
                                            text=status_text,
                                            parse_mode="Markdown"
                                        )
                                        last_edit_time = current_time
                                        last_edit_text = preview
                                    except Exception as e:
                                        # Message not changed or other error
                                        pass
                        
                        # Check if process finished
                        if process.returncode is not None:
                            break
                            
                    except asyncio.TimeoutError:
                        # No output for 0.5 seconds, check if process is done
                        if process.returncode is not None:
                            break
                        # Continue waiting
                            
                    except Exception as e:
                        logger.error(f"Error reading output: {e}")
                        break
                
                # Get any remaining stderr
                stderr = await process.stderr.read()
                error = stderr.decode('utf-8', errors='replace')
                
                if process.returncode != 0 and error:
                    logger.error(f"Cline error: {error}")
                
                logger.info(f"Cline completed. Output length: {len(output)} chars")
                
                # Try to delete the streaming message
                if context and chat_id and stream_msg_id:
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=stream_msg_id)
                    except:
                        pass
                
                return (self.cline.clean_output(output) or "✅ Cline completed.", task_id, None)
                
            except FileNotFoundError:
                return ("❌ Cline CLI not found. Make sure it's installed and in PATH.", None, None)
            except Exception as e:
                logger.error(f"Error communicating with Cline: {e}")
                return (f"Error: {str(e)}", None, None)


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
        "/files - List files in working directory\n"
        "/get <filename> - Download a specific file\n"
        "/kill - Kill and restart session\n\n"
        "*💡 Tip:* Ask Cline to create HTML/CSS/JS files and they'll be sent to you automatically!",
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


async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /tasks command - list recent tasks."""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("Unauthorized access.")
        return
    
    # Run cline history to get task list
    try:
        process = await asyncio.create_subprocess_exec(
            CLINE_PATH, "history",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=bridge.cline.working_dir
        )
        stdout, stderr = await process.communicate()
        output = stdout.decode('utf-8', errors='replace')
        
        if not output.strip():
            await update.message.reply_text("📋 No tasks found.")
            return
        
        # Parse and format tasks
        lines = output.strip().split('\n')[:20]  # Last 20 tasks
        msg = "📋 *Recent Tasks:*\n\n"
        
        for line in lines:
            if line.strip():
                # Clean up the line
                clean = line.strip()[:100]
                msg += f"`{clean}`\n"
        
        msg += "\n_Use /resume <taskId> to continue a task_"
        
        await update.message.reply_text(msg[:4000], parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error listing tasks: {str(e)}")


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /resume command - resume a specific task."""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("Unauthorized access.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /resume <taskId>\nUse /tasks to list available tasks.", parse_mode="Markdown")
        return
    
    task_id = context.args[0]
    bridge.cline.task_id = task_id
    
    await update.message.reply_text(
        f"✅ Task set to: `{task_id}`\n"
        f"Next message will continue this task.",
        parse_mode="Markdown"
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
    """Handle /status command - show detailed session stats."""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("Unauthorized access.")
        return
    
    stats = bridge.cline.get_stats()
    
    status_emoji = "🟢" if stats["active"] else "🔴"
    uptime_mins = stats["uptime_seconds"] // 60
    uptime_secs = stats["uptime_seconds"] % 60
    
    msg = (
        f"📊 *Session Statistics*\n\n"
        f"*Status:* {status_emoji} {'Active' if stats['active'] else 'Inactive'}\n"
        f"*Task ID:* `{stats['task_id'] or 'None'}`\n"
        f"*Messages:* {stats['messages']}\n"
        f"*Uptime:* {uptime_mins}m {uptime_secs}s\n"
        f"*Model:* `{stats['model']}`\n"
        f"*Directory:* `{stats['working_dir']}`\n\n"
        f"_Use /reset to start a new session_"
    )
    
    await update.message.reply_text(msg, parse_mode="Markdown")


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


async def files_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /files command - list files in working directory."""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("Unauthorized access.")
        return
    
    files = bridge.scan_files()
    
    if not files:
        await update.message.reply_text("📂 No files found in working directory.")
        return
    
    # Group by extension
    by_ext = {}
    for f in files:
        ext = os.path.splitext(f)[1].lower() or 'other'
        if ext not in by_ext:
            by_ext[ext] = []
        by_ext[ext].append(os.path.basename(f))
    
    # Build message
    msg = f"📂 *Files in* `{bridge.cline.working_dir}`:\n\n"
    for ext, names in sorted(by_ext.items()):
        msg += f"*{ext}:*\n"
        for name in names[:10]:  # Max 10 per type
            msg += f"  • `{name}`\n"
        if len(names) > 10:
            msg += f"  _...and {len(names) - 10} more_\n"
        msg += "\n"
    
    # Truncate if too long
    if len(msg) > 4000:
        msg = msg[:3997] + "..."
    
    await update.message.reply_text(msg, parse_mode="Markdown")


async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /get command - download a specific file."""
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("Unauthorized access.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /get <filename>", parse_mode="Markdown")
        return
    
    file_name = " ".join(context.args)
    
    # Search for the file
    files = bridge.scan_files()
    matches = [f for f in files if os.path.basename(f).lower() == file_name.lower()]
    
    if not matches:
        # Try partial match
        matches = [f for f in files if file_name.lower() in os.path.basename(f).lower()]
    
    if not matches:
        await update.message.reply_text(f"❌ File not found: `{file_name}`", parse_mode="Markdown")
        return
    
    if len(matches) > 5:
        await update.message.reply_text(f"⚠️ Too many matches ({len(matches)}). Be more specific.", parse_mode="Markdown")
        return
    
    for file_path in matches:
        try:
            file_size = os.path.getsize(file_path)
            if file_size > 50 * 1024 * 1024:
                await update.message.reply_text(f"⚠️ File too large: `{os.path.basename(file_path)}` ({file_size // (1024*1024)}MB)", parse_mode="Markdown")
                continue
            
            ext = os.path.splitext(file_path)[1].lower()
            actual_name = os.path.basename(file_path)
            
            if ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
                with open(file_path, 'rb') as f:
                    await update.message.reply_photo(
                        photo=InputFile(f, filename=actual_name),
                        caption=f"📷 `{actual_name}`",
                        parse_mode="Markdown"
                    )
            else:
                with open(file_path, 'rb') as f:
                    await update.message.reply_document(
                        document=InputFile(f, filename=actual_name),
                        caption=f"📄 `{actual_name}`",
                        parse_mode="Markdown"
                    )
        except Exception as e:
            await update.message.reply_text(f"❌ Failed to send `{os.path.basename(file_path)}`: {str(e)}", parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not is_authorized(user_id):
        await update.message.reply_text("Unauthorized access.")
        return
    
    user_message = update.message.text
    logger.info(f"Message from {user_id}: {user_message[:50]}...")
    
    # Track existing files before running Cline
    bridge.track_current_files()
    
    # Send initial "processing" message
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    # Send to Cline and get response (with live streaming)
    response, task_id, _ = await bridge.send_to_cline(user_message, chat_id=chat_id, context=context)
    
    # Store task ID for resume
    if task_id:
        bridge.cline.task_id = task_id
    
    # Check for new files created by Cline
    new_files = bridge.get_new_files()
    
    # Send response back to user
    if not response or not response.strip():
        response = "✅ Cline completed."
    
    # Add task ID if available
    if task_id:
        response += f"\n\n📋 Task ID: `{task_id}`\n_Resume with: continue_"
    
    await update.message.reply_text(response, parse_mode="Markdown")
    
    # Send any new files to the user
    if new_files:
        await update.message.reply_text(f"📎 *New files created:* {len(new_files)}", parse_mode="Markdown")
        
        for file_path in new_files:
            try:
                # Skip large files (> 50MB)
                file_size = os.path.getsize(file_path)
                if file_size > 50 * 1024 * 1024:
                    await update.message.reply_text(f"⚠️ File too large to send: `{os.path.basename(file_path)}` ({file_size // (1024*1024)}MB)", parse_mode="Markdown")
                    continue
                
                # Check file type
                ext = os.path.splitext(file_path)[1].lower()
                file_name = os.path.basename(file_path)
                
                # Images - send as photo
                if ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
                    with open(file_path, 'rb') as f:
                        await update.message.reply_photo(
                            photo=InputFile(f, filename=file_name),
                            caption=f"📷 `{file_name}`",
                            parse_mode="Markdown"
                        )
                # Code files - send as document
                elif ext in ['.html', '.css', '.js', '.py', '.json', '.md', '.txt', '.xml', '.yaml', '.yml']:
                    with open(file_path, 'rb') as f:
                        await update.message.reply_document(
                            document=InputFile(f, filename=file_name),
                            caption=f"📄 `{file_name}`",
                            parse_mode="Markdown"
                        )
                else:
                    # Other files as generic document
                    with open(file_path, 'rb') as f:
                        await update.message.reply_document(
                            document=InputFile(f, filename=file_name),
                            caption=f"📁 `{file_name}`",
                            parse_mode="Markdown"
                        )
                
                logger.info(f"Sent file: {file_name}")
                
            except Exception as e:
                logger.error(f"Failed to send file {file_path}: {e}")
                await update.message.reply_text(f"❌ Failed to send: `{os.path.basename(file_path)}` - {str(e)}", parse_mode="Markdown")


def handle_terminal_command(message: str) -> bool:
    """Handle terminal commands locally. Returns True if command was handled."""
    global bridge
    
    msg = message.strip().lower()
    args = message.strip().split(maxsplit=1)
    arg = args[1] if len(args) > 1 else None
    
    # /status or /info
    if msg in ['/status', '/info']:
        stats = bridge.cline.get_stats()
        print(f"\n📊 Session Status:")
        print(f"   Task ID: {stats['task_id'] or 'None'}")
        print(f"   Model: {stats['model']}")
        print(f"   Directory: {stats['working_dir']}")
        print(f"   Messages: {stats['messages']}\n")
        return True
    
    # /reset
    if msg == '/reset':
        bridge.cline.restart()
        print("\n✅ Session reset. Next message starts fresh.\n")
        return True
    
    # /tasks
    if msg == '/tasks':
        print("\n📋 Run 'cline history' in a separate terminal to see tasks.")
        print("   Then use /resume <taskId> to continue.\n")
        return True
    
    # /resume <id>
    if msg.startswith('/resume '):
        task_id = arg
        if task_id:
            bridge.cline.task_id = task_id
            print(f"\n✅ Task set to: {task_id}")
            print("   Next message will continue this task.\n")
        else:
            print("\nUsage: /resume <taskId>\n")
        return True
    
    # /model
    if msg == '/model':
        print(f"\n🧠 Current model: {bridge.cline.model}")
        print("   Usage: /model <model_name>\n")
        return True
    
    if msg.startswith('/model '):
        if arg:
            bridge.cline.model = arg
            print(f"\n✅ Model set to: {arg}")
            print("   Use /reset to apply.\n")
        return True
    
    # /files
    if msg == '/files':
        files = bridge.scan_files()
        if files:
            print(f"\n📂 Files ({len(files)}):")
            for f in files[:20]:
                print(f"   • {os.path.basename(f)}")
            if len(files) > 20:
                print(f"   ... and {len(files) - 20} more\n")
        else:
            print("\n📂 No files found.\n")
        return True
    
    # /help
    if msg in ['/help', '/start']:
        print("""
🖥️  TERMINAL COMMANDS:
   /status, /info  - Show session status
   /reset          - Start new session
   /tasks          - Show task info
   /resume <id>    - Resume a task
   /model [name]   - Show/set model
   /files          - List files
   /help           - Show this help
   
💬 Any other message goes to Cline!
""")
        return True
    
    return False


def terminal_input_thread():
    """Thread to read terminal input and queue it for Cline."""
    print("\n" + "="*60)
    print("🖥️  TERMINAL INPUT MODE")
    print("="*60)
    print("Commands: /status /reset /tasks /resume /model /files /help")
    print("Any other message goes to Cline.")
    print("="*60 + "\n")
    
    while True:
        try:
            user_input = input("💬 You: ")
            if user_input.strip():
                # Check if it's a local command
                if user_input.strip().startswith('/'):
                    handle_terminal_command(user_input)
                else:
                    terminal_input_queue.put(user_input)
                    print("🔄 Sending to Cline...\n")
        except EOFError:
            break
        except KeyboardInterrupt:
            print("\n👋 Exiting terminal input mode...")
            break


async def process_terminal_input(context):
    """Process terminal input and send to Cline."""
    while True:
        try:
            if not terminal_input_queue.empty():
                message = terminal_input_queue.get()
                print(f"\n🤖 Processing terminal message: {message[:50]}...")
                
                # Track files
                bridge.track_current_files()
                
                # Send to Cline
                response, task_id, _ = await bridge.send_to_cline(message, chat_id=None, context=None)
                
                # Show response
                print("\n" + "="*60)
                print("🤖 CLINE RESPONSE:")
                print("-"*60)
                print(response or "✅ Completed")
                print("="*60 + "\n")
                
                # Check for new files
                new_files = bridge.get_new_files()
                if new_files:
                    print(f"📎 New files created: {len(new_files)}")
                    for f in new_files:
                        print(f"  • {os.path.basename(f)}")
                    print()
                    
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Error processing terminal input: {e}")
            await asyncio.sleep(1)


def main() -> None:
    """Start the bot with both Telegram and Terminal interfaces."""
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
    
    # Start terminal input thread
    input_thread = threading.Thread(target=terminal_input_thread, daemon=True)
    input_thread.start()
    
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
    application.add_handler(CommandHandler("files", files_command))
    application.add_handler(CommandHandler("get", get_command))
    application.add_handler(CommandHandler("tasks", tasks_command))
    application.add_handler(CommandHandler("resume", resume_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Start bot with terminal input processing
    logger.info("Starting Telegram-Cline Bridge with Terminal Interface...")
    
    async def post_init(application):
        """Start terminal input processing after bot initializes."""
        asyncio.create_task(process_terminal_input(application))
    
    application.post_init = post_init
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()