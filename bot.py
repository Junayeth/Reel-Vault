from telegram.ext import Application, MessageHandler, CommandHandler, filters
from telegram import Update
from telegram.ext import ContextTypes
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from database import save_reminder, get_due_reminders, mark_reminder_sent, get_user_reminders
import google.generativeai as genai
import os, asyncio, json
from flask import Flask, request
from datetime import datetime, timezone

load_dotenv()

genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
model = genai.GenerativeModel(
    "gemini-1.5-flash",
    system_instruction="""You are a helpful AI assistant in Telegram. You can:
- Answer any question clearly and concisely
- Summarise articles, text or documents the user pastes
- Draft messages, emails or any written content
- Help with research and explain complex topics
- Help with productivity and planning

Keep responses concise and well formatted for Telegram.
Use *bold* for emphasis and keep paragraphs short.
If the user pastes a long text, summarise it unless they ask otherwise.

IMPORTANT — Reminder detection:
If the user is asking you to remind them of something, respond ONLY with a JSON object like this:
{
  "type": "reminder",
  "message": "what to remind them about",
  "remind_at": "ISO 8601 datetime in UTC e.g. 2026-03-09T15:00:00Z"
}
Current UTC time is: """ + datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + """
If the user asks to see their reminders, respond with just: {"type": "list_reminders"}
For everything else respond normally as a helpful assistant."""
)

flask_app = Flask(__name__)
tg_app = None
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
conversations = {}


def get_chat(user_id):
    if user_id not in conversations:
        conversations[user_id] = model.start_chat(history=[])
    return conversations[user_id]


def check_reminders():
    """Runs every minute — sends due reminders"""
    due = get_due_reminders()
    for reminder in due:
        try:
            asyncio.run_coroutine_threadsafe(
                tg_app.bot.send_message(
                    chat_id=reminder['user_id'],
                    text=f"⏰ *Reminder:* {reminder['message']}",
                    parse_mode='Markdown'
                ),
                loop
            ).result(timeout=10)
            mark_reminder_sent(reminder['id'])
        except Exception as e:
            print(f"Failed to send reminder: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ''
    user_id = str(update.effective_user.id)

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    try:
        chat = get_chat(user_id)
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: chat.send_message(text)
        )
        reply = response.text.strip()

        # Check if Gemini returned a reminder JSON
        if reply.startswith('{'):
            try:
                data = json.loads(reply)

                if data.get('type') == 'reminder':
                    save_reminder(user_id, data['message'], data['remind_at'])
                    # Format time nicely for confirmation
                    remind_time = datetime.fromisoformat(data['remind_at'].replace('Z', '+00:00'))
                    formatted = remind_time.strftime("%A %d %B at %H:%M UTC")
                    await update.message.reply_text(
                        f"✅ I'll remind you: *{data['message']}*\n📅 {formatted}",
                        parse_mode='Markdown'
                    )
                    return

                elif data.get('type') == 'list_reminders':
                    reminders = get_user_reminders(user_id)
                    if not reminders:
                        await update.message.reply_text("You have no upcoming reminders.")
                        return
                    lines = []
                    for r in reminders:
                        t = datetime.fromisoformat(r['remind_at'].replace('Z', '+00:00'))
                        lines.append(f"• *{r['message']}* — {t.strftime('%a %d %b at %H:%M UTC')}")
                    await update.message.reply_text(
                        "📋 *Your reminders:*\n\n" + "\n".join(lines),
                        parse_mode='Markdown'
                    )
                    return

            except json.JSONDecodeError:
                pass  # Not JSON, treat as normal reply

        await update.message.reply_text(reply, parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(
            "Sorry, something went wrong. Try again or use /clear to reset."
        )
        print(f"Error: {e}")


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    conversations.pop(user_id, None)
    await update.message.reply_text(
        "👋 Hi! I'm your AI assistant.\n\n"
        "I can help you with:\n"
        "• *Answering questions* — just ask\n"
        "• *Summarising* — paste any text or article\n"
        "• *Drafting* — ask me to write emails, messages etc\n"
        "• *Research* — ask me to explain anything\n"
        "• *Reminders* — \"Remind me to call John tomorrow at 3pm\"\n\n"
        "Just type anything to get started.\n"
        "Use /clear to start a fresh conversation.",
        parse_mode='Markdown'
    )


async def handle_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    conversations.pop(user_id, None)
    await update.message.reply_text("✅ Conversation cleared. Starting fresh!")


@flask_app.route("/webhook", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(), tg_app.bot)
    loop.run_until_complete(tg_app.process_update(update))
    return "ok"


@flask_app.route("/")
def health():
    return "Bot is running"


def main():
    global tg_app
    token = os.getenv('TELEGRAM_TOKEN')
    webhook_url = os.getenv('WEBHOOK_URL')

    tg_app = Application.builder().token(token).build()
    tg_app.add_handler(CommandHandler("start", handle_start))
    tg_app.add_handler(CommandHandler("clear", handle_clear))
    tg_app.add_handler(MessageHandler(filters.TEXT, handle_message))

    loop.run_until_complete(tg_app.initialize())
    loop.run_until_complete(tg_app.bot.set_webhook(f"{webhook_url}/webhook"))

    # Start reminder scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_reminders, 'interval', minutes=1)
    scheduler.start()

    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)


if __name__ == '__main__':
    main()
