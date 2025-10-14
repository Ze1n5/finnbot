import os
import json
import asyncio
import threading
import atexit
import signal
from datetime import datetime
from flask import Flask, jsonify, request, send_from_directory
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, CallbackContext, filters
from simple_bot import SimpleFinnBot

# ========== PERSISTENT STORAGE SETUP ==========
PERSISTENT_DIR = "/data"

def get_persistent_path(filename):
    os.makedirs(PERSISTENT_DIR, exist_ok=True)
    return os.path.join(PERSISTENT_DIR, filename)

print(f"🎯 FORCING persistent directory: {PERSISTENT_DIR}")

# ========== FLASK APP INITIALIZATION ==========
app = Flask(__name__)
BOT_TOKEN = os.environ.get('BOT_TOKEN')

# ========== WEB ENDPOINTS ==========
@app.route('/health')
def health_check():
    return jsonify({"status": "healthy", "message": "Server is running"})

@app.route('/debug-storage')
def debug_storage():
    storage_info = {
        "persistent_dir": PERSISTENT_DIR,
        "data_dir_exists": os.path.exists(PERSISTENT_DIR),
        "current_directory": os.listdir(".") if os.path.exists(".") else [],
        "data_directory": os.listdir(PERSISTENT_DIR) if os.path.exists(PERSISTENT_DIR) else []
    }
    return jsonify(storage_info)

@app.route('/api/financial-data')
def api_financial_data():
    try:
        # Read from persistent storage
        transactions_file = get_persistent_path("transactions.json")
        incomes_file = get_persistent_path("incomes.json")
        
        # Calculate totals from persistent files
        total_income = 0
        total_expenses = 0
        balance = 0
        
        try:
            with open(incomes_file, 'r') as f:
                incomes_data = json.load(f)
                if isinstance(incomes_data, list):
                    total_income = sum(item.get('amount', 0) for item in incomes_data if isinstance(item, dict))
                elif isinstance(incomes_data, dict):
                    total_income = sum(incomes_data.values())
        except:
            pass
            
        try:
            with open(transactions_file, 'r') as f:
                transactions = json.load(f)
                if isinstance(transactions, list):
                    total_expenses = sum(t.get('amount', 0) for t in transactions if isinstance(t, dict) and t.get('amount', 0) < 0)
                elif isinstance(transactions, dict):
                    # Handle user-based transaction structure
                    all_transactions = []
                    for user_transactions in transactions.values():
                        if isinstance(user_transactions, list):
                            all_transactions.extend(user_transactions)
                    total_expenses = sum(t.get('amount', 0) for t in all_transactions if isinstance(t, dict) and t.get('amount', 0) < 0)
        except:
            pass
            
        balance = total_income + total_expenses
        
        # Get recent transactions for display
        recent_transactions = []
        try:
            with open(transactions_file, 'r') as f:
                transactions_data = json.load(f)
                
                if isinstance(transactions_data, list):
                    recent_data = transactions_data[-5:]  # Last 5 transactions
                elif isinstance(transactions_data, dict):
                    # Get all transactions and sort by date
                    all_transactions = []
                    for user_transactions in transactions_data.values():
                        if isinstance(user_transactions, list):
                            all_transactions.extend(user_transactions)
                    # Sort by timestamp if available, otherwise take last ones
                    recent_data = all_transactions[-5:]
                else:
                    recent_data = []
                    
                for transaction in recent_data:
                    if isinstance(transaction, dict):
                        amount = transaction.get('amount', 0)
                        description = transaction.get('description', 'Unknown')
                        category = transaction.get('category', 'Other')
                        
                        # Determine emoji
                        emoji = "💰"
                        if any(word in description.lower() for word in ['rent', 'house', 'apartment']):
                            emoji = "🏠"
                        elif any(word in description.lower() for word in ['food', 'lunch', 'dinner', 'restaurant', 'groceries']):
                            emoji = "🍕"
                        elif any(word in description.lower() for word in ['transport', 'bus', 'taxi', 'fuel']):
                            emoji = "🚗"
                        elif any(word in description.lower() for word in ['shopping', 'store', 'market']):
                            emoji = "🛍️"
                            
                        recent_transactions.append({
                            "emoji": emoji,
                            "name": description,
                            "amount": amount
                        })
        except:
            pass

        response_data = {
            'balance': balance,
            'income': total_income,
            'spending': abs(total_expenses),
            'savings': 0,  # You can calculate this if you have savings data
            'transactions': recent_transactions,
            'transaction_count': len(recent_transactions)
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"❌ Error in financial data API: {e}")
        return jsonify({'error': 'Calculation error'}), 500

# Serve mini app main page
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
            background-color: #000000;
            color: #ffffff;
            padding: 0;
            display: flex;
            justify-content: center;
            min-height: 100vh;
        }
        
        .container {
            width: 100%;
            max-width: 400px;
            background-color: #1c1c1e;
            border-radius: 0;
            box-shadow: none;
            overflow: hidden;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }
        
        .balance-section {
            padding: 40px 20px 24px;
            text-align: center;
            border-bottom: 1px solid #2c2c2e;
            background-color: #1c1c1e;
        }
        
        .balance-label {
            font-size: 16px;
            color: #8e8e93;
            margin-bottom: 8px;
        }
        
        .balance-amount {
            font-size: 36px;
            font-weight: 700;
            color: #ffffff;
        }
        
        .summary-section {
            display: flex;
            padding: 20px;
            border-bottom: 1px solid #2c2c2e;
            background-color: #1c1c1e;
        }
        
        .summary-item {
            flex: 1;
            text-align: center;
        }
        
        .summary-label {
            font-size: 14px;
            color: #8e8e93;
            margin-bottom: 4px;
        }
        
        .summary-amount {
            font-size: 20px;
            font-weight: 600;
        }
        
        .income-amount {
            color: #30d158;
        }
        
        .spending-amount {
            color: #ff453a;
        }
        
        .savings-amount {
            color: #0a84ff;
        }
        
        .transactions-section {
            padding: 20px;
            background-color: #1c1c1e;
            flex-grow: 1;
            overflow-y: auto;
        }
        
        .transactions-header {
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 16px;
            color: #ffffff;
        }
        
        .transaction-item {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            padding: 12px 0;
            border-bottom: 1px solid #2c2c2e;
        }
        
        .transaction-info {
            display: flex;
            align-items: flex-start;
            flex: 1;
        }
        
        .transaction-emoji {
            font-size: 20px;
            margin-right: 12px;
            width: 24px;
            text-align: center;
            margin-top: 2px;
        }
        
        .transaction-details {
            flex: 1;
        }
        
        .transaction-name {
            font-size: 16px;
            color: #ffffff;
            margin-bottom: 4px;
        }
        
        .transaction-date {
            font-size: 12px;
            color: #8e8e93;
        }
        
        .transaction-amount {
            font-size: 16px;
            font-weight: 400;
            text-align: right;
            min-width: 80px;
        }
        
        .loading {
            text-align: center;
            padding: 20px;
            color: #8e8e93;
        }
        
        .no-transactions {
            text-align: center;
            padding: 40px 20px;
            color: #8e8e93;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="balance-section">
            <div class="balance-label">Balance</div>
            <div class="balance-amount" id="balance-amount">0</div>
        </div>
        
        <div class="summary-section">
            <div class="summary-item">
                <div class="summary-label">Income</div>
                <div class="summary-amount income-amount" id="income-amount">0</div>
            </div>
            <div class="summary-item">
                <div class="summary-label">Spending</div>
                <div class="summary-amount spending-amount" id="spending-amount">0</div>
            </div>
            <div class="summary-item">
                <div class="summary-label">Savings</div>
                <div class="summary-amount savings-amount" id="savings-amount">0</div>
            </div>
        </div>
        
        <div class="transactions-section" id="transactions-section">
            <div class="transactions-header">Transactions</div>
            <div id="transactions-list">
                <div class="loading">Loading transactions...</div>
            </div>
        </div>
    </div>

    <script>
        // Fetch real data from your API
        async function loadFinancialData() {
            try {
                const response = await fetch('/api/financial-data');
                if (!response.ok) {
                    throw new Error('API response not ok');
                }
                const data = await response.json();
                
                console.log('📊 API Response:', data);
                
                // Update the UI with real data
                document.getElementById('balance-amount').textContent = formatCurrency(data.balance || 0);
                document.getElementById('income-amount').textContent = formatCurrency(data.income || 0);
                document.getElementById('spending-amount').textContent = formatCurrency(data.spending || 0);
                document.getElementById('savings-amount').textContent = formatCurrency(data.savings || 0);
                
                // Update transactions list
                const transactionsList = document.getElementById('transactions-list');
                if (data.transactions && data.transactions.length > 0) {
                    transactionsList.innerHTML = '';
                    data.transactions.forEach(transaction => {
                        const transactionElement = document.createElement('div');
                        transactionElement.className = 'transaction-item';
                        
                        const isIncome = transaction.amount > 0;
                        const amountClass = isIncome ? 'income-amount' : 'spending-amount';
                        const amountDisplay = isIncome ? 
                            `+${formatCurrency(transaction.amount)}` : 
                            `-${formatCurrency(Math.abs(transaction.amount))}`;
                        
                        transactionElement.innerHTML = `
                            <div class="transaction-info">
                                <div class="transaction-emoji">${transaction.emoji || '💰'}</div>
                                <div class="transaction-details">
                                    <div class="transaction-name">${transaction.name || 'Transaction'}</div>
                                </div>
                            </div>
                            <div class="transaction-amount ${amountClass}">
                                ${amountDisplay}₴
                            </div>
                        `;
                        transactionsList.appendChild(transactionElement);
                    });
                } else {
                    transactionsList.innerHTML = `
                        <div class="no-transactions">
                            <div style="font-size: 24px; margin-bottom: 8px;">📊</div>
                            <div>No transactions yet</div>
                            <div style="font-size: 12px; margin-top: 8px;">Start adding transactions in the bot</div>
                        </div>
                    `;
                }
                
            } catch (error) {
                console.error('Error loading financial data:', error);
                document.getElementById('balance-amount').textContent = '0';
                document.getElementById('income-amount').textContent = '0';
                document.getElementById('spending-amount').textContent = '0';
                document.getElementById('savings-amount').textContent = '0';
                document.getElementById('transactions-list').innerHTML = '<div class="loading">Failed to load transactions</div>';
            }
        }

        function formatCurrency(amount) {
            return new Intl.NumberFormat('en-US').format(amount);
        }

        // Load data when page loads
        document.addEventListener('DOMContentLoaded', function() {
            loadFinancialData();
        });
    </script>
</body>
</html>"""

# ========== BOT INSTANCE INITIALIZATION ==========
bot_instance = SimpleFinnBot()

# ========== SHUTDOWN HANDLER ==========
def save_all_data():
    """Save all data before shutdown"""
    print("💾 Saving all data before shutdown...")
    try:
        bot_instance.save_transactions()
        bot_instance.save_incomes()
        bot_instance.save_user_categories()
        bot_instance.save_user_languages()
        print("✅ All data saved successfully!")
    except Exception as e:
        print(f"❌ Error during shutdown save: {e}")

# Register shutdown handlers
atexit.register(save_all_data)
signal.signal(signal.SIGTERM, lambda signum, frame: save_all_data())
signal.signal(signal.SIGINT, lambda signum, frame: save_all_data())

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
        incomes_file = get_persistent_path("incomes.json")
        transactions_file = get_persistent_path("transactions.json")
        
        with open(incomes_file, 'r') as f:
            incomes = json.load(f)
    except:
        incomes = []
    
    try:
        with open(transactions_file, 'r') as f:
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
        categories_file = get_persistent_path("user_categories.json")
        with open(categories_file, 'r') as f:
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
        categories_file = get_persistent_path("user_categories.json")
        with open(categories_file, 'r') as f:
            categories = json.load(f)
    except:
        categories = []
    
    if category not in categories:
        categories.append(category)
        with open(categories_file, 'w') as f:
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
            transactions_file = get_persistent_path("transactions.json")
            with open(transactions_file, 'r') as f:
                transactions = json.load(f)
        except:
            transactions = []
        
        transactions.append(transaction)
        
        with open(transactions_file, 'w') as f:
            json.dump(transactions, f)
        
        await update.message.reply_text(f"✅ Recorded: {description} - {amount}₴")
        
    except ValueError:
        await update.message.reply_text("Please provide a valid amount number!")

def set_webhook():
    """Set Telegram webhook URL only if token is available"""
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        print("❌ Cannot set webhook - bot token not configured")
        return
    
    try:
        webhook_url = "https://finnbot-production.up.railway.app/webhook"
        # You might need to implement webhook logic here
        print(f"✅ Webhook would be set to: {webhook_url}")
    except Exception as e:
        print(f"❌ Error setting webhook: {e}")

# ========== MAIN EXECUTION ==========

if __name__ == "__main__":
    # Railway will set PORT environment variable
    port = int(os.environ.get("PORT", 8080))
    
    # Check for bot token but don't exit - just warn
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        print("❌ WARNING: Bot token not set. Telegram bot features will not work.")
        print("💡 Please set BOT_TOKEN environment variable on Railway")
    else:
        # Only set webhook if token is available
        set_webhook()
        print("✅ Bot token found - Telegram bot is active")
    
    print(f"🚀 Starting FinnBot on port {port}...")
    print(f"🎯 Persistent directory: {PERSISTENT_DIR}")
    
    # Start bot in a separate thread
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()
    
    app.run(host='0.0.0.0', port=port, debug=False)