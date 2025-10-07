from flask import Blueprint, send_from_directory

# Create a blueprint for the mini app
mini_app = Blueprint('mini_app', __name__)

@mini_app.route('/mini-app')
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
        </style>
    </head>
    <body>
        <div class="container">
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
            // Load real data from API
            async function loadData() {
                try {
                    const response = await fetch('/api/financial-data');
                    const data = await response.json();
                    
                    document.getElementById('balance').textContent = data.total_balance + '₴';
                    document.getElementById('income').textContent = data.total_income;
                    document.getElementById('expenses').textContent = Math.abs(data.total_expenses);
                    
                } catch (error) {
                    console.error('Failed to load data:', error);
                    document.getElementById('balance').textContent = 'Error loading data';
                }
            }
            
            // Load data when page opens
            loadData();
        </script>
    </body>
    </html>
    """
