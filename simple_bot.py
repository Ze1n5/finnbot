import os
import json
import re
import requests
import time
from dotenv import load_dotenv
from datetime import datetime
from flask import Flask, request, jsonify

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Flask App Setup
flask_app = Flask(__name__)
bot_instance = None

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
        
        # USER-SPECIFIC SPENDING CATEGORIES
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
            
            # ✅ SYNC INCOMES TO RAILWAY
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

        # ✅ SYNC TO RAILWAY
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
                "Food": ["restaurant", "cafe", "lunch", "dinner", "breakfast", "food", "groceries"],
                "Transport": ["bus", "taxi", "fuel", "metro", "transport", "uber"],
                "Shopping": ["mall", "store", "shop", "buy", "purchase"],
                "Bills": ["bill", "utilities", "electricity", "water", "internet"],
                "Entertainment": ["movie", "cinema", "game", "concert", "netflix"],
                "Health": ["doctor", "medicine", "hospital", "pharmacy"],
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
        if category_name in user_categories and category_name not in ["Food", "Transport", "Shopping", "Bills", "Entertainment", "Health", "Other"]:
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
            urgency = "🏦 Conservative Savings"
        else:
            # Smaller income (≤100,000 UAH) - recommend 15-20% savings
            min_save = income_amount * 0.15
            max_save = income_amount * 0.20
            urgency = "💪 Balanced Approach"
        
        # Format amounts in UAH
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

# Flask Routes
@flask_app.route('/')
def home():
    return "🤖 FinnBot is running!"

def get_category_color(category):
    """Assign colors to categories for the mini app"""
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

@flask_app.route('/api/user-data/<user_id>')
def get_user_data(user_id):
    try:
        if not bot_instance:
            return jsonify({'error': 'Bot not initialized'}), 500
            
        # Get user transactions
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
                for t in user_transactions[-10:]  # Last 10 transactions
            ]
        }
        
        return jsonify(user_data)
        
    except Exception as e:
        print(f"❌ Error in mini app API: {e}")
        return jsonify({'error': str(e)}), 500

@flask_app.route('/webhook', methods=['POST'])
def webhook():
    """Handle Telegram webhook updates"""
    try:
        print("📨 Webhook received - checking request...")
        
        # Log the request details
        print(f"📝 Method: {request.method}")
        print(f"📝 Content-Type: {request.content_type}")
        
        if request.method == 'POST':
            if request.content_type == 'application/json':
                update = request.get_json()
                print(f"📝 Update data received")
                
                if update:
                    if "message" in update:
                        msg = update["message"]
                        chat_id = msg["chat"]["id"]
                        text = msg.get("text", "")
                        print(f"📝 Message from {chat_id}: {text}")
                        
                        # Simple echo response for testing
                        if bot_instance:
                            response_text = f"Echo: {text}"
                            bot_instance.send_message(chat_id, response_text)
                            print(f"✅ Sent response to {chat_id}")
                        else:
                            print("❌ Bot instance not initialized")
                    
                    return jsonify({'status': 'ok'})
                else:
                    print("❌ No JSON data in request")
                    return jsonify({'status': 'error', 'message': 'No JSON data'})
            else:
                print(f"❌ Wrong content type: {request.content_type}")
                return jsonify({'status': 'error', 'message': 'Wrong content type'})
        else:
            print("❌ Wrong method")
            return jsonify({'status': 'error', 'message': 'Method not allowed'})
            
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500

@flask_app.route('/set_webhook')
def set_webhook_route():
    """Manual webhook setup endpoint"""
    try:
        webhook_url = "https://finnbot-production.up.railway.app/webhook"
        print(f"🔧 Setting webhook to: {webhook_url}")
        
        response = requests.post(
            f"{BASE_URL}/setWebhook",
            json={"url": webhook_url}
        )
        
        result = response.json()
        print(f"🔧 Telegram response: {result}")
        
        return jsonify({
            "status": "success" if result.get('ok') else "failed",
            "webhook_url": webhook_url,
            "telegram_response": result
        })
    except Exception as e:
        print(f"❌ Error setting webhook: {e}")
        return jsonify({"status": "error", "error": str(e)})

@flask_app.route('/get_webhook')
def get_webhook_route():
    """Check webhook status"""
    try:
        response = requests.get(f"{BASE_URL}/getWebhookInfo")
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)})

def set_bot_commands():
    """Set up the mini app button in Telegram"""
    try:
        mini_app_url = "https://finnbot-production.up.railway.app/mini-app"
        
        response = requests.post(f"{BASE_URL}/setChatMenuButton", json={
            "menu_button": {
                "type": "web_app",
                "text": "App",
                "web_app": {"url": mini_app_url}
            }
        })
        
        if response.status_code == 200:
            print("✅ Mini App button set successfully!")
        else:
            print(f"⚠️ Failed to set mini app button: {response.status_code}")
            
    except Exception as e:
        print(f"⚠️ Error setting mini app button: {e}")

def set_webhook():
    """Set Telegram webhook on Railway"""
    try:
        railway_url = "https://finnbot-production.up.railway.app"
        webhook_url = f"{railway_url}/webhook"
        
        print(f"🔧 Setting webhook to: {webhook_url}")
        
        response = requests.post(
            f"{BASE_URL}/setWebhook",
            json={
                "url": webhook_url,
                "max_connections": 40,
            },
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                print(f"✅ Webhook set successfully: {webhook_url}")
                return True
            else:
                print(f"❌ Webhook setup failed: {result.get('description')}")
        else:
            print(f"❌ HTTP error setting webhook: {response.status_code}")
            
        return False
            
    except Exception as e:
        print(f"❌ Error setting webhook: {e}")
        return False

def main():
    try:
        print("🔧 Starting bot initialization...")
        
        if not BOT_TOKEN:
            print("❌ BOT_TOKEN is not set")
            return
        
        bot = SimpleFinnBot()
        global bot_instance
        bot_instance = bot
        
        print("🤖 Simple FinnBot is running in WEBHOOK mode...")
        
        # Set webhook for Telegram
        set_webhook()
        
        # Set up the mini app button
        set_bot_commands()
        
        # Start Flask server
        port = int(os.getenv('PORT', 8080))
        print(f"🚀 Starting server on port {port}")
        flask_app.run(host='0.0.0.0', port=port, debug=False)
        
    except Exception as e:
        print(f"❌ CRITICAL ERROR in main: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()