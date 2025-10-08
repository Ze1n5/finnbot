import os
print("🔧 Starting test...")
print(f"PORT: {os.getenv('PORT')}")
print(f"BOT_TOKEN set: {bool(os.getenv('BOT_TOKEN'))}")

try:
    from flask import Flask
    print("✅ Flask imported successfully")
except ImportError as e:
    print(f"❌ Flask import error: {e}")

print("✅ Test completed successfully")