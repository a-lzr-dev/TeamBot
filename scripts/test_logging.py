import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.logger import admin_logger, api_logger, app_logger, bot_logger, db_logger

print("🔍 Testing loggers...")
print(f"🔍 Current dir: {Path.cwd()}")

app_logger.info("✅ TEST: app_logger works")
db_logger.info("✅ TEST: db_logger works")
api_logger.info("✅ TEST: api_logger works")
bot_logger.info("✅ TEST: bot_logger works")
admin_logger.info("✅ TEST: admin_logger works")

print("✅ Log messages sent. Check logs/ directory.")
