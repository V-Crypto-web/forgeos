import os
import aiohttp
import asyncio
import json
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message

# Configure logging
logging.basicConfig(level=logging.INFO)

# Fetch token from environment variable
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set. Please set it before running the bot.")

# Initialize bot and dispatcher
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# ForgeOS API Endpoints
FORGEOS_API_URL = "http://localhost:8081/api/v1"
FORGEOS_WS_URL = "ws://localhost:8081/ws/logs"

async def tail_forgeos_logs(issue_id: str, chat_id: int):
    """
    Connects to the ForgeOS WebSocket to listen for State Machine transitions.
    Sends push notifications to the user for major milestones.
    """
    try:
        # In our MVP, project ID is just the branch name usually, but for global logs we connect to issue_id
        # Our gateway `ws/logs/{project_id}` actually reads the /tmp/forgeos_telemetry.log in the backend
        # We will poll the telemetry log directly here for simplicity since the gateway WS is currently tied to project paths
        
        last_notified_state = None
        
        while True:
            # Simple polling of the global telemetry file for this issue
            try:
                with open("/tmp/forgeos_telemetry.log", "r") as f:
                    lines = f.readlines()
                    for line in reversed(lines):
                        if not line.strip(): continue
                        try:
                            event = json.loads(line)
                            if str(event.get("issue_number")) == str(issue_id):
                                current_state = event.get("state")
                                
                                # Only notify on state changes to avoid spam
                                if current_state != last_notified_state and event.get("event_type") == "state_transition":
                                    last_notified_state = current_state
                                    
                                    msg = f"🛠️ **[ForgeOS]** Issue #{issue_id}\n"
                                    if current_state == "PLAN":
                                        msg += "🧠 **Status**: PLAN. Generating architecture and logic..."
                                    elif current_state == "IMPACT_ANALYSIS":
                                        msg += "🔍 **Status**: IMPACT_ANALYSIS. Scoring change risk."
                                    elif current_state == "PATCH":
                                        msg += "💻 **Status**: PATCH. Coder is writing code..."
                                    elif current_state == "RUN_TESTS":
                                        msg += "🧪 **Status**: RUN_TESTS. Executing Sandbox verification."
                                    elif current_state == "RETRY":
                                        msg += "⚠️ **Status**: RETRY. Test failed. Routing to Failure Memory."
                                    elif current_state == "CREATE_PR":
                                        msg += "🚀 **Status**: CREATE_PR. Tests passed. Opening PR."
                                    elif current_state == "DONE":
                                        msg += "✅ **Status**: DONE. Autonomous resolution complete."
                                        await bot.send_message(chat_id, msg, parse_mode="Markdown")
                                        return # Exit polling when DONE
                                    elif current_state == "FAILED":
                                        msg += "❌ **Status**: FAILED. Execution halted due to critical error or budget cap."
                                        await bot.send_message(chat_id, msg, parse_mode="Markdown")
                                        return # Exit polling when FAILED
                                        
                                    if msg != f"🛠️ **[ForgeOS]** Issue #{issue_id}\n":
                                        await bot.send_message(chat_id, msg, parse_mode="Markdown")
                                        
                                    break # Only care about the latest state
                        except:
                            pass
            except FileNotFoundError:
                pass
                
            await asyncio.sleep(2) # Poll every 2 seconds
            
    except Exception as e:
        logging.error(f"Error in log tailer: {e}")

@dp.message(Command("start"))
async def send_welcome(message: Message):
    """
    This handler will be called when user sends `/start` command
    """
    welcome_msg = (
        "👋 Welcome to the **ForgeOS Mobile Command Center**! 🤖\n\n"
        "I am your autonomous AI engineering assistant.\n"
        "You can command me to solve GitHub issues directly from this chat.\n\n"
        "**Usage:**\n"
        "`/solve <issue_number> <repository_path_or_url>`\n\n"
        "Example:\n"
        "`/solve 1027 https://github.com/pallets/flask`"
    )
    await message.reply(welcome_msg, parse_mode="Markdown")

@dp.message(Command("solve"))
async def solve_issue(message: Message):
    """
    Triggers the ForgeOS Gateway to start a job.
    """
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply("❌ Invalid format. Use: `/solve <issue_number> <repository_path>`", parse_mode="Markdown")
        return

    issue_number = parts[1]
    repo_path = parts[2]
    
    # Send HTTP request to ForgeOS API Gateway
    payload = {
        "repo_url": repo_path,
        "issue_id": issue_number
    }
    
    await message.reply(f"🚀 Triggering ForgeOS Engine for **Issue #{issue_number}**...\nRepository: `{repo_path}`", parse_mode="Markdown")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{FORGEOS_API_URL}/jobs", json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    job_id = data.get("job_id")
                    await message.reply(f"✅ Job `{job_id}` created successfully. Starting execution stream...", parse_mode="Markdown")
                    
                    # Start background polling/streaming
                    task = asyncio.create_task(tail_forgeos_logs(issue_number, message.chat.id))
                else:
                    error_data = await resp.text()
                    await message.reply(f"❌ Failed to start job. Status: {resp.status}\n{error_data}", parse_mode="Markdown")
    except Exception as e:
         await message.reply(f"❌ Connection error. Is the ForgeOS Gateway running on port 8081?\nError: `{e}`", parse_mode="Markdown")


async def main():
    print("Starting ForgeOS Telegram Bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
