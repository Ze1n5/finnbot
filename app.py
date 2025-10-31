import os
import json
import re
import asyncio
import threading
import atexit
import signal
from datetime import datetime
from flask import Flask, jsonify, request
import psycopg2
from urllib.parse import urlparse
from simple_bot import get_bot_instance, save_all_data

bot_instance = get_bot_instance()
print(f"🔍 DEBUG: Bot instance created: {bool(bot_instance)}")

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
        bot_instance.sync_transactions_to_postgres()
        bot_instance.save_incomes()
        bot_instance.save_user_categories()
        bot_instance.save_user_languages()
        print("✅ All data saved successfully!")
    except Exception as e:
        print(f"❌ Error during shutdown save: {e}")

@app.route('/api/debug-savings-categories')
def debug_savings_categories():
    """Debug savings categories"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "No database connection"}), 500
        
        cur = conn.cursor()
        
        # Check if savings categories exist
        savings_categories = ["Crypto", "Bank", "Personal", "Investment"]
        
        results = {}
        for category in savings_categories:
            cur.execute("SELECT id, user_id, is_default FROM categories WHERE name = %s AND user_id IS NULL", (category,))
            result = cur.fetchone()
            results[category] = {
                "exists": bool(result),
                "id": result[0] if result else None,
                "user_id": result[1] if result else None,
                "is_default": result[2] if result else None
            }
        
        conn.close()
        
        return jsonify({
            "savings_categories_status": results,
            "all_exist": all(item["exists"] for item in results.values())
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/financial-data', methods=['GET'])
def api_financial_data():
    try:
        # Get user_id from query parameter
        user_id = request.args.get('user_id', type=int)
        if not user_id:
            return jsonify({'error': 'user_id parameter is required'}), 400
            
        print(f"🧮 CALCULATING FINANCIAL DATA FOR USER {user_id}...")
        
        if not bot_instance:
            return jsonify({'error': 'Bot not initialized'}), 500
        
        # Get transactions ONLY for this specific user
        user_transactions = bot_instance.transactions.get(user_id, [])
        print(f"📊 User {user_id} has {len(user_transactions)} transactions")
        
        # Calculate financial health FIRST
        health_score = bot_instance.calculate_financial_health(user_id)
        health_emoji, health_display = bot_instance.get_financial_health_display(health_score)
        # Initialize totals for THIS USER ONLY
        balance = 0
        total_income = 0
        total_expenses = 0
        total_savings = 0
        transaction_count = 0
        recent_transactions = []

        # NEW: Track dates for averages
        income_dates = set()
        expense_dates = set()
        all_dates = set()

        # Calculate totals from THIS USER'S transactions only
        for transaction in user_transactions:
            if isinstance(transaction, dict):
                amount = float(transaction.get('amount', 0))
                trans_type = transaction.get('type', 'expense')
                description = transaction.get('description', 'Unknown')
                
                # Extract date for averages
                transaction_date = None
                if 'date' in transaction:
                    try:
                        if 'T' in transaction['date']:
                            transaction_date = transaction['date'].split('T')[0]  # Get YYYY-MM-DD
                        else:
                            transaction_date = transaction['date'].split(' ')[0]  # Get YYYY-MM-DD
                    except:
                        transaction_date = None
                
                if transaction_date:
                    all_dates.add(transaction_date)
                
                # CORRECTED BALANCE CALCULATION
                if trans_type == 'income':
                    balance += amount
                    total_income += amount
                    if transaction_date:
                        income_dates.add(transaction_date)
                elif trans_type == 'expense':
                    balance -= amount
                    total_expenses += amount
                    if transaction_date:
                        expense_dates.add(transaction_date)
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
        
        # NEW: Calculate daily averages
        total_days = len(all_dates) if all_dates else 1
        total_income_days = len(income_dates) if income_dates else 1
        total_expense_days = len(expense_dates) if expense_dates else 1
        
        daily_income_avg = total_income / total_income_days if total_income_days > 0 else 0
        daily_expense_avg = total_expenses / total_expense_days if total_expense_days > 0 else 0
        daily_net_avg = (total_income - total_expenses) / total_days if total_days > 0 else 0

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
                    "amount": amount
                })

        # Use total_savings for savings display
        actual_savings = total_savings
        
        print("=" * 50)
        print(f"✅ USER {user_id} CALCULATION:")
        print(f"   Balance: {balance}")
        print(f"   Total Income: {total_income}") 
        print(f"   Total Expenses: {total_expenses}")
        print(f"   Total Savings: {actual_savings}")
        print(f"   Daily Income Avg: {daily_income_avg:,.0f}₴")
        print(f"   Daily Expense Avg: {daily_expense_avg:,.0f}₴")
        print(f"   Transaction Count: {transaction_count}")
        print(f"   Recent Transactions: {len(recent_transactions)}")
        print("=" * 50)
        
        response_data = {
            'balance': balance,
            'income': total_income,
            'spending': total_expenses,
            'savings': actual_savings,
            'daily_income_avg': daily_income_avg,
            'daily_expense_avg': daily_expense_avg,
            'daily_net_avg': daily_net_avg,
            'tracking_days': total_days,
            'financial_health': health_score,
            'financial_health_emoji': health_emoji,
            'transactions': recent_transactions,
            'transaction_count': transaction_count
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"❌ CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Calculation error'}), 500

@app.route('/api/transactions', methods=['GET'])
def api_transactions():
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 10))
        user_id = request.args.get('user_id', type=int)
        
        if not user_id:
            return jsonify({'error': 'user_id parameter is required'}), 400
        
        if not bot_instance:
            return jsonify({'error': 'Bot not initialized'}), 500
        
        # Get transactions ONLY for this specific user
        user_transactions = bot_instance.transactions.get(user_id, [])
        
        # Sort by date (newest first)
        user_transactions.sort(key=lambda x: x.get('date', ''), reverse=True)
        
        # Calculate pagination
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_transactions = user_transactions[start_idx:end_idx]
        
        # Format transactions for display
        formatted_transactions = []
        for transaction in paginated_transactions:
            amount = float(transaction.get('amount', 0))
            trans_type = transaction.get('type', 'expense')
            description = transaction.get('description', '')
            category = transaction.get('category', 'Other')
            timestamp = transaction.get('date', '')
            
            # Determine emoji based on category and type
            emoji = "💰"  # Default
            
            # INCOME TRANSACTIONS
            if trans_type == 'income':
                emoji = "💵"
                display_name = category  # Show category name for income
                
            # SAVINGS TRANSACTIONS  
            elif trans_type == 'savings':
                emoji = "🏦"
                display_name = f"Savings • {category}"
                
            # DEBT TRANSACTIONS
            elif trans_type == 'debt':
                emoji = "💳" 
                display_name = "Debt"
            elif trans_type == 'debt_return':
                emoji = "🔙"
                display_name = "Debt Return"
                
            # SAVINGS WITHDRAWAL
            elif trans_type == 'savings_withdraw':
                emoji = "📥"
                display_name = "Savings Withdraw"
                
            # EXPENSE TRANSACTIONS - Use custom categories properly
            else:  # expense
                # Map categories to emojis
                category_emoji_map = {
                    'Food': '🍕',
                    'Rent': '🏠', 
                    'Transport': '🚗',
                    'Shopping': '🛍️',
                    'Entertainment': '🎬',
                    'Healthcare': '🏥',
                    'Utilities': '💡',
                    'Other': '🛒'
                }
                
                # Use custom emoji if category exists, otherwise default
                emoji = category_emoji_map.get(category, '🛒')
                
                # Clean description - remove numbers and symbols
                clean_description = re.sub(r'[\d+.,₴\-]', '', description).strip()
                
                # Create display name: show category and cleaned description
                if clean_description and clean_description.lower() != category.lower():
                    display_name = f"{category} • {clean_description}"
                else:
                    display_name = category
            
            # Format amount with proper sign
            display_amount = amount
            if trans_type in ['expense', 'savings', 'debt_return']:
                display_amount = -abs(amount)  # Negative for expenses
            elif trans_type in ['income', 'debt', 'savings_withdraw']:
                display_amount = abs(amount)   # Positive for income/debt
                
            # Truncate long display names
            if len(display_name) > 25:
                display_name = display_name[:22] + "..."
            
            formatted_transactions.append({
                "emoji": emoji,
                "name": display_name,
                "display_name": display_name,
                "amount": display_amount,
                "timestamp": timestamp,
                "type": trans_type,
                "category": category
            })
        
        has_more = len(user_transactions) > end_idx
        
        return jsonify({
            'transactions': formatted_transactions,
            'has_more': has_more,
            'current_page': page,
            'total_transactions': len(user_transactions)
        })
        
    except Exception as e:
        print(f"❌ Error in transactions API: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Failed to load transactions'}), 500

@app.route('/api/restore-protected-categories')
def restore_protected_categories():
    """Restore the protected savings categories"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "No database connection"}), 500
        
        cur = conn.cursor()
        
        # Protected savings categories (user_id = NULL means shared for all users)
        protected_categories = [
            ("Crypto", None, True),
            ("Bank", None, True),
            ("Personal", None, True),
            ("Investment", None, True)
        ]
        
        added_count = 0
        for name, user_id, is_default in protected_categories:
            # Insert if not exists
            cur.execute("""
                INSERT INTO categories (name, user_id, is_default) 
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, name) DO NOTHING
            """, (name, user_id, is_default))
            
            if cur.rowcount > 0:
                added_count += 1
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": f"Restored {added_count} protected savings categories",
            "categories_added": ["Crypto", "Bank", "Personal", "Investment"]
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/remove-emoji-constraints')
def remove_emoji_constraints():
    """Remove all emoji constraints from categories table"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "No database connection"}), 500
        
        cur = conn.cursor()
        
        # 1. Remove UNIQUE constraint on emoji
        try:
            cur.execute("ALTER TABLE categories DROP CONSTRAINT categories_emoji_key;")
            print("✅ Removed emoji unique constraint")
        except:
            print("✅ No emoji unique constraint to remove")
        
        # 2. Remove NOT NULL constraint from emoji
        try:
            cur.execute("ALTER TABLE categories ALTER COLUMN emoji DROP NOT NULL;")
            print("✅ Removed emoji NOT NULL constraint")
        except:
            print("✅ emoji already nullable")
        
        # 3. Set all emoji values to NULL (we don't need them)
        cur.execute("UPDATE categories SET emoji = NULL;")
        print("✅ Set all emojis to NULL")
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": "ALL emoji constraints removed! Categories will now use names only."
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/complete-database-reset')
def complete_database_reset():
    """COMPLETELY RESET the categories table - 100% GUARANTEED TO WORK"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "No database connection"}), 500
        
        cur = conn.cursor()
        
        print("🔄 STARTING COMPLETE DATABASE RESET...")
        
        # 1. Drop the current categories table
        cur.execute("DROP TABLE IF EXISTS categories;")
        print("✅ Dropped old categories table")
        
        # 2. Create NEW categories table with NO emoji constraints
        cur.execute("""
            CREATE TABLE categories (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                user_id TEXT,
                is_default BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        print("✅ Created new categories table")
        
        # 3. Add unique constraint (but NOT on emoji since we don't have it)
        cur.execute("""
            ALTER TABLE categories 
            ADD CONSTRAINT categories_user_name_unique UNIQUE (user_id, name);
        """)
        print("✅ Added unique constraint")
        
        # 4. Insert default categories (WITHOUT EMOJI)
        default_categories = [
            ("Salary", None, True),
            ("Business", None, True), 
            ("Crypto", None, True),
            ("Bank", None, True),
            ("Personal", None, True),
            ("Investment", None, True),
            ("Other", None, True)
        ]
        
        for name, user_id, is_default in default_categories:
            cur.execute(
                "INSERT INTO categories (name, user_id, is_default) VALUES (%s, %s, %s)",
                (name, user_id, is_default)
            )
        
        print("✅ Added default categories")
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": "COMPLETE DATABASE RESET SUCCESSFUL!",
            "status": "Categories table completely rebuilt WITHOUT emoji column",
            "guarantee": "This will 100% fix the category creation issue"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/fix-emoji-null')
def fix_emoji_null():
    """Remove NOT NULL constraint from emoji column"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "No database connection"}), 500
        
        cur = conn.cursor()
        
        # Remove NOT NULL constraint from emoji
        cur.execute("ALTER TABLE categories ALTER COLUMN emoji DROP NOT NULL;")
        
        # Set default value for existing NULLs
        cur.execute("UPDATE categories SET emoji = '📝' WHERE emoji IS NULL;")
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": "emoji NOT NULL constraint removed"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/init-db')
def api_init_db():
    """Manual database initialization"""
    success = init_db()
    return jsonify({"success": success, "message": "Database initialized"})

@app.route('/api/final-fix-text-ids')
def final_fix_text_ids():
    """FINAL FIX: Store all IDs as TEXT to avoid integer issues"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "No database connection"}), 500
        
        cur = conn.cursor()
        
        print("🔄 Implementing FINAL fix...")
        
        # 1. Change user_id to TEXT (handles any ID format)
        try:
            cur.execute("ALTER TABLE categories ALTER COLUMN user_id TYPE TEXT;")
            print("✅ user_id changed to TEXT")
        except Exception as e:
            print(f"⚠️ Could not change to TEXT: {e}")
        
        # 2. Update existing numeric IDs to text format
        try:
            cur.execute("UPDATE categories SET user_id = user_id::TEXT WHERE user_id IS NOT NULL;")
            print("✅ Existing IDs converted to text")
        except:
            print("✅ No existing IDs to convert")
        
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": "FINAL FIX APPLIED: All IDs now stored as TEXT",
            "guaranteed_to_work": "YES - TEXT handles any ID format including large negative group IDs"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/debug-categories-columns')
def debug_categories_columns():
    """Check the actual column names in categories table"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "No database connection"}), 500
        
        cur = conn.cursor()
        
        # Get column names
        cur.execute("""
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'categories'
        """)
        
        columns = cur.fetchall()
        
        # Check if user_id column exists
        column_names = [col[0] for col in columns]
        
        conn.close()
        
        return jsonify({
            "columns": [
                {"name": col[0], "type": col[1], "nullable": col[2]} 
                for col in columns
            ],
            "column_names": column_names,
            "user_id_exists": "user_id" in column_names
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/force-add-user-id-column')
def force_add_user_id_column():
    """Force add user_id column to categories table"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "No database connection"}), 500
        
        cur = conn.cursor()
        
        # Check if user_id column exists
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'categories' AND column_name = 'user_id'
        """)
        
        if not cur.fetchone():
            # Add user_id column
            cur.execute("ALTER TABLE categories ADD COLUMN user_id BIGINT;")
            print("✅ Added user_id column to categories table")
        else:
            print("✅ user_id column already exists")
        
        # Update existing categories to have NULL user_id (they become shared)
        cur.execute("UPDATE categories SET user_id = NULL WHERE user_id IS NULL;")
        
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "message": "user_id column verified/added"})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/init-protected-categories')
def init_protected_categories():
    """Initialize protected categories for all users"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "No database connection"}), 500
        
        cur = conn.cursor()
        
        protected_categories = [
            ("💰", "Salary", True),
            ("💼", "Business", True),
            ("₿", "Crypto", True),
            ("🏦", "Bank", True),
            ("👤", "Personal", True),
            ("📈", "Investment", True),
            ("❓", "Other", True)
        ]
        
        for emoji, name, is_default in protected_categories:
            # Insert protected categories with NULL user_id (shared for all users)
            cur.execute("""
                INSERT INTO categories (emoji, name, is_default, user_id) 
                VALUES (%s, %s, %s, NULL)
                ON CONFLICT (user_id, name) DO NOTHING
            """, (emoji, name, is_default))
        
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "message": "Protected categories initialized"})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/make-categories-user-specific')
def make_categories_user_specific():
    """Update categories table to be user-specific"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "No database connection"}), 500
        
        cur = conn.cursor()
        
        # Add user_id column to categories table
        try:
            cur.execute("ALTER TABLE categories ADD COLUMN user_id BIGINT;")
        except:
            print("⚠️ user_id column may already exist")
        
        # Set user_id for existing categories (assign to a default user or keep as shared)
        # For now, we'll set existing categories to NULL (shared/legacy)
        cur.execute("UPDATE categories SET user_id = NULL WHERE user_id IS NULL;")
        
        # Remove the unique constraint on name and add unique constraint on (user_id, name)
        try:
            cur.execute("ALTER TABLE categories DROP CONSTRAINT IF EXISTS categories_name_key;")
        except:
            pass
        
        # Add unique constraint for user_id and name combination
        try:
            cur.execute("""
                ALTER TABLE categories 
                ADD CONSTRAINT categories_user_name_unique UNIQUE (user_id, name);
            """)
        except:
            print("⚠️ Constraint may already exist")
        
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "message": "Categories table updated to be user-specific"})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/fix-categories-constraints')
def fix_categories_constraints():
    """Completely fix categories table constraints"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "No database connection"}), 500
        
        cur = conn.cursor()
        
        # Remove any unique constraint on emoji column
        try:
            cur.execute("ALTER TABLE categories DROP CONSTRAINT IF EXISTS categories_emoji_key;")
        except Exception as e:
            print(f"⚠️ Could not drop unique constraint: {e}")
        
        # Remove NOT NULL constraint from emoji column
        try:
            cur.execute("ALTER TABLE categories ALTER COLUMN emoji DROP NOT NULL;")
        except Exception as e:
            print(f"⚠️ Could not drop NOT NULL constraint: {e}")
        
        # Add a default value for existing categories that might be NULL
        cur.execute("UPDATE categories SET emoji = '❓' WHERE emoji IS NULL;")
        
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "message": "Categories table constraints fixed"})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/remove-emoji-requirement')
def remove_emoji_requirement():
    """Update categories table to handle categories without emojis"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "No database connection"}), 500
        
        cur = conn.cursor()
        
        # Remove any unique constraint on emoji column
        try:
            cur.execute("ALTER TABLE categories DROP CONSTRAINT IF EXISTS categories_emoji_key;")
        except:
            pass
        
        # Allow NULL values in emoji column
        try:
            cur.execute("ALTER TABLE categories ALTER COLUMN emoji DROP NOT NULL;")
        except:
            pass
        
        # Update existing spending categories to have NULL emoji
        cur.execute("""
            UPDATE categories 
            SET emoji = NULL 
            WHERE name NOT IN ('Salary', 'Business', 'Crypto', 'Bank', 'Personal', 'Investment', 'Other')
            AND emoji = '🏷️';
        """)
        
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "message": "Emoji requirement removed from categories table"})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/fix-categories-table')
def fix_categories_table():
    """Fix the categories table to allow same emoji for multiple categories"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "No database connection"}), 500
        
        cur = conn.cursor()
        
        # Remove the unique constraint on emoji column
        cur.execute("ALTER TABLE categories DROP CONSTRAINT IF EXISTS categories_emoji_key;")
        
        # Add a new unique constraint on (emoji, name) combination instead
        cur.execute("""
            ALTER TABLE categories 
            ADD CONSTRAINT categories_emoji_name_unique UNIQUE (emoji, name);
        """)
        
        conn.commit()
        conn.close()
        
        return jsonify({"success": True, "message": "Categories table fixed - same emoji now allowed for multiple categories"})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
        bot_instance.sync_transactions_to_postgres()
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
    update_data = request.get_json()
    print(f"🔍 DEBUG WEBHOOK: Processing update: {update_data}")
    if request.method == 'POST':    
        def process_and_save():
            bot_instance.process_update(update_data)
            # KEEP THIS - it saves NEW transactions to PostgreSQL
            bot_instance.sync_transactions_to_postgres()
            bot_instance.save_incomes()
            print("💾 Data saved after webhook processing")
        
        threading.Thread(target=process_and_save).start()
        
        return jsonify({"status": "success"}), 200
    
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

@app.route('/mini-app')
def serve_mini_app():
    return """
    <!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FinnBot - Financial Tracker</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }
        
        body {
            background-color: #f5f5f7;
            padding: 20px;
            color: #1d1d1f;
        }
        
        .container {
            max-width: 400px;
            margin: 0 auto;
        }
        
        /* Navigation Styles */
        .nav-bar {
            background: white;
            border-radius: 16px;
            padding: 8px;
            margin-bottom: 20px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
            display: flex;
            gap: 8px;
        }
        
        .nav-button {
            flex: 1;
            padding: 12px 16px;
            text-align: center;
            background: transparent;
            border: none;
            border-radius: 12px;
            font-size: 16px;
            font-weight: 500;
            color: #8e8e93;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        
        .nav-button.active {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
        }
        
        /* Page Styles */
        .page {
            display: none;
        }
        
        .page.active {
            display: block;
        }
        
        /* Balance Page Styles */
        .balance-card {
            background: white;
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 20px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
            text-align: center;
        }

        .health-indicator {
            text-align: center;
            margin: 10px 0;
            padding: 8px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 20px;
            color: white;
        }

        .health-display {
            font-size: 18px;
            font-weight: bold;
        }

        .balance-label {
            font-size: 16px;
            color: #8e8e93;
            margin-bottom: 8px;
        }
        
        .balance-amount {
            font-size: 36px;
            font-weight: 600;
            margin-bottom: 20px;
        }
        
        .income-expense {
            display: flex;
            justify-content: space-around;
        }
        
        .income, .expense {
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        
        .income-amount {
            color: #34c759;
            font-size: 18px;
            font-weight: 600;
        }
        
        .expense-amount {
            color: #ff3b30;
            font-size: 18px;
            font-weight: 600;
        }
        
        .income-label, .expense-label {
            font-size: 14px;
            color: #8e8e93;
            margin-top: 4px;
        }
        
        .transactions {
            background: white;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
        }
        
        .transaction {
            padding: 16px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #f2f2f7;
            min-height: 60px;
        }
        
        .transaction:last-child {
            border-bottom: none;
        }
        
        .transaction-info {
            flex: 1;
            display: flex;
            align-items: center;
            gap: 12px;
            min-width: 0;
        }
        
        .transaction-emoji {
            font-size: 20px;
            width: 30px;
            flex-shrink: 0;
            text-align: center;
        }
        
        .transaction-details {
            flex: 1;
            min-width: 0;
            overflow: hidden;
        }
        
        .transaction-title {
            font-size: 16px;
            font-weight: 500;
            margin-bottom: 2px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        
        .transaction-category {
            font-size: 12px;
            color: #8e8e93;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        
        .transaction-amount {
            font-size: 16px;
            font-weight: 500;
            text-align: right;
            flex-shrink: 0;
            margin-left: 10px;
        }
        
        .amount-negative {
            color: #ff3b30;
        }
        
        .amount-positive {
            color: #34c759;
        }
        
        /* Statistics Page Styles */
        .stats-card {
            background: white;
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 16px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
        }
        
        .stats-header {
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 16px;
            color: #1d1d1f;
            text-align: center;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-bottom: 20px;
        }
        
        .stat-item {
            background: #f8f9fa;
            border-radius: 12px;
            padding: 16px;
            text-align: center;
            border: 1px solid #e9ecef;
        }
        
        .stat-value {
            font-size: 20px;
            font-weight: 600;
            margin-bottom: 4px;
            color: #1d1d1f;
        }
        
        .stat-label {
            font-size: 12px;
            color: #6c757d;
        }
        
        .stat-positive {
            color: #34c759;
        }
        
        .stat-negative {
            color: #ff3b30;
        }
        
        .stat-neutral {
            color: #007AFF;
        }
        
        .category-breakdown {
            margin-top: 20px;
        }
        
        .category-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid #f2f2f7;
        }
        
        .category-item:last-child {
            border-bottom: none;
        }
        
        .category-info {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .category-emoji {
            font-size: 18px;
            width: 24px;
            text-align: center;
        }
        
        .category-name {
            font-size: 14px;
            font-weight: 500;
        }
        
        .category-amount {
            font-size: 14px;
            font-weight: 600;
        }
        
        .averages-section {
            margin: 15px 0;
            padding: 12px;
            background: #f8f9fa;
            border-radius: 12px;
            border: 1px solid #e9ecef;
        }

        .averages-row {
            display: flex;
            justify-content: space-between;
            gap: 10px;
        }

        .average-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            flex: 1;
        }

        .average-label {
            font-size: 12px;
            color: #6c757d;
            text-align: center;
            margin-bottom: 4px;
        }

        .average-amount {
            font-size: 14px;
            font-weight: 600;
            color: #495057;
        }
        
        .loading {
            text-align: center;
            padding: 20px;
            color: #8e8e93;
        }
        
        .error {
            text-align: center;
            padding: 20px;
            color: #ff3b30;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Navigation Bar -->
        <div class="nav-bar">
            <button class="nav-button active" data-page="balance">Balance</button>
            <button class="nav-button" data-page="statistics">Statistics</button>
        </div>
        
        <!-- Balance Page -->
        <div class="page active" id="balancePage">
            <div class="balance-card">
                <div class="balance-label">Current Balance</div>
                <div class="balance-amount" id="balanceAmount">0₴</div>
                
                <div class="income-expense">
                    <div class="expense">
                        <div class="expense-amount" id="expenseAmount">0₴</div>
                        <div class="expense-label">Spending</div>
                    </div>
                    <div class="income">
                        <div class="income-amount" id="incomeAmount">0₴</div>
                        <div class="income-label">Income</div>
                    </div>
                </div>
            </div>
            
            <div class="transactions" id="transactionsContainer">
                <div class="loading">Loading transactions...</div>
            </div>
        </div>
        
        <!-- Statistics Page -->
        <div class="page" id="statisticsPage">
            <div class="stats-card">
                <div class="stats-header">Financial Overview</div>
                <div class="stats-grid">
                    <div class="stat-item">
                        <div class="stat-value stat-positive" id="totalIncome">0₴</div>
                        <div class="stat-label">Total Income</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value stat-negative" id="totalExpenses">0₴</div>
                        <div class="stat-label">Total Expenses</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value stat-neutral" id="totalSavings">0₴</div>
                        <div class="stat-label">Total Savings</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value" id="transactionCount">0</div>
                        <div class="stat-label">Transactions</div>
                    </div>
                </div>
                
                <div class="averages-section">
                    <div class="averages-row">
                        <div class="average-item">
                            <div class="average-label">📈 Daily Income</div>
                            <div class="average-amount stat-positive" id="statsDailyIncome">0₴</div>
                        </div>
                        <div class="average-item">
                            <div class="average-label">📉 Daily Spending</div>
                            <div class="average-amount stat-negative" id="statsDailyExpense">0₴</div>
                        </div>
                    </div>
                    <div class="averages-row" style="margin-top: 8px;">
                        <div class="average-item">
                            <div class="average-label">💰 Daily Net</div>
                            <div class="average-amount" id="statsDailyNet">0₴</div>
                        </div>
                        <div class="average-item">
                            <div class="average-label">📅 Tracking Days</div>
                            <div class="average-amount" id="trackingDays">0</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="stats-card">
                <div class="stats-header">Financial Health</div>
                <div class="health-indicator" style="margin: 0;">
                    <div class="health-display" id="statsHealthDisplay">⛺️ 0%</div>
                </div>
            </div>
            
            <div class="stats-card" id="categoryBreakdown" style="display: none;">
                <div class="stats-header">Spending by Category</div>
                <div class="category-breakdown" id="categoryList">
                    <!-- Categories will be populated here -->
                </div>
            </div>
        </div>
    </div>

    <script>
        // Initialize Telegram WebApp
        Telegram.WebApp.ready();
        Telegram.WebApp.expand();

        let currentUserData = null;

        // Navigation functionality
        function setupNavigation() {
            const navButtons = document.querySelectorAll('.nav-button');
            const pages = document.querySelectorAll('.page');
            
            navButtons.forEach(button => {
                button.addEventListener('click', function() {
                    // Remove active class from all buttons and pages
                    navButtons.forEach(btn => btn.classList.remove('active'));
                    pages.forEach(page => page.classList.remove('active'));
                    
                    // Add active class to clicked button and corresponding page
                    this.classList.add('active');
                    const pageId = this.getAttribute('data-page') + 'Page';
                    document.getElementById(pageId).classList.add('active');
                    
                    // If switching to statistics page and we have data, update it
                    if (this.getAttribute('data-page') === 'statistics' && currentUserData) {
                        updateStatisticsPage(currentUserData);
                    }
                });
            });
        }

        // Load financial data and transactions
        async function loadFinancialData() {
            try {
                // Get user ID from Telegram
                const user = Telegram.WebApp.initDataUnsafe?.user;
                const user_id = user?.id;
                
                if (!user_id) {
                    showError('Cannot identify user. Please open via Telegram.');
                    return;
                }

                console.log('Loading data for user:', user_id);

                // Load balance and totals WITH user_id parameter
                const financeResponse = await fetch(`/api/financial-data?user_id=${user_id}`);
                const financeData = await financeResponse.json();
                
                if (financeResponse.ok) {
                    currentUserData = financeData;
                    updateBalancePage(financeData);
                    updateStatisticsPage(financeData);
                } else {
                    showError('Failed to load financial data: ' + (financeData.error || 'Unknown error'));
                }
                
                // Load transactions WITH user_id parameter
                const transactionsResponse = await fetch(`/api/transactions?user_id=${user_id}`);
                const transactionsData = await transactionsResponse.json();
                
                if (transactionsResponse.ok) {
                    renderTransactions(transactionsData.transactions || transactionsData);
                } else {
                    showError('Failed to load transactions: ' + (transactionsData.error || 'Unknown error'));
                }
                
            } catch (error) {
                console.error('Error loading data:', error);
                showError('Network error - please check your connection');
            }
        }
        
        function updateBalancePage(data) {
            // Update balance
            const balanceElement = document.getElementById('balanceAmount');
            if (data.balance !== undefined) {
                balanceElement.textContent = `${data.balance >= 0 ? '+' : ''}${data.balance.toLocaleString()}₴`;
                balanceElement.style.color = data.balance >= 0 ? '#34c759' : '#ff3b30';
            }
            
            // Update income and expenses
            if (data.income !== undefined) {
                document.getElementById('incomeAmount').textContent = `+${data.income.toLocaleString()}₴`;
            }
            if (data.spending !== undefined) {
                document.getElementById('expenseAmount').textContent = `-${data.spending.toLocaleString()}₴`;
            }
        
        function updateStatisticsPage(data) {
            // Update main statistics
            if (data.income !== undefined) {
                document.getElementById('totalIncome').textContent = `+${data.income.toLocaleString()}₴`;
            }
            if (data.spending !== undefined) {
                document.getElementById('totalExpenses').textContent = `-${data.spending.toLocaleString()}₴`;
            }
            if (data.savings !== undefined) {
                document.getElementById('totalSavings').textContent = `${data.savings.toLocaleString()}₴`;
            }
            if (data.transaction_count !== undefined) {
                document.getElementById('transactionCount').textContent = data.transaction_count;
            }
            
            // Update averages in statistics
            if (data.daily_income_avg !== undefined) {
                document.getElementById('statsDailyIncome').textContent = `+${Math.round(data.daily_income_avg).toLocaleString()}₴`;
            }
            if (data.daily_expense_avg !== undefined) {
                document.getElementById('statsDailyExpense').textContent = `-${Math.round(data.daily_expense_avg).toLocaleString()}₴`;
            }
            if (data.daily_net_avg !== undefined) {
                const netAvgElement = document.getElementById('statsDailyNet');
                netAvgElement.textContent = `${data.daily_net_avg >= 0 ? '+' : ''}${Math.round(data.daily_net_avg).toLocaleString()}₴`;
                netAvgElement.style.color = data.daily_net_avg >= 0 ? '#34c759' : '#ff3b30';
            }
            if (data.tracking_days !== undefined) {
                document.getElementById('trackingDays').textContent = data.tracking_days;
            }
            
            // Update financial health in statistics
            if (data.financial_health !== null && data.financial_health_emoji !== null) {
                document.getElementById('statsHealthDisplay').textContent = 
                    `${data.financial_health_emoji} ${data.financial_health}%`;
                
                const statsHealthIndicator = document.querySelector('#statisticsPage .health-indicator');
                updateHealthIndicatorColor(data.financial_health, statsHealthIndicator);
            }
        }
        
        function updateHealthIndicatorColor(score, element) {
            if (score >= 80) {
                element.style.background = 'linear-gradient(135deg, #4CAF50 0%, #45a049 100%)';
            } else if (score >= 60) {
                element.style.background = 'linear-gradient(135deg, #FF9800 0%, #F57C00 100%)';
            } else if (score >= 40) {
                element.style.background = 'linear-gradient(135deg, #FF5722 0%, #D84315 100%)';
            } else {
                element.style.background = 'linear-gradient(135deg, #F44336 0%, #C62828 100%)';
            }
        }
        
        function renderTransactions(transactions) {
            const container = document.getElementById('transactionsContainer');
            
            if (!transactions || transactions.length === 0) {
                container.innerHTML = `
                    <div class="transaction">
                        <div class="transaction-info">
                            <div class="transaction-emoji">📭</div>
                            <div class="transaction-details">
                                <div class="transaction-title">No transactions yet</div>
                                <div class="transaction-category">Start adding transactions in the bot</div>
                            </div>
                        </div>
                    </div>
                `;
                return;
            }
            
            let transactionsHTML = '';
            
            transactions.forEach(transaction => {
                const amount = transaction.amount;
                const isPositive = amount >= 0;
                const amountDisplay = `${isPositive ? '+' : ''}${Math.abs(amount).toLocaleString()}₴`;
                
                const displayName = transaction.name || transaction.category || 'Transaction';
                const displayDescription = transaction.description || '';
                
                transactionsHTML += `
                    <div class="transaction">
                        <div class="transaction-info">
                            <div class="transaction-emoji">${transaction.emoji || '💰'}</div>
                            <div class="transaction-details">
                                <div class="transaction-title">${displayName}</div>
                                ${displayDescription ? `<div class="transaction-category">${displayDescription}</div>` : ''}
                            </div>
                        </div>
                        <div class="transaction-amount ${isPositive ? 'amount-positive' : 'amount-negative'}">
                            ${amountDisplay}
                        </div>
                    </div>
                `;
            });
            
            container.innerHTML = transactionsHTML;
        }
        
        function showError(message) {
            const container = document.getElementById('transactionsContainer');
            container.innerHTML = `<div class="error">${message}</div>`;
        }
        
        // Initialize the app
        document.addEventListener('DOMContentLoaded', function() {
            console.log('Mini-app initialized');
            setupNavigation();
            loadFinancialData();
        });
        
        // Refresh data every 30 seconds
        setInterval(loadFinancialData, 30000);
        
        // Also refresh when the app becomes visible
        document.addEventListener('visibilitychange', function() {
            if (!document.hidden) {
                loadFinancialData();
            }
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