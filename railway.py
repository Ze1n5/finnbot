import os
from flask import Flask, jsonify
import json

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "OK", "message": "FinnBot API is running!"})

@app.route('/api/financial-data')
def api_financial_data():
    try:
        # Read incomes
        try:
            with open('incomes.json', 'r') as f:
                incomes = json.load(f)
        except:
            incomes = []
            
        # Read transactions  
        try:
            with open('transactions.json', 'r') as f:
                transactions = json.load(f)
        except:
            transactions = []
        
        # Calculate totals - handle both formats
        total_income = 0
        total_expenses = 0
        
        # Process incomes (could be array or object)
        if isinstance(incomes, list):
            for item in incomes:
                if isinstance(item, dict):
                    if item.get('type') == 'income':
                        total_income += item.get('amount', 0)
                    elif 'amount' in item and item.get('type') != 'expense':
                        total_income += item.get('amount', 0)
        elif isinstance(incomes, dict):
            # Handle old format: {"user_id": amount}
            total_income = sum(incomes.values())
        
        # Process transactions
        for transaction in transactions:
            if isinstance(transaction, dict):
                amount = transaction.get('amount', 0)
                if amount < 0 or transaction.get('type') == 'expense':
                    total_expenses += abs(amount)
                elif amount > 0 and transaction.get('type') != 'expense':
                    total_income += amount
        
        total_balance = total_income - total_expenses
        
        return jsonify({
            'total_balance': total_balance,
            'total_income': total_income,
            'total_expenses': total_expenses,
            'savings': max(total_balance, 0),
            'transaction_count': len(transactions),
            'income_count': len(incomes) if isinstance(incomes, list) else 1
        })
        
    except Exception as e:
        print(f"❌ Error in API: {e}")
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/debug-data')
def debug_data():
    try:
        with open('incomes.json', 'r') as f:
            incomes = json.load(f)
    except:
        incomes = []
        
    try:
        with open('transactions.json', 'r') as f:
            transactions = json.load(f)
    except:
        transactions = []
    
    return jsonify({
        'incomes': incomes,
        'transactions': transactions,
        'income_count': len(incomes),
        'transaction_count': len(transactions)
    })

@app.route('/mini-app')
def mini_app():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Financial Dashboard</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>
            body { font-family: Arial; padding: 20px; background: #1a1a1a; color: white; }
            .card { background: #2d2d2d; padding: 20px; margin: 10px 0; border-radius: 10px; }
        </style>
    </head>
    <body>
        <div style="max-width: 400px; margin: 0 auto;">
            <h2>💰 Financial Dashboard</h2>
            <div class="card">
                <h3>Total Balance</h3>
                <h1 id="balance">Loading...</h1>
            </div>
            <div class="card">
                <h3>Income vs Expenses</h3>
                <p>Income: <span id="income">0</span>₴</p>
                <p>Expenses: <span id="expenses">0</span>₴</p>
            </div>
        </div>
        <script>
            fetch('/api/financial-data')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('balance').textContent = data.total_balance + '₴';
                    document.getElementById('income').textContent = data.total_income;
                    document.getElementById('expenses').textContent = Math.abs(data.total_expenses);
                });
        </script>
    </body>
    </html>
    """

# ========== EXISTING ENDPOINTS (KEEP THESE) ==========

@app.route('/api/financial-data')
def api_financial_data():
    # Your existing code here - KEEP THIS
    pass

@app.route('/')
def health_check():
    # Your existing code here - KEEP THIS  
    pass

@app.route('/mini-app')
def serve_mini_app():
    # Your existing code here - KEEP THIS
    pass

# ========== NEW REAL-TIME SYNC ENDPOINTS (ADD THESE) ==========

@app.route('/api/add-transaction', methods=['POST'])
def add_transaction():
    try:
        transaction_data = request.json
        
        # Read current transactions
        try:
            with open('transactions.json', 'r') as f:
                transactions = json.load(f)
        except:
            transactions = []
        
        # Add new transaction
        transactions.append(transaction_data)
        
        # Save back to file
        with open('transactions.json', 'w') as f:
            json.dump(transactions, f)
        
        return jsonify({'status': 'success', 'message': 'Transaction added'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/add-income', methods=['POST']) 
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"🚀 Starting server on port {port}")
    from waitress import serve
    serve(app, host='0.0.0.0', port=port)