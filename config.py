import os

# آی‌دی عددی ادمین اصلی (سازنده) ربات - این مقدار همیشه دسترسی کامل دارد
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

# توکن ربات که از @BotFather می‌گیری
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# مسیر فایل دیتابیس
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "autisma.db"))

# اسمی که برای صدا زدن اعضای گروه استفاده میشه
MEMBERS_CALL_NAME = "اوتیسمی‌های گل"
