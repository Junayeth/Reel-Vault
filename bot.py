from telegram.ext import Application, MessageHandler, CommandHandler, filters
from telegram import Update
from telegram.ext import ContextTypes
from processor import process_reel, answer_question
from database import save_reel, get_user_reels
from dotenv import load_dotenv
import re, os, asyncio
from flask import Flask, request

load_dotenv()

INSTAGRAM_RE = re.compile(r'https?://(www\.)?instagram\.com/reel/\S+')
flask_app = Flask(__name__)
tg_app = None


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ''
    user_id = str(update.effective_user.id)
    match = INSTAGRAM_RE.search(text)

    if match:
        url = match.group()
        reel_id = save_reel(user_id, url)
        await update.message.reply_text("Saved! Analysing your reel... ⏳ (~20 secs)")
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, process_reel, reel_id, url)
        await update.message.reply_text(
            f"✅ *{result['title']}*\n\n"
            f"{result['summary']}\n\n"
            f"Tags: {' '.join(['#' + t for t in result.get('tags', [])])}",
            parse_mode='Markdown'
        )
    else:
        reels = get_user_reels(user_id)
        if not reels:
            await update.message.reply_text(
                "No reels saved yet! Share an Instagram reel link to this chat."
            )
            return
        await update.message.reply_text("Searching your reels... 🔍")
        loop = asyncio.get_event_loop()
        answer = await loop.run_in_executor(None, answer_question, text, reels)
        await update.message.reply_text(answer)


async def handle_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    reels = get_user_reels(user_id)
    if not reels:
        await update.message.reply_text("No reels saved yet!")
        return
    lines = [f"{i+1}. *{r['title']}* — {r['category']}" for i, r in enumerate(reels)]
    await update.message.reply_text(
        "Your saved reels:\n\n" + "\n".join(lines),
        parse_mode='Markdown'
    )


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to ReelsBot!\n\n"
        "• Share any Instagram reel link to this chat to save it\n"
        "• Ask me anything about your saved reels\n"
        "• Use /list to see all saved reels"
    )


@flask_app.route("/webhook", methods=["POST"])
def webhook():
    asyncio.run(
        tg_app.update_queue.put(
            Update.de_json(request.get_json(), tg_app.bot)
        )
    )
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
    tg_app.add_handler(CommandHandler("list", handle_list))
    tg_app.add_handler(MessageHandler(filters.TEXT, handle_message))

    asyncio.run(tg_app.bot.set_webhook(f"{webhook_url}/webhook"))

    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)


if __name__ == '__main__':
    main()
  
