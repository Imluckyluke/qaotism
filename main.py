import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    InlineQueryHandler,
    ContextTypes,
    filters,
)

import database as db
from config import BOT_TOKEN, OWNER_ID
import handlers_panel as panel
import handlers_builder as builder
import handlers_editor as editor
import handlers_runner as runner

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("خطا در پردازش آپدیت", exc_info=context.error)
    if isinstance(update, Update) and update.callback_query:
        try:
            await update.callback_query.answer("یه خطای غیرمنتظره پیش اومد، دوباره امتحان کن.", show_alert=True)
        except Exception:
            pass


async def callback_query_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data

    # in-group quiz session related callbacks (init/j/go/a/skip) don't require admin
    if data.startswith(("init:", "j:", "go:", "a:", "skip:")):
        handled = await runner.session_callback_router(update, context)
        if handled:
            return

    if data == "mk_new":
        uid = update.callback_query.from_user.id
        if not db.is_admin(uid):
            await update.callback_query.answer("⛔️ دسترسی نداری.", show_alert=True)
            return
        await builder.start_new_quiz(update, context)
        return
    if data in ("bopt_done", "bq_more", "bq_finish") or data.startswith("bcorrect:"):
        if not db.is_admin(update.callback_query.from_user.id):
            await update.callback_query.answer("⛔️ دسترسی نداری.", show_alert=True)
            return
    if data.startswith(("qedit:", "qedit_", "eopt_done", "ecorrect:")):
        if not db.is_admin(update.callback_query.from_user.id):
            await update.callback_query.answer("⛔️ دسترسی نداری.", show_alert=True)
            return
        handled = await editor.edit_callback(update, context)
        if handled:
            return
    if data == "bopt_done":
        await builder.finish_options(update, context)
        return
    if data.startswith("bcorrect:"):
        if context.user_data.get("state") == "await_edit_new_correct":
            await editor.handle_edit_new_correct(update, context)
        else:
            await builder.set_correct_option(update, context)
        return
    if data == "bq_more":
        await builder.add_more_question(update, context)
        return
    if data == "bq_finish":
        await builder.finish_quiz(update, context)
        return

    # everything else (panel, mk_list, qv, qdel, adm_*, close) -> panel handler
    await panel.panel_callback(update, context)


def build_app():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN تنظیم نشده. متغیر محیطی BOT_TOKEN رو ست کن.")
    if not OWNER_ID:
        logger.warning("OWNER_ID تنظیم نشده! هیچکس دسترسی ادمین کامل نخواهد داشت.")

    db.init_db()

    app = Application.builder().token(BOT_TOKEN).post_init(runner.recover_running_sessions).build()

    if app.job_queue is None:
        raise SystemExit(
            "تایمر سوال‌ها به JobQueue نیاز داره. نصب کن:\n"
            "pip install -r requirements.txt   (باید python-telegram-bot[job-queue] نصب بشه)"
        )

    app.add_handler(CommandHandler("start", panel.start_cmd))
    app.add_handler(CommandHandler("panel", panel.panel_cmd))
    app.add_handler(CommandHandler("addadmin", panel.addadmin_cmd))
    app.add_handler(CommandHandler("testrich", panel.testrich_cmd))

    app.add_handler(CallbackQueryHandler(callback_query_router))
    app.add_handler(InlineQueryHandler(runner.inline_query_handler))

    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & (filters.TEXT & ~filters.COMMAND),
            builder.handle_text_router,
        )
    )

    app.add_error_handler(error_handler)

    return app


if __name__ == "__main__":
    application = build_app()
    logger.info("ربات اوتیسما در حال اجراست...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
