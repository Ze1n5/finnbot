import os
import json
import re
import asyncio
import threading
import atexit
import signal
from datetime import datetime
from flask import Flask, jsonify, request
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

# ========== BOT INSTANCE INITIALIZATION ==========
bot_instance = SimpleFinnBot()
print("🔄 Reloading bot data for consistency...")
bot_instance.load_all_data()
print(f"📊 Bot initialized with {len(bot_instance.transactions)} users' transactions")

# Force use of /data directory on Railway
def setup_persistent_storage():
    """Setup persistent storage - force /data on Railway"""
    # Always use /data on Railway
    if os.environ.get('RAILWAY_ENVIRONMENT'):
        storage_dir = "/data"
        print("🎯 FORCING Railway persistent storage: /data")
    else:
        storage_dir = "."
        print("⚠️  Using local directory for storage")
    
    # Create directory if it doesn't exist
    os.makedirs(storage_dir, exist_ok=True)
    return storage_dir

PERSISTENT_DIR = setup_persistent_storage()

def get_persistent_path(filename):
    """Get path in persistent storage directory"""
    return os.path.join(PERSISTENT_DIR, filename)

print(f"📁 Persistent directory: {PERSISTENT_DIR}")

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

@app.route('/')
def home():
    return jsonify({
        "status": "OK", 
        "message": "FinnBot is running!",
        "endpoints": {
            "mini_app": "/mini-app",
            "financial_data": "/api/financial-data",
            "health": "/health"
        }
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

# ========== WEB ENDPOINTS ==========
@app.route('/debug-storage')
def debug_storage():
    storage_info = {
        "persistent_dir": PERSISTENT_DIR,
        "data_dir_exists": os.path.exists(PERSISTENT_DIR),
        "current_directory": os.listdir(".") if os.path.exists(".") else [],
        "data_directory": os.listdir(PERSISTENT_DIR) if os.path.exists(PERSISTENT_DIR) else []
    }
    return jsonify(storage_info)

@app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    """Receive updates from Telegram for SimpleFinnBot"""
    if request.method == 'GET':
        return jsonify({"status": "healthy", "message": "Webhook endpoint active"})
    
    if request.method == 'POST':
        update_data = request.get_json()
        print(f"📨 Received webhook update")
        
        # Process the update in a separate thread to avoid timeout
        threading.Thread(target=bot_instance.process_update, args=(update_data,)).start()
        
        return jsonify({"status": "success"}), 200

@app.route('/api/financial-data')
def api_financial_data():
    try:
        print("🧮 CALCULATING FINANCIAL DATA FROM BOT INSTANCE...")
        
        if not bot_instance:
            return jsonify({'error': 'Bot not initialized'}), 500
        
        # Get transactions from the bot instance
        all_transactions = bot_instance.transactions
        print(f"📊 Total users with transactions: {len(all_transactions)}")
        
        # Initialize totals
        balance = 0
        total_income = 0
        total_expenses = 0
        total_savings = 0
        transaction_count = 0
        recent_transactions = []

        # Process ALL transactions for calculation
        if isinstance(all_transactions, dict):
            for user_id, user_transactions in all_transactions.items():
                if isinstance(user_transactions, list):
                    print(f"👤 User {user_id}: {len(user_transactions)} transactions")
                    
                    # Calculate totals from ALL transactions
                    for transaction in user_transactions:
                        if isinstance(transaction, dict):
                            amount = float(transaction.get('amount', 0))
                            trans_type = transaction.get('type', 'expense')
                            description = transaction.get('description', 'Unknown')
                            
                            print(f"   📝 {trans_type}: {amount} - {description}")
                            
                            # CORRECTED BALANCE CALCULATION
                            if trans_type == 'income':
                                balance += amount
                                total_income += amount
                            elif trans_type == 'expense':
                                balance -= amount
                                total_expenses += amount
                            elif trans_type == 'savings':
                                balance -= amount  # Money moved to savings
                                total_savings += amount
                            elif trans_type == 'debt':
                                balance += amount  # You receive money as debt
                            elif trans_type == 'debt_return':
                                balance -= amount  # You pay back debt
                            elif trans_type == 'savings_withdraw':
                                balance += amount  # You take money from savings
                                total_savings -= amount
                            
                            transaction_count += 1
                    
                    # Get recent transactions for display (last 5)
                    for transaction in user_transactions[-5:]:
                        if isinstance(transaction, dict):
                            amount = float(transaction.get('amount', 0))
                            trans_type = transaction.get('type', 'expense')
                            description = transaction.get('description', 'Unknown')
                            category = transaction.get('category', 'Other')
                            
                            # Determine emoji and display format
                            emoji = "💰"
                            display_name = description
                            
                            if trans_type == 'income':
                                emoji = "💵"
                                # For income, show category instead of description
                                display_name = category
                            elif trans_type == 'expense':
                                if any(word in description.lower() for word in ['rent', 'house', 'apartment']):
                                    emoji = "🏠"
                                elif any(word in description.lower() for word in ['food', 'lunch', 'dinner', 'restaurant', 'groceries']):
                                    emoji = "🍕"
                                elif any(word in description.lower() for word in ['transport', 'bus', 'taxi', 'fuel']):
                                    emoji = "🚗"
                                elif any(word in description.lower() for word in ['shopping', 'store', 'market']):
                                    emoji = "🛍️"
                                else:
                                    emoji = "🛒"
                            elif trans_type == 'savings':
                                emoji = "🏦"
                                display_name = "Savings"
                            elif trans_type == 'debt':
                                emoji = "💳"
                                display_name = "Debt"
                            elif trans_type == 'debt_return':
                                emoji = "🔙"
                                display_name = "Debt Return"
                            elif trans_type == 'savings_withdraw':
                                emoji = "📥"
                                display_name = "Savings Withdraw"
                            
                            # Truncate long descriptions
                            if len(display_name) > 25:
                                display_name = display_name[:22] + "..."
                            
                            recent_transactions.append({
                                "emoji": emoji,
                                "name": display_name,
                                "amount": amount  # Use original amount, let frontend handle sign
                            })

        # Use total_savings for savings display
        actual_savings = total_savings
        
        # FINAL VERIFICATION
        print("=" * 50)
        print(f"✅ FINAL CALCULATION:")
        print(f"   Balance: {balance}")
        print(f"   Total Income: {total_income}") 
        print(f"   Total Expenses: {total_expenses}")
        print(f"   Total Savings: {actual_savings}")
        print(f"   Transaction Count: {transaction_count}")
        print(f"   Recent Transactions: {len(recent_transactions)}")
        print("=" * 50)
        
        response_data = {
            'balance': balance,
            'income': total_income,
            'spending': total_expenses,
            'savings': actual_savings,
            'transactions': recent_transactions,
            'transaction_count': transaction_count
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"❌ CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Calculation error'}), 500

@app.route('/api/transactions')
def api_transactions():
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 10))
        
        if not bot_instance:
            return jsonify({'error': 'Bot not initialized'}), 500
        
        all_transactions = bot_instance.transactions
        all_transactions_list = []
        
        # Collect all transactions from all users
        if isinstance(all_transactions, dict):
            for user_id, user_transactions in all_transactions.items():
                if isinstance(user_transactions, list):
                    for transaction in user_transactions:
                        if isinstance(transaction, dict):
                            # Add user_id to transaction for uniqueness
                            transaction_with_user = transaction.copy()
                            transaction_with_user['user_id'] = user_id
                            all_transactions_list.append(transaction_with_user)
        
        # Sort by date (newest first)
        all_transactions_list.sort(key=lambda x: x.get('date', ''), reverse=True)
        
        # Calculate pagination
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_transactions = all_transactions_list[start_idx:end_idx]
        
        # Format transactions for display
        formatted_transactions = []
        for transaction in paginated_transactions:
            amount = float(transaction.get('amount', 0))
            trans_type = transaction.get('type', 'expense')
            description = transaction.get('description', 'Unknown')
            category = transaction.get('category', 'Other')
            timestamp = transaction.get('date', '')
            
            # Determine emoji and display name
            emoji = "💰"
            display_name = ""
            
            if trans_type == 'income':
                emoji = "💵"
                # For income: show category instead of description
                display_name = f"{category}"
            elif trans_type == 'expense':
                if any(word in description.lower() for word in ['rent', 'house', 'apartment']):
                    emoji = "🏠"
                elif any(word in description.lower() for word in ['food', 'lunch', 'dinner', 'restaurant', 'groceries']):
                    emoji = "🍕"
                elif any(word in description.lower() for word in ['transport', 'bus', 'taxi', 'fuel']):
                    emoji = "🚗"
                elif any(word in description.lower() for word in ['shopping', 'store', 'market']):
                    emoji = "🛍️"
                else:
                    emoji = "🛒"
                
                # For expenses: extract the actual description (remove numbers and symbols)
                # The description might be "100 food" - we want just "food"
                clean_description = description
                
                # Remove numbers and currency symbols
                clean_description = re.sub(r'[\d+.,₴]', '', clean_description).strip()
                
                # Remove common transaction symbols
                clean_description = re.sub(r'[+-]+', '', clean_description).strip()
                
                # If we have a meaningful description after cleaning
                if clean_description and clean_description.lower() != category:
                    display_name = f"{category} {clean_description}"
                else:
                    display_name = f"{category}"
                    
            elif trans_type == 'savings':
                emoji = "🏦"
                display_name = "Savings"
            elif trans_type == 'debt':
                emoji = "💳"
                display_name = "Debt"
            elif trans_type == 'debt_return':
                emoji = "🔙"
                display_name = "Debt Return"
            elif trans_type == 'savings_withdraw':
                emoji = "📥"
                display_name = "Savings Withdraw"
            
            # Truncate long descriptions
            if len(display_name) > 30:
                display_name = display_name[:27] + "..."
            
            formatted_transactions.append({
                "emoji": emoji,
                "name": display_name,
                "display_name": display_name,
                "amount": amount,
                "timestamp": timestamp,
                "type": trans_type
            })
        
        has_more = len(all_transactions_list) > end_idx
        
        return jsonify({
            'transactions': formatted_transactions,
            'has_more': has_more,
            'current_page': page,
            'total_transactions': len(all_transactions_list)
        })
        
    except Exception as e:
        print(f"❌ Error in transactions API: {e}")
        return jsonify({'error': 'Failed to load transactions'}), 500

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

def set_webhook():
    """Set Telegram webhook URL for SimpleFinnBot"""
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        print("❌ Cannot set webhook - bot token not configured")
        return
    
    try:
        webhook_url = "https://finnbot-production.up.railway.app/webhook"
        import requests
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            json={"url": webhook_url}
        )
        if response.status_code == 200:
            print("✅ Webhook set successfully!")
        else:
            print(f"❌ Failed to set webhook: {response.status_code} - {response.text}")
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
    print(f"📊 Loaded data: {len(bot_instance.transactions)} users")
    
    app.run(host='0.0.0.0', port=port, debug=False)