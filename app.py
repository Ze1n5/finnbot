import os
import json
import asyncio
import threading
from datetime import datetime
from flask import Flask, jsonify, request, send_from_directory
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, CallbackContext, filters

# Initialize Flask app
app = Flask(__name__)
BOT_TOKEN = os.environ.get('BOT_TOKEN')

# Your existing command functions
async def start_command(update: Update, context: CallbackContext):
    # This will be your Railway URL - we'll get it after deployment
    web_app_url = "https://finnbot-production.up.railway.app/mini-app"    
    keyboard = [
        [InlineKeyboardButton("📊 Open Financial Dashboard", web_app=WebAppInfo(url=web_app_url))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Welcome to FinnBot! Your personal finance assistant. 📈\n\n"
        "Use /addcategory to create spending categories\n"
        "Use /summary to see your financial overview\n"
        "Or tap below to open your dashboard:",
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: CallbackContext):
    help_text = """
🤖 **FinnBot Commands:**

/start - Start the bot and see dashboard
/help - Show this help message
/summary - Get financial summary
/categories - View spending categories
/addcategory - Add new spending category

**How to use:**
1. First, use /addcategory to create spending categories
2. Then just send messages like:
   - "Lunch 150₴" 
   - "Salary 5000₴"
   - "Groceries 300₴ Food"
3. Use /summary to see your finances
"""
    await update.message.reply_text(help_text)

async def summary_command(update: Update, context: CallbackContext):
    try:
        with open('incomes.json', 'r') as f:
            incomes = json.load(f)
    except:
        incomes = []
    
    try:
        with open('transactions.json', 'r') as f:
            transactions = json.load(f)
    except:
        transactions = []
    
    total_income = sum(item.get('amount', 0) for item in incomes if isinstance(item, dict))
    total_expenses = sum(t.get('amount', 0) for t in transactions if isinstance(t, dict) and t.get('amount', 0) < 0)
    balance = total_income + total_expenses
    
    summary_text = f"""
💼 **Financial Summary**

💰 Total Income: {total_income}₴
💸 Total Expenses: {abs(total_expenses)}₴
🏦 Current Balance: {balance}₴
📊 Total Transactions: {len(transactions)}
"""
    await update.message.reply_text(summary_text)

async def categories_command(update: Update, context: CallbackContext):
    try:
        with open('user_categories.json', 'r') as f:
            categories = json.load(f)
    except:
        categories = []
    
    if not categories:
        await update.message.reply_text("No categories yet. Use /addcategory to create some!")
        return
    
    categories_text = "📁 **Your Categories:**\n" + "\n".join([f"• {cat}" for cat in categories])
    await update.message.reply_text(categories_text)

async def add_category_command(update: Update, context: CallbackContext):
    if not context.args:
        await update.message.reply_text("Usage: /addcategory <category_name>")
        return
    
    category = ' '.join(context.args)
    
    try:
        with open('user_categories.json', 'r') as f:
            categories = json.load(f)
    except:
        categories = []
    
    if category not in categories:
        categories.append(category)
        with open('user_categories.json', 'w') as f:
            json.dump(categories, f)
        await update.message.reply_text(f"✅ Category '{category}' added!")
    else:
        await update.message.reply_text(f"ℹ️ Category '{category}' already exists!")

async def handle_text_message(update: Update, context: CallbackContext):
    user_message = update.message.text
    
    parts = user_message.split()
    if len(parts) < 2:
        await update.message.reply_text("Please send in format: <amount> <description>")
        return
    
    try:
        amount = float(parts[0])
        description = ' '.join(parts[1:])
        
        transaction = {
            'amount': amount,
            'description': description,
            'timestamp': datetime.now().isoformat()
        }
        
        try:
            with open('transactions.json', 'r') as f:
                transactions = json.load(f)
        except:
            transactions = []
        
        transactions.append(transaction)
        
        with open('transactions.json', 'w') as f:
            json.dump(transactions, f)
        
        await update.message.reply_text(f"✅ Recorded: {description} - {amount}₴")
        
    except ValueError:
        await update.message.reply_text("Please provide a valid amount number!")

# ========== WEB ENDPOINTS ==========

# Serve mini app main page
# Simple mini app
@app.route('/mini-app')
def serve_mini_app():
    return """
    <!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Budget Tracker</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
        }
        
        body {
            background-color: #f5f5f7;
            color: #1d1d1f;
            padding: 20px;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }
        
        .container {
            width: 100%;
            max-width: 400px;
            background-color: white;
            border-radius: 16px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
            overflow: hidden;
        }
        
        .header {
            padding: 24px 20px 16px;
            text-align: center;
            border-bottom: 1px solid #e5e5e7;
        }
        
        .header h1 {
            font-size: 24px;
            font-weight: 600;
            color: #1d1d1f;
        }
        
        .balance-section {
            padding: 24px 20px;
            text-align: center;
            border-bottom: 1px solid #e5e5e7;
        }
        
        .balance-label {
            font-size: 16px;
            color: #86868b;
            margin-bottom: 8px;
        }
        
        .balance-amount {
            font-size: 36px;
            font-weight: 700;
            color: #1d1d1f;
        }
        
        .summary-section {
            display: flex;
            padding: 20px;
            border-bottom: 1px solid #e5e5e7;
        }
        
        .summary-item {
            flex: 1;
            text-align: center;
        }
        
        .summary-label {
            font-size: 14px;
            color: #86868b;
            margin-bottom: 4px;
        }
        
        .summary-amount {
            font-size: 20px;
            font-weight: 600;
        }
        
        .income-amount {
            color: #34c759;
        }
        
        .spending-amount {
            color: #ff3b30;
        }
        
        .savings-amount {
            color: #007aff;
        }
        
        .transactions-section {
            padding: 20px;
        }
        
        .transactions-header {
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 16px;
            color: #1d1d1f;
        }
        
        .transaction-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid #f2f2f7;
        }
        
        .transaction-item:last-child {
            border-bottom: none;
        }
        
        .transaction-info {
            display: flex;
            align-items: center;
        }
        
        .transaction-emoji {
            font-size: 20px;
            margin-right: 12px;
            width: 24px;
            text-align: center;
        }
        
        .transaction-name {
            font-size: 16px;
            color: #1d1d1f;
        }
        
        .transaction-amount {
            font-size: 16px;
            font-weight: 600;
            color: #1d1d1f;
        }
        
        .rent-amount {
            color: #ff3b30;
        }
        
        .food-amount {
            color: #ff3b30;
        }
        
        .other-amount {
            color: #007aff;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Balance</h1>
        </div>
        
        <div class="balance-section">
            <div class="balance-label">Balance</div>
            <div class="balance-amount">20,000</div>
        </div>
        
        <div class="summary-section">
            <div class="summary-item">
                <div class="summary-label">Income</div>
                <div class="summary-amount income-amount">20,000</div>
            </div>
            <div class="summary-item">
                <div class="summary-label">Spending</div>
                <div class="summary-amount spending-amount">1,000</div>
            </div>
            <div class="summary-item">
                <div class="summary-label">Savings</div>
                <div class="summary-amount savings-amount">12,000</div>
            </div>
        </div>
        
        <div class="transactions-section">
            <div class="transactions-header">Transactions</div>
            
            <div class="transaction-item">
                <div class="transaction-info">
                    <div class="transaction-emoji">🏠</div>
                    <div class="transaction-name">Rent</div>
                </div>
                <div class="transaction-amount rent-amount">12,000</div>
            </div>
            
            <div class="transaction-item">
                <div class="transaction-info">
                    <div class="transaction-emoji">🍕</div>
                    <div class="transaction-name">Food</div>
                </div>
                <div class="transaction-amount food-amount">1,000</div>
            </div>
            
            <div class="transaction-item">
                <div class="transaction-info">
                    <div class="transaction-emoji">🍽️</div>
                    <div class="transaction-name">food</div>
                </div>
                <div class="transaction-amount other-amount">11,000</div>
            </div>
        </div>
    </div>
</body>
</html>"""

# ========== TELEGRAM BOT SETUP ==========

async def setup_bot():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("summary", summary_command))
    application.add_handler(CommandHandler("categories", categories_command))
    application.add_handler(CommandHandler("addcategory", add_category_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    
    print("🤖 Bot setup complete - ready to start polling...")
    return application

def start_bot():
    try:
        print("🚀 Starting Telegram bot...")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        application = loop.run_until_complete(setup_bot())
        application.run_polling()
    except Exception as e:
        print(f"❌ Error starting bot: {e}")

# ========== MAIN EXECUTION ==========

if __name__ == '__main__':
    # Railway uses PORT environment variable
    port = int(os.environ.get('PORT', 8080))
    
    # Don't start the bot in web environment - it causes issues
    if BOT_TOKEN:
        print("✅ Bot token found (bot disabled in web environment)")
    else:
        print("⚠️  Bot token not set")
    
    # Start Flask app with production server
    print(f"🌐 Starting production server on port {port}...")
    from waitress import serve
    serve(app, host='0.0.0.0', port=port)
