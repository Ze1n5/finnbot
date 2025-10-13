import os
import json
import re
import requests
import time
from dotenv import load_dotenv
from datetime import datetime
from flask import Flask, jsonify, request
import threading

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

class SimpleFinnBot:
    def __init__(self):
        # Income categories (shared for all users)
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
        self.transactions = {}
        self.pending = {}
        self.delete_mode = {}
        self.user_incomes = {}
        self.pending_income = set()
        self.user_categories = {}  # {user_id: {category_name: [keywords]}}
        self.user_languages = {}  # {user_id: 'en' or 'uk'}
        self.load_user_languages()
        self.daily_reminders = {}
        self.protected_savings_categories = ["Crypto", "Bank", "Personal", "Investment"]
        
        # Load existing data
        self.load_transactions()
        self.load_incomes()
        self.load_user_categories()
        self.monthly_totals = {}  # {user_id: {'needs': 0, 'wants': 0, 'future': 0, 'income': 0}}
        self.monthly_percentages = {}  # {user_id: {'needs': 0, 'wants': 0, 'future': 0}}
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
        self.translations = {
    'en': {
        'welcome': """Hi! I'm *Finn* - your AI finance assistant 🤖💰

Together we'll build your financial health using the *50/30/20 rule* - a simple and powerful system for managing your money:

🎯 *50/30/20 Breakdown:*
• 🏠 *50% Needs* - Rent, food, utilities, transport
• 🎉 *30% Wants* - Dining, entertainment, shopping  
• 🏦 *20% Future* - Savings, debt repayment, investments

🚀 *Quick Start:*
`+5000 salary` - Add income
`150 lunch` - Add expense  
`++1000` - Add to savings
`-200 loan` - Add debt

Let's build your financial health together! 💪""",
        # ... keep other English translations the same ...
    },
    'uk': {
        'welcome': """Привіт! Я *Finn* - твій AI фінансовий помічник 🤖💰

Разом ми будемо будувати вашу фінансову здоров'я за допомогою *правила 50/30/20* - простої та ефективної системи управління грошима:

🎯 *Розподіл 50/30/20:*
• 🏠 *50% Потреби* - Оренда, їжа, комунальні, транспорт
• 🎉 *30% Бажання* - Ресторани, розваги, шопінг
• 🏦 *20% Майбутнє* - Заощадження, погашення боргів, інвестиції

🚀 *Швидкий старт:*
`+5000 зарплата` - Додати дохід
`150 обід` - Додати витрату
`++1000` - Додати до заощаджень
`-200 кредит` - Додати борг

Давайте будувати ваше фінансове здоров'я разом! 💪""",
        # ... keep other Ukrainian translations the same ...
    }
}
        
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

    def save_user_languages(self):
        """Save user language preferences"""
        try:
            with open("user_languages.json", "w") as f:
                json.dump(self.user_languages, f, indent=2)
        except Exception as e:
            print(f"❌ Error saving user languages: {e}")

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

    def save_incomes(self):
        """Save user incomes to JSON file"""
        try:
            with open("incomes.json", "w") as f:
                json.dump(self.user_incomes, f, indent=2)
            print(f"💾 Saved incomes for {len(self.user_incomes)} users")
            
            # Sync incomes to Railway
            for user_id, amount in self.user_incomes.items():
                sync_to_railway({
                    'amount': amount,
                    'description': 'Monthly Income',
                    'timestamp': datetime.now().isoformat(),
                    'type': 'income',
                    'user_id': user_id
                })
                
        except Exception as e:
            print(f"❌ Error saving incomes: {e}")

    def get_user_income(self, user_id):
        """Get monthly income for a specific user"""
        return self.user_incomes.get(str(user_id))

    def save_transactions(self):
        """Save transactions to JSON file (separated by user)"""
        try:
            with open("transactions.json", "w") as f:
                json.dump(self.transactions, f, indent=2)
            print(f"💾 Saved transactions for {len(self.transactions)} users")
        except Exception as e:
            print(f"❌ Error saving transactions: {e}")

    def load_transactions(self):
        """Load transactions from JSON file (separated by user)"""
        try:
            if os.path.exists("transactions.json"):
                with open("transactions.json", "r") as f:
                    data = json.load(f)
                
                # Safely convert data to proper format
                self.transactions = {}
                for key, value in data.items():
                    try:
                        user_id = int(key)
                        # Ensure value is a list of transactions
                        if isinstance(value, list):
                            self.transactions[user_id] = value
                        else:
                            print(f"⚠️ Invalid data for user {user_id}, resetting")
                            self.transactions[user_id] = []
                    except (ValueError, TypeError):
                        print(f"⚠️ Skipping invalid user ID: {key}")
                
                print(f"📂 Loaded transactions for {len(self.transactions)} users")
            else:
                print("📂 No existing transactions file, starting fresh")
                self.transactions = {}
        except Exception as e:
            print(f"❌ Error loading transactions: {e}")
            self.transactions = {}

    def save_user_transaction(self, user_id, transaction):
        #Add transaction for a specific user and save to file
        if user_id not in self.transactions:
            self.transactions[user_id] = []
            
        self.transactions[user_id].append(transaction)
        self.save_transactions()
    
        # Sync to Railway
        """sync_to_railway({
            'amount': transaction['amount'],
            'description': transaction['description'],
            'category': transaction['category'],
            'timestamp': transaction['date'],
            'type': transaction['type']
        })"""

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

    def save_user_categories(self):
        """Save user categories to JSON file"""
        try:
            with open("user_categories.json", "w") as f:
                json.dump(self.user_categories, f, indent=2)
            print(f"💾 Saved spending categories for {len(self.user_categories)} users")
        except Exception as e:
            print(f"❌ Error saving user categories: {e}")

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
        # Check transaction type - order matters!
        is_savings = '++' in text  # Check for savings FIRST
        is_debt_return = '+-' in text  # +- for returning debt
        is_savings_withdraw = '-+' in text  # -+ for withdrawing from savings
        is_income = '+' in text and not is_savings and not is_debt_return and not is_savings_withdraw  # Single + but not others
        is_debt = text.strip().startswith('-') and not is_savings_withdraw  # - for debt, but not -+
        
        print(f"🔍 DEBUG extract_amount: text='{text}'")
        print(f"   is_income: {is_income}, is_debt: {is_debt}, is_savings: {is_savings}")
        print(f"   is_debt_return: {is_debt_return}, is_savings_withdraw: {is_savings_withdraw}")
        
        # Find amounts (including those with +, ++, +-, -+ or - signs)
        amounts = re.findall(r'[+-]+\s*(\d+[.,]\d{1,2})|\b(\d+[.,]\d{1,2})\b', text)
        if amounts:
            flat_amounts = [amt for group in amounts for amt in group if amt]
            if flat_amounts:
                amounts_float = []
                for amt in flat_amounts:
                    try:
                        clean_amt = amt.replace(',', '.')
                        amounts_float.append(float(clean_amt))
                    except ValueError:
                        continue
                if amounts_float:
                    amount = max(amounts_float)
                    print(f"   Extracted amount: {amount}")
                    return amount, is_income, is_debt, is_savings, is_debt_return, is_savings_withdraw
        
        # If no amount found with pattern, check if the entire text is a number
        try:
            clean_text = text.strip().replace('+', '').replace('-', '')
            amount = float(clean_text)
            print(f"   Extracted amount (clean): {amount}")
            return amount, is_income, is_debt, is_savings, is_debt_return, is_savings_withdraw
        except ValueError:
            pass
        
        # Find whole numbers within text
        whole_numbers = re.findall(r'\b(\d+)\b', text)
        if whole_numbers:
            try:
                amount = float(max(whole_numbers, key=lambda x: float(x)))
                print(f"   Extracted amount (whole): {amount}")
                return amount, is_income, is_debt, is_savings, is_debt_return, is_savings_withdraw
            except ValueError:
                pass
        
        print(f"   No amount found")
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
        print(f"🔍 DEBUG - pending_income: {chat_id in self.pending_income}")
        print(f"🔍 DEBUG - delete_mode: {self.delete_mode.get(chat_id, False)}")
        print(f"📨 Processing message from {chat_id}: {text}")
        
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
                            
                            self.save_transactions()
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
        if text == "/start":
            user_name = msg["chat"].get("first_name", "there")
            
            # Show language selection first
            keyboard = {
                "inline_keyboard": [
                    [{"text": "🇺🇸 English", "callback_data": "start_lang_en"}],
                    [{"text": "🇺🇦 Українська", "callback_data": "start_lang_uk"}]
                ]
            }
            
            welcome_text = f"👋 Welcome {user_name}! Let's set up your language first.\n\nPlease choose your language / Будь ласка, оберіть вашу мову:"
            
            self.send_message(chat_id, welcome_text, keyboard)

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
                
                # ... your existing summary calculations ...
                
                # ADD THIS SECTION AFTER THE EXISTING SUMMARY SECTIONS:
                # SAVINGS BY CATEGORY SECTION
                if savings_by_category:
                    summary_text += "\n🏦 *Savings by Category:*\n"
                    for category, amount in sorted(savings_by_category.items(), key=lambda x: x[1], reverse=True):
                        percentage = (amount / savings_deposits) * 100 if savings_deposits > 0 else 0
                        summary_text += f"   {category}: {amount:,.0f}₴ ({percentage:.1f}%)\n"
                
                self.send_message(chat_id, summary_text, parse_mode='Markdown', reply_markup=self.get_main_menu())
                # Handle income collection (only for initial setup)

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
                        # For other transaction types, just confirm
                        if user_lang == 'uk':
                            type_names = {
                                'expense': 'Витрата',
                                'savings': 'Заощадження', 
                                'debt': 'Борг',
                                'debt_return': 'Повернення боргу',
                                'savings_withdraw': 'Зняття заощаджень'
                            }
                            message = f"🧮 Розрахунок: {text}\n💰 Результат: {symbol}{amount:,.0f}₴\n\nЦе правильно?"
                        else:
                            type_names = {
                                'expense': 'Expense',
                                'savings': 'Savings',
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
            
            # Original transaction processing (keep your existing code)
            amount, is_income, is_debt, is_savings, is_debt_return, is_savings_withdraw = self.extract_amount(text)
        
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
                    # Use protected savings categories
                    user_lang = self.get_user_language(chat_id)
                    
                    if user_lang == 'uk':
                        savings_cats = ["Кріпто", "Банк", "Особисте", "Інвестиції"]
                        # Map display names to internal names
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
                            # Use the internal English name for callback_data
                            internal_name = savings_map[cat]
                            row.append({"text": cat, "callback_data": f"cat_{internal_name}"})
                        keyboard_rows.append(row)
                    
                    keyboard = {"inline_keyboard": keyboard_rows}
                    
                    if user_lang == 'uk':
                        message = f"🏦 Заощадження: ++{amount:,.0f}₴\n📝 Опис: {text}\n\nОберіть категорію заощаджень:"
                    else:
                        message = f"🏦 Savings: ++{amount:,.0f}₴\n📝 Description: {text}\n\nSelect savings category:"
                    
                    self.send_message(chat_id, message, keyboard)

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
                    
                elif is_savings:
                    message = f"🏦 Savings: ++{amount:,.0f}₴\n📝 Description: {text}\n\nIs this correct?"
                    keyboard = {"inline_keyboard": [[
                        {"text": "✅ Confirm Savings", "callback_data": "cat_Savings"}
                    ]]}
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
            
            else:
                self.send_message(chat_id, """🤔 Oops! Let me help you format that correctly:
                                 
🛒 10 - Expense (lunch, shopping, etc.)
                                 
💰 +100 - Income (salary, business, etc.) 
                                  
🏦 ++100 - Savings (put money aside)
                                 
💳 -100 - Debt (borrowed money)
                                 
🔙 +-100 - Returned debt (paying back)
                                 
📥 -+100 - Savings withdrawal (taking from savings)
""")

    def process_callback(self, query):
        """Process callback from webhook"""
        chat_id = query["message"]["chat"]["id"]
        message_id = query["message"]["message_id"]
        data = query["data"]
        
        print(f"🔍 DEBUG: Received callback - data: '{data}', chat_id: {chat_id}")
        
        # Answer the callback query first to remove loading state
        self.answer_callback(query["id"])

            # NEW: Handle start language selection
        # NEW: Handle start language selection
        if data.startswith("start_lang_"):
            language = data[11:]  # 'en' or 'uk'
            self.set_user_language(chat_id, language)
            
            if language == 'uk':
                welcome_text = """
Привіт! Я *Finn* - твій AI фінансовий помічник 🤖💰
Разом ми будемо будувати вашу фінансову здоров'я за допомогою *правила 50/30/20* - простої та ефективної системи управління грошима:

🎯 *Розподіл 50/30/20:*
• 🏠 *50% Потреби* - Оренда, їжа, комунальні, транспорт
• 🎉 *30% Бажання* - Ресторани, розваги, шопінг
• 🏦 *20% Майбутнє* - Заощадження, погашення боргів, інвестиції

🚀 *Швидкий старт:*
`+5000 зарплата` - Додати дохід
`150 обід` - Додати витрату
`++1000` - Додати до заощаджень
`-200 кредит` - Додати борг

Давайте будувати ваше фінансове здоров'я разом! 💪"""
            else:
                welcome_text = """
Hi! I'm *Finn* - your AI finance assistant 🤖💰
Together we'll build your financial health using the *50/30/20 rule* - a simple and powerful system for managing your money:

🎯 *50/30/20 Breakdown:*
• 🏠 *50% Needs* - Rent, food, utilities, transport
• 🎉 *30% Wants* - Dining, entertainment, shopping  
• 🏦 *20% Future* - Savings, debt repayment, investments

🚀 *Quick Start:*
`+5000 salary` - Add income
`150 lunch` - Add expense  
`++1000` - Add to savings
`-200 loan` - Add debt

Let's build your financial health together! 💪"""
            
            self.send_message(chat_id, welcome_text, parse_mode='Markdown', reply_markup=self.get_main_menu())
            
            # Delete the language selection message
            try:
                delete_response = requests.post(f"{BASE_URL}/deleteMessage", json={
                    "chat_id": chat_id,
                    "message_id": message_id
                })
            except Exception as e:
                print(f"⚠️ Error deleting language message: {e}")
            
            return

        
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
                    self.save_transactions()
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
            
            # Clear all user data
            user_id_str = str(chat_id)
            
            # Clear transactions
            if chat_id in self.transactions:
                del self.transactions[chat_id]
            
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
            
            # Save all changes
            self.save_transactions()
            self.save_incomes()
            self.save_user_categories()
            
            if user_lang == 'uk':
                success_msg = """✅ *Бота перезапущено!*
                
        Всі ваші дані було успішно видалено. Бот готовий до роботи з чистої сторінки!

        🚀 *Давайте почнемо знову!*
        Додайте вашу першу транзакцію або використовуйте меню для початку роботи."""
            else:
                success_msg = """✅ *Bot restarted!*
                
        All your data has been successfully deleted. The bot is ready to start fresh!

        🚀 *Let's start fresh!*
        Add your first transaction or use the menu to get started."""
            
            self.send_message(chat_id, success_msg, parse_mode='Markdown', reply_markup=self.get_main_menu())
            
            # Delete the confirmation message
            try:
                delete_response = requests.post(f"{BASE_URL}/deleteMessage", json={
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

# Initialize bot instance
bot_instance = SimpleFinnBot()

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
# ========== MINI-APP ROUTES ==========

@flask_app.route('/mini-app')
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
        
        .transaction-container {
            position: relative;
            overflow: hidden;
            border-bottom: 1px solid #2c2c2e;
        }
        
        .transaction-item {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            padding: 12px 0;
            background-color: #1c1c1e;
            position: relative;
            transition: transform 0.3s ease;
            width: 100%;
        }
        
        .transaction-item.swiping {
            transition: none;
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
        
        .delete-action {
            position: absolute;
            right: -80px;
            top: 0;
            bottom: 0;
            width: 80px;
            background-color: #ff453a;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
            transition: right 0.3s ease;
        }
        
        .delete-action.visible {
            right: 0;
        }
        
        .delete-text {
            font-size: 14px;
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
        
        .swipe-hint {
            text-align: center;
            padding: 10px 20px;
            color: #8e8e93;
            font-size: 12px;
            border-bottom: 1px solid #2c2c2e;
            background-color: #1c1c1e;
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
        
        <div class="swipe-hint">
            💡 Swipe left on any transaction to delete
        </div>
        
        <div class="transactions-section" id="transactions-section">
            <div class="transactions-header">Transactions</div>
            <div id="transactions-list">
                <div class="loading">Loading transactions...</div>
            </div>
        </div>
    </div>

    <script>
        let currentPage = 1;
        let isLoading = false;
        let hasMoreTransactions = true;
        const transactionsPerPage = 10;
        let touchStartX = 0;
        let currentSwipeElement = null;
        let swipeThreshold = 50;

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
                
            } catch (error) {
                console.error('Error loading financial data:', error);
                document.getElementById('balance-amount').textContent = '0';
                document.getElementById('income-amount').textContent = '0';
                document.getElementById('spending-amount').textContent = '0';
                document.getElementById('savings-amount').textContent = '0';
            }
        }

        // Load transactions with pagination
        async function loadTransactions(page = 1) {
            if (isLoading) return;
            
            isLoading = true;
            
            try {
                const response = await fetch(`/api/transactions?page=${page}&limit=${transactionsPerPage}`);
                if (!response.ok) {
                    throw new Error('API response not ok');
                }
                const data = await response.json();
                
                const transactionsList = document.getElementById('transactions-list');
                
                // Remove loading message on first load
                if (page === 1) {
                    transactionsList.innerHTML = '';
                }
                
                if (data.transactions && data.transactions.length > 0) {
                    data.transactions.forEach(transaction => {
                        const transactionElement = createTransactionElement(transaction);
                        transactionsList.appendChild(transactionElement);
                    });
                    
                    // Check if there are more transactions
                    hasMoreTransactions = data.has_more || false;
                    
                    // Remove loading indicator if it exists
                    const existingLoader = document.getElementById('loading-indicator');
                    if (existingLoader) {
                        existingLoader.remove();
                    }
                    
                    // Add loading indicator if there are more transactions
                    if (hasMoreTransactions) {
                        const loadingIndicator = document.createElement('div');
                        loadingIndicator.className = 'loading';
                        loadingIndicator.id = 'loading-indicator';
                        loadingIndicator.textContent = 'Loading more transactions...';
                        transactionsList.appendChild(loadingIndicator);
                    }
                } else if (page === 1) {
                    // No transactions at all
                    transactionsList.innerHTML = `
                        <div class="no-transactions">
                            <div style="font-size: 24px; margin-bottom: 8px;">📊</div>
                            <div>No transactions yet</div>
                            <div style="font-size: 12px; margin-top: 8px;">Start adding transactions in the bot</div>
                        </div>
                    `;
                }
                
                currentPage = page;
                
            } catch (error) {
                console.error('Error loading transactions:', error);
                if (page === 1) {
                    document.getElementById('transactions-list').innerHTML = 
                        '<div class="loading">Failed to load transactions</div>';
                }
            } finally {
                isLoading = false;
            }
        }

        // Create transaction element with swipe functionality
        function createTransactionElement(transaction) {
            const container = document.createElement('div');
            container.className = 'transaction-container';
            
            const transactionElement = document.createElement('div');
            transactionElement.className = 'transaction-item';
            
            // Delete action panel
            const deleteAction = document.createElement('div');
            deleteAction.className = 'delete-action';
            deleteAction.innerHTML = '<div class="delete-text">DELETE</div>';
            
            // Determine transaction type and amount display
            const isIncome = transaction.type === 'income';
            const isSavings = transaction.type === 'savings';
            const isDebt = transaction.type === 'debt';
            const isDebtReturn = transaction.type === 'debt_return';
            const isSavingsWithdraw = transaction.type === 'savings_withdraw';
            
            const amountClass = isIncome ? 'income-amount' : 'spending-amount';
            
            // FIXED: Expenses, debt returns, and savings withdrawals should show negative
            let amountDisplay;
            if (isIncome || isDebt) {
                amountDisplay = `+${formatCurrency(transaction.amount)}`;
            } else {
                amountDisplay = `-${formatCurrency(transaction.amount)}`;
            }
            
            // Format date
            const transactionDate = new Date(transaction.timestamp || transaction.date);
            const formattedDate = formatDate(transactionDate);
            
            transactionElement.innerHTML = `
                <div class="transaction-info">
                    <div class="transaction-emoji">${transaction.emoji || '💰'}</div>
                    <div class="transaction-details">
                        <div class="transaction-name">${transaction.display_name || transaction.name || 'Transaction'}</div>
                        <div class="transaction-date">${formattedDate}</div>
                    </div>
                </div>
                <div class="transaction-amount ${amountClass}">
                    ${amountDisplay}₴
                </div>
            `;
            
            container.appendChild(transactionElement);
            container.appendChild(deleteAction);
            
            // Add swipe functionality
            addSwipeListeners(container, transactionElement, deleteAction, transaction);
            
            return container;
        }

        // Add swipe functionality to transaction
        function addSwipeListeners(container, transactionElement, deleteAction, transaction) {
            let startX = 0;
            let currentX = 0;
            let isSwiping = false;
            
            transactionElement.addEventListener('touchstart', (e) => {
                startX = e.touches[0].clientX;
                currentX = startX;
                isSwiping = true;
                transactionElement.classList.add('swiping');
                
                // Reset other swiped elements
                resetOtherSwipes(container);
            });
            
            transactionElement.addEventListener('touchmove', (e) => {
                if (!isSwiping) return;
                
                currentX = e.touches[0].clientX;
                const diff = startX - currentX;
                
                // Only allow left swipe (positive diff)
                if (diff > 0) {
                    transactionElement.style.transform = `translateX(-${Math.min(diff, 80)}px)`;
                    
                    // Show delete action when threshold is reached
                    if (diff > swipeThreshold) {
                        deleteAction.classList.add('visible');
                    } else {
                        deleteAction.classList.remove('visible');
                    }
                }
            });
            
            transactionElement.addEventListener('touchend', () => {
                if (!isSwiping) return;
                
                const diff = startX - currentX;
                isSwiping = false;
                transactionElement.classList.remove('swiping');
                
                // If swiped beyond threshold, keep it open, otherwise reset
                if (diff > swipeThreshold) {
                    transactionElement.style.transform = 'translateX(-80px)';
                    deleteAction.classList.add('visible');
                    
                    // Add click listener to delete action
                    const deleteHandler = () => {
                        deleteTransaction(transaction, container);
                        deleteAction.removeEventListener('click', deleteHandler);
                    };
                    deleteAction.addEventListener('click', deleteHandler);
                } else {
                    resetSwipe(transactionElement, deleteAction);
                }
            });
            
            // Reset on click/tap
            transactionElement.addEventListener('click', () => {
                resetSwipe(transactionElement, deleteAction);
            });
        }

        // Reset swipe position
        function resetSwipe(transactionElement, deleteAction) {
            transactionElement.style.transform = 'translateX(0)';
            deleteAction.classList.remove('visible');
        }

        // Reset other swiped elements
        function resetOtherSwipes(currentContainer) {
            const allContainers = document.querySelectorAll('.transaction-container');
            allContainers.forEach(container => {
                if (container !== currentContainer) {
                    const transactionEl = container.querySelector('.transaction-item');
                    const deleteEl = container.querySelector('.delete-action');
                    resetSwipe(transactionEl, deleteEl);
                }
            });
        }

        // Delete transaction
        async function deleteTransaction(transaction, container) {
            if (!confirm('Are you sure you want to delete this transaction?')) {
                resetSwipe(container.querySelector('.transaction-item'), container.querySelector('.delete-action'));
                return;
            }
            
            try {
                // Show loading state
                container.style.opacity = '0.5';
                
                // Here you would call your backend API to delete the transaction
                // For now, we'll just remove it from the frontend and reload data
                console.log('Deleting transaction:', transaction);
                
                // Remove from UI immediately
                container.style.transition = 'opacity 0.3s ease';
                container.style.opacity = '0';
                setTimeout(() => {
                    container.remove();
                }, 300);
                
                // Reload financial data to update balances
                await loadFinancialData();
                
                // Show success message
                showNotification('Transaction deleted successfully');
                
            } catch (error) {
                console.error('Error deleting transaction:', error);
                showNotification('Error deleting transaction', true);
                container.style.opacity = '1';
            }
        }

        // Show notification
        function showNotification(message, isError = false) {
            const notification = document.createElement('div');
            notification.style.cssText = `
                position: fixed;
                top: 20px;
                left: 50%;
                transform: translateX(-50%);
                background-color: ${isError ? '#ff453a' : '#30d158'};
                color: white;
                padding: 12px 20px;
                border-radius: 8px;
                font-weight: 600;
                z-index: 1000;
                animation: slideDown 0.3s ease;
            `;
            
            notification.textContent = message;
            document.body.appendChild(notification);
            
            setTimeout(() => {
                notification.remove();
            }, 3000);
        }

        // Format date as "Oct 11, 2:50 PM"
        // Format date using browser's local timezone
        function formatDate(dateString) {
            if (!dateString) return 'Recent';
            
            const date = new Date(dateString);
            
            if (isNaN(date.getTime())) {
                return 'Recent';
            }
            
            // Use browser's local timezone
            const options = { 
                month: 'short', 
                day: 'numeric',
                hour: 'numeric',
                minute: '2-digit',
                hour12: true
            };
    
    return date.toLocaleDateString('en-US', options);
}

        function formatCurrency(amount) {
            return new Intl.NumberFormat('en-US').format(amount);
        }

        // Infinite scroll handler
        function handleScroll() {
            const transactionsSection = document.getElementById('transactions-section');
            const scrollTop = transactionsSection.scrollTop;
            const scrollHeight = transactionsSection.scrollHeight;
            const clientHeight = transactionsSection.clientHeight;
            
            // Load more when 100px from bottom
            if (scrollHeight - scrollTop - clientHeight < 100 && hasMoreTransactions && !isLoading) {
                loadTransactions(currentPage + 1);
            }
        }

        // Initialize everything when page loads
        document.addEventListener('DOMContentLoaded', function() {
            // Load financial data and first page of transactions
            loadFinancialData();
            loadTransactions(1);
            
            // Add scroll event listener for infinite scroll
            const transactionsSection = document.getElementById('transactions-section');
            transactionsSection.addEventListener('scroll', handleScroll);
        });
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
        
        # Read current transactions
        try:
            with open('transactions.json', 'r') as f:
                transactions = json.load(f)
        except:
            transactions = {}
        
        # Add new transaction (your data structure is {user_id: [transactions]})
        user_id = str(transaction_data.get('user_id', 'default_user'))
        if user_id not in transactions:
            transactions[user_id] = []
        
        transactions[user_id].append({
            'amount': transaction_data.get('amount', 0),
            'description': transaction_data.get('description', ''),
            'category': transaction_data.get('category', 'Other'),
            'type': transaction_data.get('type', 'expense'),
            'timestamp': transaction_data.get('timestamp', '')
        })
        
        # Save back to file
        with open('transactions.json', 'w') as f:
            json.dump(transactions, f)
        
        print("✅ Transaction added successfully")
        return jsonify({'status': 'success', 'message': 'Transaction added'})
        
    except Exception as e:
        print(f"❌ Error adding transaction: {e}")
        return jsonify({'error': str(e)}), 500
    
@flask_app.route('/api/delete-transaction', methods=['POST'])
def delete_transaction():
    try:
        data = request.json
        transaction_id = data.get('transaction_id')
        user_id = data.get('user_id')
        
        # Your logic to delete the transaction from your data store
        # This would remove it from transactions.json and update calculations
        
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
    """Set Telegram webhook URL"""
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

# Start the periodic checker
if not hasattr(bot_instance, 'reminder_started'):
    reminder_thread = threading.Thread(target=check_reminders_periodically, daemon=True)
    reminder_thread.start()
    bot_instance.reminder_started = True
    print("✅ Periodic reminder checker started")

if __name__ == "__main__":
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        print("❌ ERROR: Please set your actual bot token in the .env file")
        exit(1)
    
    # Set webhook when starting
    set_webhook()
    
    # Start Flask app - Railway will handle the production server
    port = int(os.environ.get('PORT', 8080))
    print(f"🚀 Starting webhook server on port {port}...")
    
    # Use Flask's built-in server (Railway handles production serving)
    flask_app.run(host='0.0.0.0', port=port, debug=False)