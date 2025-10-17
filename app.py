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
import psycopg2
from urllib.parse import urlparse

def get_db_connection():
    """Get PostgreSQL connection"""
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("❌ No DATABASE_URL environment variable found")
        return None
    
    try:
        result = urlparse(database_url)
        conn = psycopg2.connect(
            database=result.path[1:],
            user=result.username,
            password=result.password,
            host=result.hostname,
            port=result.port
        )
        return conn
    except Exception as e:
        print(f"❌ Database connection error: {e}")
        return None

def init_db():
    """Initialize database tables"""
    conn = get_db_connection()
    if not conn:
        print("❌ No database connection - tables not created")
        return False
    
    try:
        cur = conn.cursor()
        
        # Check if tables exist first
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'transactions'
            );
        """)
        transactions_exists = cur.fetchone()[0]
        
        if not transactions_exists:
            print("🔄 Creating transactions table...")
            cur.execute('''
                CREATE TABLE transactions (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    amount DECIMAL(10,2) NOT NULL,
                    description TEXT,
                    category TEXT,
                    type TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        
        # Check if incomes table exists
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'incomes'
            );
        """)
        incomes_exists = cur.fetchone()[0]
        
        if not incomes_exists:
            print("🔄 Creating incomes table...")
            cur.execute('''
                CREATE TABLE incomes (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT UNIQUE NOT NULL,
                    amount DECIMAL(10,2) NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        
        # Create indexes
        print("🔄 Creating indexes...")
        cur.execute('CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_transactions_created_at ON transactions(created_at)')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS user_languages (
                id SERIAL PRIMARY KEY,
                user_id BIGINT UNIQUE NOT NULL,
                language TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cur.execute('''
            CREATE TABLE IF NOT EXISTS user_categories (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                category_name TEXT NOT NULL,
                category_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        print("✅ PostgreSQL database tables initialized")
        return True
        # Add to your init_db() function after the incomes table:
        
    except Exception as e:
        print(f"❌ Database initialization error: {e}")
        return False
    # Add to your init_db() function after the incomes table:


# Initialize database when app starts
init_db()

# ========== PERSISTENT STORAGE SETUP ==========
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

# ========== FLASK APP INITIALIZATION ==========
app = Flask(__name__)
BOT_TOKEN = os.environ.get('BOT_TOKEN')

# ========== BOT INSTANCE INITIALIZATION ==========
print("🤖 Initializing SimpleFinnBot...")
bot_instance = SimpleFinnBot()

# Force reload of data to ensure consistency
print("🔄 Reloading bot data for consistency...")
bot_instance.load_all_data()

print(f"📊 Bot initialized with {len(bot_instance.transactions)} users' transactions")
for user_id, transactions in bot_instance.transactions.items():
    print(f"   👤 User {user_id}: {len(transactions)} transactions")
    for txn in transactions:
        print(f"      💰 {txn.get('type', 'unknown')}: {txn.get('amount', 0)} - {txn.get('description', 'no desc')}")

print(f"📊 Bot initialized with {len(bot_instance.transactions)} users' transactions")

# ========== SHUTDOWN HANDLER ==========
def save_all_data():
    """Save all data before shutdown"""
    print("💾 Saving all data before shutdown...")
    try:
        print(f"📊 Before save - Transactions: {sum(len(txns) for txns in bot_instance.transactions.values())}")
        bot_instance.save_transactions()
        bot_instance.save_incomes()
        bot_instance.save_user_categories()
        bot_instance.save_user_languages()
        print("✅ All data saved successfully!")
    except Exception as e:
        print(f"❌ Error during shutdown save: {e}")

@app.route('/api/init-db')
def api_init_db():
    """Manual database initialization"""
    success = init_db()
    return jsonify({"success": success, "message": "Database initialized"})

@app.route('/api/hard-reset', methods=['POST'])
def hard_reset():
    """COMPLETELY clear all transactions from PostgreSQL"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "No database connection"}), 500
        
        cur = conn.cursor()
        
        # Count before
        cur.execute('SELECT COUNT(*) FROM transactions')
        before_count = cur.fetchone()[0]
        
        # DELETE ALL transactions
        cur.execute('DELETE FROM transactions')
        
        # Count after
        cur.execute('SELECT COUNT(*) FROM transactions')
        after_count = cur.fetchone()[0]
        
        conn.commit()
        conn.close()
        
        # Also clear the bot's memory
        bot_instance.transactions = {}
        
        return jsonify({
            "message": "COMPLETE RESET - All transactions deleted from PostgreSQL",
            "deleted_count": before_count,
            "remaining_count": after_count
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/check-db')
def check_db():
    """Check database content"""
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "No database connection"})
    
    try:
        cur = conn.cursor()
        
        # Get transaction count
        cur.execute('SELECT COUNT(*) FROM transactions')
        transaction_count = cur.fetchone()[0]
        
        # Get sample transactions
        cur.execute('SELECT user_id, amount, description, type FROM transactions LIMIT 5')
        sample_transactions = cur.fetchall()
        
        conn.close()
        
        return jsonify({
            "transaction_count": transaction_count,
            "sample_transactions": [
                {
                    "user_id": row[0],
                    "amount": float(row[1]),
                    "description": row[2],
                    "type": row[3]
                } for row in sample_transactions
            ]
        })
        
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/api/clear-duplicates')
def clear_duplicates():
    """Clear duplicate transactions"""
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "No database connection"})
    
    try:
        cur = conn.cursor()
        
        # Count before
        cur.execute('SELECT COUNT(*) FROM transactions')
        before_count = cur.fetchone()[0]
        
        # Keep only the most recent transaction for each unique combination
        cur.execute('''
            DELETE FROM transactions 
            WHERE id NOT IN (
                SELECT MAX(id) 
                FROM transactions 
                GROUP BY user_id, amount, description, category, type
            )
        ''')
        
        # Count after
        cur.execute('SELECT COUNT(*) FROM transactions')
        after_count = cur.fetchone()[0]
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "removed_duplicates": before_count - after_count,
            "remaining_transactions": after_count
        })
        
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/check-tables')
def check_tables():
    """Check if tables exist"""
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "No database connection"})
    
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        tables = [row[0] for row in cur.fetchall()]
        conn.close()
        return jsonify({"tables": tables})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/debug-transactions')
def debug_transactions():
    """Debug transaction loading issue"""
    try:
        # Check what's in the bot instance RIGHT NOW
        bot_data = {
            "transactions_count": len(bot_instance.transactions),
            "transactions_users": list(bot_instance.transactions.keys()),
            "user_659184170_count": len(bot_instance.transactions.get(659184170, [])),
            "user_659184170_sample": bot_instance.transactions.get(659184170, [])[:2] if bot_instance.transactions.get(659184170) else []
        }
        
        # Also check the file directly
        try:
            with open('transactions.json', 'r') as f:
                file_content = json.load(f)
            file_data = {
                "file_user_659184170_count": len(file_content.get('659184170', [])),
                "file_user_659184170_sample": file_content.get('659184170', [])[:2] if file_content.get('659184170') else []
            }
        except Exception as e:
            file_data = {"file_error": str(e)}
        
        return jsonify({
            "bot_instance": bot_data,
            "file_content": file_data
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/save-data')
def save_data():
    """Manual save endpoint"""
    try:
        bot_instance.save_transactions()
        bot_instance.save_incomes()
        return jsonify({"status": "saved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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


@app.route('/api/debug-data')
def debug_data():
    """Debug endpoint to check data loading"""
    try:
        # Check if data files exist
        transactions_file = get_persistent_path("transactions.json")
        transactions_exists = os.path.exists(transactions_file)
        
        # Read file content directly
        file_content = {}
        if transactions_exists:
            with open(transactions_file, 'r') as f:
                file_content = json.load(f)
        
        return jsonify({
            "persistent_dir": PERSISTENT_DIR,
            "transactions_file": transactions_file,
            "transactions_exists": transactions_exists,
            "file_content_keys": list(file_content.keys()) if file_content else [],
            "file_content_sample": file_content,
            "bot_transactions_count": len(bot_instance.transactions),
            "bot_transactions_users": list(bot_instance.transactions.keys()),
            "bot_loaded_data": {str(k): len(v) for k, v in bot_instance.transactions.items()}
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/health')
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

@app.route('/api/debug-fs')
def debug_fs():
    """Debug the actual file system"""
    try:
        import os
        
        # Check different locations
        locations = {
            "/data": "/data",
            "current_dir": ".",
            "root": "/"
        }
        
        results = {}
        for name, path in locations.items():
            try:
                exists = os.path.exists(path)
                if exists:
                    files = os.listdir(path)
                    results[name] = {
                        "exists": True,
                        "files": files
                    }
                else:
                    results[name] = {
                        "exists": False,
                        "files": []
                    }
            except Exception as e:
                results[name] = {
                    "exists": False,
                    "error": str(e)
                }
        
        # Also check if we can create a test file
        test_file = "/data/test.txt"
        try:
            with open(test_file, 'w') as f:
                f.write("test")
            can_write = True
            # Clean up
            os.remove(test_file)
        except:
            can_write = False
        
        return jsonify({
            "file_system_check": results,
            "can_write_to_data": can_write
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== WEB ENDPOINTS ==========
@app.route('/debug-storage')
def debug_storage():
    storage_info = {
        "persistent_dir": PERSISTENT_DIR,
        "data_dir_exists": os.path.exists(PERSISTENT_DIR),
        "current_directory": os.listdir(".") if os.path.exists(".") else [],
        "data_directory": os.listdir(PERSISTENT_DIR) if os.path.exists(PERSISTENT_DIR) else [],
        "transactions_file": get_persistent_path("transactions.json"),
        "transactions_exists": os.path.exists(get_persistent_path("transactions.json")),
        "bot_transactions_count": len(bot_instance.transactions) if bot_instance else 0
    }
    return jsonify(storage_info)

@app.route('/webhook', methods=['POST'])
def webhook():
    """Receive updates from Telegram for SimpleFinnBot"""
    if request.method == 'POST':
        update_data = request.get_json()
        print(f"📨 Received webhook update")
        
        def process_and_save():
            bot_instance.process_update(update_data)
            # SAVE DATA AFTER PROCESSING
            bot_instance.save_transactions()
            bot_instance.save_incomes()
            print("💾 Data saved after webhook processing")
        
        threading.Thread(target=process_and_save).start()
        
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
    
@app.route('/api/check-data-files')
def check_data_files():
    """Check what's actually in the data files"""
    try:
        # Read files directly from /data
        transactions_file = "/data/transactions.json"
        incomes_file = "/data/incomes.json"
        
        with open(transactions_file, 'r') as f:
            transactions_content = json.load(f)
            
        with open(incomes_file, 'r') as f:
            incomes_content = json.load(f)
            
        return jsonify({
            "transactions_file_content": transactions_content,
            "incomes_file_content": incomes_content,
            "transactions_keys": list(transactions_content.keys()) if isinstance(transactions_content, dict) else [],
            "file_sizes": {
                "transactions": len(str(transactions_content)),
                "incomes": len(str(incomes_content))
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
                # For income: show category in brackets
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
    if not BOT_TOKEN:
        print("❌ Cannot set webhook - BOT_TOKEN environment variable not configured")
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
    port = int(os.environ.get("PORT", 8080))
    
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        print("❌ WARNING: Bot token not set. Telegram bot features will not work.")
    else:
        set_webhook()
        print("✅ Bot token found - Telegram bot is active")
    
    print(f"🚀 Starting FinnBot on port {port}...")
    
    # Use Waitress for production instead of Flask dev server
    from waitress import serve
    serve(app, host='0.0.0.0', port=port)