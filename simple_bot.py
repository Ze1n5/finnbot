import os
import json
import re
import requests
import time
from dotenv import load_dotenv
from datetime import datetime
import threading
import atexit
import signal
import psycopg2
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone



PERSISTENT_DIR = "/data" if os.path.exists("/data") else "."

def get_persistent_path(filename):
    return os.path.join(PERSISTENT_DIR, filename)

print(f"📁 Using persistent directory: {PERSISTENT_DIR}")

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

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
    
def init_categories_table():
    """Initialize categories table with default 'Other' category"""
    try:
        database_url = os.environ.get('DATABASE_URL')
        if not database_url:
            print("❌ No DATABASE_URL - skipping categories table init")
            return
            
        result = urlparse(database_url)
        conn = psycopg2.connect(
            database=result.path[1:],
            user=result.username,
            password=result.password,
            host=result.hostname,
            port=result.port
        )
        
        with conn.cursor() as cur:
            # Create categories table if it doesn't exist
            cur.execute("""
                CREATE TABLE IF NOT EXISTS categories (
                    id SERIAL PRIMARY KEY,
                    emoji VARCHAR(10) UNIQUE NOT NULL,
                    name VARCHAR(50) UNIQUE NOT NULL,
                    is_default BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Insert default "Other" category if it doesn't exist
            cur.execute("""
                INSERT INTO categories (emoji, name, is_default) 
                VALUES ('❓', 'Other', TRUE)
                ON CONFLICT (emoji) DO NOTHING
            """)
            
            conn.commit()
            conn.close()
            print("✅ Categories table initialized")
    except Exception as e:
        print(f"❌ Error initializing categories table: {e}")

# Call this when your app starts
init_categories_table()

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
    def calculate_financial_health(self, user_id):
        """Calculate financial health score (0-100) with emoji indicator"""
        user_transactions = self.get_user_transactions(user_id)
        
        if not user_transactions or len(user_transactions) < 3:  # Need some data
            return None  # Not enough data to calculate
        
        # Calculate basic metrics
        total_income = sum(t['amount'] for t in user_transactions if t['type'] == 'income')
        total_expenses = sum(t['amount'] for t in user_transactions if t['type'] == 'expense')
        total_savings = sum(t['amount'] for t in user_transactions if t['type'] == 'savings')
        total_debt = sum(abs(t['amount']) for t in user_transactions if t['type'] in ['debt', 'debt_return'])
        
        # Get monthly averages (assuming 30 days for calculation)
        income_dates = set()
        expense_dates = set()
        
        for transaction in user_transactions:
            if 'date' in transaction:
                try:
                    if 'T' in transaction['date']:
                        date_str = transaction['date'].split('T')[0]
                    else:
                        date_str = transaction['date'].split(' ')[0]
                    
                    if transaction['type'] == 'income':
                        income_dates.add(date_str)
                    elif transaction['type'] == 'expense':
                        expense_dates.add(date_str)
                except:
                    continue
        
        # Calculate component scores (0-100 each)
        
        # 1. Emergency Fund Score (40% weight)
        monthly_expenses = total_expenses / len(expense_dates) * 30 if expense_dates else total_expenses
        emergency_months = total_savings / monthly_expenses if monthly_expenses > 0 else 0
        emergency_score = min(emergency_months / 6 * 100, 100)  # 6 months ideal
        
        # 2. Savings Rate Score (30% weight)
        savings_rate = (total_savings / total_income * 100) if total_income > 0 else 0
        savings_score = min(savings_rate / 20 * 100, 100)  # 20% ideal
        
        # 3. Debt-to-Income Score (20% weight)
        debt_ratio = (total_debt / total_income * 100) if total_income > 0 else 0
        debt_score = max(100 - (debt_ratio / 0.3), 0) if debt_ratio > 0 else 100  # 30% is warning level
        
        # 4. 50/30/20 Score (10% weight)
        # Get current month's 50/30/20 status
        user_id_str = str(user_id)
        if user_id_str in self.monthly_percentages:
            percentages = self.monthly_percentages[user_id_str]
            needs_score = max(0, 100 - max(0, percentages.get('needs', 0) - 50) * 2)  # Penalty for over 50%
            future_score = min(percentages.get('future', 0) / 20 * 100, 100)  # Reward for reaching 20%
            rule_score = (needs_score + future_score) / 2
        else:
            rule_score = 50  # Neutral if no data
        
        # Calculate weighted final score
        final_score = (
            emergency_score * 0.40 +
            savings_score * 0.30 + 
            debt_score * 0.20 +
            rule_score * 0.10
        )
        
        # Ensure score is between 0-100
        final_score = max(0, min(100, final_score))
        
        return int(final_score)
    
    def handle_total_command(self, chat_id):
        """Handle /total command - show totals for SPENDING categories only"""
        print(f"🔍 Handling /total command for {chat_id}")
        
        user_transactions = self.get_user_transactions(chat_id)
        if not user_transactions:
            user_lang = self.get_user_language(chat_id)
            if user_lang == 'uk':
                self.send_message(chat_id, "📭 Немає транзакцій для відображення.", reply_markup=self.get_main_menu(chat_id))
            else:
                self.send_message(chat_id, "📭 No transactions to display.", reply_markup=self.get_main_menu(chat_id))
            return
        
        # Calculate totals for SPENDING CATEGORIES ONLY (expense transactions)
        category_totals = {}
        total_spending = 0
        
        for transaction in user_transactions:
            # Only process EXPENSE transactions
            if transaction['type'] == 'expense':
                category = transaction['category']
                amount = transaction['amount']
                
                if category not in category_totals:
                    category_totals[category] = 0
                category_totals[category] += amount
                total_spending += amount
        
        if not category_totals:
            user_lang = self.get_user_language(chat_id)
            if user_lang == 'uk':
                self.send_message(chat_id, "💸 Немає витрат для відображення.", reply_markup=self.get_main_menu(chat_id))
            else:
                self.send_message(chat_id, "💸 No spending transactions to display.", reply_markup=self.get_main_menu(chat_id))
            return
        
        # Sort categories by spending amount (descending)
        sorted_categories = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
        
        # Generate the message
        user_lang = self.get_user_language(chat_id)
        
        if user_lang == 'uk':
            total_text = "💸 *Загальні витрати по категоріях:*\n\n"
            
            for category, total in sorted_categories:
                total_text += f"• *{category}:* {total:,.0f}₴\n"
            
            # Add overall spending summary
            total_text += f"\n💰 *Загальні витрати:* {total_spending:,.0f}₴"
            
        else:
            total_text = "💸 *Total Spending by Category:*\n\n"
            
            for category, total in sorted_categories:
                total_text += f"• *{category}:* {total:,.0f}₴\n"
            
            # Add overall spending summary
            total_text += f"\n💰 *Total Spending:* {total_spending:,.0f}₴"
        
        self.send_message(chat_id, total_text, parse_mode='Markdown', reply_markup=self.get_main_menu(chat_id))

    def get_financial_health_display(self, score):
        """Get emoji and display text for financial health score"""
        if score is None:
            return "📊 Collecting data...", ""
        
        if score <= 20:
            emoji = "⛺️"
        elif score <= 40:
            emoji = "🛖" 
        elif score <= 60:
            emoji = "🏚"
        elif score <= 80:
            emoji = "🏠"
        else:
            emoji = "🏰"
        
        return emoji, f"{score}%"

    def handle_financial_summary(self, chat_id):
        """Handle Financial Summary button"""
        print(f"🔍 Handling Financial Summary for {chat_id}")
        
        # Calculate financial health ONCE at the beginning
        health_score = self.calculate_financial_health(chat_id)
        health_emoji, health_display = self.get_financial_health_display(health_score)
        
        user_transactions = self.get_user_transactions(chat_id)
        if not user_transactions:
            user_lang = self.get_user_language(chat_id)
            if user_lang == 'uk':
                self.send_message(chat_id, "📭 Немає транзакцій для відображення.", reply_markup=self.get_main_menu(chat_id))
            else:
                self.send_message(chat_id, "📭 No transactions to display.", reply_markup=self.get_main_menu(chat_id))
            return
        
        # Calculate basic totals
        income = 0
        expenses = 0
        savings_deposits = 0
        savings_withdrawn = 0
        debt_incurred = 0
        debt_returned = 0
        
        # Track dates for averages
        income_dates = set()
        expense_dates = set()
        all_dates = set()
        
        for transaction in user_transactions:
            # Extract date from transaction
            transaction_date = None
            if 'date' in transaction:
                try:
                    # Parse the date string to get just the date part
                    if 'T' in transaction['date']:
                        transaction_date = transaction['date'].split('T')[0]  # Get YYYY-MM-DD
                    else:
                        transaction_date = transaction['date'].split(' ')[0]  # Get YYYY-MM-DD
                except:
                    transaction_date = None
            
            if transaction_date:
                all_dates.add(transaction_date)
            
            if transaction['type'] == 'income':
                income += transaction['amount']
                if transaction_date:
                    income_dates.add(transaction_date)
            elif transaction['type'] == 'savings':
                savings_deposits += transaction['amount']
            elif transaction['type'] == 'debt':
                debt_incurred += abs(transaction['amount'])
            elif transaction['type'] == 'debt_return':
                debt_returned += abs(transaction['amount'])
            elif transaction['type'] == 'savings_withdraw':
                savings_withdrawn += transaction['amount']
            else:  # Regular expenses
                expenses += transaction['amount']
                if transaction_date:
                    expense_dates.add(transaction_date)
        
        net_savings = savings_deposits - savings_withdrawn
        net_debt = debt_incurred - debt_returned
        net_flow = income - expenses - net_savings
        
        # Calculate averages based on last 30 days
        current_date = datetime.now().date()
        thirty_days_ago = current_date - timedelta(days=30)

        # Filter transactions from last 30 days
        recent_income = 0
        recent_expenses = 0
        all_recent_days = set()

        print(f"🔍 DEBUG: Filtering transactions from {thirty_days_ago} to {current_date}")

        for transaction in user_transactions:
            if 'date' in transaction:
                try:
                    # Parse transaction date
                    transaction_date = None
                    if 'T' in transaction['date']:
                        transaction_date_str = transaction['date'].split('T')[0]
                        transaction_date = datetime.strptime(transaction_date_str, '%Y-%m-%d').date()
                    else:
                        # Try different date formats
                        transaction_date_str = transaction['date'].split(' ')[0]
                        transaction_date = datetime.strptime(transaction_date_str, '%Y-%m-%d').date()
                    
                    # Only include transactions from last 30 days
                    if transaction_date >= thirty_days_ago:
                        all_recent_days.add(transaction_date)
                        
                        if transaction['type'] == 'income':
                            recent_income += transaction['amount']
                            print(f"🔍 DEBUG: Added income {transaction['amount']} from {transaction_date}")
                        elif transaction['type'] == 'expense':
                            recent_expenses += transaction['amount']
                            print(f"🔍 DEBUG: Added expense {transaction['amount']} from {transaction_date}")
                            
                except Exception as e:
                    print(f"⚠️ Error parsing transaction date '{transaction.get('date')}': {e}")
                    continue

        print(f"🔍 DEBUG FINAL TOTALS:")
        print(f"   Recent income total: {recent_income:,.0f}₴")
        print(f"   Recent expenses total: {recent_expenses:,.0f}₴")
        print(f"   Unique days with activity: {len(all_recent_days)}")

        # Calculate daily averages for last 30 days
        daily_income_avg = recent_income / 30
        daily_expense_avg = recent_expenses / 30
        daily_net_avg = (recent_income - recent_expenses) / 30

        print(f"🔍 DEBUG DAILY AVERAGES:")
        print(f"   Daily income avg: {daily_income_avg:,.0f}₴")
        print(f"   Daily expense avg: {daily_expense_avg:,.0f}₴")
        
        user_lang = self.get_user_language(chat_id)
        
        # CREATE SUMMARY TEXT ONLY ONCE with all sections
        if user_lang == 'uk':
            summary_text = f"""📊 *Фінансовий звіт*

💎 *Фінансове здоров'я:* {health_emoji} {health_display}

💸 *Аналіз готівкового потоку:*
Дохід: {income:,.0f}₴
Витрати: {expenses:,.0f}₴
Заощадження: {net_savings:,.0f}₴
─────────────────
Чистий потік: {net_flow:,.0f}₴

📈 *Щоденні середні показники (за останні 30 днів):*
Середній дохід/день: {daily_income_avg:,.0f}₴
Cередні витрати/день: {daily_expense_avg:,.0f}₴
Середній чистий потік/день: {daily_net_avg:,.0f}₴

🏦 *Заощадження:*
Внесено: {savings_deposits:,.0f}₴
Чисті заощадження: {net_savings:,.0f}₴"""
            
            if debt_incurred > 0 or debt_returned > 0:
                summary_text += f"\n\n💳 *Борги:*\n   Заборгованість: {debt_incurred:,.0f}₴"
                if debt_returned > 0:
                    summary_text += f"\n   Повернено: {debt_returned:,.0f}₴"
                summary_text += f"\n   Чистий борг: {net_debt:,.0f}₴"
            
            # Add context about tracking period
            recent_days_count = len(all_recent_days)
            if recent_days_count > 0:
                summary_text += f"\n\n📅 *Активність за останні 30 днів:* {recent_days_count} днів"
            
        else:
            summary_text = f"""📊 *Financial Summary*

💎 *Financial Health:* {health_emoji} {health_display}

💸 *Cash Flow Analysis:*
Income: {income:,.0f}₴
Expenses: {expenses:,.0f}₴
Savings: {net_savings:,.0f}₴
────────────────────
Net Cash Flow: {net_flow:,.0f}₴

📈 *Daily Averages (Last 30 Days):*
Avg Income/Day: {daily_income_avg:,.0f}₴
Avg Expenses/Day: {daily_expense_avg:,.0f}₴
Avg Net Flow/Day: {daily_net_avg:,.0f}₴

🏦 *Savings Account:*
Deposited: {savings_deposits:,.0f}₴
Net Savings: {net_savings:,.0f}₴"""
            
            if debt_incurred > 0 or debt_returned > 0:
                summary_text += f"\n\n💳 *Debt Account:*\n   Incurred: {debt_incurred:,.0f}₴"
                if debt_returned > 0:
                    summary_text += f"\n   Returned: {debt_returned:,.0f}₴"
                summary_text += f"\n   Net Debt: {net_debt:,.0f}₴"
            
            # Add context about tracking period
            recent_days_count = len(all_recent_days)
            if recent_days_count > 0:
                summary_text += f"\n\n📅 *Activity in last 30 days:* {recent_days_count} days"
        
        self.send_message(chat_id, summary_text, parse_mode='Markdown', reply_markup=self.get_main_menu(chat_id))

    def handle_503020_status(self, chat_id):
        """Handle 50/30/20 Status button"""
        print(f"🔍 Handling 50/30/20 Status for {chat_id}")
        
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
        
        # COPY YOUR EXISTING 50/30/20 LOGIC HERE
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
        
        self.send_message(chat_id, summary, parse_mode='Markdown', reply_markup=self.get_main_menu(chat_id))
    
    def parse_transaction_date(self, date_string):
        """Parse transaction date for sorting"""
        if not date_string:
            return datetime.min  # Very old date for missing dates
        
        try:
            # Extract just the date part (YYYY-MM-DD) for comparison
            if 'T' in date_string:
                date_part = date_string.split('T')[0]
            else:
                date_part = date_string.split(' ')[0]
            
            # Parse as naive datetime (no timezone)
            return datetime.strptime(date_part, '%Y-%m-%d')
        except Exception as e:
            print(f"❌ Error parsing date '{date_string}': {e}")
            return datetime.min

    def format_transaction_date(self, transaction, chat_id):
        """Format transaction date for display - FORCE UTC+2"""
        user_lang = self.get_user_language(chat_id)
        
        transaction_date = transaction.get('date')
        if not transaction_date:
            return "???" if user_lang == 'uk' else "???"
        
        try:
            # Parse the date string
            if 'T' in transaction_date:
                # Extract the datetime parts manually
                date_part, time_part = transaction_date.split('T')
                time_part = time_part.split('+')[0].split('.')[0]  # Remove timezone and milliseconds
                
                # Parse as naive datetime
                dt_naive = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M:%S")
                
                # Add 2 hours for Ukraine time (UTC+2)
                dt_local = dt_naive + timedelta(hours=2)
            else:
                # Simple date format
                dt_local = datetime.strptime(transaction_date.split(' ')[0], '%Y-%m-%d')
            
            # Format based on user language
            if user_lang == 'uk':
                return dt_local.strftime("%d.%m.%Y %H:%M")
            else:
                return dt_local.strftime("%m/%d/%Y %H:%M")
                
        except Exception as e:
            print(f"❌ Error formatting date '{transaction_date}': {e}")
            return "???" if user_lang == 'uk' else "???"

    def format_brief_date(self, transaction, chat_id):
        """Format date in brief format"""
        user_lang = self.get_user_language(chat_id)
        
        transaction_date = transaction.get('date')
        if not transaction_date:
            return "???" if user_lang == 'uk' else "???"
        
        try:
            if 'T' in transaction_date:
                if '.' in transaction_date:
                    dt = datetime.fromisoformat(transaction_date.replace('Z', '+00:00'))
                else:
                    dt = datetime.fromisoformat(transaction_date.replace('Z', '+00:00').split('+')[0])
            else:
                dt = datetime.strptime(transaction_date.split(' ')[0], '%Y-%m-%d')
            
            # Brief format: DD.MM HH:MM
            if user_lang == 'uk':
                return dt.strftime("%d.%m %H:%M")
            else:
                return dt.strftime("%m/%d %H:%M")
                
        except Exception:
            return "???" if user_lang == 'uk' else "???"

    def create_simplified_delete_list(self, chat_id, transaction_map):
        """Create simplified list when too many transactions"""
        user_lang = self.get_user_language(chat_id)
        user_transactions = self.get_user_transactions(chat_id)
        
        # Sort transactions by date (newest first) for simplified list too
        try:
            sorted_transactions = sorted(
                user_transactions, 
                key=lambda x: self.parse_transaction_date(x.get('date', '')), 
                reverse=True
            )
        except Exception as e:
            print(f"❌ Error sorting in simplified list: {e}")
            sorted_transactions = user_transactions
        
        if user_lang == 'uk':
            delete_text = "🗑️ *Список транзакцій*\n\n"
            delete_text += "⏹️  `0` - Скасувати\n\n"
        else:
            delete_text = "🗑️ *Transaction List*\n\n"
            delete_text += "⏹️  `0` - Cancel\n\n"
        
        current_number = 1
        new_transaction_map = {}
        
        for transaction in sorted_transactions:
            if current_number > 50:  # Limit to 50 transactions in simplified view
                break
                
            original_index = user_transactions.index(transaction)
            
            # Get amount with symbol
            trans_type = transaction['type']
            if trans_type == 'income':
                amount_display = f"+{transaction['amount']:,.0f}₴"
            elif trans_type == 'savings':
                amount_display = f"++{transaction['amount']:,.0f}₴"
            elif trans_type == 'debt':
                amount_display = f"-{transaction['amount']:,.0f}₴"
            elif trans_type == 'debt_return':
                amount_display = f"+-{transaction['amount']:,.0f}₴"
            elif trans_type == 'savings_withdraw':
                amount_display = f"-+{transaction['amount']:,.0f}₴"
            else:
                amount_display = f"-{transaction['amount']:,.0f}₴"
            
            # Brief date
            date_display = self.format_brief_date(transaction, chat_id)
            
            # Truncate description
            description = transaction['description']
            if len(description) > 20:
                description = description[:17] + "..."
            
            delete_text += f"`{current_number:2d}.` {transaction['category']}: {description}\n"
            delete_text += f"    {amount_display}  {date_display}\n\n"
            
            new_transaction_map[current_number] = original_index
            current_number += 1
        
        # Update the transaction map for this simplified view
        self.delete_mode[chat_id] = new_transaction_map
        
        if user_lang == 'uk':
            delete_text += "💡 *Введіть номер для видалення*"
        else:
            delete_text += "💡 *Type a number to delete*"
        
        return delete_text
        
    def create_simplified_delete_list(self, chat_id, transaction_map):
        """Create simplified list when too many transactions"""
        user_lang = self.get_user_language(chat_id)
        user_transactions = self.get_user_transactions(chat_id)
        
        # Sort transactions by date (newest first) for simplified list too
        sorted_transactions = sorted(
            user_transactions, 
            key=lambda x: self.parse_transaction_date(x.get('date', '')), 
            reverse=True
        )
        
        if user_lang == 'uk':
            delete_text = "🗑️ *Список транзакцій*\n\n"
            delete_text += "⏹️  `0` - Скасувати\n\n"
        else:
            delete_text = "🗑️ *Transaction List*\n\n"
            delete_text += "⏹️  `0` - Cancel\n\n"
        
        current_number = 1
        new_transaction_map = {}
        
        for transaction in sorted_transactions:
            if current_number > 50:  # Limit to 50 transactions in simplified view
                break
                
            original_index = user_transactions.index(transaction)
            
            # Get amount with symbol
            trans_type = transaction['type']
            if trans_type == 'income':
                amount_display = f"+{transaction['amount']:,.0f}₴"
            elif trans_type == 'savings':
                amount_display = f"++{transaction['amount']:,.0f}₴"
            elif trans_type == 'debt':
                amount_display = f"-{transaction['amount']:,.0f}₴"
            elif trans_type == 'debt_return':
                amount_display = f"+-{transaction['amount']:,.0f}₴"
            elif trans_type == 'savings_withdraw':
                amount_display = f"-+{transaction['amount']:,.0f}₴"
            else:
                amount_display = f"-{transaction['amount']:,.0f}₴"
            
            # Brief date
            date_display = self.format_brief_date(transaction, chat_id)
            
            # Truncate description
            description = transaction['description']
            if len(description) > 20:
                description = description[:17] + "..."
            
            delete_text += f"`{current_number:2d}.` {transaction['category']}: {description}\n"
            delete_text += f"    {amount_display}  {date_display}\n\n"
            
            new_transaction_map[current_number] = original_index
            current_number += 1
        
        # Update the transaction map for this simplified view
        self.delete_mode[chat_id] = new_transaction_map
        
        if user_lang == 'uk':
            delete_text += "💡 *Введіть номер для видалення*"
        else:
            delete_text += "💡 *Type a number to delete*"
        
        return delete_text

    def handle_delete_transaction(self, chat_id):
        """Handle Delete Transaction button"""
        print(f"🔍 Handling Delete Transaction for {chat_id}")
        
        user_transactions = self.get_user_transactions(chat_id)
        if not user_transactions:
            user_lang = self.get_user_language(chat_id)
            if user_lang == 'uk':
                self.send_message(chat_id, "📭 Немає транзакцій для видалення.", reply_markup=self.get_main_menu(chat_id))
            else:
                self.send_message(chat_id, "📭 No transactions to delete.", reply_markup=self.get_main_menu(chat_id))
            return
        
        # Sort transactions by date (newest first) with error handling
        try:
            sorted_transactions = sorted(
                user_transactions, 
                key=lambda x: self.parse_transaction_date(x.get('date', '')), 
                reverse=True  # Newest first
            )
            print(f"🔍 DEBUG: Successfully sorted {len(sorted_transactions)} transactions")
        except Exception as e:
            print(f"❌ Error sorting transactions: {e}. Using original order.")
            sorted_transactions = user_transactions  # Fallback to original order
        
        delete_text = "🗑️ *Select Transaction to Delete*\n\n"
        delete_text += "⏹️  `0` - Cancel & Exit\n\n"
        
        current_number = 1
        transaction_map = {}  # Map display numbers to actual indices in ORIGINAL list
        
        # Show all transactions in simple list format (newest first)
        for i, transaction in enumerate(sorted_transactions):
            # Find the original index of this transaction
            original_index = user_transactions.index(transaction)
            
            # Get transaction symbol and amount
            trans_type = transaction['type']
            if trans_type == 'income':
                amount_display = f"+{transaction['amount']:,.0f}₴"
            elif trans_type == 'savings':
                amount_display = f"++{transaction['amount']:,.0f}₴"
            elif trans_type == 'debt':
                amount_display = f"-{transaction['amount']:,.0f}₴"
            elif trans_type == 'debt_return':
                amount_display = f"+-{transaction['amount']:,.0f}₴"
            elif trans_type == 'savings_withdraw':
                amount_display = f"-+{transaction['amount']:,.0f}₴"
            else:  # expense
                amount_display = f"-{transaction['amount']:,.0f}₴"
            
            # Get date and time
            date_display = self.format_transaction_date(transaction, chat_id)
            
            # Truncate description if too long
            description = transaction['description']
            if len(description) > 30:
                description = description[:27] + "..."
            
            # Simple format: Number. Category: Description
            #              Amount Date Time
            delete_text += f"`{current_number:2d}.` {transaction['category']}: {description}\n"
            delete_text += f"    {amount_display}  {date_display}\n\n"
            
            # Map display number to ORIGINAL index in user_transactions
            transaction_map[current_number] = original_index
            current_number += 1
        
        delete_text += "💡 *Type a number to delete, or 0 to cancel*"
        
        # Store the mapping for this user
        self.delete_mode[chat_id] = transaction_map
        
        # Split long messages if needed
        if len(delete_text) > 4000:
            delete_text = self.create_simplified_delete_list(chat_id, transaction_map)
        
        self.send_message(chat_id, delete_text, parse_mode='Markdown')

    def handle_manage_categories(self, chat_id):
        """Handle Manage Categories button"""
        print(f"🔍 Handling Manage Categories for {chat_id}")
        
        # Use your existing categories management logic
        category_names = self.get_user_categories(chat_id)
        user_lang = self.get_user_language(chat_id)
        
        if user_lang == 'uk':
            categories_text = "🏷️ *Ваші категорії*\n\n"
            categories_text += "*🔒 Фіксовані категорії:*\n"
            categories_text += "• Зарплата • Бізнес • Кріпто • Банк • Особисте • Інвестиції\n\n"
            categories_text += "*💼 Ваші кастомні категорії:*\n"
            
            fixed_categories = ["Зарплата", "Бізнес", "Кріпто", "Банк", "Особисте", "Інвестиції", "Other"]
            has_custom_categories = False
            
            for category_name in category_names:
                if category_name not in fixed_categories:
                    categories_text += f"• *{category_name}*\n"
                    has_custom_categories = True
            
            if not has_custom_categories:
                categories_text += "📝 Поки що немає кастомних категорій\n"
            
            categories_text += "\n*Швидкі команди:*\n"
            categories_text += "• `+Їжа` - Додати нову категорію\n"
            categories_text += "• `-Їжа` - Видалити категорію\n"
            categories_text += "• Фіксовані категорії не можна змінити"
        else:
            categories_text = "🏷️ *Your Categories*\n\n"
            categories_text += "*🔒 Fixed Categories:*\n"
            categories_text += "• Salary • Business • Crypto • Bank • Personal • Investment\n\n"
            categories_text += "*💼 Your Custom Categories:*\n"
            
            fixed_categories = ["Salary", "Business", "Crypto", "Bank", "Personal", "Investment", "Other"]
            has_custom_categories = False
            
            for category_name in category_names:
                if category_name not in fixed_categories:
                    categories_text += f"• *{category_name}*\n"
                    has_custom_categories = True
            
            if not has_custom_categories:
                categories_text += "📝 No custom categories yet\n"
            
            categories_text += "\n*Quick Commands:*\n"
            categories_text += "• `+Food` - Add new category\n"
            categories_text += "• `-Food` - Remove category\n"
            categories_text += "• Fixed categories cannot be modified"
        
        self.send_message(chat_id, categories_text, parse_mode='Markdown', reply_markup=self.get_main_menu(chat_id))

    def handle_restart_bot(self, chat_id):
        """Handle Restart Bot button"""
        print(f"🔍 Handling Restart Bot for {chat_id}")
        
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

    def handle_language_selection(self, chat_id):
        """Handle Language button"""
        print(f"🔍 Handling Language Selection for {chat_id}")
        
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

    def send_transaction_guide(self, chat_id):
        """Send visual transaction guide to user"""
        user_lang = self.get_user_language(chat_id)
            
        if user_lang == 'uk':
            guide_text = """🎯 *Фінансовий командний центр*

        🛒 `150 обід` - Щоденні витрати
        💰 `+5000 зарплата` - Дохід  
        🏦 `++1000` - Зберегти гроші
        💳 `-2000 кредит` - Новий борг
        🔙 `+-1500` - Повернути борг
        📥 `-+800` - Зняти заощадження

        🧮 `100+50=150` - Розрахунки працюють!
        📝 Додавайте описи: `150 uber до аеропорту`

        🚀 *Ваша фінансова подорож починається зараз!*"""
        else:
            guide_text = """🎯 *Financial Command Center*

        🛒 `150 lunch` - Daily expenses
        💰 `+5000 salary` - Income  
        🏦 `++1000` - Save money
        💳 `-2000 loan` - New debt
        🔙 `+-1500` - Return debt
        📥 `-+800` - Withdraw savings

        🧮 `100+50=150` - Calculations work!
        📝 Add descriptions: `150 uber to airport`

        🚀 *Your financial journey starts now!*"""
            
        self.send_message(chat_id, guide_text, parse_mode='Markdown')

    def save_user_languages(self):
        """Save user languages - placeholder for now"""
        print("💾 User languages would be saved here")
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
        
    def is_message_for_bot(self, text, msg):
        """Check if message is directed at the bot in groups"""
        if not text:
            return False
        
        print(f"🔍 DEBUG is_message_for_bot: text='{text}'")
        
        # Always process commands (they start with /)
        if text.startswith('/'):
            print(f"🔍 DEBUG: Processing command: {text}")
            return True
        
        # Get bot username
        bot_username = self.get_bot_username()
        print(f"🔍 DEBUG: Bot username: {bot_username}")
        
        # Check for bot mention
        if bot_username and f"@{bot_username}" in text:
            print(f"🔍 DEBUG: Processing bot mention")
            return True
        
        # Check for transaction patterns (++, +-, -+, +, -)
        transaction_patterns = ['++', '+-', '-+', '+', '-']
        if any(pattern in text for pattern in transaction_patterns):
            print(f"🔍 DEBUG: Processing transaction pattern")
            return True
        
        # Check if it's a simple number (like "300" - expense)
        if text.strip().replace('.', '').replace(',', '').isdigit():
            print(f"🔍 DEBUG: Processing simple number (expense)")
            return True
        
        # Check if it's a number with description (like "150 lunch")
        words = text.split()
        if len(words) >= 1:
            # Check if first word is a number
            first_word = words[0].replace('.', '').replace(',', '')
            if first_word.isdigit():
                print(f"🔍 DEBUG: Processing number with description")
                return True
        
        print(f"🔍 DEBUG: Ignoring message not for bot")
        return False

    def get_bot_username(self):
        """Get bot username"""
        try:
            response = requests.get(f"{BASE_URL}/getMe")
            if response.status_code == 200:
                username = response.json()["result"]["username"]
                print(f"🔍 DEBUG: Found bot username: {username}")
                return username
            else:
                print(f"❌ Error getting bot info: {response.status_code}")
        except Exception as e:
            print(f"❌ Error getting bot username: {e}")
        return None

    def clean_bot_mention(self, text):
        """Remove bot mention from text"""
        bot_username = self.get_bot_username()
        if bot_username:
            # Remove @mention
            original_text = text
            text = text.replace(f"@{bot_username}", "").strip()
            # Remove leading/trailing whitespace and colons
            text = re.sub(r'^[\s:]+|[\s:]+$', '', text)
            print(f"🔍 DEBUG clean_bot_mention: '{original_text}' -> '{text}'")
        return text

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
        """Calculate mathematical expressions with percentages and currency"""
        try:
            # Check for currency symbols
            has_usd = '$' in text
            has_eur = '€' in text or 'eur' in text.lower()
            
            # Default to UAH if no currency specified
            currency = 'UAH'
            if has_usd:
                currency = 'USD'
            elif has_eur:
                currency = 'EUR'
            
            # Remove currency symbols for calculation
            expression_text = text.replace('$', '').replace('€', '').replace('₴', '')
            expression_text = re.sub(r'\b(uah|eur|usd)\b', '', expression_text, flags=re.IGNORECASE).strip()
            
            # Remove spaces and convert to lowercase
            expression = expression_text.replace(' ', '').lower()
            
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
            
            return amount, trans_type, symbol, currency  # Return currency as well
            
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

    def add_user_category(self, user_id, category_name):
        """Add category - WORKING VERSION"""
        try:
            print(f"🔍 Adding category: '{category_name}' for ID: {user_id}")
            
            conn = self.get_db_connection()
            if not conn:
                return False, "No database connection"
            
            cur = conn.cursor()
            
            # Handle user_id based on type
            if user_id < 0:  # Group
                import hashlib
                user_id_safe = hashlib.md5(f"group_{user_id}".encode()).hexdigest()[:20]
            else:  # User
                user_id_safe = str(user_id)
            
            print(f"🔍 Using safe ID: {user_id_safe}")
            
            # Check if category already exists
            cur.execute(
                "SELECT name FROM categories WHERE user_id = %s AND name = %s",
                (user_id_safe, category_name)
            )
            if cur.fetchone():
                conn.close()
                return False, f"Category '{category_name}' already exists"
            
            # **CORRECT INSERT** - only use existing columns
            cur.execute(
                "INSERT INTO categories (name, user_id) VALUES (%s, %s)",
                (category_name, user_id_safe)
            )
            
            conn.commit()
            conn.close()
            
            print(f"✅ Category '{category_name}' added successfully")
            return True, f"Category '{category_name}' added successfully"
            
        except Exception as e:
            print(f"❌ Error: {e}")
            return False, f"Failed to add category: {str(e)}"
        
    def add_group_category_safe(self, group_id, category_name):
        """Safe method for groups"""
        try:
            conn = self.get_db_connection()
            if not conn:
                return False, "No database connection"
            
            cur = conn.cursor()
            
            # Create a UNIQUE identifier
            import hashlib
            unique_identifier = hashlib.md5(f"group_{group_id}".encode()).hexdigest()[:20]
            
            print(f"🔍 Group category - Using safe ID: {unique_identifier}")
            
            # Check if category already exists
            cur.execute(
                "SELECT name FROM categories WHERE user_id = %s AND name = %s",
                (unique_identifier, category_name)
            )
            if cur.fetchone():
                conn.close()
                return False, f"Category '{category_name}' already exists"
            
            # Insert with emoji to satisfy NOT NULL constraint
            cur.execute(
                "INSERT INTO categories (emoji, name, user_id) VALUES (%s, %s, %s)",
                ("📝", category_name, unique_identifier)  # Provide emoji!
            )
            
            conn.commit()
            conn.close()
            
            print(f"✅ Group category '{category_name}' added successfully")
            return True, f"Category '{category_name}' added successfully"
            
        except Exception as e:
            print(f"❌ Group category error: {e}")
            return False, f"Failed to add category: {str(e)}"

    def add_regular_category_safe(self, user_id, category_name):
        """Safe method for regular users"""
        try:
            conn = self.get_db_connection()
            if not conn:
                return False, "No database connection"
            
            cur = conn.cursor()
            
            user_id_str = str(user_id)
            
            print(f"🔍 User category - Using ID: {user_id_str}")
            
            cur.execute(
                "SELECT name FROM categories WHERE user_id = %s AND name = %s",
                (user_id_str, category_name)
            )
            if cur.fetchone():
                conn.close()
                return False, f"Category '{category_name}' already exists"
            
            # Insert with emoji to satisfy NOT NULL constraint
            cur.execute(
                "INSERT INTO categories (emoji, name, user_id) VALUES (%s, %s, %s)",
                ("📝", category_name, user_id_str)  # Provide emoji!
            )
            
            conn.commit()
            conn.close()
            
            return True, f"Category '{category_name}' added successfully"
            
        except Exception as e:
            print(f"❌ User category error: {e}")
            return False, f"Failed to add category: {str(e)}"

    def get_user_categories(self, user_id):
        """Get categories for user/group - ROBUST VERSION"""
        try:
            conn = self.get_db_connection()
            if not conn:
                print("❌ No database connection in get_user_categories")
                return ["Other"]  # Fallback
            
            cur = conn.cursor()
            
            # Handle user_id based on type
            if user_id < 0:  # Group
                import hashlib
                user_id_safe = hashlib.md5(f"group_{user_id}".encode()).hexdigest()[:20]
            else:  # User
                user_id_safe = str(user_id)
            
            # Get categories for this user/group + shared categories (user_id IS NULL)
            cur.execute("""
                SELECT name FROM categories 
                WHERE user_id = %s OR user_id IS NULL 
                ORDER BY name
            """, (user_id_safe,))
            
            categories_data = cur.fetchall()
            conn.close()
            
            category_names = [cat[0] for cat in categories_data]
            print(f"📊 Loaded {len(category_names)} categories for user {user_id}")
            return category_names
            
        except Exception as e:
            print(f"❌ Error fetching categories for user {user_id}: {e}")
            # Return basic categories as fallback
            return ["Salary", "Business", "Crypto", "Bank", "Personal", "Investment", "Other"]
        
    def remove_user_category(self, user_id, category_name):
        """Remove a custom category - PROTECTS SAVINGS CATEGORIES"""
        try:
            conn = self.get_db_connection()
            if not conn:
                return False, "No database connection"
            
            cur = conn.cursor()
            
            # Check if it's a protected category (both spending and savings)
            protected_categories = [
                # Spending categories
                "Salary", "Business", "Other",
                # Savings categories  
                "Crypto", "Bank", "Personal", "Investment"
            ]
            
            if category_name in protected_categories:
                conn.close()
                return False, f"'{category_name}' is a protected category and cannot be removed"
            
            # Handle user_id based on type
            if user_id < 0:  # Group
                import hashlib
                user_id_safe = hashlib.md5(f"group_{user_id}".encode()).hexdigest()[:20]
            else:  # User
                user_id_safe = str(user_id)
            
            cur.execute(
                "DELETE FROM categories WHERE user_id = %s AND name = %s",
                (user_id_safe, category_name)
            )
            
            if cur.rowcount == 0:
                conn.close()
                return False, f"Category '{category_name}' not found"
            
            conn.commit()
            conn.close()
            
            return True, f"Category '{category_name}' removed successfully"
                
        except Exception as e:
            print(f"❌ Error removing category: {e}")
            return False, f"Error: {str(e)}"
        
    def show_custom_keyboard(self, chat_id, message=None):
        """Explicitly show the custom keyboard"""
        user_lang = self.get_user_language(chat_id)
        
        if not message:
            if user_lang == 'uk':
                message = "⌨️ Використовуйте меню:"
            else:
                message = "⌨️ Use the menu:"
        
        return self.send_message(chat_id, message, reply_markup=self.get_main_menu(chat_id))
        
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
        
        # Check if this is a group (negative chat ID)
        is_group = user_id and user_id < 0
        
        menu_config = {
            "keyboard": keyboard,
            "resize_keyboard": True,
            "one_time_keyboard": False,
            "selective": is_group
        }
        
        print(f"🔍 DEBUG MENU: User ID: {user_id}, Is group: {is_group}, Selective: {is_group}")
        return menu_config
    
    def show_menu_keyboard(self, chat_id, message_text=None):
        """Explicitly show the menu keyboard in groups"""
        user_lang = self.get_user_language(chat_id)
        
        if not message_text:
            if user_lang == 'uk':
                message_text = "🏠 Головне меню:"
            else:
                message_text = "🏠 Main menu:"
        
        print(f"🔍 DEBUG SHOW_MENU: Showing menu for chat {chat_id}")
        return self.send_message(chat_id, message_text, reply_markup=self.get_main_menu(chat_id))

    def send_menu_to_chat(self, chat_id, text, parse_mode=None):
        """Send menu to chat, handling both private and group chats"""
        try:
            # Get chat info to determine type
            chat_info = requests.post(f"{BASE_URL}/getChat", json={"chat_id": chat_id}).json()
            chat_type = chat_info.get("result", {}).get("type", "private")
            
            if chat_type == "private":
                # Private chat - send normal menu
                return self.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=self.get_main_menu(chat_id))
            else:
                # Group chat - send message with selective keyboard
                menu = self.get_main_menu()
                menu["selective"] = True  # Show menu only to the user who triggered it
                return self.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=menu)
                
        except Exception as e:
            print(f"⚠️ Error sending menu: {e}")
            # Fallback - send without menu
            return self.send_message(chat_id, text, parse_mode=parse_mode)
    
    def extract_amount(self, text):
        # Clean the text first
        clean_text = text.strip()
        print(f"🔍 DEBUG extract_amount: text='{clean_text}'")
        
        # Check for currency symbols
        has_usd = '$' in clean_text
        has_eur = '€' in clean_text or 'eur' in clean_text.lower()
        has_uah = '₴' in clean_text or 'uah' in clean_text.lower()
        
        # Default to UAH if no currency specified
        currency = 'UAH'
        if has_usd:
            currency = 'USD'
        elif has_eur:
            currency = 'EUR'
        
        print(f"🔍 DEBUG: Currency detected: {currency}")
        
        # Remove currency symbols for amount parsing
        clean_text_for_parsing = clean_text.replace('$', '').replace('€', '').replace('₴', '')
        clean_text_for_parsing = re.sub(r'\b(uah|eur|usd)\b', '', clean_text_for_parsing, flags=re.IGNORECASE).strip()
        
        # Check transaction types in priority order
        is_savings = '++' in clean_text_for_parsing
        is_debt_return = '+-' in clean_text_for_parsing
        is_savings_withdraw = '-+' in clean_text_for_parsing
        is_income = '+' in clean_text_for_parsing and not any(x in clean_text_for_parsing for x in ['++', '+-', '-+'])
        is_debt = clean_text_for_parsing.startswith('-') and not is_savings_withdraw
        
        print(f"   Transaction type detection:")
        print(f"   - is_savings: {is_savings}")
        print(f"   - is_income: {is_income}")
        print(f"   - is_debt: {is_debt}")
        print(f"   - is_debt_return: {is_debt_return}")
        print(f"   - is_savings_withdraw: {is_savings_withdraw}")
        print(f"   - currency: {currency}")
        
        # Extract amount using regex that handles various formats
        amount_pattern = r'[+-]*\s*(\d+(?:[.,]\d{1,2})?)'
        amounts = re.findall(amount_pattern, clean_text_for_parsing)
        
        if amounts:
            # Get the first valid amount found
            for amt_str in amounts:
                try:
                    # Clean the amount string
                    clean_amt = amt_str.replace(',', '.').strip()
                    amount = float(clean_amt)
                    print(f"   ✅ Extracted amount: {amount} {currency}")
                    return amount, is_income, is_debt, is_savings, is_debt_return, is_savings_withdraw, currency
                except ValueError:
                    continue
        
        print(f"   ❌ No valid amount found")
        return None, is_income, is_debt, is_savings, is_debt_return, is_savings_withdraw, currency

    def guess_category(self, text, user_id):
        """Guess spending category for a specific user"""
        text_lower = text.lower()
        
        # Check learned patterns first (these are already user-specific)
        user_patterns = self.learned_patterns.get(user_id, {})
        for pattern, category in user_patterns.items():
            if pattern in text_lower:
                return category
        
        # Use user-specific spending categories
        category_names = self.get_user_categories(user_id)
        
        # Guess expense category
        for category_name in category_names:
            if category_name == "Other":
                continue
            if category_name.lower() in text_lower:
                return category_name
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
        chat_type = msg["chat"].get("type", "private")
        
        print(f"📨 Processing message from {chat_id} ({chat_type}): '{text}'")

        if "new_chat_members" in msg:
            for member in msg["new_chat_members"]:
                bot_username = self.get_bot_username()
                if member.get("is_bot", False) and member.get("username") == bot_username:
                    # Bot was added to group - show welcome with keyboard
                    user_lang = self.get_user_language(chat_id)
                    if user_lang == 'uk':
                        welcome = "🤖 ФіннБот додано до групи! Використовуйте меню нижче:"
                    else:
                        welcome = "🤖 FinnBot added to group! Use the menu below:"
                    
                    self.show_menu_keyboard(chat_id, welcome)
                    return  # Stop processing after handling bot addition

        # Handle group messages
        # Handle group messages
        if chat_type in ["group", "supergroup"]:
            print(f"🔍 DEBUG GROUP: Checking if message is for bot")
            
            # Check if message is directed at the bot
            if not self.is_message_for_bot(text, msg):
                print(f"🔍 DEBUG GROUP: Ignoring group message not directed at bot")
                return
            
            # Remove bot mention from text for processing
            original_text = text
            text = self.clean_bot_mention(text)
            print(f"🔍 DEBUG GROUP: Processing group message. Original: '{original_text}', Cleaned: '{text}'")
            
            # SHOW THE MENU KEYBOARD AFTER PROCESSING ANY GROUP MESSAGE
            # This ensures the keyboard appears after every interaction
            if text and text.strip():  # Only if we have actual text to process
                # Process the message first, then show menu
                # We'll handle this after the main processing
                pass
        
        if text == "📊 Financial Summary":
            return self.handle_financial_summary(chat_id)
        
        elif text == "📊 50/30/20 Status":
            return self.handle_503020_status(chat_id)
        
        elif text == "🗑️ Delete Transaction":
            return self.handle_delete_transaction(chat_id)
        
        elif text == "🏷️ Manage Categories":
            return self.handle_manage_categories(chat_id)
        
        elif text == "🔄 Restart Bot":
            return self.handle_restart_bot(chat_id)
        
        elif text == "🌍 Language":
            return self.handle_language_selection(chat_id)
        
        elif text == "/total" or text.startswith("/total@"):
            self.handle_total_command(chat_id)
            return
        
        elif text == "/delete" or text.startswith("/delete@"):
            self.handle_delete_transaction(chat_id)
            return
        
        # Ukrainian menu buttons
        elif text == "📊 Фінансовий звіт":
            return self.handle_financial_summary(chat_id)
        
        elif text == "🗑️ Видалити транзакцію":
            return self.handle_delete_transaction(chat_id)
        
        elif text == "🏷️ Керування категоріями":
            return self.handle_manage_categories(chat_id)
        
        elif text == "🔄 Перезапустити бота":
            return self.handle_restart_bot(chat_id)
        
        elif text == "🌍 Мова":
            return self.handle_language_selection(chat_id)
        
        # Handle delete mode first if active
        if self.delete_mode.get(chat_id):
            if text.isdigit():
                user_transactions = self.get_user_transactions(chat_id)
                transaction_map = self.delete_mode[chat_id]
                
                if text == "0":
                    self.delete_mode[chat_id] = False
                    self.send_message(chat_id, "✅ Exit delete mode. Back to normal operation.", reply_markup=self.get_main_menu(chat_id))

                
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
                            
                            self.send_message(chat_id, f"🗑️ {symbol} Deleted: {amount_display} - {deleted['category']}", reply_markup=self.get_main_menu(chat_id))
                            
                            # Update IDs for remaining transactions
                            for i, transaction in enumerate(user_transactions):
                                transaction['id'] = i + 1
                            
                            self.sync_transactions_to_postgres()
                            # IMPORTANT: Clear delete mode to force refresh
                            self.delete_mode[chat_id] = False
                        else:
                            self.send_message(chat_id, f"❌ Invalid transaction number. Type 0 to exit delete mode.", reply_markup=self.get_main_menu(chat_id))
                    else:
                        self.send_message(chat_id, f"❌ Invalid transaction number. Type 0 to exit delete mode.", reply_markup=self.get_main_menu(chat_id))
            else:
                # Any non-digit text cancels delete mode
                self.delete_mode[chat_id] = False
                self.send_message(chat_id, "❌ Delete mode cancelled.", reply_markup=self.get_main_menu(chat_id))
            return

                # Temporary debug - add this to your process_message method
        elif text == "/debugkeyboard" or text.startswith("/debugkeyboard@"):
            chat_type = msg["chat"].get("type", "private")
            is_group = chat_id < 0
            
            debug_info = f"""
        🔍 KEYBOARD DEBUG:
        - Chat ID: {chat_id}
        - Chat Type: {chat_type}
        - Is Group: {is_group}
        - User ID from param: {chat_id}
        - Selective setting: {is_group}
        """
            self.send_message(chat_id, debug_info)
            # Also try to show the keyboard
            self.show_custom_keyboard(chat_id, "Testing keyboard...")
            return
        
        elif text == "/menu" or text.startswith("/menu@"):
            self.show_menu_keyboard(chat_id, "🏠 Menu:")
            return

        elif text == "/showmenu" or text.startswith("/showmenu@"):
            self.show_menu_keyboard(chat_id, "⌨️ Showing menu...")
            return

        elif text == "/help" or text.startswith("/help@"):
            user_lang = self.get_user_language(chat_id)
            if user_lang == 'uk':
                help_text = """🤖 *ФіннБот - Довідка для груп*

        *Команди:*
        • `/menu` - Показати меню
        • `/summary` - Фінансовий звіт
        • `/help` - Ця довідка

        *Транзакції:*
        • `150 обід` - Витрата
        • `+5000 зарплата` - Дохід
        • `++1000` - Заощадження
        • `-200 кредит` - Борг"""
            else:
                help_text = """🤖 *FinnBot - Group Help*

        *Commands:*
        • `/menu` - Show menu
        • `/summary` - Financial summary  
        • `/help` - This help

        *Transactions:*
        • `150 lunch` - Expense
        • `+5000 salary` - Income
        • `++1000` - Savings
        • `-200 loan` - Debt"""
            
            self.send_message(chat_id, help_text, parse_mode='Markdown')
            return
        
        elif text == "/summary" or text.startswith("/summary@"):
            user_transactions = self.get_user_transactions(chat_id)
            if not user_transactions:
                user_lang = self.get_user_language(chat_id)
                if user_lang == 'uk':
                    self.send_message(chat_id, "📭 Немає транзакцій для відображення.", reply_markup=self.get_main_menu(chat_id))
                else:
                    self.send_message(chat_id, "📭 No transactions to display.", reply_markup=self.get_main_menu(chat_id))
            else:
                # Use your existing financial summary logic
                income = 0
                expenses = 0
                savings_deposits = 0
                savings_withdrawn = 0
                debt_incurred = 0
                debt_returned = 0
                expense_by_category = {}
                
                for transaction in user_transactions:
                    if transaction['type'] == 'income':
                        income += transaction['amount']
                    elif transaction['type'] == 'savings':
                        savings_deposits += transaction['amount']
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
                
                net_savings = savings_deposits - savings_withdrawn
                net_debt = debt_incurred - debt_returned
                net_flow = income - expenses - net_savings
                
                user_lang = self.get_user_language(chat_id)
                
                if user_lang == 'uk':
                    summary_text = f"""📊 *Фінансовий звіт групи*

        💸 *Аналіз готівкового потоку:*
        Дохід: {income:,.0f}₴
        Витрати: {expenses:,.0f}₴
        Заощадження: {net_savings:,.0f}₴
        ─────────────────
        Чистий потік: {net_flow:,.0f}₴

        🏦 *Заощадження:*
        Внесено: {savings_deposits:,.0f}₴
        Чисті заощадження: {net_savings:,.0f}₴"""
                    
                    if debt_incurred > 0 or debt_returned > 0:
                        summary_text += f"\n\n💳 *Борги:*\n   Заборгованість: {debt_incurred:,.0f}₴"
                        if debt_returned > 0:
                            summary_text += f"\n   Повернено: {debt_returned:,.0f}₴"
                        summary_text += f"\n   Чистий борг: {net_debt:,.0f}₴"
                else:
                    summary_text = f"""📊 *Group Financial Summary*

        💸 *Cash Flow Analysis:*
        Income: {income:,.0f}₴
        Expenses: {expenses:,.0f}₴
        Savings: {net_savings:,.0f}₴
        ─────────────────
        Net Cash Flow: {net_flow:,.0f}₴

        🏦 *Savings Account:*
        Deposited: {savings_deposits:,.0f}₴
        Net Savings: {net_savings:,.0f}₴"""
                    
                    if debt_incurred > 0 or debt_returned > 0:
                        summary_text += f"\n\n💳 *Debt Account:*\n   Incurred: {debt_incurred:,.0f}₴"
                        if debt_returned > 0:
                            summary_text += f"\n   Returned: {debt_returned:,.0f}₴"
                        summary_text += f"\n   Net Debt: {net_debt:,.0f}₴"
                
                # Show menu after summary in groups
                self.send_message(chat_id, summary_text, parse_mode='Markdown')
                
                # ===== STEP 6: Show menu after summary in groups =====
                chat_type = msg["chat"].get("type", "private")
                if chat_type in ["group", "supergroup"]:
                    user_lang = self.get_user_language(chat_id)
                    if user_lang == 'uk':
                        menu_msg = "📊 Звіт показано! Що далі?"
                    else:
                        menu_msg = "📊 Summary shown! What's next?"
                    
                    self.show_menu_keyboard(chat_id, menu_msg)
                # ===== END STEP 6 =====
            return

        # NORMAL MESSAGE PROCESSING (when not in delete mode)
        elif text == "/start" or text.startswith("/start@"):
            chat_type = msg["chat"].get("type", "private")
            
            if chat_type == "private":
                # Your existing private start code...
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
            else:
                # Group start command
                user_lang = self.get_user_language(chat_id)
                if user_lang == 'uk':
                    group_welcome = """🤖 *ФіннБот - Фінансовий помічник для груп*

        *Доступні команди:*
        • `/start` - Це меню
        • `/help` - Довідка по командам
        • `/summary` - Фінансовий звіт групи

        *Додавання транзакцій:*
        • `150 обід` - Витрата
        • `+5000 зарплата` - Дохід  
        • `++1000` - Заощадження
        • `-200 кредит` - Борг

        *Або звертайтеся до бота:*
        `@finnbot 150 обід`
        `@finnbot ++500`"""
                else:
                    group_welcome = """🤖 *FinnBot - Financial Assistant for Groups*

        *Available Commands:*
        • `/start` - This menu
        • `/help` - Command help
        • `/summary` - Group financial summary

        *Adding Transactions:*
        • `150 lunch` - Expense
        • `+5000 salary` - Income
        • `++1000` - Savings
        • `-200 loan` - Debt

        *Or mention the bot:*
        `@finnbot 150 lunch`
        `@finnbot ++500`"""
                
                self.send_message(chat_id, group_welcome, parse_mode='Markdown')

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
            
            # FIX: Add proper keyboard creation
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
                'type': "savings",
                'currency': currency
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
            
            self.send_message(chat_id, help_text, parse_mode='Markdown', reply_markup=self.get_main_menu(chat_id))

        
        elif text == "📊 Financial Summary":
            user_transactions = self.get_user_transactions(chat_id)
            if not user_transactions:
                self.send_message(chat_id, "No transactions recorded yet.", reply_markup=self.get_main_menu(chat_id))
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
                
                self.send_message(chat_id, summary_text, parse_mode='Markdown', reply_markup=self.get_main_menu(chat_id))

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
                self.send_message(chat_id, "📭 No transactions to delete.", reply_markup=self.get_main_menu(chat_id))
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
            # Get categories as names
            category_names = self.get_user_categories(chat_id)
            user_lang = self.get_user_language(chat_id)
            
            if user_lang == 'uk':
                categories_text = "🏷️ *Ваші категорії*\n\n"
                categories_text += "*🔒 Фіксовані категорії:*\n"
                categories_text += "• Зарплата • Бізнес • Кріпто • Банк • Особисте • Інвестиції\n\n"
                categories_text += "*💼 Ваші кастомні категорії:*\n"
            else:
                categories_text = "🏷️ *Your Categories*\n\n"
                categories_text += "*🔒 Fixed Categories:*\n"
                categories_text += "• Salary • Business • Crypto • Bank • Personal • Investment\n\n"
                categories_text += "*💼 Your Custom Categories:*\n"
            
            # Show only custom categories (exclude fixed ones)
            fixed_categories = ["Salary", "Business", "Crypto", "Bank", "Personal", "Investment", "Other"]
            if user_lang == 'uk':
                fixed_categories = ["Зарплата", "Бізнес", "Кріпто", "Банк", "Особисте", "Інвестиції", "Other"]
            
            has_custom_categories = False
            for category_name in category_names:
                if category_name not in fixed_categories:
                    categories_text += f"• *{category_name}*\n"
                    has_custom_categories = True
            
            if not has_custom_categories:
                if user_lang == 'uk':
                    categories_text += "📝 Поки що немає кастомних категорій\n"
                else:
                    categories_text += "📝 No custom categories yet\n"
            
            if user_lang == 'uk':
                categories_text += "\n*Швидкі команди:*\n"
                categories_text += "• `+Їжа` - Додати нову категорію\n"
                categories_text += "• `-Їжа` - Видалити категорію\n"
                categories_text += "• Фіксовані категорії не можна змінити"
            else:
                categories_text += "\n*Quick Commands:*\n"
                categories_text += "• `+Food` - Add new category\n"
                categories_text += "• `-Food` - Remove category\n"
                categories_text += "• Fixed categories cannot be modified"

            self.send_message(chat_id, categories_text, parse_mode='Markdown', reply_markup=self.get_main_menu(chat_id))

        elif text.startswith("+") and len(text) > 1 and not any(char.isdigit() for char in text[1:]):
            # Add new spending category
            try:
                new_category = text[1:].strip()
                
                # Check if it's a protected category
                protected_categories = ["Salary", "Business", "Crypto", "Bank", "Personal", "Investment", "Other"]
                if new_category in protected_categories:
                    self.send_message(chat_id, f"❌ *{new_category}* is a protected category and cannot be modified!", parse_mode='Markdown', reply_markup=self.get_main_menu(chat_id))
                    return
                
                # REMOVED: No emoji parameter needed
                success, message = self.add_user_category(chat_id, new_category)
                
                if success:
                    self.send_message(chat_id, f"✅ Added new spending category: *{new_category}*", parse_mode='Markdown', reply_markup=self.get_main_menu(chat_id))
                else:
                    self.send_message(chat_id, f"❌ {message}", parse_mode='Markdown', reply_markup=self.get_main_menu(chat_id))
                    
            except Exception as e:
                self.send_message(chat_id, f"❌ Error: {str(e)}", reply_markup=self.get_main_menu(chat_id))

        elif text.startswith("-") and len(text) > 1 and not any(char.isdigit() for char in text[1:]):
            # Remove spending category
            try:
                category_to_remove = text[1:].strip()
                
                # Check if it's a protected category
                protected_categories = ["Salary", "Business", "Crypto", "Bank", "Personal", "Investment", "Other"]
                if category_to_remove in protected_categories:
                    self.send_message(chat_id, f"❌ *{category_to_remove}* is a protected category and cannot be removed!", parse_mode='Markdown', reply_markup=self.get_main_menu(chat_id))
                    return
                
                success, message = self.remove_user_category(chat_id, category_to_remove)
                
                if success:
                    self.send_message(chat_id, f"✅ Removed spending category: *{category_to_remove}*", parse_mode='Markdown', reply_markup=self.get_main_menu(chat_id))
                else:
                    self.send_message(chat_id, f"❌ {message}", parse_mode='Markdown', reply_markup=self.get_main_menu(chat_id))
                    
            except Exception as e:
                self.send_message(chat_id, f"❌ Error: {str(e)}", reply_markup=self.get_main_menu(chat_id))

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
                
                self.send_message(chat_id, success_text, parse_mode='Markdown', reply_markup=self.get_main_menu(chat_id))
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
                    amount, trans_type, symbol, currency = result
                    
                    # Store pending transaction
                    self.pending[chat_id] = {
                        'amount': amount, 
                        'text': f"{text} = {symbol}{amount:,.0f}{'₴' if currency == 'UAH' else '$' if currency == 'USD' else '€'}",
                        'category': "Salary" if trans_type == 'income' else "Other",
                        'type': trans_type,
                        'currency': currency  # Add currency
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
                        
                        # FIX: Add proper keyboard creation
                        keyboard_rows = []
                        for i in range(0, len(income_cats), 2):
                            row = []
                            for cat in income_cats[i:i+2]:
                                row.append({"text": cat, "callback_data": f"cat_{cat}"})
                            keyboard_rows.append(row)
                        
                        keyboard = {"inline_keyboard": keyboard_rows}
                        
                    else:
                        # For savings transactions, show category selection
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
                            
                            # FIXED: Create keyboard properly without undefined 'i'
                            keyboard_rows = [
                                [
                                    {"text": savings_cats[0], "callback_data": f"cat_{savings_map[savings_cats[0]]}"},
                                    {"text": savings_cats[1], "callback_data": f"cat_{savings_map[savings_cats[1]]}"}
                                ],
                                [
                                    {"text": savings_cats[2], "callback_data": f"cat_{savings_map[savings_cats[2]]}"},
                                    {"text": savings_cats[3], "callback_data": f"cat_{savings_map[savings_cats[3]]}"}
                                ]
                            ]
                            
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
                    
                    # In the process_message method, update the help text:

                if user_lang == 'uk':
                    help_text = """🤔 Ой! Дозвольте допомогти вам правильно відформатувати:

🛒 10 - Витрата в гривнях (обід, шопінг тощо)
🛒 10$ - Витрата в доларах  
🛒 10€ - Витрата в євро
                                        
💰 +100 - Дохід в гривнях (зарплата, бізнес тощо) 
💰 +100$ - Дохід в доларах
💰 +100€ - Дохід в євро
                                        
🏦 ++100 - Заощадження в гривнях
🏦 ++100$ - Заощадження в доларах
🏦 ++100€ - Заощадження в євро

💡 *Приклади:*
`150 обід` - Витрата на обід в гривнях
`50$ кава` - Витрата на каву в доларах
`+5000 зарплата` - Дохід в гривнях
`+1000$ фріланс` - Дохід в доларах"""
                else:
                    help_text = """🤔 Oops! Let me help you format that correctly:
                                        
🛒 10 - Expense in UAH (lunch, shopping, etc.)
🛒 10$ - Expense in USD  
🛒 10€ - Expense in EUR
                                        
💰 +100 - Income in UAH (salary, business, etc.) 
💰 +100$ - Income in USD
💰 +100€ - Income in EUR
                                        
🏦 ++100 - Savings in UAH
🏦 ++100$ - Savings in USD  
🏦 ++100€ - Savings in EUR

💡 *Examples:*
`150 lunch` - Expense for lunch in UAH
`50$ coffee` - Expense for coffee in USD
`+5000 salary` - Income in UAH  
`+1000$ freelance` - Income in USD"""

                    self.send_message(chat_id, help_text, parse_mode='Markdown', reply_markup=self.get_main_menu(chat_id))
                    return
            
            # Original transaction processing (keep your existing code)
            amount, is_income, is_debt, is_savings, is_debt_return, is_savings_withdraw, currency = self.extract_amount(text)
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
                    
                    # Store pending transaction
                    self.pending[chat_id] = {
                        'amount': amount, 
                        'text': text, 
                        'category': "Savings",
                        'type': "savings",
                        'currency': currency
                    }
                    
                    # Get user language
                    user_lang = self.get_user_language(chat_id)
                    
                    # FIXED: Use preset savings categories - NO DATABASE CALL NEEDED!
                    if user_lang == 'uk':
                        savings_cats = ["Кріпто", "Банк", "Особисте", "Інвестиції"]
                        savings_map = {
                            "Кріпто": "Crypto",
                            "Банк": "Bank", 
                            "Особисте": "Personal", 
                            "Інвестиції": "Investment"
                        }
                    else:
                        savings_cats = ["Crypto", "Bank", "Personal", "Investment"]
                        savings_map = {cat: cat for cat in savings_cats}
                    
                    # Create keyboard with preset categories
                    keyboard_rows = [
                        [
                            {"text": savings_cats[0], "callback_data": f"cat_{savings_map[savings_cats[0]]}"},
                            {"text": savings_cats[1], "callback_data": f"cat_{savings_map[savings_cats[1]]}"}
                        ],
                        [
                            {"text": savings_cats[2], "callback_data": f"cat_{savings_map[savings_cats[2]]}"},
                            {"text": savings_cats[3], "callback_data": f"cat_{savings_map[savings_cats[3]]}"}
                        ]
                    ]
                    
                    keyboard = {"inline_keyboard": keyboard_rows}
                    
                    # Send message
                    if user_lang == 'uk':
                        message = f"🏦 Заощадження: ++{amount:,.0f}₴\n📝 Опис: {text}\n\nОберіть категорію заощаджень:"
                    else:
                        message = f"🏦 Savings: ++{amount:,.0f}₴\n📝 Description: {text}\n\nSelect savings category:"
                    
                    self.send_message(chat_id, message, keyboard)
                    return  # Stop further processing

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
                    'type': transaction_type,
                    'currency': currency
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
                # In the income transaction part:
                elif is_income:
                    message = f"💰 Income: +{amount:,.0f}₴\n📝 Description: {text}\n\nSelect category:"
                    
                    # Create proper inline keyboard for income categories using names
                    if user_lang == 'uk':
                        income_cats = ["Зарплата", "Бізнес"]
                    else:
                        income_cats = ["Salary", "Business"]
                    
                    keyboard_rows = []
                    for i in range(0, len(income_cats), 2):
                        row = []
                        for cat_name in income_cats[i:i+2]:
                            row.append({"text": cat_name, "callback_data": f"cat_{cat_name}"})
                        keyboard_rows.append(row)
                    
                    keyboard = {"inline_keyboard": keyboard_rows}
                    
                else:
                    # For expense transactions, show category names
                    message = f"💰 Expense: -{amount:,.0f}₴\n📝 Description: {text}\n\nSelect correct category:"
                    
                    # Get user's spending categories as names
                    category_names = self.get_user_categories(chat_id)
                    
                    # Create keyboard with category names only
                    keyboard_rows = []
                    for i in range(0, len(category_names), 2):
                        row = []
                        for cat_name in category_names[i:i+2]:
                            row.append({"text": cat_name, "callback_data": f"cat_{cat_name}"})
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
                image_caption = """👋 *Привіт! Я Finn!*"

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
Тепер ви готові до роботи з Finn! 🚀
💡 Почніть відстежувати транзакції або використовуйте меню!"""
            else:
                complete_msg = """🎉 *Profile Created!*
You're now ready to use Finn! 🚀 
💡 Start tracking transactions or use the menu!"""
            
            # Clear onboarding state
            if chat_id in self.onboarding_state:
                del self.onboarding_state[chat_id]
            
            self.send_message(chat_id, complete_msg, parse_mode='Markdown', reply_markup=self.get_main_menu(chat_id))
            time.sleep(2)
            self.send_transaction_guide(chat_id)

        
        elif data.startswith("cat_"):
            category = data[4:]
            print(f"🔍 DEBUG: Processing category selection - category: '{category}', chat_id in pending: {chat_id in self.pending}")
            
            # In the process_callback method, update the category selection part:

            if chat_id in self.pending:
                pending = self.pending[chat_id]
                amount = pending["amount"]
                text = pending["text"]
                transaction_type = pending["type"]
                currency = pending.get("currency", "UAH")  # Default to UAH if not specified
                
                # Get currency symbol for display
                currency_symbol = '₴'
                if currency == 'USD':
                    currency_symbol = '$'
                elif currency == 'EUR':
                    currency_symbol = '€'
                
                print(f"🔍 DEBUG: Processing {transaction_type} transaction - amount: {amount}, currency: {currency}, category: {category}")
                
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
                        "currency": currency,  # Add this line
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
                
                user_lang = self.get_user_language(chat_id)

                # Update 50/30/20 tracking
                bucket = self.categorize_transaction(category, text)

                # For income transactions, update income total
                if transaction_type == 'income':
                    self.update_income_for_503020(chat_id, amount)
                else:
                    self.update_503020_totals(chat_id, amount, bucket)

                # Check for 50/30/20 limit crossings
                # Check for 50/30/20 limit crossings - ONLY in private chats
                chat_type = query["message"]["chat"].get("type", "private")
                is_group = chat_type in ["group", "supergroup"]

                if not is_group:  # Only send 50/30/20 limit messages in private chats
                    limit_messages = self.check_503020_limits(chat_id)
                    for message in limit_messages:
                        self.send_message(chat_id, message, parse_mode='Markdown')
                
                # ===== DELETE THE CATEGORY SELECTION MESSAGE FIRST =====
                try:
                    delete_response = requests.post(f"{BASE_URL}/deleteMessage", json={
                        "chat_id": chat_id,
                        "message_id": message_id
                    })
                    if delete_response.status_code == 200:
                        print(f"✅ Deleted category selection message {message_id}")
                    else:
                        print(f"⚠️ Failed to delete category message: {delete_response.status_code}")
                except Exception as e:
                    print(f"⚠️ Error deleting category message: {e}")
                
                # Send appropriate confirmation message based on transaction type
                # Send appropriate confirmation message based on transaction type
                # Send appropriate confirmation message based on transaction type
                if transaction_type == 'income':
                    # ===== MODIFICATION: Only send savings recommendation in private chats =====
                    chat_type = query["message"]["chat"].get("type", "private")
                    is_group = chat_type in ["group", "supergroup"]
                    
                    if not is_group:  # Only in private chats
                        # Send savings recommendation
                        savings_msg = self.calculate_savings_recommendation(chat_id, amount, text)
                        self.send_message(chat_id, savings_msg, parse_mode='Markdown')
                    # ===== END MODIFICATION =====
                    
                    # Send confirmation WITH MENU
                    if user_lang == 'uk':
                        confirmation_msg = f"✅ Дохід збережено!\n +{amount:,.0f}{currency_symbol}\n: {category}"
                    else:
                        confirmation_msg = f"✅ Income saved!\n {amount:,.0f}{currency_symbol}: {category}"
                    self.send_message(chat_id, confirmation_msg, reply_markup=self.get_main_menu(chat_id))
                    
                elif transaction_type == 'savings':
                    if user_lang == 'uk':
                        message = f"✅ Заощадження збережено!\n ++{amount:,.0f}{currency_symbol}"
                    else:
                        message = f"✅ Savings saved!\n ++{amount:,.0f}{currency_symbol}"
                    self.send_message(chat_id, message, reply_markup=self.get_main_menu(chat_id))
                    
                elif transaction_type == 'debt':        
                    if user_lang == 'uk':
                        message = f"✅ Борг збережено!\n -{amount:,.0f}{currency_symbol}"
                    else:
                        message = f"✅ Debt saved!\n -{amount:,.0f}{currency_symbol}"
                    self.send_message(chat_id, message, reply_markup=self.get_main_menu(chat_id))
                    
                elif transaction_type == 'debt_return':
                    if user_lang == 'uk':
                        message = f"✅ Борг повернено!\n +-{amount:,.0f}₴"
                    else:
                        message = f"✅ Debt returned!\n +-{amount:,.0f}₴"
                    self.send_message(chat_id, message, reply_markup=self.get_main_menu(chat_id))
                    
                elif transaction_type == 'savings_withdraw':
                    if user_lang == 'uk':
                        message = f"✅ Заощадження знято!\n -+{amount:,.0f}₴"
                    else:
                        message = f"✅ Savings withdrawn!\n💰 -+{amount:,.0f}₴"
                    self.send_message(chat_id, message, reply_markup=self.get_main_menu(chat_id))
                    
                else:  # expense
                    if user_lang == 'uk':
                        message = f"✅ Витрату збережено!\n -{amount:,.0f}{currency_symbol}: {category}"
                    else:
                        message = f"✅ Expense saved!\n -{amount:,.0f}{currency_symbol}: {category}"
                    self.send_message(chat_id, message, reply_markup=self.get_main_menu(chat_id))

            else:
                print(f"❌ No pending transaction found for user {chat_id}")
                self.send_message(chat_id, "❌ Transaction expired. Please enter the transaction again.", reply_markup=self.get_main_menu(chat_id))

        elif data == "confirm_restart":
            user_lang = self.get_user_language(chat_id)
            
            print(f"🔍 DEBUG: Starting bot reset for user {chat_id}")
            
            try:
                # Delete the confirmation message FIRST
                try:
                    delete_response = requests.post(f"{BASE_URL}/deleteMessage", json={
                        "chat_id": chat_id,
                        "message_id": message_id
                    }, timeout=5)
                    if delete_response.status_code == 200:
                        print(f"✅ Deleted confirmation message {message_id}")
                    else:
                        print(f"⚠️ Failed to delete message: {delete_response.status_code}")
                except Exception as e:
                    print(f"⚠️ Error deleting confirmation message: {e}")
                
                # 1. Clear from memory - IMPORTANT: Clear ALL user data
                user_id_str = str(chat_id)
                
                # Clear transactions from memory
                if chat_id in self.transactions:
                    print(f"🔍 DEBUG: Before memory clear - {len(self.transactions[chat_id])} transactions in memory")
                    self.transactions[chat_id] = []  # Clear this user's transactions
                    print(f"🔍 DEBUG: After memory clear - {len(self.transactions[chat_id])} transactions in memory")
                
                # Also clear from the monthly totals (50/30/20 tracking)
                if user_id_str in self.monthly_totals:
                    del self.monthly_totals[user_id_str]
                if user_id_str in self.monthly_percentages:
                    del self.monthly_percentages[user_id_str]
                
                # 2. Clear from PostgreSQL database - MORE COMPREHENSIVE
                conn = self.get_db_connection()
                if conn:
                    try:
                        cur = conn.cursor()
                        # Delete ALL transactions for this user
                        cur.execute('DELETE FROM transactions WHERE user_id = %s', (chat_id,))
                        # Also clear incomes
                        cur.execute('DELETE FROM incomes WHERE user_id = %s', (chat_id,))
                        conn.commit()
                        conn.close()
                        print(f"✅ Deleted all data from PostgreSQL for user {chat_id}")
                    except Exception as e:
                        print(f"❌ Error deleting from PostgreSQL: {e}")
                
                # 3. Clear states
                if chat_id in self.onboarding_state:
                    del self.onboarding_state[chat_id]
                
                # Clear income from memory
                if user_id_str in self.user_incomes:
                    del self.user_incomes[user_id_str]
                
                # Clear user categories from memory
                if user_id_str in self.user_categories:
                    del self.user_categories[user_id_str]
                
                # Clear pending states
                if chat_id in self.pending:
                    del self.pending[chat_id]
                if chat_id in self.pending_income:
                    self.pending_income.discard(chat_id)
                if chat_id in self.delete_mode:
                    del self.delete_mode[chat_id]
                
                # 4. Force reload data to ensure clean state
                self.load_all_data()
                
                # Save changes
                self.save_incomes()
                
                # 5. Send success message
                if user_lang == 'uk':
                    success_msg = """✅ *Бота перезапущено!*

        Всі ваші транзакції та дані було успішно видалено. 

        🚀 Бот готовий до роботи з чистої сторінки!

        💡 *Порада:* Оновіть міні-додаток, щоб побачити чисті дані."""
                else:
                    success_msg = """✅ *Bot restarted!*

        All your transactions and data have been successfully deleted.

        🚀 The bot is ready to start fresh!

        💡 *Tip:* Refresh the mini-app to see clean data."""
                
                # Send the confirmation message
                result = self.send_message(chat_id, success_msg, parse_mode='Markdown', reply_markup=self.get_main_menu(chat_id))
                
                if result and result.status_code == 200:
                    print(f"✅ Success message sent to user {chat_id}")
                    time.sleep(2)
                    self.send_transaction_guide(chat_id)
                else:
                    print(f"❌ Failed to send success message to user {chat_id}")
                    
            except Exception as e:
                print(f"❌ Error during bot reset: {e}")
                # Send error message
                error_msg = "❌ Error during reset. Please try again." if user_lang != 'uk' else "❌ Помилка під час перезапуску. Спробуйте ще раз."
                self.send_message(chat_id, error_msg, reply_markup=self.get_main_menu(chat_id))

        elif data == "cancel_restart":
            user_lang = self.get_user_language(chat_id)
            
            if user_lang == 'uk':
                cancel_msg = "❌ Перезапуск скасовано. Ваші дані залишилися недоторканими."
            else:
                cancel_msg = "❌ Restart cancelled. Your data remains untouched."
            
            self.send_message(chat_id, cancel_msg, reply_markup=self.get_main_menu(chat_id))
            
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
            
            self.send_message(chat_id, confirmation, reply_markup=self.get_main_menu(chat_id))

            try:
                delete_response = requests.post(f"{BASE_URL}/deleteMessage", json={
                    "chat_id": chat_id,
                    "message_id": message_id
                })
            except Exception as e:
                print(f"⚠️ Error deleting language message: {e}")

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