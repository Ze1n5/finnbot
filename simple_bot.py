import os
from flask import Flask, request, jsonify

flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "🤖 FinnBot is running!"

@flask_app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        return jsonify({"status": "healthy", "message": "Webhook endpoint active"})
    return jsonify({"status": "received"})

@flask_app.route('/test')
def test():
    return "✅ Test route works!", 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)