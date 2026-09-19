from telegram import Update
from telegram.ext import ContextTypes

import database as db
import keyboards as kb
import rich_report
from config import BOT_TOKEN, MEMBERS_CALL_NAME, PANEL_TITLE, RICH_RESULTS


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    uid = update.effective_user.id
    if db.is_admin(uid):
        await update.message.reply_text(
            f"سلام {MEMBERS_CALL_NAME}! 👋\nبرای مدیریت آزمون‌ها از /panel استفاده کن."
        )
    else:
        await update.message.reply_text(
            f"سلام {MEMBERS_CALL_NAME}! این ربات مخصوص آزمون گروهیه. فقط ادمین‌ها به پنل دسترسی دارن."
        )


async def panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text("پنل مدیریت فقط در چت خصوصی با ربات کار می‌کنه.")
        return
    uid = update.effective_user.id
    if not db.is_admin(uid):
        await update.message.reply_text("⛔️ فقط ادمین‌ها به این پنل دسترسی دارن.")
        return
    context.user_data.clear()
    if RICH_RESULTS and BOT_TOKEN:
        try:
            ok, _ = await rich_report.try_send_rich(
                BOT_TOKEN, update.effective_chat.id,
                rich_report.panel_home_html(),
                reply_markup_dict=kb.main_panel_kb(db.is_owner(uid)).to_dict(),
            )
            if ok:
                return
        except Exception:
            pass
    await update.message.reply_text(
        PANEL_TITLE, reply_markup=kb.main_panel_kb(db.is_owner(uid))
    )


async def testrich_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/testrich: sends a minimal Rich Message to diagnose sendRichMessage support."""
    if update.effective_chat.type != "private":
        return
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ فقط ادمین‌ها.")
        return
    if not BOT_TOKEN:
        await update.message.reply_text("BOT_TOKEN تنظیم نشده.")
        return
    await update.message.reply_text("دارم Rich Message تستی می‌فرستم…")
    ok, reason = await rich_report.send_rich_chunks(
        BOT_TOKEN, update.effective_chat.id, [rich_report.sample_rich_html()]
    )
    if ok:
        await update.message.reply_text("✅ Rich Message کار می‌کنه.")
    else:
        await update.message.reply_text(
            f"❌ Rich Message ناموفق بود و نتیجه‌ها متن ساده میشن.\nدلیل: {reason}"
        )


async def addadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/addadmin <id> shortcut command, owner only."""
    uid = update.effective_user.id
    if not db.is_owner(uid):
        await update.message.reply_text("⛔️ فقط سازنده اصلی ربات می‌تونه ادمین اضافه کنه.")
        return
    if not context.args:
        await update.message.reply_text("استفاده: /addadmin <آی‌دی عددی>")
        return
    try:
        new_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("آی‌دی باید عدد باشه.")
        return
    ok = db.add_admin(new_id, None, uid)
    if ok:
        await update.message.reply_text(f"✅ کاربر {new_id} به عنوان ادمین اضافه شد.")
    else:
        await update.message.reply_text("این کاربر از قبل ادمین بود.")


async def _show_quiz_list(q, rows):
    """Quiz list: rich table first, plain fallback."""
    if RICH_RESULTS and BOT_TOKEN and q.message is not None:
        try:
            ok, _ = await rich_report.try_edit_rich(
                BOT_TOKEN, rich_report.quiz_list_html(rows),
                chat_id=q.message.chat.id, message_id=q.message.message_id,
                reply_markup_dict=kb.quiz_list_kb(rows).to_dict(),
            )
            if ok:
                return
        except Exception:
            pass
    await q.edit_message_text("📋 لیست آزمون‌ها:", reply_markup=kb.quiz_list_kb(rows))


async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all callback_data used by the admin panel (prefix-based)."""
    q = update.callback_query
    uid = q.from_user.id
    data = q.data

    if not db.is_admin(uid):
        await q.answer("⛔️ دسترسی نداری.", show_alert=True)
        return

    if data == "close":
        await q.answer()
        await q.message.delete()
        return

    if data == "mk_panel":
        context.user_data.clear()
        await q.answer()
        if RICH_RESULTS and BOT_TOKEN and q.message is not None:
            try:
                ok, _ = await rich_report.try_edit_rich(
                    BOT_TOKEN, rich_report.panel_home_html(),
                    chat_id=q.message.chat.id, message_id=q.message.message_id,
                    reply_markup_dict=kb.main_panel_kb(db.is_owner(uid)).to_dict(),
                )
                if ok:
                    return
            except Exception:
                pass
        await q.edit_message_text(
            PANEL_TITLE, reply_markup=kb.main_panel_kb(db.is_owner(uid))
        )
        return

    if data == "mk_list":
        await q.answer()
        rows = db.list_quizzes()
        if not rows:
            await q.edit_message_text(
                "هنوز هیچ آزمونی ساخته نشده.", reply_markup=kb.back_close_kb()
            )
            return
        await _show_quiz_list(q, rows)
        return

    if data.startswith("qclone:"):
        quiz_id = int(data.split(":")[1])
        new_id = db.duplicate_quiz(quiz_id, uid)
        if not new_id:
            await q.answer("این آزمون دیگه وجود نداره.", show_alert=True)
            return
        await q.answer("کپی شد ✅")
        await _show_quiz_list(q, db.list_quizzes())
        return

    if data.startswith("qv:"):
        quiz_id = int(data.split(":")[1])
        quiz = db.get_quiz(quiz_id)
        await q.answer()
        if not quiz:
            await q.edit_message_text("این آزمون دیگه وجود نداره.", reply_markup=kb.back_close_kb("mk_list"))
            return
        questions = db.get_questions(quiz_id)
        if RICH_RESULTS and BOT_TOKEN and q.message is not None:
            try:
                ok, _ = await rich_report.try_edit_rich(
                    BOT_TOKEN, rich_report.quiz_detail_html(quiz, questions),
                    chat_id=q.message.chat.id, message_id=q.message.message_id,
                    reply_markup_dict=kb.quiz_detail_kb(quiz_id).to_dict(),
                )
                if ok:
                    return
            except Exception:
                pass
        lines = [f"📝 آزمون: {quiz['name']}", f"تعداد سوالات: {len(questions)}", ""]
        for i, qs in enumerate(questions, 1):
            lines.append(f"{i}. {qs['text']} ({len(qs['options'])} گزینه)")
        await q.edit_message_text("\n".join(lines), reply_markup=kb.quiz_detail_kb(quiz_id))
        return

    if data.startswith("qdel:"):
        quiz_id = int(data.split(":")[1])
        await q.answer()
        await q.edit_message_text(
            "مطمئنی می‌خوای این آزمون رو حذف کنی؟ این کار قابل بازگشت نیست.",
            reply_markup=kb.quiz_delete_confirm_kb(quiz_id),
        )
        return

    if data.startswith("qdelok:"):
        quiz_id = int(data.split(":")[1])
        if db.has_active_sessions(quiz_id):
            await q.answer("این آزمون الان در حال اجراست و نمی‌شه حذفش کرد.", show_alert=True)
            return
        db.delete_quiz(quiz_id)
        await q.answer("حذف شد ✅")
        rows = db.list_quizzes()
        if not rows:
            await q.edit_message_text("هنوز هیچ آزمونی ساخته نشده.", reply_markup=kb.back_close_kb())
            return
        await q.edit_message_text("📋 لیست آزمون‌ها:", reply_markup=kb.quiz_list_kb(rows))
        return

    # ---------------- Admin management (owner only) ----------------
    if data == "adm_menu":
        if not db.is_owner(uid):
            await q.answer("⛔️ فقط سازنده اصلی.", show_alert=True)
            return
        await q.answer()
        await q.edit_message_text("👥 مدیریت ادمین‌ها", reply_markup=kb.admin_menu_kb())
        return

    if data == "adm_add":
        if not db.is_owner(uid):
            await q.answer("⛔️ فقط سازنده اصلی.", show_alert=True)
            return
        context.user_data["state"] = "await_admin_id"
        await q.answer()
        await q.edit_message_text(
            "آی‌دی عددی کاربر رو بفرست، یا یه پیام از اون رو برای من فوروارد کن.\n\n"
            "برای انصراف /panel رو بزن.",
        )
        return

    if data == "adm_list":
        if not db.is_owner(uid):
            await q.answer("⛔️ فقط سازنده اصلی.", show_alert=True)
            return
        await q.answer()
        rows = db.list_admins()
        if not rows:
            await q.edit_message_text("هنوز ادمینی (به جز سازنده اصلی) اضافه نشده.", reply_markup=kb.admin_menu_kb())
            return
        await q.edit_message_text("📋 لیست ادمین‌ها (برای حذف بزن):", reply_markup=kb.admin_list_kb(rows))
        return

    if data.startswith("adm_rm:"):
        if not db.is_owner(uid):
            await q.answer("⛔️ فقط سازنده اصلی.", show_alert=True)
            return
        rm_id = int(data.split(":")[1])
        db.remove_admin(rm_id)
        await q.answer("حذف شد ✅")
        rows = db.list_admins()
        if not rows:
            await q.edit_message_text("هیچ ادمینی باقی نمونده.", reply_markup=kb.admin_menu_kb())
            return
        await q.edit_message_text("📋 لیست ادمین‌ها (برای حذف بزن):", reply_markup=kb.admin_list_kb(rows))
        return


async def handle_admin_id_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Called from the generic text router when state == await_admin_id.
    Returns True if it consumed the message."""
    uid = update.effective_user.id
    if not db.is_owner(uid):
        return False
    msg = update.message
    new_id = None
    username = None

    # Bot API 7.0+ replaced forward_from with forward_origin; support both
    # so this works regardless of the installed python-telegram-bot version.
    forward_user = None
    origin = getattr(msg, "forward_origin", None)
    if origin is not None and getattr(origin, "sender_user", None) is not None:
        forward_user = origin.sender_user
    else:
        forward_user = getattr(msg, "forward_from", None)

    if forward_user:
        new_id = forward_user.id
        username = forward_user.username
    elif msg.text and msg.text.strip().lstrip("-").isdigit():
        new_id = int(msg.text.strip())
    else:
        if origin is not None:
            await msg.reply_text(
                "این پیام فوروارد شده ولی حریم خصوصی فرستنده اصلی مخفیه، نمی‌تونم آی‌دیش رو بگیرم.\n"
                "یه آی‌دی عددی معتبر بفرست."
            )
        else:
            await msg.reply_text("یه آی‌دی عددی معتبر بفرست یا یه پیام از اون کاربر برام فوروارد کن.")
        return True

    ok = db.add_admin(new_id, username, uid)
    context.user_data["state"] = None
    if ok:
        await msg.reply_text(f"✅ کاربر {new_id} به عنوان ادمین اضافه شد.")
    else:
        await msg.reply_text("این کاربر از قبل ادمین بود.")
    await msg.reply_text(PANEL_TITLE, reply_markup=kb.main_panel_kb(True))
    return True
