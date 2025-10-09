import os
import logging
from flask import Flask, request, jsonify
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import asyncio

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Flask app
flask_app = Flask(__name__)

# Get environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
RAILWAY_STATIC_URL = os.environ.get("RAILWAY_STATIC_URL", "")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required!")

# Initialize Telegram bot
bot = Bot(token=BOT_TOKEN)
application = Application.builder().token(BOT_TOKEN).build()

# Store active webhook URL
WEBHOOK_URL = f"{RAILWAY_STATIC_URL}/webhook".replace("http://", "https://")

# Telegram command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    user = update.effective_user
    await update.message.reply_html(
        f"Hi {user.mention_html()}! 👋\n\n"
        f"I'm FinnBot! Send me a message and I'll echo it back to you."
    )

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Echo the user message."""
    await update.message.reply_text(f"Echo: {update.message.text}")

# Add handlers to application
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

# Flask routes
@flask_app.route('/')
def home():
    return "🤖 FinnBot is running! Send a message to your bot on Telegram."

@flask_app.route('/webhook', methods=['POST', 'GET'])
async def webhook():
    if request.method == 'GET':
        return jsonify({"status": "healthy", "message": "Webhook endpoint active"})
    
    try:
        # Process Telegram update
        data = request.get_json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"Error processing update: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@flask_app.route('/test')
def test_route():
    return "✅ Test route works!", 200

async def setup_webhook():
    """Set up Telegram webhook"""
    try:
        # Remove existing webhook
        await bot.delete_webhook()
        
        # Set new webhook
        webhook_info = await bot.get_webhook_info()
        logger.info(f"Current webhook: {webhook_info.url}")
        
        result = await bot.set_webhook(WEBHOOK_URL)
        logger.info(f"Webhook set successfully: {result}")
        logger.info(f"Webhook URL: {WEBHOOK_URL}")
        
        # Verify webhook
        webhook_info = await bot.get_webhook_info()
        logger.info(f"Verified webhook: {webhook_info.url}")
        logger.info(f"Webhook info: {webhook_info}")
        
    except Exception as e:
        logger.error(f"Error setting webhook: {e}")

def run_flask():
    """Run Flask app"""
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"🚀 Starting server on port {port}")
    flask_app.run(host='0.0.0.0', port=port, debug=False)

async def main():
    """Main async function to set up and run the bot"""
    # Set up webhook
    await setup_webhook()
    
    # Run Flask app
    run_flask()

if __name__ == '__main__':
    # Run the async main function
    asyncio.run(main())