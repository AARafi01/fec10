import sys
import os
import requests
import json

# Add the workspace root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import ConfigService

def test_telegram_delivery():
    print("="*60)
    print("📢 TELEGRAM & CRON INTEGRATION TEST GUIDE")
    print("="*60)
    
    telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    
    if not telegram_token or not chat_id:
        try:
            config = ConfigService()
            telegram_token = config.get('SETTINGS', 'TELEGRAM_BOT_TOKEN', '')
            chat_id = config.get('SETTINGS', 'TELEGRAM_CHAT_ID', '')
        except Exception:
            pass
            
    print("⚙️ Configuration Detected:")
    print(f"   - TELEGRAM_BOT_TOKEN: {repr(telegram_token[:5] + '...' if telegram_token else None)}")
    print(f"   - TELEGRAM_CHAT_ID: {repr(chat_id)}")
    print("-" * 60)
    
    if not telegram_token or not chat_id:
        print("❌ Telegram credentials are not set yet!")
        print("\n📝 HOW TO CONFIGURE:")
        print("Option A (Local Testing): Add them under the [SETTINGS] section in 'config.ini':")
        print("   [SETTINGS]")
        print("   TELEGRAM_BOT_TOKEN = your_bot_token_here")
        print("   TELEGRAM_CHAT_ID = your_chat_id_here")
        print("\nOption B (Vercel Deployment): Set them as Environment Variables in Vercel Dashboard:")
        print("   - Name: TELEGRAM_BOT_TOKEN")
        print("   - Name: TELEGRAM_CHAT_ID")
        print("="*60)
        return
        
    # Trigger a real test message
    print("⚡ Sending a simulated Exam Notification to your Telegram...")
    text = (
        "🚨 *[Test] New DU CMC Exam Detected!*\n\n"
        "*Exam ID*: `9999`\n"
        "*Exam Name*: `Semester 5 (3rd Year 1st Semester)`\n\n"
        "Would you like to approve and start scraping?"
    )
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve & Scrape", "callback_data": "app:9999"},
                {"text": "❌ Ignore", "callback_data": "ign:9999"}
            ]
        ]
    }
    
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": json.dumps(reply_markup)
    }
    
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print("🎉 SUCCESS! A test notification has been sent to your Telegram chat.")
            print("👉 Check your Telegram app now. You should see a message with 'Approve & Scrape' and 'Ignore' buttons!")
        else:
            print(f"❌ Failed to send. Server returned status {res.status_code}: {res.text}")
    except Exception as e:
        print(f"❌ Connection error: {e}")
        
    print("-" * 60)
    print("🕒 HOW TO VERIFY CRON EXECUTION:")
    print("1. Start your local Flask server:")
    print("   .venv/bin/python3 app.py")
    print("\n2. Force execution of the exam check cron via curl:")
    print("   curl \"http://localhost:5000/api/cron/check-exams?force=true\"")
    print("\n3. If a new exam dropdown option is found on the DU CMC website:")
    print("   - You will instantly receive a notification on Telegram!")
    print("   - Clicking 'Approve & Scrape' will automatically fetch all results and store them in your database.")
    print("="*60)

if __name__ == "__main__":
    test_telegram_delivery()
