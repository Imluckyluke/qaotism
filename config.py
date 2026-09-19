import os

# آی‌دی عددی ادمین اصلی (سازنده) ربات - این مقدار همیشه دسترسی کامل دارد
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

# توکن ربات که از @BotFather می‌گیری
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# مسیر فایل دیتابیس
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "autisma.db"))

# اسمی که برای صدا زدن اعضای گروه استفاده میشه
MEMBERS_CALL_NAME = "اوتیسمی‌های گل"

# متنی که بالای پنل ادمین نمایش داده میشه
PANEL_TITLE = "سلام اوتیسمی! 👋\n🎛 پنل مدیریت آزمون"

# متن دکمه‌ی ثبت‌نام در آزمون
JOIN_BUTTON_TEXT = "🙋 من یک اوتیسمی پایه هستم"

# ---------------- تایمر و امتیازدهی ----------------

# مهلت پاسخ به هر سوال (ثانیه). پیش‌فرض ۲ دقیقه.
QUESTION_TIME_LIMIT = int(os.environ.get("QUESTION_TIME_LIMIT", "120"))

# امتیاز جواب درست: اگه فوری جواب بدی MAX_POINTS، اگه دقیقاً آخر مهلت جواب بدی MIN_POINTS.
# بین این دو، امتیاز به‌صورت خطی با زمان کم میشه. جواب غلط = ۰ امتیاز.
MAX_POINTS = int(os.environ.get("MAX_POINTS", "1000"))
MIN_POINTS = int(os.environ.get("MIN_POINTS", "100"))
