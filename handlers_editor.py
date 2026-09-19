"""Edit flows for existing quizzes (admin only, private chat).

Callbacks (handled here, routed from main.callback_query_router):
  qedit:<quiz_id>            edit menu
  qedit_name:<quiz_id>       ask new quiz name  -> state await_edit_quiz_name
  qedit_qs:<quiz_id>         question list for editing
  qedit_q:<question_id>      single-question edit menu
  qedit_qtext:<question_id>  ask new question text -> state await_edit_q_text
  qedit_opts:<question_id>   option list for editing
  qedit_opt:<qid>:<idx>      ask new option text -> state await_edit_opt_text
  qedit_qcorr:<question_id>  choose new correct option (ecorrect:<qid>:<idx>)
  qedit_qdel:<question_id>   delete confirm
  qedit_qdelok:<question_id> delete + back to question list
  qedit_addq:<quiz_id>       add new question -> state await_edit_new_q_text
  eopt_done                  finish collecting options for the new question
  ecorrect:<qid>:<idx>       (for qedit_qcorr) set new correct option

Edits are blocked while the quiz has joining/running sessions,
because runner reads questions live.
"""

from telegram import Update
from telegram.ext import ContextTypes

import database as db
import keyboards as kb
from handlers_builder import MAX_OPTIONS


def _blocked_text() -> str:
    return "این آزمون الان در حال اجراست؛ اول اجراش تموم بشه بعد ویرایش کن."


async def _show_edit_menu(q, quiz_id: int):
    quiz = db.get_quiz(quiz_id)
    if not quiz:
        await q.answer()
        await q.edit_message_text("این آزمون دیگه وجود نداره.", reply_markup=kb.back_close_kb("mk_list"))
        return
    await q.answer()
    await q.edit_message_text(
        f"✏️ ویرایش آزمون: {quiz['name']}\nچی رو تغییر بدم؟",
        reply_markup=kb.quiz_edit_menu_kb(quiz_id),
    )


async def _show_questions(q, quiz_id: int):
    quiz = db.get_quiz(quiz_id)
    if not quiz:
        await q.answer()
        await q.edit_message_text("این آزمون دیگه وجود نداره.", reply_markup=kb.back_close_kb("mk_list"))
        return
    questions = db.get_questions(quiz_id)
    await q.answer()
    if not questions:
        await q.edit_message_text(
            f"✏️ «{quiz['name']}» هنوز سوالی نداره. یه سوال جدید اضافه کن:",
            reply_markup=kb.quiz_edit_menu_kb(quiz_id),
        )
        return
    await q.edit_message_text(
        "کدوم سوال رو ویرایش کنم؟", reply_markup=kb.quiz_edit_questions_kb(quiz_id, questions)
    )


async def _show_question(q, question_id: int):
    qs = db.get_question(question_id)
    if not qs:
        await q.answer("این سوال دیگه وجود نداره.", show_alert=True)
        return
    lines = [f"❓ {qs['text']}", ""]
    for i, opt in enumerate(qs["options"]):
        mark = "✅" if i == qs["correct_option"] else "▫️"
        lines.append(f"{mark} {i+1}) {opt}")
    await q.answer()
    await q.edit_message_text(
        "\n".join(lines), reply_markup=kb.question_edit_kb(question_id, qs["quiz_id"])
    )


async def edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Returns True if the callback was handled here."""
    q = update.callback_query
    data = q.data

    # خنثی کردن state متنی قبلی وقتی کاربر بین منوها می‌چرخه (جلوگیری از rename اشتباهی).
    # کال‌بک‌هایی که خودشون state جدید می‌سازن (qedit_name/qedit_qtext/qedit_opt/qedit_addq) مستثنا هستن.
    if data.startswith(("qedit:", "qedit_qs:", "qedit_q:", "qedit_opts:", "qedit_qcorr:", "qedit_qdel:")):
        context.user_data["state"] = None
        context.user_data.pop("edit_quiz_id", None)
        context.user_data.pop("edit_question_id", None)
        context.user_data.pop("edit_option_idx", None)
        context.user_data.pop("edit_new_q", None)

    if data.startswith("qedit_name:"):
        quiz_id = int(data.split(":")[1])
        if db.has_active_sessions(quiz_id):
            await q.answer(_blocked_text(), show_alert=True)
            return True
        if not db.get_quiz(quiz_id):
            await q.answer("این آزمون دیگه وجود نداره.", show_alert=True)
            return True
        context.user_data["state"] = "await_edit_quiz_name"
        context.user_data["edit_quiz_id"] = quiz_id
        await q.answer()
        await q.edit_message_text("اسم جدید آزمون رو بفرست:\n\nبرای انصراف /panel رو بزن.")
        return True

    if data.startswith("qedit_qs:"):
        quiz_id = int(data.split(":")[1])
        await _show_questions(q, quiz_id)
        return True

    if data.startswith("qedit_q:") and not data.startswith("qedit_qdel"):
        question_id = int(data.split(":")[1])
        await _show_question(q, question_id)
        return True

    if data.startswith("qedit:"):
        quiz_id = int(data.split(":")[1])
        await _show_edit_menu(q, quiz_id)
        return True

    if data.startswith("qedit_qtext:"):
        question_id = int(data.split(":")[1])
        qs = db.get_question(question_id)
        if not qs:
            await q.answer("این سوال دیگه وجود نداره.", show_alert=True)
            return True
        if db.has_active_sessions(qs["quiz_id"]):
            await q.answer(_blocked_text(), show_alert=True)
            return True
        context.user_data["state"] = "await_edit_q_text"
        context.user_data["edit_question_id"] = question_id
        await q.answer()
        await q.edit_message_text(
            f"متن فعلی:\n{qs['text']}\n\nمتن جدید سوال رو بفرست:"
        )
        return True

    if data.startswith("qedit_opts:"):
        question_id = int(data.split(":")[1])
        qs = db.get_question(question_id)
        if not qs:
            await q.answer("این سوال دیگه وجود نداره.", show_alert=True)
            return True
        await q.answer()
        await q.edit_message_text(
            "کدوم گزینه رو ویرایش کنم؟",
            reply_markup=kb.option_edit_list_kb(question_id, qs["options"]),
        )
        return True

    if data.startswith("qedit_opt:"):
        _, question_id, opt_idx = data.split(":")
        question_id, opt_idx = int(question_id), int(opt_idx)
        qs = db.get_question(question_id)
        if not qs or not 0 <= opt_idx < len(qs["options"]):
            await q.answer("گزینه نامعتبره.", show_alert=True)
            return True
        if db.has_active_sessions(qs["quiz_id"]):
            await q.answer(_blocked_text(), show_alert=True)
            return True
        context.user_data["state"] = "await_edit_opt_text"
        context.user_data["edit_question_id"] = question_id
        context.user_data["edit_option_idx"] = opt_idx
        await q.answer()
        await q.edit_message_text(
            f"گزینه فعلی:\n{qs['options'][opt_idx]}\n\nمتن جدید گزینه رو بفرست:"
        )
        return True

    if data.startswith("qedit_qcorr:"):
        question_id = int(data.split(":")[1])
        qs = db.get_question(question_id)
        if not qs:
            await q.answer("این سوال دیگه وجود نداره.", show_alert=True)
            return True
        if db.has_active_sessions(qs["quiz_id"]):
            await q.answer(_blocked_text(), show_alert=True)
            return True
        await q.answer()
        await q.edit_message_text(
            f"سوال: {qs['text']}\n\nجواب درست جدید کدومه؟",
            reply_markup=kb.edit_choose_correct_kb(question_id, qs["options"]),
        )
        return True

    if data.startswith("ecorrect:"):
        _, question_id, opt_idx = data.split(":")
        question_id, opt_idx = int(question_id), int(opt_idx)
        qs = db.get_question(question_id)
        if not qs or not 0 <= opt_idx < len(qs["options"]):
            await q.answer("گزینه نامعتبره.", show_alert=True)
            return True
        if db.has_active_sessions(qs["quiz_id"]):
            await q.answer(_blocked_text(), show_alert=True)
            return True
        db.update_question_correct(question_id, opt_idx)
        await q.answer("جواب درست عوض شد ✅")
        await _show_question(q, question_id)
        return True

    if data.startswith("qedit_qdel:"):
        question_id = int(data.split(":")[1])
        qs = db.get_question(question_id)
        if not qs:
            await q.answer("این سوال دیگه وجود نداره.", show_alert=True)
            return True
        if db.has_active_sessions(qs["quiz_id"]):
            await q.answer(_blocked_text(), show_alert=True)
            return True
        await q.answer()
        await q.edit_message_text(
            f"مطمئنی می‌خوای این سوال رو حذف کنی؟\n\n{qs['text']}",
            reply_markup=kb.question_delete_confirm_kb(question_id, qs["quiz_id"]),
        )
        return True

    if data.startswith("qedit_qdelok:"):
        question_id = int(data.split(":")[1])
        qs = db.get_question(question_id)
        if not qs:
            await q.answer("این سوال دیگه وجود نداره.", show_alert=True)
            return True
        if db.has_active_sessions(qs["quiz_id"]):
            await q.answer(_blocked_text(), show_alert=True)
            return True
        quiz_id = qs["quiz_id"]
        db.delete_question(question_id)
        await q.answer("سوال حذف شد ✅")
        await _show_questions(q, quiz_id)
        return True

    if data.startswith("qedit_addq:"):
        quiz_id = int(data.split(":")[1])
        if db.has_active_sessions(quiz_id):
            await q.answer(_blocked_text(), show_alert=True)
            return True
        if not db.get_quiz(quiz_id):
            await q.answer("این آزمون دیگه وجود نداره.", show_alert=True)
            return True
        context.user_data["state"] = "await_edit_new_q_text"
        context.user_data["edit_quiz_id"] = quiz_id
        context.user_data["edit_new_q"] = None
        await q.answer()
        await q.edit_message_text("متن سوال جدید رو بفرست:")
        return True

    if data == "eopt_done":
        new_q = context.user_data.get("edit_new_q")
        quiz_id = context.user_data.get("edit_quiz_id")
        if not new_q or len(new_q.get("options", [])) < 2:
            await q.answer("حداقل ۲ گزینه لازمه.", show_alert=True)
            return True
        if not db.get_quiz(quiz_id):
            await q.answer("این آزمون دیگه وجود نداره.", show_alert=True)
            return True
        if db.has_active_sessions(quiz_id):
            await q.answer(_blocked_text(), show_alert=True)
            return True
        context.user_data["state"] = "await_edit_new_correct"
        await q.answer()
        await q.edit_message_text(
            f"سوال: {new_q['text']}\n\nکدوم گزینه جواب صحیحه؟",
            reply_markup=kb.choose_correct_kb(new_q["options"]),
        )
        return True

    return False


# ---------------- free-text states ----------------

async def handle_edit_quiz_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    quiz_id = context.user_data.get("edit_quiz_id")
    if not name:
        await update.message.reply_text("اسم نمی‌تونه خالی باشه. دوباره بفرست:")
        return
    if not db.get_quiz(quiz_id):
        context.user_data.clear()
        await update.message.reply_text("این آزمون دیگه وجود نداره.")
        return
    if db.has_active_sessions(quiz_id):
        context.user_data.clear()
        await update.message.reply_text(_blocked_text())
        return
    db.rename_quiz(quiz_id, name)
    context.user_data.clear()
    await update.message.reply_text(
        f"✅ اسم آزمون عوض شد: {name}",
        reply_markup=kb.back_close_kb(f"qv:{quiz_id}"),
    )


async def handle_edit_q_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    question_id = context.user_data.get("edit_question_id")
    if not text:
        await update.message.reply_text("متن سوال نمی‌تونه خالی باشه.")
        return
    qs = db.get_question(question_id)
    if not qs:
        context.user_data.clear()
        await update.message.reply_text("این سوال دیگه وجود نداره.")
        return
    if db.has_active_sessions(qs["quiz_id"]):
        context.user_data.clear()
        await update.message.reply_text(_blocked_text())
        return
    db.update_question_text(question_id, text)
    quiz_id = qs["quiz_id"]
    context.user_data.clear()
    await update.message.reply_text(
        "✅ متن سوال عوض شد.", reply_markup=kb.back_close_kb(f"qedit_q:{question_id}")
    )


async def handle_edit_opt_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    question_id = context.user_data.get("edit_question_id")
    opt_idx = context.user_data.get("edit_option_idx")
    if not text:
        await update.message.reply_text("گزینه نمی‌تونه خالی باشه.")
        return
    qs = db.get_question(question_id)
    if not qs or opt_idx is None or not 0 <= opt_idx < len(qs["options"]):
        context.user_data.clear()
        await update.message.reply_text("این گزینه دیگه وجود نداره.")
        return
    if db.has_active_sessions(qs["quiz_id"]):
        context.user_data.clear()
        await update.message.reply_text(_blocked_text())
        return
    db.update_option_text(question_id, opt_idx, text)
    context.user_data.clear()
    await update.message.reply_text(
        "✅ گزینه عوض شد.", reply_markup=kb.back_close_kb(f"qedit_q:{question_id}")
    )


async def handle_edit_new_q_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("متن سوال نمی‌تونه خالی باشه.")
        return
    context.user_data["edit_new_q"] = {"text": text, "options": []}
    context.user_data["state"] = "await_edit_new_opt"
    await update.message.reply_text("گزینه‌ی اول سوال جدید رو بفرست:")


async def handle_edit_new_opt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("گزینه نمی‌تونه خالی باشه.")
        return
    new_q = context.user_data.get("edit_new_q")
    if not new_q:
        context.user_data["state"] = "await_edit_new_q_text"
        await update.message.reply_text("متن سوال جدید رو بفرست:")
        return
    if len(new_q["options"]) >= MAX_OPTIONS:
        await update.message.reply_text(
            f"حداکثر {MAX_OPTIONS} گزینه می‌تونی اضافه کنی. روی «✅ پایان گزینه‌ها» بزن.",
            reply_markup=kb.edit_option_collect_kb(),
        )
        return
    new_q["options"].append(text)
    n = len(new_q["options"])
    if n >= MAX_OPTIONS:
        await update.message.reply_text(
            f"گزینه {n} ثبت شد ✅\nبه سقف {MAX_OPTIONS} گزینه رسیدی، روی دکمه بزن:",
            reply_markup=kb.edit_option_collect_kb(),
        )
        return
    if n < 2:
        await update.message.reply_text(f"گزینه {n} ثبت شد ✅\nگزینه بعدی رو بفرست:")
        return
    await update.message.reply_text(
        f"گزینه {n} ثبت شد ✅\nگزینه بعدی رو بفرست، یا اگه تمومه رو دکمه بزن:",
        reply_markup=kb.edit_option_collect_kb(),
    )


async def handle_edit_new_correct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Chosen via bcorrect:<idx> buttons (choose_correct_kb) while adding a question."""
    q = update.callback_query
    idx = int(q.data.split(":")[1])
    new_q = context.user_data.get("edit_new_q")
    quiz_id = context.user_data.get("edit_quiz_id")
    if not new_q or idx >= len(new_q["options"]):
        await q.answer("گزینه نامعتبره.", show_alert=True)
        return
    if not db.get_quiz(quiz_id):
        await q.answer("این آزمون دیگه وجود نداره.", show_alert=True)
        return
    if db.has_active_sessions(quiz_id):
        await q.answer(_blocked_text(), show_alert=True)
        return
    order = db.next_question_order(quiz_id)
    qid = db.add_question(quiz_id, new_q["text"], order, idx)
    for j, opt in enumerate(new_q["options"]):
        db.add_option(qid, opt, j)
    context.user_data.clear()
    await q.answer("سوال اضافه شد ✅")
    await q.edit_message_text(
        f"✅ سوال جدید به آزمون اضافه شد.\nجواب درست: {new_q['options'][idx]}",
        reply_markup=kb.back_close_kb(f"qedit_qs:{quiz_id}"),
    )
