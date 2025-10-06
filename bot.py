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
    web_app_url = "https://YOUR-APP.railway.app/mini-app"
    
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
@app.route('/mini-app')
def serve_mini_app():
    return send_from_directory('finnbot-mini-app-fixed', 'index.html')

# Serve mini app static files (JS, CSS, etc.)
@app.route('/mini-app/<path:filename>')
def serve_mini_app_files(filename):
    return send_from_directory('finnbot-mini-app-fixed', filename)

# API Endpoint for Mini App
@app.route('/api/financial-data')
def api_financial_data():
    try:
        user_id = request.args.get('user_id')
        print(f"📊 Fetching financial data for user: {user_id}")
        
        # Read your actual data files
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
        
        # Calculate real totals from your data
        total_income = sum(item.get('amount', 0) for item in incomes if isinstance(item, dict))
        total_expenses = sum(t.get('amount', 0) for t in transactions if isinstance(t, dict) and t.get('amount', 0) < 0)
        total_balance = total_income + total_expenses
        savings = max(total_balance, 0)
        
        # Calculate expenses by category
        expenses_by_category = []
        category_totals = {}
        
        for transaction in transactions:
            if isinstance(transaction, dict) and transaction.get('amount', 0) < 0:
                category = transaction.get('category', 'Other')
                amount = abs(transaction.get('amount', 0))
                category_totals[category] = category_totals.get(category, 0) + amount
        
        colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7', '#DDA0DD', '#98D8C8', '#F7DC6F']
        for i, (category, amount) in enumerate(category_totals.items()):
            expenses_by_category.append({
                'category': category,
                'amount': amount,
                'color': colors[i % len(colors)]
            })
        
        recent_transactions = transactions[-10:] if transactions else []
        
        return jsonify({
            'total_balance': total_balance,
            'total_income': total_income,
            'total_expenses': total_expenses,
            'savings': savings,
            'net_debt': min(total_balance, 0),
            'expenses_by_category': expenses_by_category,
            'recent_transactions': recent_transactions,
            'transaction_count': len(transactions),
            'income_count': len(incomes)
        })
        
    except Exception as e:
        print(f"❌ Error in API: {e}")
        return jsonify({'error': 'Failed to fetch data'}), 500

# Health check endpoint
@app.route('/')
def health_check():
    return jsonify({'status': 'OK', 'message': 'FinnBot is running!'})

@app.route('/api/test')
def test_api():
    return jsonify({'message': 'API is working!', 'data': {'balance': 1000, 'income': 5000}})

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
    # Start bot in a separate thread
    bot_thread = threading.Thread(target=start_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Start Flask app
    print("🌐 Starting Flask server on port 8000...")
    app.run(host='0.0.0.0', port=8000, debug=False)