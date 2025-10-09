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
        
        # User-specific data
        self.learned_patterns = {}
        self.transactions = {}
        self.pending = {}
        self.delete_mode = {}
        self.user_incomes = {}
        self.pending_income = set()
        self.user_categories = {}  # {user_id: {category_name: [keywords]}}
        
        # Load existing data
        self.load_transactions()
        self.load_incomes()
        self.load_user_categories()

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
        """Add transaction for a specific user and save to file"""
        if user_id not in self.transactions:
            self.transactions[user_id] = []
            
        self.transactions[user_id].append(transaction)
        self.save_transactions()
    
        # Sync to Railway
        sync_to_railway({
            'amount': transaction['amount'],
            'description': transaction['description'],
            'category': transaction['category'],
            'timestamp': transaction['date'],
            'type': transaction['type']
        })

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
        if category_name in user_categories and category_name not in ["Food", "Other"]:
            del user_categories[category_name]
            self.save_user_categories()
            return True
        return False

    def get_main_menu(self):
        """Returns the persistent menu keyboard"""
        keyboard = [
            ["📊 Financial Summary", "📋 Commands"],
            ["🗑️ Delete Transaction", "🏷️ Manage Categories"]
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
        is_income = '+' in text and not is_savings  # Single + but not ++
        is_debt = text.strip().startswith('-')  # - for debt
        is_debt_return = '+-' in text  # +- for returning debt
        is_savings_withdraw = '-+' in text  # -+ for withdrawing from savings
        
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
                    return max(amounts_float), is_income, is_debt, is_savings, is_debt_return, is_savings_withdraw
        
        # If no amount found with pattern, check if the entire text is a number
        try:
            clean_text = text.strip()
            amount = float(clean_text)
            return amount, is_income, is_debt, is_savings, is_debt_return, is_savings_withdraw
        except ValueError:
            pass
        
        # Find whole numbers within text
        whole_numbers = re.findall(r'\b(\d+)\b', text)
        if whole_numbers:
            try:
                amount = float(max(whole_numbers, key=lambda x: float(x)))
                return amount, is_income, is_debt, is_savings, is_debt_return, is_savings_withdraw
            except ValueError:
                pass
        
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
        
        # UAH-specific savings rules
        if income_amount > 100000:
            # Large income (>100,000 UAH) - recommend 10% savings
            min_save = income_amount * 0.10
            max_save = income_amount * 0.15
            min_percent = 10
            max_percent = 15
            urgency = "🏦 Conservative Savings"
            reason = "Large income detected! 10% savings will build significant wealth over time."
            
        else:
            # Smaller income (≤100,000 UAH) - recommend 15-20% savings
            min_save = income_amount * 0.15
            max_save = income_amount * 0.20
            min_percent = 15
            max_percent = 20
            urgency = "💪 Balanced Approach"
            reason = "Perfect income range for building savings! 15-20% is the sweet spot."
        
        # Adjust based on current savings in UAH context
        if current_savings < 50000:
            reason += " You're building your initial emergency fund - every UAH counts! 💰"
        elif current_savings < 200000:
            reason += " Good progress! You're building a solid financial cushion. 🎯"
        else:
            reason += " Excellent savings discipline! You're building real financial security. 🚀"
        
        # Format amounts in UAH (English only)
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
            welcome_text = f"""👋 Hi, I'm *Finn* - your AI finance companion 💰

Let's start our journey building your wealth by understanding your current situation.

💼 *Please send me your current average income:*

Just send me the amount, for example:  
`30000`"""
            
            self.pending_income.add(chat_id)
            self.send_message(chat_id, welcome_text, parse_mode='Markdown')

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
                
                # CALCULATE NET AMOUNTS
                net_savings = savings_deposits - savings_withdrawn
                net_debt = debt_incurred - debt_returned
                net_flow = income - expenses - net_savings
                
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
                
                self.send_message(chat_id, summary_text, parse_mode='Markdown', reply_markup=self.get_main_menu())

        # Handle income collection
        elif chat_id in self.pending_income:
            try:
                income = float(text)
                if income <= 0:
                    self.send_message(chat_id, "❌ Please enter a positive amount for your income.")
                else:
                    # Save the income
                    self.user_incomes[str(chat_id)] = income
                    self.save_incomes()
                    self.pending_income.remove(chat_id)
                    
                    # Welcome message with next steps
                    success_text = f"""✅ *Income set:* {income:,.0f}₴ monthly

🎉 Now we can start enhancing your financial health together, and remember:

_The best time to plant a tree was 20 years ago. The second best time is now._

📱 *Get started:*
Track your first transaction:

1 = Spending | +1 = Income | ++1 = Savings
-10 = Debt | +- 1 = Debt returned | -+1 = Savings withdrawal
+food - Add category | -food - Delete category

Use the menu below or just start tracking!"""
                    self.send_message(chat_id, success_text, parse_mode='Markdown', reply_markup=self.get_main_menu())
    
            except ValueError:
                self.send_message(chat_id, "❌ Please enter a valid number for your monthly income.\n\nExample: `15000` for 15,000₴ per month", parse_mode='Markdown')
                                    
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
                        # Add section header
                        if trans_type == 'income':
                            delete_text += "💰 *INCOME*\n"
                        elif trans_type == 'expense':
                            delete_text += "🛒 *EXPENSES*\n"
                        elif trans_type == 'savings':
                            delete_text += "🏦 *SAVINGS*\n"
                        elif trans_type == 'debt':
                            delete_text += "💳 *DEBT*\n"
                        elif trans_type == 'debt_return':
                            delete_text += "🔙 *RETURNED DEBT*\n"
                        elif trans_type == 'savings_withdraw':
                            delete_text += "📥 *SAVINGS WITHDRAWAL*\n"
                        
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
                            
                            delete_text += f"`{current_number:2d}` {amount_display} • {transaction['category']}\n"
                            
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
            categories_text = "🏷️ *Your Spending Categories*\n\n"
            for category, keywords in user_categories.items():
                categories_text += f"• *{category}*"
                if keywords:
                    categories_text += f" - {', '.join(keywords[:3])}{'...' if len(keywords) > 3 else ''}"
                categories_text += "\n"
            
            categories_text += "\n*Quick Commands:*\n"
            categories_text += "• `+Food` - Add new category\n"
            categories_text += "• `-Shopping` - Remove category\n"
            categories_text += "• Categories are used to auto-categorize your expenses"
            
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
        
        else:
            # Regular transaction processing
            print(f"🔍 DEBUG: Processing transaction - text: '{text}'")
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
                    category = "Savings"
                    transaction_type = "savings"
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
                        "date": datetime.now().isoformat()
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
                
                # Send appropriate confirmation message WITHOUT menu
                if transaction_type == 'income':
                    # Send savings recommendation
                    savings_msg = self.calculate_savings_recommendation(chat_id, amount, text)
                    self.send_message(chat_id, savings_msg, parse_mode='Markdown')
                    
                    # Send confirmation WITHOUT menu
                    confirmation_msg = f"✅ Income saved!\n💰 +{amount:,.0f}₴\n🏷️ {category}"
                    self.send_message(chat_id, confirmation_msg)
                    
                elif transaction_type == 'savings':
                    message = f"✅ Savings saved!\n💰 ++{amount:,.0f}₴"
                    self.send_message(chat_id, message)
                elif transaction_type == 'debt':        
                    message = f"✅ Debt saved!\n💰 -{amount:,.0f}₴"
                    self.send_message(chat_id, message)
                elif transaction_type == 'debt_return':
                    message = f"✅ Debt returned!\n💰 +-{amount:,.0f}₴"
                    self.send_message(chat_id, message)
                elif transaction_type == 'savings_withdraw':
                    message = f"✅ Savings withdrawn!\n💰 -+{amount:,.0f}₴"
                    self.send_message(chat_id, message)
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

# Health check route
@flask_app.route('/', methods=['GET', 'POST'])
def health_check():
    if request.method == 'POST':
        # Handle POST requests gracefully
        return jsonify({"status": "OK", "message": "FinnBot is running!", "method": "POST"})
    
    return jsonify({"status": "OK", "message": "FinnBot is running with webhooks!"})

# Your existing API routes
@flask_app.route('/api/user-data/<user_id>')
def get_user_data(user_id):
    try:
        if not bot_instance:
            return jsonify({'error': 'Bot not initialized'}), 500
            
        # Get user transactions from your existing data structure
        user_transactions = bot_instance.get_user_transactions(int(user_id))
        
        # Calculate statistics
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
            elif transaction['type'] == 'savings_withdraw':
                savings_withdrawn += transaction['amount']
            elif transaction['type'] == 'debt':
                debt_incurred += abs(transaction['amount'])
            elif transaction['type'] == 'debt_return':
                debt_returned += abs(transaction['amount'])
            elif transaction['type'] == 'expense':
                expenses += transaction['amount']
                category = transaction['category']
                if category not in expense_by_category:
                    expense_by_category[category] = 0
                expense_by_category[category] += transaction['amount']
        
        net_savings = savings_deposits - savings_withdrawn
        net_debt = debt_incurred - debt_returned
        net_flow = income - expenses - net_savings
        
        def get_category_color(category):
            color_map = {
                'Food': '#ff6b6b',
                'Transport': '#4dabf7', 
                'Shopping': '#ffd43b',
                'Bills': '#69db7c',
                'Entertainment': '#cc5de8',
                'Health': '#ff8787',
                'Salary': '#00d26a',
                'Business': '#20c997',
                'Savings': '#4dabf7',
                'Debt': '#ff8787',
                'Other': '#adb5bd'
            }
            return color_map.get(category, '#adb5bd')
        
        # Prepare data for the mini app
        user_data = {
            'totalIncome': income,
            'totalExpenses': expenses,
            'totalSavings': net_savings,
            'netFlow': net_flow,
            'netDebt': net_debt,
            'expensesByCategory': [
                {'category': cat, 'amount': amount, 'color': get_category_color(cat)}
                for cat, amount in expense_by_category.items()
            ],
            'recentTransactions': [
                {
                    'description': t['description'][:30],
                    'category': t['category'],
                    'amount': t['amount'] if t['type'] in ['income', 'savings'] else -t['amount'],
                    'type': t['type'],
                    'date': t['date'][:10] if 'date' in t else 'Unknown'
                }
                for t in user_transactions[-10:]
            ]
        }
        
        return jsonify(user_data)
        
    except Exception as e:
        print(f"❌ Error in mini app API: {e}")
        return jsonify({'error': str(e)}), 500
    
# ========== MINI-APP ROUTES ==========

@flask_app.route('/mini-app')
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

@flask_app.route('/api/financial-data')
def api_financial_data():
    try:
        print("📊 Fetching financial data for mini-app...")
        
        # Read incomes
        try:
            with open('incomes.json', 'r') as f:
                incomes_data = json.load(f)
            print(f"💰 Incomes data type: {type(incomes_data)}, data: {incomes_data}")
        except Exception as e:
            print(f"❌ Error reading incomes: {e}")
            incomes_data = {}

        # Read transactions  
        try:
            with open('transactions.json', 'r') as f:
                transactions_data = json.load(f)
            print(f"📂 Transactions data type: {type(transactions_data)}, keys: {list(transactions_data.keys()) if isinstance(transactions_data, dict) else 'list'}")
        except Exception as e:
            print(f"❌ Error reading transactions: {e}")
            transactions_data = {}

        # Calculate totals
        total_income = 0
        total_expenses = 0
        all_transactions = []

        # Process incomes (your data is in dict format: {"user_id": amount})
        if isinstance(incomes_data, dict):
            for user_id, amount in incomes_data.items():
                if isinstance(amount, (int, float)) and amount > 0:
                    total_income += amount
                    all_transactions.append({
                        'amount': amount,
                        'type': 'income',
                        'description': 'Monthly Income'
                    })
        elif isinstance(incomes_data, list):
            for item in incomes_data:
                if isinstance(item, dict):
                    amount = item.get('amount', 0)
                    if isinstance(amount, (int, float)) and amount > 0:
                        total_income += amount

        # Process transactions (your data is in dict format: {"user_id": [transactions]})
        if isinstance(transactions_data, dict):
            for user_id, user_transactions in transactions_data.items():
                if isinstance(user_transactions, list):
                    for transaction in user_transactions:
                        if isinstance(transaction, dict):
                            amount = transaction.get('amount', 0)
                            trans_type = transaction.get('type', 'expense')
                            
                            if isinstance(amount, (int, float)):
                                if trans_type == 'income' or amount > 0:
                                    total_income += amount
                                elif trans_type == 'expense' or amount < 0:
                                    total_expenses += abs(amount)
                                
                                all_transactions.append(transaction)

        total_balance = total_income - total_expenses
        
        response_data = {
            'total_balance': total_balance,
            'total_income': total_income,
            'total_expenses': total_expenses,
            'savings': max(total_balance, 0),
            'transaction_count': len(all_transactions),
            'income_count': len(incomes_data) if isinstance(incomes_data, dict) else 0
        }
        
        print(f"📈 Financial data calculated: {response_data}")
        return jsonify(response_data)
        
    except Exception as e:
        print(f"❌ Error in financial data API: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

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
        webhook_url = "https://finnbot-production.up.railway.app/"
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