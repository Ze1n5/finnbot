import os
import json
import asyncio
import threading
from datetime import datetime
from flask import Flask, jsonify, request, send_from_directory
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, CallbackContext, filters

# Initialize Flask app first
app = Flask(__name__)

# Get BOT_TOKEN after Flask app is created
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    print("❌ BOT_TOKEN environment variable is not set!")
    print("Please set it in Railway dashboard → Variables")

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
    <html>
    <head>
        <title>Financial Dashboard</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>
            body { 
                font-family: Arial, sans-serif; 
                margin: 0; 
                padding: 20px; 
                background: #1a1a1a; 
                color: white; 
            }
            .container { max-width: 400px; margin: 0 auto; }
            .card { 
                background: #2d2d2d; 
                padding: 20px; 
                margin: 10px 0; 
                border-radius: 10px; 
            }
            .loading { color: #888; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>💰 Financial Dashboard</h2>
            
            <div class="card">
                <h3>Total Balance</h3>
                <h1 id="balance" class="loading">Loading...</h1>
            </div>
            
            <div class="card">
                <h3>Income vs Expenses</h3>
                <p>Income: <span id="income" class="loading">0</span>₴</p>
                <p>Expenses: <span id="expenses" class="loading">0</span>₴</p>
            </div>
            
            <div class="card">
                <h3>Recent Activity</h3>
                <p>Transactions: <span id="transactionCount" class="loading">0</span></p>
                <p>Incomes: <span id="incomeCount" class="loading">0</span></p>
            </div>
        </div>
        
        <script>
            // Load real data from API
            async function loadData() {
                try {
                    console.log('Loading financial data...');
                    const response = await fetch('/api/financial-data');
                    const data = await response.json();
                    
                    console.log('Real data received:', data);
                    
                    // Update UI with real data
                    document.getElementById('balance').textContent = data.total_balance + '₴';
                    document.getElementById('balance').className = '';
                    
                    document.getElementById('income').textContent = data.total_income;
                    document.getElementById('income').className = '';
                    
                    document.getElementById('expenses').textContent = Math.abs(data.total_expenses);
                    document.getElementById('expenses').className = '';
                    
                    document.getElementById('transactionCount').textContent = data.transaction_count;
                    document.getElementById('transactionCount').className = '';
                    
                    document.getElementById('incomeCount').textContent = data.income_count;
                    document.getElementById('incomeCount').className = '';
                    
                } catch (error) {
                    console.error('Failed to load data:', error);
                    document.getElementById('balance').textContent = 'Error loading data';
                }
            }
            
            // Load data when page opens
            document.addEventListener('DOMContentLoaded', loadData);
        </script>
    </body>
    </html>
    """

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
    # Railway uses PORT environment variable
    port = int(os.environ.get('PORT', 8080))
    
    # Check if bot token exists
    if BOT_TOKEN:
        print("✅ Bot token found")
        # Don't start the bot in thread - it causes issues
        print("⚠️  Bot disabled in web environment")
    else:
        print("⚠️  Bot token not set")
    
    # Start Flask app with Waitress production server
    print(f"🌐 Starting production server on port {port}...")
    
    if os.environ.get('RAILWAY_ENVIRONMENT'):
        # Use Waitress in production (Railway)
        from waitress import serve
        serve(app, host='0.0.0.0', port=port)
    else:
        # Use Flask dev server locally
        app.run(host='0.0.0.0', port=port, debug=False)