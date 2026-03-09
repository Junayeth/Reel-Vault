from telegram.ext import Application, MessageHandler, CommandHandler, filters
from telegram import Update
from telegram.ext import ContextTypes
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from database import save_reminder, get_due_reminders, mark_reminder_sent, get_user_reminders
import google.generativeai as genai
from PIL import Image
import os, asyncio, json, io
from flask import Flask, request
from datetime import datetime, timezone

load_dotenv()

genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

model = genai.GenerativeModel(
    "gemini-1.5-flash",
    system_instruction="""Always respond in the same language the user writes in. If they write in Bangla, respond in Bangla. If English, respond in English. You can handle both in the same conversation.

You are a powerful AI assistant on Telegram. You can:
- Answer any question using your knowledge
- Summarise text, articles or documents
- Draft messages, emails or any content
- Analyse images sent by the user
- Set and manage reminders

Formatting rules:
- Use *bold* for key points
- Keep paragraphs short — this is Telegram not a document
- If the user pastes a long text without instructions, summarise it

IMPORTANT — Reminder detection:
If the user wants a reminder, respond ONLY with JSON:
{
  "type": "reminder",
  "message": "what to remind them",
  "remind_at": "ISO 8601 UTC datetime e.g. 2026-03-09T15:00:00Z"
}
Current UTC time: """ + datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + """
If they ask to see reminders: {"type": "list_reminders"}
For everything else respond normally."""
)

vision_model = genai.GenerativeModel("gemini-1.5-flash")

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
            print(f"Reminder error: {e}")


async def process_reply(update, reply, user_id):
    reply = reply.strip()

    if reply.startswith('{'):
        try:
            data = json.loads(reply)

            if data.get('type') == 'reminder':
                save_reminder(user_id, data['message'], data['remind_at'])
                t = datetime.fromisoformat(data['remind_at'].replace('Z', '+00:00'))
                formatted = t.strftime("%A %d %B at %H:%M UTC")
                await update.message.reply_text(
                    f"✅ Reminder set: *{data['message']}*\n📅 {formatted}",
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
            pass

    if len(reply) > 4096:
        for i in range(0, len(reply), 4096):
            await update.message.reply_text(reply[i:i+4096], parse_mode='Markdown')
    else:
        await update.message.reply_text(reply, parse_mode='Markdown')


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ''
    user_id = str(update.effective_user.id)

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        chat = get_chat(user_id)
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: chat.send_message(text)
        )
        await process_reply(update, response.text, user_id)
    except Exception as e:
        await update.message.reply_text("Sorry, something went wrong. Try again or use /clear.")
        print(f"Text error: {e}")


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    caption = update.message.caption or "Analyse this image and describe what you see in detail."

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        img_bytes = await file.download_as_bytearray()
        img = Image.open(io.BytesIO(img_bytes))

        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: vision_model.generate_content([img, caption])
        )
        await process_reply(update, response.text, user_id)

    except Exception as e:
        await update.message.reply_text("Sorry, I couldn't analyse that image. Try again.")
        print(f"Image error: {e}")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        doc = update.message.document
        if doc.mime_type and 'text' in doc.mime_type:
            file = await context.bot.get_file(doc.file_id)
            file_bytes = await file.download_as_bytearray()
            text = file_bytes.decode('utf-8', errors='ignore')[:8000]

            chat = get_chat(user_id)
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: chat.send_message(f"Please summarise this document:\n\n{text}")
            )
            await process_reply(update, response.text, user_id)
        else:
            await update.message.reply_text(
                "I can summarise text files. For other file types, copy and paste the content."
            )
    except Exception as e:
        await update.message.reply_text("Sorry, I couldn't read that file.")
        print(f"Document error: {e}")


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    conversations.pop(user_id, None)
    await update.message.reply_text(
        "👋 Hi! I'm your AI assistant.\n\n"
        "Here's what I can do:\n\n"
        "💬 *Chat & Q&A* — ask me anything\n"
        "📝 *Summarise* — paste any text or article\n"
        "✍️ *Draft* — emails, messages, posts\n"
        "🖼 *Analyse images* — send me any photo\n"
        "📄 *Read files* — send a text document\n"
        "⏰ *Reminders* — \"Remind me to call John at 3pm\"\n"
        "📋 *List reminders* — \"Show my reminders\"\n\n"
        "I also speak Bangla 🇧🇩 — just write in Bangla and I'll reply in Bangla.\n\n"
        "Use /clear to start a fresh conversation.",
        parse_mode='Markdown'
    )


async def handle_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    conversations.pop(user_id, None)
    await update.message.reply_text("✅ Conversation cleared. Starting fresh!")


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Commands:*\n"
        "/start — Welcome message\n"
        "/clear — Reset conversation\n"
        "/help — Show this message\n\n"
        "*Tips:*\n"
        "• Send a photo with a question as caption\n"
        "• Paste long text and I'll summarise it\n"
        "• Say *\"remind me to...\"* to set a reminder\n"
        "• Write in Bangla and I'll reply in Bangla",
        parse_mode='Markdown'
    )


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
    tg_app.add_handler(CommandHandler("help", handle_help))
    tg_app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    tg_app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    tg_app.add_handler(MessageHandler(filters.TEXT, handle_message))

    loop.run_until_complete(tg_app.initialize())
    loop.run_until_complete(tg_app.bot.set_webhook(f"{webhook_url}/webhook"))

    scheduler = BackgroundScheduler()
    scheduler.add_job(check_reminders, 'interval', minutes=1)
    scheduler.start()

    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)


if __name__ == '__main__':
    main()
