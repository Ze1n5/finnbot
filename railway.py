import os
from flask import Flask, jsonify
import json

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "OK", "message": "FinnBot API is running!"})

@app.route('/api/financial-data')
def financial_data():
    try:
        # Read your data files
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
        
        # Calculate totals
        total_income = sum(item.get('amount', 0) for item in incomes if isinstance(item, dict))
        total_expenses = sum(t.get('amount', 0) for t in transactions if isinstance(t, dict) and t.get('amount', 0) < 0)
        total_balance = total_income + total_expenses
        
        return jsonify({
            'total_balance': total_balance,
            'total_income': total_income,
            'total_expenses': total_expenses,
            'savings': max(total_balance, 0),
            'transaction_count': len(transactions),
            'income_count': len(incomes)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"🚀 Starting server on port {port}")
    from waitress import serve
    serve(app, host='0.0.0.0', port=port)