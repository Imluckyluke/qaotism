from telegram import Update
from telegram.ext import ContextTypes

import database as db
import keyboards as kb

MAX_OPTIONS = 10


def _fresh_build():
    return {"name": None, "questions": [], "current_q": None}


async def start_new_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    context.user_data.clear()
    context.user_data["state"] = "await_quiz_name"
    context.user_data["build"] = _fresh_build()
    await q.answer()
    await q.edit_message_text(
        "اسم آزمون رو بفرست (مثلاً: آزمون فرهنگ عمومی اوتیسما):"
    )


async def handle_quiz_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("اسم نمی‌تونه خالی باشه. دوباره بفرست:")
        return
    context.user_data["build"]["name"] = name
    context.user_data["state"] = "await_question_text"
    await update.message.reply_text(
        f"✅ اسم آزمون: {name}\n\nحالا متن سوال اول رو بفرست:"
    )


async def handle_question_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("متن سوال نمی‌تونه خالی باشه.")
        return
    context.user_data["build"]["current_q"] = {"text": text, "options": []}
    context.user_data["state"] = "await_option_text"
    await update.message.reply_text(
        "گزینه‌ی اول رو بفرست:"
    )


async def handle_option_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("گزینه نمی‌تونه خالی باشه.")
        return
    cq = context.user_data["build"]["current_q"]
    if len(cq["options"]) >= MAX_OPTIONS:
        await update.message.reply_text(
            f"حداکثر {MAX_OPTIONS} گزینه می‌تونی اضافه کنی. روی «✅ پایان گزینه‌ها» بزن.",
            reply_markup=kb.option_collect_kb(),
        )
        return
    cq["options"].append(text)
    n = len(cq["options"])
    if n >= MAX_OPTIONS:
        await update.message.reply_text(
            f"گزینه {n} ثبت شد ✅\nبه سقف {MAX_OPTIONS} گزینه رسیدی، روی دکمه بزن:",
            reply_markup=kb.option_collect_kb(),
        )
        return
    if n < 2:
        await update.message.reply_text(f"گزینه {n} ثبت شد ✅\nگزینه بعدی رو بفرست:")
        return
    await update.message.reply_text(
        f"گزینه {n} ثبت شد ✅\nگزینه بعدی رو بفرست، یا اگه گزینه‌ها تمومه رو دکمه بزن:",
        reply_markup=kb.option_collect_kb(),
    )


async def finish_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    cq = context.user_data.get("build", {}).get("current_q")
    if not cq or len(cq["options"]) < 2:
        await q.answer("حداقل ۲ گزینه لازمه.", show_alert=True)
        return
    context.user_data["state"] = "await_correct_choice"
    await q.answer()
    await q.edit_message_text(
        f"سوال: {cq['text']}\n\nکدوم گزینه جواب صحیحه؟",
        reply_markup=kb.choose_correct_kb(cq["options"]),
    )


async def set_correct_option(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    idx = int(q.data.split(":")[1])
    cq = context.user_data["build"]["current_q"]
    if idx >= len(cq["options"]):
        await q.answer("گزینه نامعتبره.", show_alert=True)
        return
    cq["correct_option"] = idx
    context.user_data["build"]["questions"].append(cq)
    context.user_data["build"]["current_q"] = None
    context.user_data["state"] = None
    n = len(context.user_data["build"]["questions"])
    await q.answer("ثبت شد ✅")
    await q.edit_message_text(
        f"سوال {n} با موفقیت ذخیره شد.\n"
        f"جواب صحیح: {cq['options'][idx]}\n\n"
        "می‌خوای سوال بعدی رو اضافه کنی یا آزمون رو ذخیره کنی؟",
        reply_markup=kb.after_question_kb(),
    )


async def add_more_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    context.user_data["state"] = "await_question_text"
    await q.answer()
    n = len(context.user_data["build"]["questions"]) + 1
    await q.edit_message_text(f"متن سوال {n} رو بفرست:")


async def finish_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    build = context.user_data.get("build")
    uid = q.from_user.id
    if not build or not build["questions"]:
        await q.answer("حداقل باید یه سوال داشته باشی.", show_alert=True)
        return
    quiz_id = db.create_quiz(build["name"], uid)
    for i, qu in enumerate(build["questions"]):
        qid = db.add_question(quiz_id, qu["text"], i, qu["correct_option"])
        for j, opt in enumerate(qu["options"]):
            db.add_option(qid, opt, j)
    context.user_data.clear()
    await q.answer("آزمون ذخیره شد ✅")
    await q.edit_message_text(
        f"🎉 آزمون «{build['name']}» با {len(build['questions'])} سوال ساخته شد.\n\n"
        "حالا برای اجرا: توی گروهت بنویس @نام_ربات و اسم آزمون رو انتخاب کن، "
        "یا از پنل، گزینه‌ی «لیست آزمون‌ها» رو ببین.",
        reply_markup=kb.back_close_kb(),
    )


async def handle_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Single entry point for all private-chat free text, dispatched by state."""
    from handlers_panel import handle_admin_id_text  # local import to avoid circular

    if update.effective_chat.type != "private":
        return
    state = context.user_data.get("state")
    if state == "await_admin_id":
        await handle_admin_id_text(update, context)
        return
    if not db.is_admin(update.effective_user.id):
        return
    if state == "await_edit_quiz_name":
        from handlers_editor import handle_edit_quiz_name

        await handle_edit_quiz_name(update, context)
        return
    if state == "await_edit_q_text":
        from handlers_editor import handle_edit_q_text

        await handle_edit_q_text(update, context)
        return
    if state == "await_edit_opt_text":
        from handlers_editor import handle_edit_opt_text

        await handle_edit_opt_text(update, context)
        return
    if state == "await_edit_new_q_text":
        from handlers_editor import handle_edit_new_q_text

        await handle_edit_new_q_text(update, context)
        return
    if state == "await_edit_new_opt":
        from handlers_editor import handle_edit_new_opt

        await handle_edit_new_opt(update, context)
        return
    if state == "await_quiz_name":
        await handle_quiz_name(update, context)
    elif state == "await_question_text":
        await handle_question_text(update, context)
    elif state == "await_option_text":
        await handle_option_text(update, context)
    # else: ignore free text with no active state
