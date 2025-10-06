import os
import json
import re
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATA_DIR = "."

# File paths
CATEGORIES_FILE = os.path.join(DATA_DIR, "categories.json")
PATTERNS_FILE = os.path.join(DATA_DIR, "learned_patterns.json")
TRANSACTIONS_FILE = os.path.join(DATA_DIR, "transactions.json")

class FinnBot:
    def __init__(self):
        self.categories = self.load_categories()
        self.learned_patterns = self.load_learned_patterns()
        self.transactions = self.load_transactions()

    def load_categories(self):
        try:
            if os.path.exists(CATEGORIES_FILE):
                with open(CATEGORIES_FILE, 'r') as f:
                    return json.load(f)
        except:
            pass
        return {
            "Food": ["meat", "vegetables", "fruit", "bread", "milk", "eggs", "cheese", "lunch", "dinner", "groceries"],
            "Sweets": ["chocolate", "candy", "cake", "cookie", "ice cream", "dessert"],
            "Transport": ["gas", "bus", "train", "taxi", "fuel", "parking", "uber"],
            "Shopping": ["clothes", "electronics", "furniture", "accessories"],
            "Bills": ["electricity", "water", "internet", "rent", "phone"],
            "Entertainment": ["movie", "game", "concert", "streaming"],
            "Health": ["medicine", "doctor", "pharmacy", "vitamins"],
            "Other": []
        }

    def load_learned_patterns(self):
        try:
            if os.path.exists(PATTERNS_FILE):
                with open(PATTERNS_FILE, 'r') as f:
                    return json.load(f)
        except:
            pass
        return {}

    def load_transactions(self):
        try:
            if os.path.exists(TRANSACTIONS_FILE):
                with open(TRANSACTIONS_FILE, 'r') as f:
                    return json.load(f)
        except:
            pass
        return []

    def save_categories(self):
        try:
            with open(CATEGORIES_FILE, 'w') as f:
                json.dump(self.categories, f, indent=2)
        except:
            pass

    def save_learned_patterns(self):
        try:
            with open(PATTERNS_FILE, 'w') as f:
                json.dump(self.learned_patterns, f, indent=2)
        except:
            pass

    def save_transactions(self):
        try:
            with open(TRANSACTIONS_FILE, 'w') as f:
                json.dump(self.transactions, f, indent=2)
        except:
            pass

    def extract_amount_from_text(self, text):
        # Find amounts like $10.50, 10.50, 10,50
        amounts = re.findall(r'[\$€£]?\s*(\d+[.,]\d{2})|\b(\d+[.,]\d{2})\b', text)
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
                    return max(amounts_float)
        
        # Try simple numbers
        try:
            numbers = re.findall(r'\b\d+\b', text)
            if numbers:
                return float(numbers[0])
        except:
            pass
            
        return None

    def guess_category(self, text):
        text_lower = text.lower()
        
        # Check learned patterns first
        for pattern, category in self.learned_patterns.items():
            if pattern.lower() in text_lower:
                return category
        
        # Check category keywords
        for category, keywords in self.categories.items():
            if category == "Other":
                continue
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    return category
        
        return "Other"

    def learn_pattern(self, text, correct_category):
        # Extract words and learn them
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        for word in words:
            self.learned_patterns[word] = correct_category
        self.save_learned_patterns()

    def add_transaction(self, amount, category, description):
        transaction = {
            "id": len(self.transactions) + 1,
            "amount": amount,
            "category": category,
            "description": description[:100],
            "date": datetime.now().isoformat()
        }
        self.transactions.append(transaction)
        self.save_transactions()

    def get_category_buttons(self):
        keyboard = []
        categories = list(self.categories.keys())
        
        # Create 2 buttons per row
        for i in range(0, len(categories), 2):
            row = []
            row.append(InlineKeyboardButton(categories[i], callback_data=f"cat_{categories[i]}"))
            if i + 1 < len(categories):
                row.append(InlineKeyboardButton(categories[i + 1], callback_data=f"cat_{categories[i + 1]}"))
            keyboard.append(row)
        
        return InlineKeyboardMarkup(keyboard)

# Initialize the bot
finn_bot = FinnBot()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """
💸 *Hey! I'm Finn, and I'll help you manage your cashflow* 💸

Here's how I can help you:

💬 *Track expenses* - Send me receipts or type "15.50 lunch"
🏷️ *Auto-categorize* - I'll learn your spending patterns  
📊 *See insights* - Get spending summaries and trends
🎯 *Stay on budget* - I'll help you manage your cashflow

*Quick start:* Just send me an expense like "15.50 lunch" and I'll handle the rest!

I learn from your corrections and get smarter over time! 🧠
    """
    await update.message.reply_text(welcome_text, parse_mode='Markdown')
    

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    # Skip command messages
    if text.startswith('/'):
        return
    
    try:
        # Extract amount from text
        amount = finn_bot.extract_amount_from_text(text)
        if not amount:
            await update.message.reply_text("❌ Please include an amount in your message (e.g., '15.50 lunch' or just '15.50')")
            return
        
        # Guess category
        category = finn_bot.guess_category(text)
        
        # Store pending transaction
        context.user_data['pending_transaction'] = {
            'amount': amount,
            'description': text
        }
        
        # Create response
        response = f"""
💰 Amount: ${amount:.2f}
🏷️ Category: {category}
📝 Description: {text}

{'🤔 I\'m not sure about this category.' if category == 'Other' else ''} Is this correct?
        """
        
        # Show category buttons
        keyboard = finn_bot.get_category_buttons()
        await update.message.reply_text(response, reply_markup=keyboard)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def handle_category_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    selected_category = query.data.replace('cat_', '')
    user_data = context.user_data.get('pending_transaction')
    
    if not user_data:
        await query.edit_message_text("❌ Transaction data missing. Please start over.")
        return
    
    amount = user_data['amount']
    description = user_data['description']
    
    # Learn if category was corrected
    original_category = finn_bot.guess_category(description)
    if original_category != selected_category:
        finn_bot.learn_pattern(description, selected_category)
    
    # Save transaction
    finn_bot.add_transaction(amount, selected_category, description)
    
    # Clear pending transaction
    context.user_data.pop('pending_transaction', None)
    
    response = f"""
✅ Transaction saved!
💰 Amount: ${amount:.2f}
🏷️ Category: {selected_category}
📝 Description: {description[:80]}...

I've learned from this for next time! 📚
    """
    
    await query.edit_message_text(response)

async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not finn_bot.transactions:
        await update.message.reply_text("No transactions recorded yet.")
        return
    
    # Calculate summary
    summary = {}
    total = 0
    
    for transaction in finn_bot.transactions:
        category = transaction['category']
        amount = transaction['amount']
        
        if category not in summary:
            summary[category] = 0
        summary[category] += amount
        total += amount
    
    # Create summary text
    summary_text = "📊 *Spending Summary*\n\n"
    for category, amount in sorted(summary.items(), key=lambda x: x[1], reverse=True):
        percentage = (amount / total) * 100 if total > 0 else 0
        summary_text += f"• {category}: ${amount:.2f} ({percentage:.1f}%)\n"
    
    summary_text += f"\n💰 Total: ${total:.2f}"
    summary_text += f"\n📈 Transactions: {len(finn_bot.transactions)}"
    
    await update.message.reply_text(summary_text, parse_mode='Markdown')

async def categories_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    categories_text = "🏷️ *Available Categories*\n\n"
    for category, keywords in finn_bot.categories.items():
        categories_text += f"• {category}"
        if keywords:
            categories_text += f" - {', '.join(keywords[:3])}{'...' if len(keywords) > 3 else ''}"
        categories_text += "\n"
    
    categories_text += f"\n💡 Learned patterns: {len(finn_bot.learned_patterns)}"
    
    await update.message.reply_text(categories_text, parse_mode='Markdown')

async def add_category_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addcategory <CategoryName>")
        return
    
    new_category = ' '.join(context.args)
    
    if new_category in finn_bot.categories:
        await update.message.reply_text(f"Category '{new_category}' already exists!")
        return
    
    finn_bot.categories[new_category] = []
    finn_bot.save_categories()
    
    await update.message.reply_text(f"✅ New category '{new_category}' added!")

def main():
    if not BOT_TOKEN:
        print("❌ Error: BOT_TOKEN not found in .env file")
        print("Please add your bot token to the .env file:")
        print("BOT_TOKEN=your_bot_token_here")
        return
    
    try:
        # Create application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("summary", summary_command))
        application.add_handler(CommandHandler("categories", categories_command))
        application.add_handler(CommandHandler("addcategory", add_category_command))
        
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
        application.add_handler(CallbackQueryHandler(handle_category_selection, pattern="^cat_"))
        
        print("🤖 FinnBot is running...")
        application.run_polling()
        
    except Exception as e:
        print(f"❌ Error starting bot: {e}")
        print("This might be a Python 3.13 compatibility issue.")
        print("Try using Python 3.11 or 3.12 instead.")

if __name__ == '__main__':
    main()