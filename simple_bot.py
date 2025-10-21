import os
import json
import re
import requests
import time
from dotenv import load_dotenv
from datetime import datetime
from flask import Flask, jsonify, request
import threading
import atexit
import signal
import psycopg2
from urllib.parse import urlparse


PERSISTENT_DIR = "/data" if os.path.exists("/data") else "."

def get_persistent_path(filename):
    return os.path.join(PERSISTENT_DIR, filename)

print(f"📁 Using persistent directory: {PERSISTENT_DIR}")

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Initialize Flask app FIRST
flask_app = Flask(__name__)

@flask_app.before_request
def log_request_info():
    print(f"🌐 Incoming: {request.method} {request.path} - From: {request.remote_addr}")

def sync_to_railway(transaction_data):
    """Send transaction data to Railway web app"""
    try:
        railway_url = "https://finnbot-production.up.railway.app"
        response = requests.post(f"{railway_url}/api/add-transaction", 
                            json=transaction_data,
                            timeout=5)
        if response.status_code == 200:
            print("✅ Synced to Railway")
        else:
            print(f"⚠️ Failed to sync to Railway: {response.status_code}")
    except Exception as e:
        print(f"⚠️ Railway sync failed: {e}")

def get_db_connection(self):
    """Get PostgreSQL connection"""
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
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

def try_load_from_db(self):
    """Load data from PostgreSQL"""
    try:
        conn = self.get_db_connection()
        if not conn:
            return False
            
        cur = conn.cursor()
        
        # Load transactions
        cur.execute('SELECT user_id, amount, description, category, type FROM transactions')
        transactions_data = cur.fetchall()
        
        self.transactions = {}
        for user_id, amount, description, category, trans_type in transactions_data:
            if user_id not in self.transactions:
                self.transactions[user_id] = []
            
            self.transactions[user_id].append({
                'amount': float(amount),
                'description': description,
                'category': category,
                'type': trans_type,
                'date': datetime.now().isoformat()
            })
        
        # Load incomes
        cur.execute('SELECT user_id, amount FROM incomes')
        incomes_data = cur.fetchall()
        
        self.user_incomes = {}
        for user_id, amount in incomes_data:
            self.user_incomes[user_id] = float(amount)
        
        conn.close()
        print(f"📊 Loaded {len(transactions_data)} transactions and {len(incomes_data)} incomes from database")
        return True
        
    except Exception as e:
        print(f"❌ Error loading from database: {e}")
        return False

def try_save_to_db(self):
    """Save data to PostgreSQL"""
    try:
        conn = self.get_db_connection()
        if not conn:
            return False
            
        cur = conn.cursor()
        
        # Clear existing data (simple approach)
        cur.execute('DELETE FROM transactions')
        cur.execute('DELETE FROM incomes')
        
        # Save transactions
        for user_id, transactions in self.transactions.items():
            for txn in transactions:
                cur.execute(
                    'INSERT INTO transactions (user_id, amount, description, category, type) VALUES (%s, %s, %s, %s, %s)',
                    (user_id, txn.get('amount', 0), txn.get('description', ''), txn.get('category', 'Other'), txn.get('type', 'expense'))
                )
        
        # Save incomes
        for user_id, amount in self.user_incomes.items():
            cur.execute(
                'INSERT INTO incomes (user_id, amount) VALUES (%s, %s)',
                (user_id, amount)
            )
        
        conn.commit()
        conn.close()
        print("💾 Data saved to PostgreSQL database")
        return True
        
    except Exception as e:
        print(f"❌ Error saving to database: {e}")
        return False

class SimpleFinnBot:
    def save_user_languages(self):
        """Save user languages - placeholder for now"""
        print("💾 User languages would be saved here")
        # We'll implement this later if needed

    def save_user_categories(self):
        """Save user categories - placeholder for now""" 
        print("💾 User categories would be saved here")
        # We'll implement this later if needed
    def get_db_connection(self):
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

    def load_all_data(self):
        """Load all data from PostgreSQL"""
        print("🔄 Loading data from PostgreSQL...")
        
        conn = self.get_db_connection()
        if not conn:
            print("❌ No database connection - starting with empty data")
            # Initialize empty if no connection
            if not hasattr(self, 'transactions'):
                self.transactions = {}
            if not hasattr(self, 'user_incomes'): 
                self.user_incomes = {}
            if not hasattr(self, 'user_categories'):
                self.user_categories = {}
            if not hasattr(self, 'user_languages'):
                self.user_languages = {}
            return
        
        try:
            cur = conn.cursor()
            
            # DEBUG: Check database count first
            cur.execute('SELECT COUNT(*) FROM transactions')
            db_count = cur.fetchone()[0]
            print(f"🔍 DEBUG: Database has {db_count} transactions")
            
            # Load transactions WITH THEIR ORIGINAL TIMESTAMPS
            cur.execute('SELECT user_id, amount, description, category, type, created_at FROM transactions ORDER BY created_at')
            transactions_data = cur.fetchall()
            
            # Create temporary transactions dictionary
            new_transactions = {}
            for user_id, amount, description, category, trans_type, created_at in transactions_data:
                user_id = int(user_id)
                if user_id not in new_transactions:
                    new_transactions[user_id] = []
                
                new_transactions[user_id].append({
                    'amount': float(amount),
                    'description': description,
                    'category': category,
                    'type': trans_type,
                    'date': created_at.isoformat() if created_at else datetime.now().isoformat()  # Use original timestamp
                })
                print(f"🔍 DEBUG: Loaded transaction with original timestamp: {created_at}")
            
            # Load incomes
            cur.execute('SELECT user_id, amount FROM incomes')
            incomes_data = cur.fetchall()
            
            new_user_incomes = {}
            for user_id, amount in incomes_data:
                new_user_incomes[int(user_id)] = float(amount)
            
            conn.close()
            
            # ONLY update the instance variables after successful load
            self.transactions = new_transactions
            self.user_incomes = new_user_incomes
            
            print(f"📊 Loaded {len(transactions_data)} transactions and {len(incomes_data)} incomes from PostgreSQL")
            
        except Exception as e:
            print(f"❌ Error loading from database: {e}")
            # Initialize empty on error
            if not hasattr(self, 'transactions'):
                self.transactions = {}
            if not hasattr(self, 'user_incomes'):
                self.user_incomes = {}
            if not hasattr(self, 'user_categories'):
                self.user_categories = {}
            if not hasattr(self, 'user_languages'):
                self.user_languages = {}

    def sync_transactions_to_postgres(self):
        """Additive sync - only add new transactions, don't delete existing ones"""
        conn = self.get_db_connection()
        if not conn:
            print("❌ No database connection for sync")
            return
        
        try:
            cur = conn.cursor()
            
            # Count what's in memory to sync
            transaction_count = 0
            for user_id, transactions in self.transactions.items():
                transaction_count += len(transactions)
            
            print(f"🔍 DEBUG: Syncing {transaction_count} transactions from memory to PostgreSQL")
            
            # ONLY insert new transactions - DON'T delete existing ones
            saved_count = 0
            for user_id, transactions in self.transactions.items():
                for txn in transactions:
                    # Check if this transaction already exists to avoid duplicates
                    cur.execute(
                        'SELECT id FROM transactions WHERE user_id = %s AND amount = %s AND description = %s AND category = %s AND type = %s',
                        (user_id, txn.get('amount', 0), txn.get('description', ''), txn.get('category', 'Other'), txn.get('type', 'expense'))
                    )
                    existing = cur.fetchone()
                    
                    if not existing:  # Only insert if it doesn't exist
                        cur.execute(
                            'INSERT INTO transactions (user_id, amount, description, category, type) VALUES (%s, %s, %s, %s, %s)',
                            (user_id, txn.get('amount', 0), txn.get('description', ''), txn.get('category', 'Other'), txn.get('type', 'expense'))
                        )
                        saved_count += 1
            
            conn.commit()
            conn.close()
            print(f"🔄 Additive sync: Added {saved_count} new transactions to PostgreSQL")
            
        except Exception as e:
            print(f"❌ Error syncing to PostgreSQL: {e}")
            import traceback
            traceback.print_exc()

    def save_incomes(self):
        """Save incomes to PostgreSQL"""
        conn = self.get_db_connection()
        if not conn:
            print("❌ Cannot save - no database connection")
            return
        
        try:
            cur = conn.cursor()
            
            # Save incomes
            for user_id, amount in self.user_incomes.items():
                cur.execute(
                    'INSERT INTO incomes (user_id, amount) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET amount = EXCLUDED.amount',
                    (user_id, amount)
                )
            
            conn.commit()
            conn.close()
            print(f"💾 Saved {len(self.user_incomes)} incomes to PostgreSQL")
            
        except Exception as e:
            print(f"❌ Error saving incomes to database: {e}")

    def __init__(self, load_data=True):
        print(f"🔍 DEBUG: SimpleFinnBot.__init__ called with load_data={load_data}")
        import traceback
        print("🔍 Call stack for bot initialization:")
        for line in traceback.format_stack()[:-1]:
            if "finnbot" in line.lower() or "simple" in line.lower():
                print(line.strip())
        # Income categories (shared for all users)
        self._transactions = {}
        self.income_categories = {
            "Salary": ["salary", "paycheck", "wages", "income", "pay"],
            "Business": ["business", "freelance", "contract", "gig", "side", "hustle", "project", "consulting"]
        }
        self.savings_category_translations = {
            'en': {
                'Crypto': 'Crypto',
                'Bank': 'Bank', 
                'Personal': 'Personal',
                'Investment': 'Investment'
            },
            'uk': {
                'Crypto': 'Кріпто',
                'Bank': 'Банк',
                'Personal': 'Особисте',
                'Investment': 'Інвестиції'
            }
        }
        
        # User-specific data
        self.learned_patterns = {}
        self.onboarding_state = {}
        self.pending = {}
        self.delete_mode = {}
        self.user_incomes = {}
        self.pending_income = set()
        self.user_categories = {}
        self.user_languages = {}
        self.daily_reminders = {}
        self.protected_savings_categories = ["Crypto", "Bank", "Personal", "Investment"]
        
        # Only load data if explicitly requested
        if load_data:
            self.load_all_data()
        else:
            # Initialize empty data structures
            self.transactions = {}
            self.user_incomes = {}
            self.user_categories = {}
            self.user_languages = {}
        
        # 50/30/20 tracking
        self.monthly_totals = {}
        self.monthly_percentages = {}
        self.current_month = datetime.now().strftime("%Y-%m")
        self.category_mapping = {
            'needs': [
                'Rent', 'Mortgage', 'Groceries', 'Utilities', 'Electricity', 
                'Water', 'Gas', 'Internet', 'Phone', 'Transport', 'Fuel', 
                'Public Transport', 'Car Maintenance', 'Healthcare', 'Insurance',
                'Medicine', 'Doctor'
            ],
            'wants': [
                'Shopping', 'Restaurants', 'Cafe', 'Dining', 'Entertainment',
                'Movies', 'Concerts', 'Hobbies', 'Travel', 'Vacation', 'Luxury',
                'Electronics', 'Clothing', 'Beauty', 'Gifts'
            ],
            'future': [
                'Savings', 'Crypto', 'Bank', 'Personal', 'Investment', 'Stock', 
                'Debt Return', 'Education', 'Retirement', 'Emergency Fund'
            ]
        }
        

    def save_user_transaction(self, chat_id, transaction):
        """Save a single transaction for a user"""
        try:
            print(f"🔍 DEBUG save_user_transaction: chat_id={chat_id}, transaction={transaction}")
            
            # Safe stack trace (optional)
            import traceback
            stack_summary = traceback.extract_stack()
            print("🔍 DEBUG: Call stack (simplified):")
            for frame in stack_summary[-5:]:  # Show last 5 frames only
                print(f"   {frame.filename}:{frame.lineno} in {frame.name}")
            
            # Initialize if needed
            if chat_id not in self.transactions:
                print(f"🔍 DEBUG: Creating new transactions list for user {chat_id}")
                self.transactions[chat_id] = []
            
            # Add transaction
            self.transactions[chat_id].append(transaction)
            print(f"🔍 DEBUG: Added transaction to memory. User now has {len(self.transactions[chat_id])} transactions")
            
            # Sync to database
            self.sync_transactions_to_postgres()
            
        except Exception as e:
            print(f"❌ Error in save_user_transaction: {e}")

    def send_photo_from_url(self, chat_id, photo_url, caption=None, keyboard=None):
        """Send photo from a public URL"""
        data = {
            "chat_id": chat_id,
            "photo": photo_url
        }
        
        if caption:
            data["caption"] = caption
            data["parse_mode"] = "Markdown"
        
        if keyboard:
            data["reply_markup"] = json.dumps(keyboard)
        
        response = requests.post(f"{BASE_URL}/sendPhoto", json=data)
        return response

    def categorize_transaction(self, category_name, description=""):
        """Categorize transaction into needs/wants/future"""
        category_lower = category_name.lower()
        description_lower = description.lower()
        
        # Check category name first
        for bucket, categories in self.category_mapping.items():
            for cat in categories:
                if cat.lower() in category_lower:
                    return bucket
        
        # Check description if category is generic
        for bucket, categories in self.category_mapping.items():
            for cat in categories:
                if cat.lower() in description_lower:
                    return bucket
        
        # Default to 'wants' for unknown categories
        return 'wants'

    def load_incomes(self):
        """Load user incomes from persistent JSON file"""
        try:
            filepath = get_persistent_path("incomes.json")
            if os.path.exists(filepath):
                with open(filepath, "r") as f:
                    self.user_incomes = json.load(f)
                print(f"💰 Loaded incomes for {len(self.user_incomes)} users from {filepath}")
            else:
                print("💰 No existing incomes file")
                self.user_incomes = {}
        except Exception as e:
            print(f"❌ Error loading incomes: {e}")
            self.user_incomes = {}

    def load_user_categories(self):
        """Load user categories from persistent JSON file"""
        try:
            filepath = get_persistent_path("user_categories.json")
            if os.path.exists(filepath):
                with open(filepath, "r") as f:
                    self.user_categories = json.load(f)
                print(f"🏷️ Loaded spending categories for {len(self.user_categories)} users from {filepath}")
            else:
                print("🏷️ No existing user categories file - starting fresh")
                self.user_categories = {}
        except Exception as e:
            print(f"❌ Error loading user categories: {e}")
            self.user_categories = {}

    def load_user_languages(self):
        """Load user language preferences from persistent JSON file"""
        try:
            filepath = get_persistent_path("user_languages.json")
            if os.path.exists(filepath):
                with open(filepath, "r") as f:
                    self.user_languages = json.load(f)
                print(f"🌍 Loaded language preferences for {len(self.user_languages)} users from {filepath}")
            else:
                print("🌍 No existing user languages file")
                self.user_languages = {}
        except Exception as e:
            print(f"❌ Error loading user languages: {e}")
            self.user_languages = {}
    
    def check_daily_reminders(self):
        """Check and send daily reminders to active users"""
        from datetime import datetime
        
        now = datetime.now()
        current_hour = now.hour
        today = now.date()
        
        for user_id in self.get_active_users():
            user_id_str = str(user_id)
            user_reminders = self.daily_reminders.get(user_id_str, {})
            
            # Lunch reminder (12:00)
            if current_hour == 12 and user_reminders.get('lunch') != today:
                self.send_reminder(user_id, 'lunch')
                self.daily_reminders.setdefault(user_id_str, {})['lunch'] = today
            
            # Evening reminder (18:00)
            elif current_hour == 18 and user_reminders.get('evening') != today:
                self.send_reminder(user_id, 'evening')
                self.daily_reminders.setdefault(user_id_str, {})['evening'] = today

    def send_reminder(self, user_id, reminder_type):
        """Send specific reminder type"""
        user_lang = self.get_user_language(user_id)
        
        if user_lang == 'uk':
            messages = {
                'lunch': "🌞 *Обідній час*\nІдеальний час, щоб занотувати ваші ранкові транзакції!",
                'evening': "🌆 *Вечірнє оновлення*\nЧас підбити підсумки дня!"
            }
        else:
            messages = {
                'lunch': "🌞 *Lunchtime Check-in*\nPerfect time to log your morning transactions!",
                'evening': "🌆 *Evening Update*\nTime to wrap up your day!"
            }
        
        self.send_message(user_id, messages[reminder_type], parse_mode='Markdown')

    def get_active_users(self):
        """Get list of users who have started the bot"""
        return [int(user_id) for user_id in self.user_languages.keys() if user_id.isdigit()]

    def update_503020_totals(self, user_id, amount, bucket):
        """Update monthly totals for 50/30/20 tracking"""
        user_id_str = str(user_id)
        current_month = datetime.now().strftime("%Y-%m")
        
        # Initialize if new user or new month
        if user_id_str not in self.monthly_totals:
            self.monthly_totals[user_id_str] = {'needs': 0, 'wants': 0, 'future': 0, 'income': 0}
        
        # Reset if new month
        if hasattr(self, 'current_month') and current_month != self.current_month:
            self.monthly_totals[user_id_str] = {'needs': 0, 'wants': 0, 'future': 0, 'income': 0}
            self.current_month = current_month
        
        # Update the bucket total
        if bucket in self.monthly_totals[user_id_str]:
            self.monthly_totals[user_id_str][bucket] += amount
        
        # Update percentages
        self.calculate_503020_percentages(user_id_str)

    def update_income_for_503020(self, user_id, amount):
        """Update income for percentage calculations"""
        user_id_str = str(user_id)
        
        if user_id_str not in self.monthly_totals:
            self.monthly_totals[user_id_str] = {'needs': 0, 'wants': 0, 'future': 0, 'income': 0}
        
        self.monthly_totals[user_id_str]['income'] += amount
        self.calculate_503020_percentages(user_id_str)

    def calculate_503020_percentages(self, user_id_str):
        """Calculate current percentages for 50/30/20"""
        if user_id_str not in self.monthly_totals:
            return
        
        totals = self.monthly_totals[user_id_str]
        income = totals['income']
        
        if income > 0:
            self.monthly_percentages[user_id_str] = {
                'needs': (totals['needs'] / income) * 100,
                'wants': (totals['wants'] / income) * 100,
                'future': (totals['future'] / income) * 100
            }
        else:
            self.monthly_percentages[user_id_str] = {'needs': 0, 'wants': 0, 'future': 0}

    def check_503020_limits(self, user_id):
        """Check if user crossed any 50/30/20 limits and return messages"""
        user_id_str = str(user_id)
        
        if user_id_str not in self.monthly_percentages:
            return []
        
        current = self.monthly_percentages[user_id_str]
        
        # Store previous percentages (you might want to persist this)
        previous = getattr(self, 'previous_percentages', {}).get(user_id_str, {'needs': 0, 'wants': 0, 'future': 0})
        
        messages = []
        user_lang = self.get_user_language(user_id)
        
        # Needs checks (45% and 50%)
        if 45 <= current['needs'] < 50 and previous['needs'] < 45:
            if user_lang == 'uk':
                messages.append("🏠 *Потреби наближаються до ліміту*\n\nВи витратили 45% вашого доходу на потреби цього місяця.\n\nВи близько до рекомендованого ліміту 50%. Розгляньте перегляд ваших основних витрат.")
            else:
                messages.append("🏠 *Needs Approaching Limit*\n\nYou've spent 45% of your income on needs this month.\n\nYou're close to the 50% recommended limit. Consider reviewing your essential expenses.")
        
        elif current['needs'] >= 50 and previous['needs'] < 50:
            if user_lang == 'uk':
                messages.append(f"🚨 *Потреби перевищили бюджет*\n\nВи витратили {current['needs']:.1f}% на потреби - понад цільовий показник 50%.\n\nЦе може вплинути на ваші заощадження та витрати на спосіб життя. Давайте оптимізуємо!")
            else:
                messages.append(f"🚨 *Needs Over Budget*\n\nYou've spent {current['needs']:.1f}% on needs - over the 50% target.\n\nThis may impact your savings and lifestyle expenses. Let's optimize!")
        
        # Wants checks (27% and 30%)
        if 27 <= current['wants'] < 30 and previous['wants'] < 27:
            if user_lang == 'uk':
                messages.append("🎉 *Бажання наближаються до ліміту*\n\nВи витратили 27% на бажання способу життя цього місяця.\n\nНаближається до ліміту 30%. Розгляньте темпу ваших дискреційних витрат.")
            else:
                messages.append("🎉 *Wants Approaching Limit*\n\nYou've spent 27% on lifestyle wants this month.\n\nApproaching the 30% limit. Consider pacing your discretionary spending.")
        
        elif current['wants'] >= 30 and previous['wants'] < 30:
            if user_lang == 'uk':
                messages.append(f"⚠️ *Бажання перевищили бюджет*\n\nВи витратили {current['wants']:.1f}% на бажання - понад цільовий показник 30%.\n\nЦе впливає на ваші майбутні заощадження. Час пріоритезувати!")
            else:
                messages.append(f"⚠️ *Wants Over Budget*\n\nYou've spent {current['wants']:.1f}% on wants - over the 30% target.\n\nThis affects your future savings. Time to prioritize!")
        
        # Future praise (20% and 25%)
        if current['future'] >= 20 and previous['future'] < 20:
            if user_lang == 'uk':
                messages.append("🏆 *Майбутня увага досягнута!*\n\nВи виділили 20%+ на ваше майбутнє цього місяця!\n\nІдеальний баланс - ви будуєте фінансову безпеку, насолоджуючись життям сьогодні. 🎯")
            else:
                messages.append("🏆 *Future Focus Achieved!*\n\nYou've allocated 20%+ to your future this month!\n\nPerfect balance - you're building financial security while enjoying life today. 🎯")
        
        elif current['future'] >= 25 and previous['future'] < 25:
            if user_lang == 'uk':
                messages.append(f"🌟 *Фінансова зірка!*\n\n{current['future']:.1f}% на ваше майбутнє? Вражаюче!\n\nВи не просто зберігаєте - ви будуєте багатство та безпеку. Це фінансове здоров'я наступного рівня! 💪")
            else:
                messages.append(f"🌟 *Financial Rockstar!*\n\n{current['future']:.1f}% to your future? Outstanding!\n\nYou're not just saving - you're building wealth and security. This is next-level financial health! 💪")
        
        # Update previous percentages
        if not hasattr(self, 'previous_percentages'):
            self.previous_percentages = {}
        self.previous_percentages[user_id_str] = current.copy()
        
        return messages

    def calculate_expression(self, text):
        """Calculate mathematical expressions with percentages"""
        try:
            # Remove spaces and convert to lowercase
            expression = text.replace(' ', '').lower()
            
            # Handle percentages: convert 1.5% to *0.015
            expression = re.sub(r'(\d+(?:\.\d+)?)%', r'*(\1/100)', expression)
            
            # Replace multiple operators with proper format
            expression = expression.replace('++', '+').replace('--', '+').replace('+-', '-').replace('-+', '-')
            
            # Basic safety check - only allow numbers, basic operators, and parentheses
            if not re.match(r'^[\d+\-*/().\s]+$', expression):
                return None, "❌ Invalid characters in expression"
            
            # Calculate the result
            result = eval(expression)
            
            # Determine transaction type based on result and original text
            if '++' in text:
                trans_type = 'savings'
                symbol = '++'
            elif '+-' in text:
                trans_type = 'debt_return' 
                symbol = '+-'
            elif '-+' in text:
                trans_type = 'savings_withdraw'
                symbol = '-+'
            elif text.strip().startswith('-') and not '-+' in text:
                trans_type = 'debt'
                symbol = '-'  # But this should INCREASE balance!
            elif '+' in text and not any(x in text for x in ['++', '+-', '-+']):
                trans_type = 'income'
                symbol = '+'
            else:
                trans_type = 'expense'
                symbol = '-'
            
            # For debt transactions, we need the POSITIVE amount since it increases balance
            amount = abs(result)
            
            return amount, trans_type, symbol
            
        except Exception as e:
            print(f"❌ Calculation error: {e}")
            return None, f"❌ Calculation error: {str(e)}"
        
    def get_user_transactions(self, user_id):
        """Get transactions for a specific user"""
        if user_id not in self.transactions:
            self.transactions[user_id] = []
        return self.transactions[user_id]
    
    def load_user_languages(self):
        """Load user language preferences"""
        try:
            if os.path.exists("user_languages.json"):
                with open("user_languages.json", "r") as f:
                    self.user_languages = json.load(f)
                print(f"🌍 Loaded language preferences for {len(self.user_languages)} users")
        except Exception as e:
            print(f"❌ Error loading user languages: {e}")

    def get_user_language(self, user_id):
        """Get user's preferred language, default to English"""
        return self.user_languages.get(str(user_id), 'en')

    def set_user_language(self, user_id, language_code):
        """Set user's preferred language"""
        self.user_languages[str(user_id)] = language_code
        self.save_user_languages()
        
        def get_user_transactions(self, user_id):
            """Get transactions for a specific user"""
            if user_id not in self.transactions:
                self.transactions[user_id] = []
            return self.transactions[user_id]

    def load_incomes(self):
        """Load user incomes from JSON file"""
        try:
            if os.path.exists("incomes.json"):
                with open("incomes.json", "r") as f:
                    self.user_incomes = json.load(f)
                print(f"💰 Loaded incomes for {len(self.user_incomes)} users")
            else:
                print("💰 No existing incomes file")
        except Exception as e:
            print(f"❌ Error loading incomes: {e}")

    def get_user_income(self, user_id):
        """Get monthly income for a specific user"""
        return self.user_incomes.get(str(user_id))
    
    def load_transactions(self):
        """Load transactions from PostgreSQL"""
        conn = self.get_db_connection()
        if not conn:
            print("❌ No database connection, skipping transaction load")
            self.transactions = {}
            return
        
        try:
            cur = conn.cursor()
            
            # DEBUG: Check database count first
            cur.execute('SELECT COUNT(*) FROM transactions')
            db_count = cur.fetchone()[0]
            print(f"🔍 DEBUG: Database has {db_count} transactions")
            
            # Load transactions FROM POSTGRESQL
            cur.execute('SELECT user_id, amount, description, category, type FROM transactions ORDER BY created_at')
            transactions_data = cur.fetchall()
            
            self.transactions = {}
            for user_id, amount, description, category, trans_type in transactions_data:
                user_id = int(user_id)
                if user_id not in self.transactions:
                    self.transactions[user_id] = []
                
                self.transactions[user_id].append({
                    'amount': float(amount),
                    'description': description,
                    'category': category,
                    'type': trans_type
                })
            
            conn.close()
            print(f"📊 Loaded {len(transactions_data)} transactions from PostgreSQL")
            
        except Exception as e:
            print(f"❌ Error loading from PostgreSQL: {e}")
            self.transactions = {}

    def load_user_categories(self):
        """Load user categories from JSON file"""
        try:
            if os.path.exists("user_categories.json"):
                with open("user_categories.json", "r") as f:
                    self.user_categories = json.load(f)
                print(f"🏷️ Loaded spending categories for {len(self.user_categories)} users")
            else:
                print("🏷️ No existing user categories file - starting fresh")
        except Exception as e:
            print(f"❌ Error loading user categories: {e}")

    def get_user_categories(self, user_id):
        """Get spending categories for a specific user"""
        user_id_str = str(user_id)
        if user_id_str not in self.user_categories:
            # Initialize with default categories for new user
            self.user_categories[user_id_str] = {
                "Other": []
            }
            self.save_user_categories()
        return self.user_categories[user_id_str]

    def add_user_category(self, user_id, category_name):
        """Add a new spending category for a user"""
        user_categories = self.get_user_categories(user_id)
        if category_name not in user_categories:
            user_categories[category_name] = []
            self.save_user_categories()
            return True
        return False

    def remove_user_category(self, user_id, category_name):
        """Remove a spending category from a user"""
        user_categories = self.get_user_categories(user_id)
        
        # Protect savings categories from deletion
        if category_name in self.protected_savings_categories:
            return False
            
        if category_name in user_categories and category_name not in ["Food", "Other"]:
            del user_categories[category_name]
            self.save_user_categories()
            return True
        return False

    def get_main_menu(self, user_id=None):
        user_lang = self.get_user_language(user_id) if user_id else 'en'
        
        if user_lang == 'uk':
            keyboard = [
                ["📊 Фінансовий звіт", "📊 50/30/20 Status"],
                ["🗑️ Видалити транзакцію", "🏷️ Керування категоріями"],
                ["🔄 Перезапустити бота", "🌍 Мова"]
            ]
        else:
            keyboard = [
                ["📊 Financial Summary", "📊 50/30/20 Status"],
                ["🗑️ Delete Transaction", "🏷️ Manage Categories"], 
                ["🔄 Restart Bot", "🌍 Language"]
            ]
        
        return {
            "keyboard": keyboard,
            "resize_keyboard": True,
            "one_time_keyboard": False,
            "selective": False
        }
    
    def extract_amount(self, text):
    # Clean the text first
        clean_text = text.strip()
        print(f"🔍 DEBUG extract_amount: text='{clean_text}'")
        
        # Check transaction types in priority order
        is_savings = '++' in clean_text
        is_debt_return = '+-' in clean_text
        is_savings_withdraw = '-+' in clean_text
        is_income = '+' in clean_text and not any(x in clean_text for x in ['++', '+-', '-+'])
        is_debt = clean_text.startswith('-') and not is_savings_withdraw
        
        print(f"   Transaction type detection:")
        print(f"   - is_savings: {is_savings}")
        print(f"   - is_income: {is_income}")
        print(f"   - is_debt: {is_debt}")
        print(f"   - is_debt_return: {is_debt_return}")
        print(f"   - is_savings_withdraw: {is_savings_withdraw}")
        
        # Extract amount using regex that handles various formats
        amount_pattern = r'[+-]*\s*(\d+(?:[.,]\d{1,2})?)'
        amounts = re.findall(amount_pattern, clean_text)
        
        if amounts:
            # Get the first valid amount found
            for amt_str in amounts:
                try:
                    # Clean the amount string
                    clean_amt = amt_str.replace(',', '.').strip()
                    amount = float(clean_amt)
                    print(f"   ✅ Extracted amount: {amount}")
                    return amount, is_income, is_debt, is_savings, is_debt_return, is_savings_withdraw
                except ValueError:
                    continue
        
        print(f"   ❌ No valid amount found")
        return None, is_income, is_debt, is_savings, is_debt_return, is_savings_withdraw

    def guess_category(self, text, user_id):
        """Guess spending category for a specific user"""
        text_lower = text.lower()
        
        # Check learned patterns first
        for pattern, category in self.learned_patterns.items():
            if pattern in text_lower:
                return category
        
        # Use user-specific spending categories
        user_categories = self.get_user_categories(user_id)
        
        # Guess expense category
        for category, keywords in user_categories.items():
            if category == "Other":
                continue
            for keyword in keywords:
                if keyword in text_lower:
                    return category
        return "Other"
    
    def calculate_savings_recommendation(self, user_id, income_amount, description=""):
        """Calculate recommended savings based on income in UAH"""
        
        # Get financial context for specific user
        user_transactions = self.get_user_transactions(user_id)
        current_savings = sum(t['amount'] for t in user_transactions if t['type'] == 'savings')
        
        # Get user language
        user_lang = self.get_user_language(user_id)
        
        # UAH-specific savings rules
        if income_amount > 100000:
            # Large income (>100,000 UAH) - recommend 10% savings
            min_save = income_amount * 0.10
            max_save = income_amount * 0.15
            if user_lang == 'uk':
                urgency = "🏦 Консервативні заощадження"
                reason = "Великий дохід виявлено! 10% заощаджень створять значне багатство з часом."
            else:
                urgency = "🏦 Conservative Savings"
                reason = "Large income detected! 10% savings will build significant wealth over time."
            
        else:
            # Smaller income (≤100,000 UAH) - recommend 15-20% savings
            min_save = income_amount * 0.15
            max_save = income_amount * 0.20
            if user_lang == 'uk':
                urgency = "💪 Збалансований підхід"
                reason = "Ідеальний діапазон доходу для накопичення заощаджень! 15-20% - це ідеальний баланс."
            else:
                urgency = "💪 Balanced Approach"
                reason = "Perfect income range for building savings! 15-20% is the sweet spot."
        
        # Adjust based on current savings in UAH context
        if user_lang == 'uk':
            if current_savings < 50000:
                reason += " Ви будуєте свій початковий резервний фонд - кожна гривня має значення! 💰"
            elif current_savings < 200000:
                reason += " Хороший прогрес! Ви будуєте солідну фінансову подушку. 🎯"
            else:
                reason += " Відмінна дисципліна заощаджень! Ви будуєте реальну фінансову безпеку. 🚀"
        else:
            if current_savings < 50000:
                reason += " You're building your initial emergency fund - every UAH counts! 💰"
            elif current_savings < 200000:
                reason += " Good progress! You're building a solid financial cushion. 🎯"
            else:
                reason += " Excellent savings discipline! You're building real financial security. 🚀"
        
        # Format amounts in UAH
        if user_lang == 'uk':
            message = f"""
    {urgency}

    *Новий дохід* і час для заощаджень 🏦

    Рекомендую заощадити: {min_save:,.0f}₴ - {max_save:,.0f}₴

    💸 *Швидкі команди для збереження:*
    `++{min_save:.0f}` - Зберегти {min_save:,.0f}₴ | `++{max_save:.0f}` - Зберегти {max_save:,.0f}₴

    _Багатство зростає з кожною транзакцією_
    """
        else:
            message = f"""
    {urgency}

    *New income* and it's time for savings 🏦

    I recommend saving: {min_save:,.0f}₴ - {max_save:,.0f}₴

    💸 *Quick Save Commands:*
    `++{min_save:.0f}` - Save {min_save:,.0f}₴ | `++{max_save:.0f}` - Save {max_save:,.0f}₴

    _Wealth grows one transaction at a time_
    """
        return message

    def send_message(self, chat_id, text, keyboard=None, parse_mode=None, reply_markup=None):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                data = {
                    "chat_id": chat_id,
                    "text": text
                }
                
                if parse_mode:
                    data["parse_mode"] = parse_mode
                    
                if keyboard:
                    data["reply_markup"] = json.dumps(keyboard)
                elif reply_markup:
                    data["reply_markup"] = json.dumps(reply_markup)
                    
                result = requests.post(f"{BASE_URL}/sendMessage", json=data, timeout=10)
                
                if result.status_code == 200:
                    return result
                else:
                    print(f"⚠️ Send message attempt {attempt + 1} failed: {result.status_code}")
                    
            except Exception as e:
                print(f"⚠️ Send message attempt {attempt + 1} error: {e}")
            
            time.sleep(2)  # Wait before retry
        
        print(f"❌ Failed to send message after {max_retries} attempts")
        return None

    def answer_callback(self, callback_id):
        """Answer callback query to remove loading state"""
        try:
            requests.post(f"{BASE_URL}/answerCallbackQuery", json={
                "callback_query_id": callback_id
            })
        except Exception as e:
            print(f"Error answering callback: {e}")

    def process_update(self, update_data):
        """Process Telegram update from webhook"""
        try:
            if "message" in update_data:
                self.process_message(update_data["message"])
            elif "callback_query" in update_data:
                self.process_callback(update_data["callback_query"])
        except Exception as e:
            print(f"❌ Error processing update: {e}")

    def process_message(self, msg):
        """Process message from webhook"""
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")
        print(f"📨 Processing message from {chat_id}: '{text}'")

        
        # Handle delete mode first if active
        if self.delete_mode.get(chat_id):
            if text.isdigit():
                user_transactions = self.get_user_transactions(chat_id)
                transaction_map = self.delete_mode[chat_id]
                
                if text == "0":
                    self.delete_mode[chat_id] = False
                    self.send_message(chat_id, "✅ Exit delete mode. Back to normal operation.", reply_markup=self.get_main_menu())

                
                else:
                    selected_number = int(text)
                    if selected_number in transaction_map:
                        actual_index = transaction_map[selected_number]
                        if 0 <= actual_index < len(user_transactions):
                            deleted = user_transactions.pop(actual_index)
                            
                            # Get proper symbol for confirmation based on transaction type
                            if deleted['type'] == 'income':
                                symbol = "💰"
                                amount_display = f"+{deleted['amount']:,.0f}₴"
                            elif deleted['type'] == 'savings':
                                symbol = "🏦" 
                                amount_display = f"++{deleted['amount']:,.0f}₴"
                            elif deleted['type'] == 'debt':
                                symbol = "💳"
                                amount_display = f"-{deleted['amount']:,.0f}₴"
                            elif deleted['type'] == 'debt_return':
                                symbol = "🔙"
                                amount_display = f"+-{deleted['amount']:,.0f}₴"
                            elif deleted['type'] == 'savings_withdraw':
                                symbol = "📥"
                                amount_display = f"-+{deleted['amount']:,.0f}₴"
                            else:  # expense
                                symbol = "🛒"
                                amount_display = f"-{deleted['amount']:,.0f}₴"
                            
                            self.send_message(chat_id, f"🗑️ {symbol} Deleted: {amount_display} - {deleted['category']}", reply_markup=self.get_main_menu())
                            
                            # Update IDs for remaining transactions
                            for i, transaction in enumerate(user_transactions):
                                transaction['id'] = i + 1
                            
                            self.sync_transactions_to_postgres()
                            # IMPORTANT: Clear delete mode to force refresh
                            self.delete_mode[chat_id] = False
                        else:
                            self.send_message(chat_id, f"❌ Invalid transaction number. Type 0 to exit delete mode.", reply_markup=self.get_main_menu())
                    else:
                        self.send_message(chat_id, f"❌ Invalid transaction number. Type 0 to exit delete mode.", reply_markup=self.get_main_menu())
            else:
                # Any non-digit text cancels delete mode
                self.delete_mode[chat_id] = False
                self.send_message(chat_id, "❌ Delete mode cancelled.", reply_markup=self.get_main_menu())
            return

        # NORMAL MESSAGE PROCESSING (when not in delete mode)
        elif text == "/start":
            user_name = msg["chat"].get("first_name", "there")
            
            # Send welcome image first
            welcome_image_url = "https://github.com/Ze1n5/finnbot/blob/3d177fe8ea8057ec09103540ff71154e1b21c8fc/Images/welcome.jpg"
            welcome_caption = f"👋 Welcome {user_name}! I'm Finn - your AI finance assistant 🤖💰\n\nLet's set up your financial profile."
            
            # Send the photo
            self.send_photo_from_url(chat_id, welcome_image_url, welcome_caption)
            
            # Then show language selection (after a short delay)
            time.sleep(1)  # Optional: wait 1 second before showing language selection
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "🇺🇸 English", "callback_data": "onboard_lang_en"}],
                    [{"text": "🇺🇦 Українська", "callback_data": "onboard_lang_uk"}]
                ]
            }
            
            language_text = "Please choose your language / Будь ласка, оберіть вашу мову:"
            self.send_message(chat_id, language_text, keyboard)

        if chat_id in self.onboarding_state:
            state = self.onboarding_state[chat_id]
            
            try:
                amount = float(text)
                user_lang = self.get_user_language(chat_id)
                
                if state == 'awaiting_balance':
                    # Save initial balance (even if 0)
                    transaction = {
                        "id": 1,
                        "amount": amount,
                        "category": "Initial Balance",
                        "description": "Starting cash balance",
                        "type": "income",
                        "date": datetime.now().astimezone().isoformat()
                    }
                    
                    print(f"🔍 DEBUG: About to call save_user_transaction with transaction: {transaction}")
                    print(f"🔍 DEBUG: Method exists: {hasattr(self, 'save_user_transaction')}")
                    
                    self.save_user_transaction(chat_id, transaction)
                    
                    # Ask for confirmation
                    if user_lang == 'uk':
                        confirm_msg = f"💵 Початковий баланс: {amount:,.0f}₴\n\nЦе правильно?"
                    else:
                        confirm_msg = f"💵 Starting balance: {amount:,.0f}₴\n\nIs this correct?"
                        
                    keyboard = {
                        "inline_keyboard": [[
                            {"text": "✅ Так" if user_lang == 'uk' else "✅ Yes", "callback_data": "confirm_balance"}
                        ]]
                    }
                    self.send_message(chat_id, confirm_msg, keyboard)
                    return
                    
                elif state == 'awaiting_debt':
                    # Save initial debt (even if 0)
                    transaction = {
                        "id": len(self.get_user_transactions(chat_id)) + 1,
                        "amount": -amount,  # Negative for debt
                        "category": "Initial Debt", 
                        "description": "Starting debt balance",
                        "type": "debt",
                        "date": datetime.now().astimezone().isoformat()
                    }
                    self.save_user_transaction(chat_id, transaction)
                    
                    # Ask for confirmation
                    if user_lang == 'uk':
                        confirm_msg = f"💳 Початковий борг: {amount:,.0f}₴\n\nЦе правильно?"
                    else:
                        confirm_msg = f"💳 Starting debt: {amount:,.0f}₴\n\nIs this correct?"
                        
                    keyboard = {
                        "inline_keyboard": [[
                            {"text": "✅ Так" if user_lang == 'uk' else "✅ Yes", "callback_data": "confirm_debt"}
                        ]]
                    }
                    self.send_message(chat_id, confirm_msg, keyboard)
                    return
                    
                elif state == 'awaiting_savings':
                    # Save initial savings (even if 0)  
                    transaction = {
                        "id": len(self.get_user_transactions(chat_id)) + 1,
                        "amount": amount,
                        "category": "Bank",
                        "description": "Starting savings balance",
                        "type": "savings",
                        "date": datetime.now().astimezone().isoformat()
                    }
                    self.save_user_transaction(chat_id, transaction)
                    
                    # Ask for confirmation
                    if user_lang == 'uk':
                        confirm_msg = f"🏦 Початкові заощадження: {amount:,.0f}₴\n\nЦе правильно?"
                    else:
                        confirm_msg = f"🏦 Starting savings: {amount:,.0f}₴\n\nIs this correct?"
                        
                    keyboard = {
                        "inline_keyboard": [[
                            {"text": "✅ Так" if user_lang == 'uk' else "✅ Yes", "callback_data": "confirm_savings"}
                        ]]
                    }
                    self.send_message(chat_id, confirm_msg, keyboard)
                    return
                    
            except ValueError:
                user_lang = self.get_user_language(chat_id)
                error_msg = "❌ Будь ласка, введіть число" if user_lang == 'uk' else "❌ Please enter a number"
                self.send_message(chat_id, error_msg)
            return


        elif text == "🌍 Language":
            # Show language selection keyboard
            keyboard = {
                "inline_keyboard": [
                    [{"text": "🇺🇸 English", "callback_data": "lang_en"}],
                    [{"text": "🇺🇦 Українська", "callback_data": "lang_uk"}]
                ]
            }
            current_lang = self.get_user_language(chat_id)
            current_lang_text = "English" if current_lang == 'en' else "Українська"
            message = f"🌍 Current language: {current_lang_text}\n\nChoose your language / Оберіть мову:"
            self.send_message(chat_id, message, keyboard)

        elif text == "🔄 Restart Bot" or text == "🔄 Перезапустити бота":
            user_lang = self.get_user_language(chat_id)
            
            if user_lang == 'uk':
                confirmation_text = """🔄 *Перезапуск бота*
                
        Ця дія видалить:
        • Всі ваші транзакції
        • Всі категорії витрат
        • Ваші налаштування
        • Історію доходів

        *Цю дію не можна скасувати!*

        Ви впевнені, що хочете продовжити?"""
                
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "✅ Так, перезапустити", "callback_data": "confirm_restart"}],
                        [{"text": "❌ Скасувати", "callback_data": "cancel_restart"}]
                    ]
                }
            else:
                confirmation_text = """🔄 *Restart Bot*
                
        This action will delete:
        • All your transactions
        • All spending categories  
        • Your settings
        • Income history

        *This action cannot be undone!*

        Are you sure you want to proceed?"""
                
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "✅ Yes, restart", "callback_data": "confirm_restart"}],
                        [{"text": "❌ Cancel", "callback_data": "cancel_restart"}]
                    ]
                }
            
            self.send_message(chat_id, confirmation_text, parse_mode='Markdown', keyboard=keyboard)

        elif text == "/test_savings":
            # Test the savings category feature directly
            test_amount = 100
            user_lang = self.get_user_language(chat_id)
            
            if user_lang == 'uk':
                savings_cats = ["Кріпто", "Банк", "Особисте", "Інвестиції"]
                savings_map = {
                    "Кріпто": "Crypto",
                    "Банк": "Bank", 
                    "Особисте": "Personal",
                    "Інвестиції": "Investment"
                }
                message = f"🔧 Тест: Заощадження ++{test_amount}₴\nОберіть категорію:"
            else:
                savings_cats = self.protected_savings_categories
                savings_map = {cat: cat for cat in self.protected_savings_categories}
                message = f"🔧 Test: Savings ++{test_amount}₴\nSelect category:"
            
            keyboard_rows = []
            for i in range(0, len(savings_cats), 2):
                row = []
                for cat in savings_cats[i:i+2]:
                    internal_name = savings_map[cat]
                    row.append({"text": cat, "callback_data": f"cat_{internal_name}"})
                keyboard_rows.append(row)
            
            keyboard = {"inline_keyboard": keyboard_rows}
            
            # Store test transaction
            self.pending[chat_id] = {
                'amount': test_amount, 
                'text': "Test savings transaction", 
                'category': "Savings",
                'type': "savings"
            }
            
            self.send_message(chat_id, message, keyboard)

        elif text == "/income":
            update_text = """💼 *Update Your Monthly Income*

Enter your new monthly income in UAH:

*Example:*
`20000` - for 20,000₴ per month
`35000` - for 35,000₴ per month

This will help me provide better financial recommendations!"""
            self.pending_income.add(chat_id)
            self.send_message(chat_id, update_text, parse_mode='Markdown')
        
        elif text == "/help":
            user_lang = self.get_user_language(chat_id)
            
            if user_lang == 'uk':
                help_text = """💡 *Доступні команди:*
        • `15.50 обід` - Додати витрату
        • `+5000 зарплата` - Додати дохід  
        • `-100 борг` - Додати борг
        • `++200 заощадження` - Додати заощадження
        • Використовуйте меню нижче для більше опцій!"""
            else:
                help_text = """💡 *Available Commands:*
        • `15.50 lunch` - Add expense
        • `+5000 salary` - Add income  
        • `-100 debt` - Add debt
        • `++200 savings` - Add savings
        • Use menu below for more options!"""
            
            self.send_message(chat_id, help_text, parse_mode='Markdown', reply_markup=self.get_main_menu())

        
        elif text == "📊 Financial Summary":
            user_transactions = self.get_user_transactions(chat_id)
            if not user_transactions:
                self.send_message(chat_id, "No transactions recorded yet.", reply_markup=self.get_main_menu())
            else:
                income = 0
                expenses = 0
                savings_deposits = 0
                savings_withdrawn = 0
                debt_incurred = 0
                debt_returned = 0
                expense_by_category = {}
                
                # ADD THIS: Savings by category tracking
                savings_by_category = {}
                
                for transaction in user_transactions:
                    if transaction['type'] == 'income':
                        income += transaction['amount']
                    elif transaction['type'] == 'savings':
                        savings_deposits += transaction['amount']
                        # Track savings by category
                        category = transaction['category']
                        if category not in savings_by_category:
                            savings_by_category[category] = 0
                        savings_by_category[category] += transaction['amount']
                    elif transaction['type'] == 'debt':
                        debt_incurred += abs(transaction['amount'])
                    elif transaction['type'] == 'debt_return':
                        debt_returned += abs(transaction['amount'])
                    elif transaction['type'] == 'savings_withdraw':
                        savings_withdrawn += transaction['amount']
                    else:  # Regular expenses
                        expenses += transaction['amount']
                        category = transaction['category']
                        if category not in expense_by_category:
                            expense_by_category[category] = 0
                        expense_by_category[category] += transaction['amount']
                
                # CALCULATE NET AMOUNTS
                net_savings = savings_deposits - savings_withdrawn
                net_debt = debt_incurred - debt_returned
                net_flow = income - expenses - net_savings
                
                # ✅ FIX: Initialize summary_text variable
                summary_text = "📊 *Financial Summary*\n\n"
                
                # CASH FLOW SECTION
                summary_text += "💸 *Cash Flow Analysis:*\n"
                summary_text += f"   Income: {income:,.0f}₴\n"
                summary_text += f"   Expenses: {expenses:,.0f}₴\n"
                summary_text += f"   Savings: {net_savings:,.0f}₴\n"
                summary_text += f"   ─────────────────\n"
                summary_text += f"   Net Cash Flow: {net_flow:,.0f}₴\n\n"
                
                # SAVINGS SECTION
                summary_text += "🏦 *Savings Account:*\n"
                summary_text += f"   Deposited: {savings_deposits:,.0f}₴\n"
                summary_text += f"   Net Savings: {net_savings:,.0f}₴\n\n"
                
                # DEBT SECTION (only show if there's debt activity)
                if debt_incurred > 0 or debt_returned > 0:
                    summary_text += "💳 *Debt Account:*\n"
                    summary_text += f"   Incurred: {debt_incurred:,.0f}₴\n"
                    if debt_returned > 0:
                        summary_text += f"   Returned: {debt_returned:,.0f}₴\n"
                    summary_text += f"   Net Debt: {net_debt:,.0f}₴\n\n"
                
                # EXPENSES BY CATEGORY
                if expense_by_category:
                    summary_text += "📋 *Expenses by Category:*\n"
                    for category, amount in sorted(expense_by_category.items(), key=lambda x: x[1], reverse=True):
                        percentage = (amount / expenses) * 100 if expenses > 0 else 0
                        summary_text += f"   {category}: {amount:,.0f}₴ ({percentage:.1f}%)\n"
                
                # ✅ FIX: ADD THIS SECTION AFTER THE EXISTING SUMMARY SECTIONS:
                # SAVINGS BY CATEGORY SECTION
                if savings_by_category:
                    summary_text += "\n🏦 *Savings by Category:*\n"
                    for category, amount in sorted(savings_by_category.items(), key=lambda x: x[1], reverse=True):
                        percentage = (amount / savings_deposits) * 100 if savings_deposits > 0 else 0
                        summary_text += f"   {category}: {amount:,.0f}₴ ({percentage:.1f}%)\n"
                
                self.send_message(chat_id, summary_text, parse_mode='Markdown', reply_markup=self.get_main_menu())

        elif text == "📊 50/30/20 Status" or text == "📊 50/30/20 Status":
            user_id_str = str(chat_id)
            user_lang = self.get_user_language(chat_id)
            
            # Check if we have data for this user
            if (user_id_str not in self.monthly_totals or 
                user_id_str not in self.monthly_percentages or
                self.monthly_totals[user_id_str]['income'] == 0):
                
                if user_lang == 'uk':
                    self.send_message(chat_id, "📊 Ще немає даних для аналізу 50/30/20 цього місяця. Додайте доходи та витрати, щоб побачити статистику.")
                else:
                    self.send_message(chat_id, "📊 No data yet for 50/30/20 analysis this month. Add some income and expenses to see your statistics.")
                return
            
            percentages = self.monthly_percentages.get(user_id_str, {'needs': 0, 'wants': 0, 'future': 0})
            totals = self.monthly_totals.get(user_id_str, {'needs': 0, 'wants': 0, 'future': 0, 'income': 0})
            
            # Ensure we have valid percentages
            needs_pct = percentages.get('needs', 0)
            wants_pct = percentages.get('wants', 0) 
            future_pct = percentages.get('future', 0)
            
            if user_lang == 'uk':
                summary = f"""📊 *Статус 50/30/20*

        🏠 Потреби: {needs_pct:.1f}% ({totals.get('needs', 0):,.0f}₴)
        🎉 Бажання: {wants_pct:.1f}% ({totals.get('wants', 0):,.0f}₴)
        🏦 Майбутнє: {future_pct:.1f}% ({totals.get('future', 0):,.0f}₴)

        💰 Загальний дохід: {totals.get('income', 0):,.0f}₴

        """
                # Add status indicators
                if needs_pct <= 50:
                    summary += "✅ Потреби в межах цілі\n"
                else:
                    summary += "⚠️ Потреби перевищують ціль\n"
                    
                if wants_pct <= 30:
                    summary += "✅ Бажання в межах цілі\n"
                else:
                    summary += "⚠️ Бажання перевищують ціль\n"
                    
                if future_pct >= 20:
                    summary += "🎯 Майбутнє на цільовому рівні!"
                else:
                    summary += "💡 Можна покращити майбутнє"
                    
            else:
                summary = f"""📊 *50/30/20 Status*

        🏠 Needs: {needs_pct:.1f}% ({totals.get('needs', 0):,.0f}₴)
        🎉 Wants: {wants_pct:.1f}% ({totals.get('wants', 0):,.0f}₴)
        🏦 Future: {future_pct:.1f}% ({totals.get('future', 0):,.0f}₴)

        💰 Total Income: {totals.get('income', 0):,.0f}₴

        """
                # Add status indicators
                if needs_pct <= 50:
                    summary += "✅ Needs within target\n"
                else:
                    summary += "⚠️ Needs over target\n"
                    
                if wants_pct <= 30:
                    summary += "✅ Wants within target\n"
                else:
                    summary += "⚠️ Wants over target\n"
                    
                if future_pct >= 20:
                    summary += "🎯 Future on target!"
                else:
                    summary += "💡 Future can be improved"
            
            self.send_message(chat_id, summary, parse_mode='Markdown')  
     
        elif text == "🗑️ Delete Transaction":
            user_transactions = self.get_user_transactions(chat_id)
            if not user_transactions:
                self.send_message(chat_id, "📭 No transactions to delete.", reply_markup=self.get_main_menu())
            else:
                # Group transactions by type for better organization
                transactions_by_type = {
                    'income': [],
                    'expense': [],
                    'savings': [],
                    'debt': [],
                    'debt_return': [],
                    'savings_withdraw': []
                }
                
                for i, transaction in enumerate(user_transactions):
                    transactions_by_type[transaction['type']].append((i, transaction))
                
                delete_text = "🗑️ *Select Transaction to Delete*\n\n"
                delete_text += "⏹️  `0` - Cancel & Exit\n\n"
                
                current_number = 1
                transaction_map = {}  # Map display numbers to actual indices
                
                # Display transactions by type with clear sections
                for trans_type, trans_list in transactions_by_type.items():
                    if trans_list:
                        # Add section header (REMOVED the balance calculation that was causing the error)
                        
                        # Add transactions for this type
                        for orig_index, transaction in trans_list:
                            # Get proper symbol and amount display
                            if trans_type == 'income':
                                amount_display = f"{transaction['amount']:,.0f} ₴"
                            elif trans_type == 'savings':
                                amount_display = f"{transaction['amount']:,.0f} ₴"
                            elif trans_type == 'debt':
                                amount_display = f"{transaction['amount']:,.0f} ₴"
                            elif trans_type == 'debt_return':
                                amount_display = f"{transaction['amount']:,.0f} ₴"
                            elif trans_type == 'savings_withdraw':
                                amount_display = f"{transaction['amount']:,.0f} ₴"
                            else:  # expense
                                amount_display = f"{transaction['amount']:,.0f} ₴"
                            
                            # Truncate long descriptions
                            description = transaction['description']
                            if len(description) > 25:
                                description = description[:22] + "..."
                            
                            delete_text += f"*`{current_number:2d} `* {amount_display} • {transaction['category']}\n"
                            
                            transaction_map[current_number] = orig_index
                            current_number += 1
                        
                        delete_text += "\n"
                delete_text += "💡 *Type a number to delete, or 0 to cancel*"
                
                # Store the mapping for this user
                self.delete_mode[chat_id] = transaction_map
                
                # Split long messages if needed (Telegram has 4096 char limit)
                if len(delete_text) > 4000:
                    delete_text = delete_text[:4000] + "\n\n... (showing first 4000 characters)"
                
                self.send_message(chat_id, delete_text, parse_mode='Markdown')
        
        elif text == "🏷️ Manage Categories":
            user_categories = self.get_user_categories(chat_id)
            user_lang = self.get_user_language(chat_id)
            
            if user_lang == 'uk':
                categories_text = "🏷️ *Ваші категорії витрат*\n\n"
                categories_text += "*🔒 Захищені категорії заощаджень:*\n"
                categories_text += "• Кріпто • Банк • Особисте • Інвестиції\n\n"
                categories_text += "*Ваші категорії витрат:*\n"
            else:
                categories_text = "🏷️ *Your Spending Categories*\n\n"
                categories_text += "*🔒 Protected Savings Categories:*\n"
                categories_text += "• Crypto • Bank • Personal • Investment\n\n"
                categories_text += "*Your Spending Categories:*\n"
            
            for category, keywords in user_categories.items():
                categories_text += f"• *{category}*"
                if keywords:
                    categories_text += f" - {', '.join(keywords[:3])}{'...' if len(keywords) > 3 else ''}"
                categories_text += "\n"
            
            if user_lang == 'uk':
                categories_text += "\n*Швидкі команди:*\n"
                categories_text += "• `+Їжа` - Додати нову категорію\n"
                categories_text += "• `-Шопінг` - Видалити категорію\n"
                categories_text += "• Захищені категорії не можна змінити"
            else:
                categories_text += "\n*Quick Commands:*\n"
                categories_text += "• `+Food` - Add new category\n"
                categories_text += "• `-Shopping` - Remove category\n"
                categories_text += "• Protected categories cannot be modified"
    
            self.send_message(chat_id, categories_text, parse_mode='Markdown', reply_markup=self.get_main_menu())

        elif text.startswith("+") and len(text) > 1 and not any(char.isdigit() for char in text[1:]):
            # Add new spending category
            try:
                new_category = text[1:].strip()
                if self.add_user_category(chat_id, new_category):
                    self.send_message(chat_id, f"✅ Added new spending category: *{new_category}*", parse_mode='Markdown', reply_markup=self.get_main_menu())
                else:
                    self.send_message(chat_id, f"❌ Spending category *{new_category}* already exists!", parse_mode='Markdown', reply_markup=self.get_main_menu())
            except Exception as e:
                self.send_message(chat_id, f"❌ Error: {str(e)}", reply_markup=self.get_main_menu())

        elif text.startswith("-") and len(text) > 1 and not any(char.isdigit() for char in text[1:]):
            # Remove spending category
            try:
                category_to_remove = text[1:].strip()
                if self.remove_user_category(chat_id, category_to_remove):
                    self.send_message(chat_id, f"✅ Removed spending category: *{category_to_remove}*", parse_mode='Markdown', reply_markup=self.get_main_menu())
                else:
                    self.send_message(chat_id, f"❌ Cannot remove *{category_to_remove}* - category not found or is essential", parse_mode='Markdown', reply_markup=self.get_main_menu())
            except Exception as e:
                self.send_message(chat_id, f"❌ Error: {str(e)}", reply_markup=self.get_main_menu())

        elif chat_id in self.pending_income:
            try:
                income = float(text)
                user_lang = self.get_user_language(chat_id)
                
                if income <= 0:
                    error_msg = "❌ Будь ласка, введіть позитивну суму для вашого доходу." if user_lang == 'uk' else "❌ Please enter a positive amount for your income."
                    self.send_message(chat_id, error_msg)
                    return  # Exit after error
                
                # Save the income
                self.user_incomes[str(chat_id)] = income
                self.save_incomes()
                self.pending_income.discard(chat_id)  # Use discard instead of remove to avoid errors
                
                # Welcome message with next steps
                if user_lang == 'uk':
                    success_text = f"""✅ *Дохід встановлено:* {income:,.0f}₴ на місяць

        🎉 Чудово! Тепер ми готові до роботи!

        🚀 *Швидкий старт:*
        • `150 обід` - Додати витрату
        • `+5000 зарплата` - Додати дохід
        • `++1000` - Додати заощадження
        • `-200 борг` - Додати борг

        📋 *Переглянути повний список команд можна в меню*

        💡 Почніть відстежувати транзакції або використовуйте меню нижче!"""
                else:
                    success_text = f"""✅ *Income set:* {income:,.0f}₴ monthly

        🎉 Excellent! Now we're ready to go!

        🚀 *Quick Start:*
        • `150 lunch` - Add expense
        • `+5000 salary` - Add income  
        • `++1000` - Add savings
        • `-200 debt` - Add debt

        📋 *View the full list of commands in the menu*

        💡 Start tracking transactions or use the menu below!"""
                
                self.send_message(chat_id, success_text, parse_mode='Markdown', reply_markup=self.get_main_menu())
                return  # CRITICAL: Exit after processing income
            
            except ValueError:
                self.send_message(chat_id, "❌ Please enter a valid number for your monthly income.\n\nExample: `15000` for 15,000₴ per month", parse_mode='Markdown')
                return  # Exit after error
        else:
            # Regular transaction processing
            print(f"🔍 DEBUG: Processing transaction - text: '{text}'")            
            # Check if it's a calculation expression (ADD THIS PART)
            if any(op in text for op in ['+', '-', '*', '/', '%']) and any(char.isdigit() for char in text):
                # Try to calculate the expression
                result = self.calculate_expression(text)
                
                if result is not None and result[0] is not None:
                    amount, trans_type, symbol = result
                    
                    # Store pending transaction
                    self.pending[chat_id] = {
                        'amount': amount, 
                        'text': f"{text} = {symbol}{amount:,.0f}₴",
                        'category': "Salary" if trans_type == 'income' else "Other",
                        'type': trans_type
                    }
                    
                    # Show calculation result and ask for category
                    user_lang = self.get_user_language(chat_id)
                    
                    if trans_type == 'income':
                        if user_lang == 'uk':
                            message = f"🧮 Розрахунок: {text}\n💰 Результат: +{amount:,.0f}₴\n📝 Оберіть категорію:"
                        else:
                            message = f"🧮 Calculation: {text}\n💰 Result: +{amount:,.0f}₴\n📝 Select category:"
                            
                        # Create category keyboard
                        if user_lang == 'uk':
                            income_cats = ["Зарплата", "Бізнес"]
                        else:
                            income_cats = list(self.income_categories.keys())
                        
                        keyboard_rows = []
                        for i in range(0, len(income_cats), 2):
                            row = []
                            for cat in income_cats[i:i+2]:
                                row.append({"text": cat, "callback_data": f"cat_{cat}"})
                            keyboard_rows.append(row)
                        
                        keyboard = {"inline_keyboard": keyboard_rows}
                        
                    else:
                        # For savings transactions, show category selection
                        if trans_type == 'savings':
                            user_lang = self.get_user_language(chat_id)
                            
                            if user_lang == 'uk':
                                savings_cats = ["Кріпто", "Банк", "Особисте", "Інвестиції"]
                                savings_map = {
                                    "Кріпто": "Crypto",
                                    "Банк": "Bank", 
                                    "Особисте": "Personal",
                                    "Інвестиції": "Investment"
                                }
                            else:
                                savings_cats = self.protected_savings_categories
                                savings_map = {cat: cat for cat in self.protected_savings_categories}
                            
                            keyboard_rows = []
                            for i in range(0, len(savings_cats), 2):
                                row = []
                                for cat in savings_cats[i:i+2]:
                                    internal_name = savings_map[cat]
                                    row.append({"text": cat, "callback_data": f"cat_{internal_name}"})
                                keyboard_rows.append(row)
                            
                            keyboard = {"inline_keyboard": keyboard_rows}
                            
                            if user_lang == 'uk':
                                message = f"🧮 Розрахунок: {text}\n💰 Результат: {symbol}{amount:,.0f}₴\n\nОберіть категорію заощаджень:"
                            else:
                                message = f"🧮 Calculation: {text}\n💰 Result: {symbol}{amount:,.0f}₴\n\nSelect savings category:"
                        
                        else:
                            # For other transaction types, just confirm
                            if user_lang == 'uk':
                                type_names = {
                                    'expense': 'Витрата',
                                    'debt': 'Борг',
                                    'debt_return': 'Повернення боргу',
                                    'savings_withdraw': 'Зняття заощаджень'
                                }
                                message = f"🧮 Розрахунок: {text}\n💰 Результат: {symbol}{amount:,.0f}₴\n\nЦе правильно?"
                            else:
                                type_names = {
                                    'expense': 'Expense',
                                    'debt': 'Debt',
                                    'debt_return': 'Debt Return', 
                                    'savings_withdraw': 'Savings Withdraw'
                                }
                                message = f"🧮 Calculation: {text}\n💰 Result: {symbol}{amount:,.0f}₴\n\nIs this correct?"

                            keyboard = {"inline_keyboard": [[
                                {"text": "✅ Так" if user_lang == 'uk' else "✅ Yes", "callback_data": f"cat_{type_names[trans_type]}"}
                            ]]}
                    
                    self.send_message(chat_id, message, keyboard)
                    return
                elif result is not None and result[0] is None:
                    # Calculation error
                    self.send_message(chat_id, result[1])
                    return
                else:
                    # ADD THIS: Show formatting help only for unrecognized transaction formats
                    user_lang = self.get_user_language(chat_id)
                    
                    if user_lang == 'uk':
                        help_text = """🤔 Ой! Дозвольте допомогти вам правильно відформатувати:

            🛒 10 - Витрата (обід, шопінг тощо)
                                            
            💰 +100 - Дохід (зарплата, бізнес тощо) 
                                            
            🏦 ++100 - Заощадження (відкласти гроші)
                                            
            💳 -100 - Борг (позичені гроші)
                                            
            🔙 +-100 - Повернення боргу (повернення)
                                            
            📥 -+100 - Зняття заощаджень (зняття з заощаджень)

            💡 *Приклади:*
            `150 обід` - Витрата на обід
            `+5000 зарплата` - Дохід
            `++1000` - Заощадження
            `-200 кредит` - Борг"""
                    else:
                        help_text = """🤔 Oops! Let me help you format that correctly:
                                            
            🛒 10 - Expense (lunch, shopping, etc.)
                                            
            💰 +100 - Income (salary, business, etc.) 
                                            
            🏦 ++100 - Savings (put money aside)
                                            
            💳 -100 - Debt (borrowed money)
                                            
            🔙 +-100 - Returned debt (paying back)
                                            
            📥 -+100 - Savings withdrawal (taking from savings)

            💡 *Examples:*
            `150 lunch` - Expense for lunch
            `+5000 salary` - Income  
            `++1000` - Savings
            `-200 loan` - Debt"""

                    self.send_message(chat_id, help_text, parse_mode='Markdown', reply_markup=self.get_main_menu())
                    return
            
            # Original transaction processing (keep your existing code)
            amount, is_income, is_debt, is_savings, is_debt_return, is_savings_withdraw = self.extract_amount(text)
            print(f"🔍 DEBUG process_message - Transaction analysis:")
            print(f"   Amount: {amount}")
            print(f"   Is savings: {is_savings}")
            print(f"   Is income: {is_income}")
            print(f"   Is debt: {is_debt}")
            print(f"   Chat ID in pending: {chat_id in self.pending}")
            print(f"   Delete mode: {self.delete_mode.get(chat_id, False)}")
        
            if amount is not None:
                # Determine transaction type and category
                if is_debt_return:
                    category = "Debt Return"
                    transaction_type = "debt_return"
                elif is_savings_withdraw:
                    category = "Savings Withdrawal" 
                    transaction_type = "savings_withdraw"
                elif is_debt:
                    category = "Debt"
                    transaction_type = "debt"
                elif is_savings:
                    print(f"🔍 DEBUG: Processing SAVINGS transaction - amount: {amount}")
                    
                    # Use protected savings categories
                    user_lang = self.get_user_language(chat_id)
                    print(f"🔍 DEBUG: User language: {user_lang}")
                    
                    if user_lang == 'uk':
                        savings_cats = ["Кріпто", "Банк", "Особисте", "Інвестиції"]
                        savings_map = {
                            "Кріпто": "Crypto",
                            "Банк": "Bank", 
                            "Особисте": "Personal",
                            "Інвестиції": "Investment"
                        }
                    else:
                        savings_cats = self.protected_savings_categories
                        savings_map = {cat: cat for cat in self.protected_savings_categories}
                    
                    print(f"🔍 DEBUG: Savings categories: {savings_cats}")
                    
                    # Create inline keyboard
                    keyboard_rows = []
                    for i in range(0, len(savings_cats), 2):
                        row = []
                        for cat in savings_cats[i:i+2]:
                            # Use the internal English name for callback_data
                            internal_name = savings_map[cat]
                            row.append({"text": cat, "callback_data": f"cat_{internal_name}"})
                        keyboard_rows.append(row)
                    
                    keyboard = {"inline_keyboard": keyboard_rows}
                    
                    # ✅ CRITICAL: Store the pending transaction BEFORE sending the message
                    self.pending[chat_id] = {
                        'amount': amount, 
                        'text': text, 
                        'category': "Savings",  # Default category
                        'type': "savings"
                    }
                    
                    if user_lang == 'uk':
                        message = f"🏦 Заощадження: ++{amount:,.0f}₴\n📝 Опис: {text}\n\nОберіть категорію заощаджень:"
                    else:
                        message = f"🏦 Savings: ++{amount:,.0f}₴\n📝 Description: {text}\n\nSelect savings category:"
                    
                    print(f"🔍 DEBUG: Sending savings category selection message with keyboard")
                    self.send_message(chat_id, message, keyboard)
                    
                    # ✅ IMPORTANT: Return to prevent further processing
                    return

                elif is_income:
                    category = "Salary"  # Default income category
                    transaction_type = "income"
                else:
                    # Expense transaction
                    category = self.guess_category(text, chat_id)
                    transaction_type = "expense"
                
                # Store pending transaction for ALL types
                self.pending[chat_id] = {
                    'amount': amount, 
                    'text': text, 
                    'category': category,
                    'type': transaction_type
                }
                
                # Create appropriate message and keyboard
                if is_debt_return:
                    message = f"✅ Debt Return: +-{amount:,.0f}₴\n📝 Description: {text}\n\nIs this correct?"
                    keyboard = {"inline_keyboard": [[
                        {"text": "✅ Confirm Debt Return", "callback_data": "cat_Debt Return"}
                    ]]}
                elif is_savings_withdraw:
                    message = f"🏦 Savings Withdrawal: -+{amount:,.0f}₴\n📝 Description: {text}\n\nIs this correct?"
                    keyboard = {"inline_keyboard": [[
                        {"text": "✅ Confirm Savings Withdrawal", "callback_data": "cat_Savings Withdrawal"}
                    ]]}
                elif is_debt:
                    message = f"💳 Debt: -{amount:,.0f}₴\n📝 Description: {text}\n\nIs this correct?"
                    keyboard = {"inline_keyboard": [[
                        {"text": "✅ Confirm Debt", "callback_data": "cat_Debt"}
                    ]]}
                elif is_income:
                    message = f"💰 Income: +{amount:,.0f}₴\n📝 Description: {text}\n\nSelect category:"
                    
                    # Create proper inline keyboard for income categories
                    income_cats = list(self.income_categories.keys())
                    keyboard_rows = []
                    for i in range(0, len(income_cats), 2):
                        row = []
                        for cat in income_cats[i:i+2]:
                            row.append({"text": cat, "callback_data": f"cat_{cat}"})
                        keyboard_rows.append(row)
                    
                    keyboard = {"inline_keyboard": keyboard_rows}
                    
                else:
                    message = f"💰 Expense: -{amount:,.0f}₴\n🏷️ Category: {category}\n📝 Description: {text}\n\nSelect correct category:"
                    # Get user's spending categories for the keyboard
                    user_categories = self.get_user_categories(chat_id)
                    category_list = list(user_categories.keys())
                    
                    # Create category selection keyboard
                    keyboard_rows = []
                    for i in range(0, len(category_list), 2):
                        row = []
                        for cat in category_list[i:i+2]:
                            row.append({"text": cat, "callback_data": f"cat_{cat}"})
                        keyboard_rows.append(row)
                    
                    keyboard = {"inline_keyboard": keyboard_rows}
                
                # SEND THE MESSAGE
                self.send_message(chat_id, message, keyboard)

    def process_callback(self, query):
        """Process callback from webhook"""
        chat_id = query["message"]["chat"]["id"]
        message_id = query["message"]["message_id"]
        data = query["data"]
        
        print(f"🔍 DEBUG: Received callback - data: '{data}', chat_id: {chat_id}")
        
        # Answer the callback query first
        self.answer_callback(query["id"])

        # ONBOARDING HANDLERS
        if data.startswith("onboard_lang_"):
            language = data[13:]  # 'en' or 'uk'
            self.set_user_language(chat_id, language)
            
            # Delete language selection message
            try:
                requests.post(f"{BASE_URL}/deleteMessage", json={
                    "chat_id": chat_id,
                    "message_id": message_id
                })
            except Exception as e:
                print(f"⚠️ Error deleting language message: {e}")
            
            # Send welcome image
            welcome_image_url = "https://raw.githubusercontent.com/Ze1n5/finnbot/main/Images/welcome.jpg"
            
            user_lang = self.get_user_language(chat_id)
            if user_lang == 'uk':
                image_caption = """👋 *Ласкаво просимо до Finn!*"

Давайте створимо ваш фінансовий профіль. Це займе лише хвилинку!
*Крок 1/4: Поточний баланс*

Скільки готівки у вас є зараз? (в гривнях)

💡 *Введіть суму:*
`5000` - якщо у вас 5,000₴
`0` - якщо готівки немає"""
            else:
                image_caption = """👋 *Hi! I'm Finn!*

Let's create your financial profile. This will just take a minute!
*Step 1/4: Current Balance*

How much cash do you have right now? (in UAH)

💡 *Enter amount:*
`5000` - if you have 5,000₴
`0` - if no cash"""
            
            # Send the welcome image
            self.send_photo_from_url(chat_id, welcome_image_url, image_caption)
            # Wait a moment then set the onboarding state
            time.sleep(1)
            self.onboarding_state[chat_id] = 'awaiting_balance'

        # Handle balance confirmation
        elif data == "confirm_balance":
            # Delete the confirmation message
            try:
                requests.post(f"{BASE_URL}/deleteMessage", json={
                    "chat_id": chat_id,
                    "message_id": message_id
                })
                print(f"🔍 DEBUG: Deleted balance confirmation message {message_id}")
            except Exception as e:
                print(f"⚠️ Error deleting balance confirmation message: {e}")
            
            # Move to debt question (your existing code)
            user_lang = self.get_user_language(chat_id)
            
            if user_lang == 'uk':
                debt_msg = """✅ *Баланс збережено!*

*Крок 2/4: Борги*

Чи є у вас борги? (кредити, позики тощо)

💡 *Введіть загальну суму боргів:*
`10000` - якщо винен 10,000₴
`0` - якщо боргів немає"""
            else:
                debt_msg = """✅ *Balance saved!*

*Step 2/4: Debts*

Do you have any debts? (loans, credits, etc.)

💡 *Enter total debt amount:*
`10000` - if you owe 10,000₴
`0` - if no debts"""
            
            self.onboarding_state[chat_id] = 'awaiting_debt'
            self.send_message(chat_id, debt_msg, parse_mode='Markdown')

        # Handle debt confirmation  
        elif data == "confirm_debt":
            # Delete the confirmation message
            try:
                requests.post(f"{BASE_URL}/deleteMessage", json={
                    "chat_id": chat_id,
                    "message_id": message_id
                })
                print(f"🔍 DEBUG: Deleted debt confirmation message {message_id}")
            except Exception as e:
                print(f"⚠️ Error deleting debt confirmation message: {e}")
            
            # Move to savings question (your existing code)
            user_lang = self.get_user_language(chat_id)
            
            if user_lang == 'uk':
                savings_msg = """✅ *Борги збережено!*

*Крок 3/4: Заощадження*

Чи є у вас заощадження? (банк, крипто, інвестиції)

💡 *Введіть загальну суму заощаджень:*
`15000` - якщо маєте 15,000₴
`0` - якщо заощаджень немає"""
            else:
                savings_msg = """✅ *Debts saved!*

*Step 3/4: Savings*

Do you have any savings? (bank, crypto, investments)

💡 *Enter total savings amount:*
`15000` - if you have 15,000₴ saved
`0` - if no savings"""
            
            self.onboarding_state[chat_id] = 'awaiting_savings'
            self.send_message(chat_id, savings_msg, parse_mode='Markdown')

        # Handle savings confirmation
        elif data == "confirm_savings":
            # Delete the confirmation message
            try:
                requests.post(f"{BASE_URL}/deleteMessage", json={
                    "chat_id": chat_id,
                    "message_id": message_id
                })
                print(f"🔍 DEBUG: Deleted savings confirmation message {message_id}")
            except Exception as e:
                print(f"⚠️ Error deleting savings confirmation message: {e}")
            
            # Complete onboarding (your existing code)
            user_lang = self.get_user_language(chat_id)
            
            if user_lang == 'uk':
                complete_msg = """🎉 *Профіль створено!*

Тепер ви готові до роботи з Finn! 

🚀 *Швидкий старт:*
`150 обід` - Додати витрату
`+5000 зарплата` - Додати дохід
`++1000` - Додати заощадження
`-200 кредит` - Додати борг

💡 Почніть відстежувати транзакції або використовуйте меню!"""
            else:
                complete_msg = """🎉 *Profile Created!*

You're now ready to use Finn!

🚀 *Quick Start:*
`150 lunch` - Add expense
`+5000 salary` - Add income
`++1000` - Add savings  
`-200 loan` - Add debt

💡 Start tracking transactions or use the menu!"""
            
            # Clear onboarding state
            if chat_id in self.onboarding_state:
                del self.onboarding_state[chat_id]
            
            self.send_message(chat_id, complete_msg, parse_mode='Markdown', reply_markup=self.get_main_menu())

        
        if data.startswith("cat_"):
            category = data[4:]
            print(f"🔍 DEBUG: Processing category selection - category: '{category}', chat_id in pending: {chat_id in self.pending}")
            
            if chat_id in self.pending:
                pending = self.pending[chat_id]
                amount = pending["amount"]
                text = pending["text"]
                transaction_type = pending["type"]
                
                print(f"🔍 DEBUG: Processing {transaction_type} transaction - amount: {amount}, category: {category}")
                
                # Learn if corrected (only for expenses, not income)
                if pending["category"] != category and transaction_type == "expense":
                    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
                    for word in words:
                        self.learned_patterns[word] = category
                
                # Add transaction for specific user
                try:
                    user_transactions = self.get_user_transactions(chat_id)
                    transaction = {
                        "id": len(user_transactions) + 1,
                        "amount": amount,
                        "category": category,
                        "description": text,
                        "type": transaction_type,
                        "date": datetime.now().astimezone().isoformat()
                    }
                    user_transactions.append(transaction)
                    self.sync_transactions_to_postgres()
                    print(f"✅ Saved {transaction_type} transaction for user {chat_id}")
                    
                    # Sync to Railway
                    sync_to_railway({
                        'amount': amount,
                        'description': text,
                        'category': category,
                        'timestamp': datetime.now().isoformat(),
                        'type': transaction_type
                    })
                    
                except Exception as e:
                    print(f"❌ Error saving transaction: {e}")
                    import traceback
                    traceback.print_exc()
                
                user_lang = self.get_user_language(chat_id)  # ADD THIS LINE

                # Update 50/30/20 tracking
                bucket = self.categorize_transaction(category, text)

                # For income transactions, update income total
                if transaction_type == 'income':
                    self.update_income_for_503020(chat_id, amount)
                else:
                    self.update_503020_totals(chat_id, amount, bucket)

                # Check for 50/30/20 limit crossings
                limit_messages = self.check_503020_limits(chat_id)
                for message in limit_messages:
                    self.send_message(chat_id, message, parse_mode='Markdown')
                
                if transaction_type == 'income':
                    # Send savings recommendation
                    savings_msg = self.calculate_savings_recommendation(chat_id, amount, text)
                    self.send_message(chat_id, savings_msg, parse_mode='Markdown')
                    
                    # Send confirmation WITHOUT menu
                    if user_lang == 'uk':
                        confirmation_msg = f"✅ Дохід збережено!\n💰 +{amount:,.0f}₴\n🏷️ {category}"
                    else:
                        confirmation_msg = f"✅ Income saved!\n💰 +{amount:,.0f}₴\n🏷️ {category}"
                    self.send_message(chat_id, confirmation_msg)
                    
                elif transaction_type == 'savings':
                    if user_lang == 'uk':
                        message = f"✅ Заощадження збережено!\n💰 ++{amount:,.0f}₴"
                    else:
                        message = f"✅ Savings saved!\n💰 ++{amount:,.0f}₴"
                    self.send_message(chat_id, message)
                elif transaction_type == 'debt':        
                    if user_lang == 'uk':
                        message = f"✅ Борг збережено!\n💰 -{amount:,.0f}₴"
                    else:
                        message = f"✅ Debt saved!\n💰 -{amount:,.0f}₴"
                    self.send_message(chat_id, message)
                elif transaction_type == 'debt_return':
                    if user_lang == 'uk':
                        message = f"✅ Борг повернено!\n💰 +-{amount:,.0f}₴"
                    else:
                        message = f"✅ Debt returned!\n💰 +-{amount:,.0f}₴"
                    self.send_message(chat_id, message)
                elif transaction_type == 'savings_withdraw':
                    if user_lang == 'uk':
                        message = f"✅ Заощадження знято!\n💰 -+{amount:,.0f}₴"
                    else:
                        message = f"✅ Savings withdrawn!\n💰 -+{amount:,.0f}₴"
                    self.send_message(chat_id, message)
                else:
                    if user_lang == 'uk':
                        message = f"✅ Витрату збережено!\n💰 -{amount:,.0f}₴\n🏷️ {category}"
                    else:
                        message = f"✅ Expense saved!\n💰 -{amount:,.0f}₴\n🏷️ {category}"
                    self.send_message(chat_id, message)
                
                # Clean up pending
                del self.pending[chat_id]
                print(f"🔍 DEBUG: Cleared pending for user {chat_id}")
                
                # Delete the original message with buttons
                try:
                    delete_response = requests.post(f"{BASE_URL}/deleteMessage", json={
                        "chat_id": chat_id,
                        "message_id": message_id
                    })
                    if delete_response.status_code == 200:
                        print(f"🔍 DEBUG: Successfully deleted message {message_id}")
                    else:
                        print(f"⚠️ Failed to delete message: {delete_response.status_code}")
                except Exception as e:
                    print(f"⚠️ Error deleting message: {e}")
            
            else:
                print(f"❌ No pending transaction found for user {chat_id}")
                self.send_message(chat_id, "❌ Transaction expired. Please enter the transaction again.", reply_markup=self.get_main_menu())

        elif data == "confirm_restart":
            user_lang = self.get_user_language(chat_id)
            
            print(f"🔍 DEBUG: Clearing all transactions for user {chat_id}")
            
            # 1. Clear from memory FIRST
            if chat_id in self.transactions:
                print(f"🔍 DEBUG: Before memory clear - {len(self.transactions[chat_id])} transactions in memory")
                self.transactions[chat_id] = []  # Empty the list
                print(f"🔍 DEBUG: After memory clear - {len(self.transactions[chat_id])} transactions in memory")
            
            # 2. Clear from PostgreSQL database
            conn = self.get_db_connection()
            if conn:
                try:
                    cur = conn.cursor()
                    # Delete ALL transactions for this user
                    cur.execute('DELETE FROM transactions WHERE user_id = %s', (chat_id,))
                    conn.commit()
                    conn.close()
                    print(f"✅ Deleted all transactions from PostgreSQL for user {chat_id}")
                except Exception as e:
                    print(f"❌ Error deleting transactions from PostgreSQL: {e}")
            
            # 3. CLEAR ONBOARDING STATE - THIS IS THE KEY FIX!
            if chat_id in self.onboarding_state:
                del self.onboarding_state[chat_id]
                print(f"🔍 DEBUG: Cleared onboarding state for user {chat_id}")
            
            # 4. Force immediate sync to ensure clean state
            self.sync_transactions_to_postgres()
            
            # Clear other user data...
            user_id_str = str(chat_id)
            
            # Clear income
            if user_id_str in self.user_incomes:
                del self.user_incomes[user_id_str]
            
            # Clear user categories (keep only default)
            if user_id_str in self.user_categories:
                self.user_categories[user_id_str] = {"Other": []}
            
            # Clear pending states
            if chat_id in self.pending:
                del self.pending[chat_id]
            if chat_id in self.pending_income:
                self.pending_income.discard(chat_id)
            if chat_id in self.delete_mode:
                del self.delete_mode[chat_id]
            
            # Save changes
            self.save_incomes()
            self.save_user_categories()
            
            if user_lang == 'uk':
                success_msg = """✅ *Бота перезапущено!*
                
        Всі ваші транзакції та дані було успішно видалено. Бот готовий до роботи з чистої сторінки!"""
            else:
                success_msg = """✅ *Bot restarted!*
                
        All your transactions and data have been successfully deleted. The bot is ready to start fresh!"""
            
            self.send_message(chat_id, success_msg, parse_mode='Markdown', reply_markup=self.get_main_menu())
            
            # Delete the confirmation message
            try:
                requests.post(f"{BASE_URL}/deleteMessage", json={
                    "chat_id": chat_id,
                    "message_id": message_id
                })
            except Exception as e:
                print(f"⚠️ Error deleting restart message: {e}")

        elif data == "cancel_restart":
            user_lang = self.get_user_language(chat_id)
            
            if user_lang == 'uk':
                cancel_msg = "❌ Перезапуск скасовано. Ваші дані залишилися недоторканими."
            else:
                cancel_msg = "❌ Restart cancelled. Your data remains untouched."
            
            self.send_message(chat_id, cancel_msg, reply_markup=self.get_main_menu())
            
            # Delete the confirmation message
            try:
                delete_response = requests.post(f"{BASE_URL}/deleteMessage", json={
                    "chat_id": chat_id,
                    "message_id": message_id
                })
            except Exception as e:
                print(f"⚠️ Error deleting restart message: {e}")

        elif data.startswith("lang_"):
            language = data[5:]  # 'en' or 'uk'
            self.set_user_language(chat_id, language)
            
            if language == 'en':
                confirmation = "✅ Language set to English!"
            else:
                confirmation = "✅ Мову встановлено українську!"
            
            self.send_message(chat_id, confirmation, reply_markup=self.get_main_menu())
        elif data.startswith("lang_"):
            language = data[5:]  # 'en' or 'uk'
            self.set_user_language(chat_id, language)
            
            if language == 'en':
                confirmation = "✅ Language set to English!"
            else:
                confirmation = "✅ Мову встановлено українську!"
            
            self.send_message(chat_id, confirmation, reply_markup=self.get_main_menu())
            
            # Delete the language selection message
            try:
                delete_response = requests.post(f"{BASE_URL}/deleteMessage", json={
                    "chat_id": chat_id,
                    "message_id": message_id
                })
            except Exception as e:
                print(f"⚠️ Error deleting language message: {e}")

# Webhook route
@flask_app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    """Receive updates from Telegram"""
    if request.method == 'GET':
        return jsonify({"status": "healthy", "message": "Webhook endpoint active"})
    
    if request.method == 'POST':
        update_data = request.get_json()
        print(f"📨 Received webhook update")
        
        # Process the update in a separate thread to avoid timeout
        threading.Thread(target=bot_instance.process_update, args=(update_data,)).start()
        
        return jsonify({"status": "success"}), 200
    
@flask_app.route('/debug-categories')
def debug_categories():
    """Debug route to check if categories are working"""
    try:
        return jsonify({
            "protected_categories": bot_instance.protected_savings_categories,
            "user_languages": bot_instance.user_languages,
            "pending_transactions": len(bot_instance.pending),
            "transactions_count": len(bot_instance.transactions)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@flask_app.route('/debug-bot-state')
def debug_bot_state():
    """Debug route to check bot internal state"""
    try:
        return jsonify({
            "bot_initialized": bool(bot_instance),
            "protected_categories": bot_instance.protected_savings_categories,
            "pending_transactions": dict(bot_instance.pending),
            "user_languages": bot_instance.user_languages,
            "transactions_count": len(bot_instance.transactions),
            "income_categories": bot_instance.income_categories,
            "category_mapping": bot_instance.category_mapping
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@flask_app.route('/debug-webhook')
def debug_webhook():
    """Debug webhook setup"""
    try:
        # Get current webhook info
        response = requests.get(f"{BASE_URL}/getWebhookInfo")
        webhook_info = response.json()
        
        # Set webhook to your correct URL
        webhook_url = "https://finnbot-production.up.railway.app/webhook"
        set_response = requests.post(
            f"{BASE_URL}/setWebhook",
            json={"url": webhook_url}
        )
        
        return jsonify({
            "current_webhook": webhook_info,
            "set_webhook_result": set_response.json(),
            "webhook_url": webhook_url,
            "bot_token_exists": bool(BOT_TOKEN and BOT_TOKEN != "your_bot_token_here")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Health check route
@flask_app.route('/', methods=['GET', 'POST'])
def health_check():
    if request.method == 'POST':
        # Handle POST requests gracefully
        return jsonify({"status": "OK", "message": "FinnBot is running!", "method": "POST"})
    
    return jsonify({"status": "OK", "message": "FinnBot is running with webhooks!"})

# Your existing API routes
@flask_app.route('/api/financial-data')
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
    

@flask_app.route('/api/transactions')
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
                "amount": display_amount,  # Use formatted amount with proper sign
                "timestamp": timestamp,
                "type": trans_type,
                "category": category  # Include raw category for frontend
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
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Failed to load transactions'}), 500
# Serve mini app main page
# ========== MINI-APP ROUTES ==========

@flask_app.route('/mini-app')
def serve_mini_app():
    return """
    <!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FinnBot - Financial Tracker</title>
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
        
        .balance-card {
            background: white;
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 20px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
            text-align: center;
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
        }
        
        .transaction:last-child {
            border-bottom: none;
        }
        
        .transaction-info {
            flex: 1;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .transaction-emoji {
            font-size: 20px;
            width: 30px;
            text-align: center;
        }
        
        .transaction-details {
            flex: 1;
        }
        
        .transaction-title {
            font-size: 16px;
            font-weight: 500;
            margin-bottom: 4px;
        }
        
        .transaction-category {
            font-size: 14px;
            color: #8e8e93;
        }
        
        .transaction-amount {
            font-size: 16px;
            font-weight: 500;
            text-align: right;
        }
        
        .amount-negative {
            color: #ff3b30;
        }
        
        .amount-positive {
            color: #34c759;
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

    <script>
        // Load financial data and transactions
        async function loadFinancialData() {
            try {
                // Load balance and totals
                const financeResponse = await fetch('/api/financial-data');
                const financeData = await financeResponse.json();
                
                if (financeResponse.ok) {
                    updateFinancialDisplay(financeData);
                } else {
                    showError('Failed to load financial data');
                }
                
                // Load transactions
                const transactionsResponse = await fetch('/api/transactions');
                const transactionsData = await transactionsResponse.json();
                
                if (transactionsResponse.ok) {
                    renderTransactions(transactionsData.transactions);
                } else {
                    showError('Failed to load transactions');
                }
                
            } catch (error) {
                console.error('Error loading data:', error);
                showError('Network error - please check your connection');
            }
        }
        
        function updateFinancialDisplay(data) {
            // Update balance
            const balanceElement = document.getElementById('balanceAmount');
            balanceElement.textContent = `${data.balance >= 0 ? '+' : ''}${data.balance.toLocaleString()}₴`;
            balanceElement.style.color = data.balance >= 0 ? '#34c759' : '#ff3b30';
            
            // Update income and expenses
            document.getElementById('incomeAmount').textContent = `+${data.income.toLocaleString()}₴`;
            document.getElementById('expenseAmount').textContent = `-${data.spending.toLocaleString()}₴`;
        }
        
        function renderTransactions(transactions) {
            const container = document.getElementById('transactionsContainer');
            
            if (!transactions || transactions.length === 0) {
                container.innerHTML = '<div class="loading">No transactions yet</div>';
                return;
            }
            
            let transactionsHTML = '';
            
            transactions.forEach(transaction => {
                const amount = transaction.amount;
                const isPositive = amount >= 0;
                const amountDisplay = `${isPositive ? '+' : ''}${Math.abs(amount).toLocaleString()}₴`;
                
                transactionsHTML += `
                    <div class="transaction">
                        <div class="transaction-info">
                            <div class="transaction-emoji">${transaction.emoji}</div>
                            <div class="transaction-details">
                                <div class="transaction-title">${transaction.name}</div>
                                <div class="transaction-category">${transaction.category}</div>
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
        document.addEventListener('DOMContentLoaded', loadFinancialData);
        
        // Refresh data every 30 seconds
        setInterval(loadFinancialData, 30000);
    </script>
</body>
</html>
    """

# ========== TELEGRAM BOT SETUP ==========

@flask_app.route('/api/add-transaction', methods=['POST', 'GET'])
def add_transaction():
    if request.method == 'GET':
        return jsonify({"status": "active", "message": "Add transaction endpoint ready"})
    
    try:
        transaction_data = request.json
        print(f"📥 Received transaction: {transaction_data}")
        
        # Use the bot instance instead of JSON file
        user_id = transaction_data.get('user_id')
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400
        
        transaction = {
            'amount': transaction_data.get('amount', 0),
            'description': transaction_data.get('description', ''),
            'category': transaction_data.get('category', 'Other'),
            'type': transaction_data.get('type', 'expense'),
            'date': transaction_data.get('timestamp', datetime.now().isoformat())
        }
        
        # Use the bot's method to save transaction
        bot_instance.save_user_transaction(user_id, transaction)
        
        print("✅ Transaction added successfully via bot instance")
        return jsonify({'status': 'success', 'message': 'Transaction added'})
        
    except Exception as e:
        print(f"❌ Error adding transaction: {e}")
        return jsonify({'error': str(e)}), 500
    
@flask_app.route('/api/delete-transaction', methods=['POST'])
def delete_transaction(self, user_id, transaction_index):
    """Delete a transaction from both memory AND PostgreSQL"""
    
    # 1. Delete from memory
    if user_id in self.transactions and transaction_index < len(self.transactions[user_id]):
        deleted_transaction = self.transactions[user_id].pop(transaction_index)
        print(f"🗑️ Deleted transaction from memory: {deleted_transaction}")
    
    # 2. Delete from PostgreSQL
    conn = self.get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            # You need a way to identify the exact transaction in PostgreSQL
            # This might require adding transaction IDs or unique identifiers
            cur.execute('DELETE FROM transactions WHERE user_id = %s AND amount = %s AND description = %s', 
                       (user_id, deleted_transaction['amount'], deleted_transaction['description']))
            conn.commit()
            conn.close()
            print("🗑️ Deleted transaction from PostgreSQL")
        except Exception as e:
            print(f"❌ Error deleting from PostgreSQL: {e}")
    self.sync_transactions_to_postgres()

@flask_app.route('/api/add-income', methods=['POST']) 
def add_income():
    try:
        income_data = request.json
        
        # Read current incomes
        try:
            with open('incomes.json', 'r') as f:
                incomes = json.load(f)
        except:
            incomes = {}
        
        # Update income
        user_id = income_data.get('user_id')
        amount = income_data.get('amount')
        incomes[user_id] = amount
        
        # Save back to file
        with open('incomes.json', 'w') as f:
            json.dump(incomes, f)
        
        return jsonify({'status': 'success', 'message': 'Income updated'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Test route
@flask_app.route('/api/test')
def test_api():
    return jsonify({'message': 'API is working!', 'data': {'balance': 1000, 'income': 5000}})

# Set webhook on startup
def set_webhook():
    """Set Telegram webhook URL only if token is available"""
    if not BOT_TOKEN or BOT_TOKEN == "8326266095:AAFTk0c6lo5kOHbCfNCGTrN4qrmJQn5Q7OI":
        print("❌ Cannot set webhook - bot token not configured")
        return
    
    try:
        webhook_url = "https://finnbot-production.up.railway.app/webhook"
        response = requests.post(
            f"{BASE_URL}/setWebhook",
            json={"url": webhook_url}
        )
        if response.status_code == 200:
            print("✅ Webhook set successfully!")
        else:
            print(f"❌ Failed to set webhook: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error setting webhook: {e}")

def check_reminders_periodically():
    """Check every hour if it's time for reminders"""
    while True:
        try:
            now = datetime.now()
            current_hour = now.hour
            
            # Only check at 12:00 and 18:00
            if current_hour in [12, 18]:
                print(f"🕐 It's {current_hour}:00, checking reminders...")
                bot_instance.check_daily_reminders()
                
                # Sleep for 1 hour to avoid sending multiple times
                time.sleep(3600)
            else:
                # Sleep for 1 hour and check again
                time.sleep(3600)
                
        except Exception as e:
            print(f"❌ Reminder error: {e}")
            time.sleep(3600)

_bot_instance = None

def get_bot_instance():
    """Get or create the bot instance (singleton pattern)"""
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = SimpleFinnBot()
    return _bot_instance

def get_bot_instance():
    """Get or create the bot instance"""
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = SimpleFinnBot()
    return _bot_instance

def save_all_data():
    """Save all data before shutdown"""
    try:
        bot_instance = get_bot_instance()
        print(f"🔍 DEBUG PRE-SHUTDOWN: Current transactions in memory: {bot_instance.transactions}")
        print(f"🔍 DEBUG PRE-SHUTDOWN: Onboarding state: {bot_instance.onboarding_state}")
        
        # Check where transactions are coming from
        if bot_instance.transactions:
            for user_id, transactions in bot_instance.transactions.items():
                for transaction in transactions:
                    if 'Starting' in transaction.get('description', ''):
                        print(f"🚨🚨🚨 CRITICAL: Found initial transaction during shutdown: {transaction}")
        
        print("💾 Saving all data before shutdown...")
        bot_instance.sync_transactions_to_postgres()
        bot_instance.save_incomes()
        bot_instance.save_user_categories()
        bot_instance.save_user_languages()
        print("✅ All data saved successfully!")
    except Exception as e:
        print(f"❌ Error during shutdown save: {e}")

# Create the bot instance
bot_instance = get_bot_instance()

# Register shutdown handler
import atexit
atexit.register(save_all_data)

# Start reminder system
if not hasattr(bot_instance, 'reminder_started'):
    bot_instance.reminder_started = True
    reminder_thread = threading.Thread(target=check_reminders_periodically, daemon=True)
    reminder_thread.start()
    print("✅ Periodic reminder checker started")

# ========== APPLICATION STARTUP ==========

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ ERROR: BOT_TOKEN environment variable not set")
        print("⚠️  Running without Telegram bot features")
    else:
        print("✅ Bot token found - setting webhook")
        set_webhook()
    
    port = int(os.environ.get('PORT', 8080))
    print(f"🚀 Starting webhook server on port {port}...")
    flask_app.run(host='0.0.0.0', port=port, debug=False)