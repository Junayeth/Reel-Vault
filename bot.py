from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from processor import process_reel, answer_question
from database import save_reel, get_user_reels
from dotenv import load_dotenv
import re, os, asyncio
from flask import Flask, request
from supabase import create_client

load_dotenv()

INSTAGRAM_RE = re.compile(r'https?://\S+')
flask_app = Flask(__name__)
tg_app = None
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
sb = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ''
    user_id = str(update.effective_user.id)
    match = INSTAGRAM_RE.search(text)

    if match:
        url = match.group()
        reel_id = save_reel(user_id, url)
        await update.message.reply_text("Saved! Analysing your reel... ⏳ (~20 secs)")
        result = await asyncio.get_event_loop().run_in_executor(None, process_reel, reel_id, url)

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("📋 Save to my notes", callback_data=f"save_{reel_id}")
        ]])

        await update.message.reply_text(
            f"✅ *{result['title']}*\n\n"
            f"{result['summary']}\n\n"
            f"Tags: {' '.join(['#' + t for t in result.get('tags', [])])}",
            parse_mode='Markdown',
            reply_markup=keyboard
        )
    else:
        reels = get_user_reels(user_id)
        if not reels:
            await update.message.reply_text(
                "No reels saved yet! Share a video link to this chat."
            )
            return
        await update.message.reply_text("Searching your reels... 🔍")
        answer = await asyncio.get_event_loop().run_in_executor(None, answer_question, text, reels)
        await update.message.reply_text(answer)


async def handle_save_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    reel_id = query.data.replace("save_", "")

    reel = sb.table('reels').select('*').eq('id', reel_id).execute().data[0]

    await context.bot.send_message(
        chat_id=query.from_user.id,
        text=f"📋 *{reel['title']}*\n\n"
             f"{reel['summary']}\n\n"
             f"🔗 {reel['url']}\n"
             f"Tags: {' '.join(['#' + t for t in (reel.get('tags') or [])])}",
        parse_mode='Markdown'
    )
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text("✅ Saved to your Telegram notes!")


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
        "👋 Welcome to Reel Vault!\n\n"
        "• Share any video link to this chat to save it\n"
        "• Ask me anything about your saved reels\n"
        "• Use /list to see all saved reels\n"
        "• Tap 📋 after any summary to save it to your Telegram notes"
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
    tg_app.add_handler(CommandHandler("list", handle_list))
    tg_app.add_handler(CallbackQueryHandler(handle_save_note))
    tg_app.add_handler(MessageHandler(filters.TEXT, handle_message))

    loop.run_until_complete(tg_app.initialize())
    loop.run_until_complete(tg_app.bot.set_webhook(f"{webhook_url}/webhook"))

    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)


if __name__ == '__main__':
    main()
