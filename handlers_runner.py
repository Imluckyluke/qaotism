import uuid

from telegram import (
    Update,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from telegram.ext import ContextTypes

import database as db
import keyboards as kb
from config import MEMBERS_CALL_NAME


async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    iq = update.inline_query
    uid = iq.from_user.id
    if not db.is_admin(uid):
        await iq.answer([], cache_time=1)
        return
    search = iq.query.strip()
    rows = db.list_quizzes(search if search else None)
    results = []
    for r in rows[:20]:
        results.append(
            InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title=f"📝 {r['name']}",
                description=f"{r['qcount']} سوال",
                input_message_content=InputTextMessageContent(
                    f"🎯 آزمون آماده‌ی اجراست: «{r['name']}»\n\n"
                    f"{MEMBERS_CALL_NAME}، برای شروع دکمه‌ی زیر رو بزنید 👇"
                ),
                reply_markup=kb.init_quiz_kb(r["id"]),
            )
        )
    await iq.answer(results, cache_time=1)


def _fmt_name(user):
    if user.username:
        return f"@{user.username}"
    return user.full_name or str(user.id)


async def _send_question(context, chat_id, message_id, session_id, quiz_id, q_index):
    questions = db.get_questions(quiz_id)
    total = len(questions)
    qdata = questions[q_index]
    text = (
        f"❓ سوال {q_index + 1} از {total}\n\n"
        f"{qdata['text']}\n\n"
        f"👥 {db.count_participants(session_id)} نفر شرکت کننده — "
        f"{db.count_answers(session_id, qdata['id'])} نفر جواب دادن"
    )
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        reply_markup=kb.question_kb(session_id, q_index, qdata["options"]),
    )


_MEDALS = {0: "🥇", 1: "🥈", 2: "🥉"}


def _build_leaderboard_section(session_id, total_questions):
    board = db.get_leaderboard(session_id)
    lines = ["🏆 رتبه‌بندی نهایی:"]
    if not board:
        lines.append("کسی شرکت نکرد.")
        return "\n".join(lines)
    for i, p in enumerate(board):
        label = p["username"] and f"@{p['username']}" or (p["full_name"] or str(p["user_id"]))
        rank = _MEDALS.get(i, f"{i+1}.")
        lines.append(f"{rank} {label} — {p['score']} از {total_questions} درست")
    return "\n".join(lines)


def _build_final_report(quiz, questions, session_id):
    lines = [f"🏁 نتایج آزمون: {quiz['name']}\n"]
    lines.append(_build_leaderboard_section(session_id, len(questions)))
    lines.append("")
    total_participants = db.count_participants(session_id)
    for i, qdata in enumerate(questions, 1):
        lines.append(f"—————————")
        lines.append(f"سوال {i}: {qdata['text']}")
        answers = db.get_answers_for_question(session_id, qdata["id"])
        by_option = {j: [] for j in range(len(qdata["options"]))}
        for a in answers:
            by_option.setdefault(a["option_index"], []).append(
                a["username"] and f"@{a['username']}" or (a["full_name"] or str(a["user_id"]))
            )
        answered_count = len(answers)
        for j, opt in enumerate(qdata["options"]):
            names = by_option.get(j, [])
            pct = (len(names) / total_participants * 100) if total_participants else 0
            mark = " ✅" if j == qdata["correct_option"] else ""
            names_str = "، ".join(names) if names else "—"
            lines.append(f"{j+1}) {opt}{mark} — {pct:.0f}% ({len(names)} نفر): {names_str}")
        not_answered = total_participants - answered_count
        if not_answered > 0:
            lines.append(f"⏳ جواب ندادن: {not_answered} نفر")
        lines.append("")
    return "\n".join(lines)


async def _finish_quiz(context, chat_id, message_id, session_id, quiz_id):
    quiz = db.get_quiz(quiz_id)
    questions = db.get_questions(quiz_id)
    db.set_session_status(session_id, "finished")
    report = _build_final_report(quiz, questions, session_id)

    # Telegram messages are capped at 4096 chars; split if needed.
    chunks = []
    cur = ""
    for line in report.split("\n"):
        if len(cur) + len(line) + 1 > 3900:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    if cur:
        chunks.append(cur)

    await context.bot.edit_message_text(
        chat_id=chat_id, message_id=message_id, text=chunks[0]
    )
    for extra in chunks[1:]:
        await context.bot.send_message(chat_id=chat_id, text=extra)


async def _advance(context, session):
    session_id = session["id"]
    chat_id = session["chat_id"]
    message_id = session["message_id"]
    quiz_id = session["quiz_id"]
    next_index = session["current_index"] + 1
    questions = db.get_questions(quiz_id)
    if next_index >= len(questions):
        await _finish_quiz(context, chat_id, message_id, session_id, quiz_id)
    else:
        db.set_session_index(session_id, next_index)
        await _send_question(context, chat_id, message_id, session_id, quiz_id, next_index)


async def session_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handles callback_data for init/join/start/answer/skip.
    Returns True if it handled the callback."""
    q = update.callback_query
    data = q.data
    user = q.from_user

    if data.startswith("init:"):
        quiz_id = int(data.split(":")[1])
        if not db.is_admin(user.id):
            await q.answer("⛔️ فقط ادمین‌ها می‌تونن آزمون رو شروع کنن.", show_alert=True)
            return True
        quiz = db.get_quiz(quiz_id)
        if not quiz:
            await q.answer("این آزمون دیگه وجود نداره.", show_alert=True)
            return True
        chat_id = q.message.chat.id
        session_id = db.create_session(quiz_id, chat_id, user.id)
        db.set_session_message(session_id, q.message.message_id)
        await q.answer()
        await q.edit_message_text(
            f"🎯 آزمون: {quiz['name']}\n\n"
            f"{MEMBERS_CALL_NAME}، هرکی می‌خواد شرکت کنه دکمه‌ی «من هستم» رو بزنه 🙋\n"
            f"⚠️ بعد از شروع، دیگه کسی نمی‌تونه اضافه بشه.\n\n"
            f"👥 شرکت‌کننده‌ها: 0 نفر",
            reply_markup=kb.join_kb(session_id),
        )
        return True

    if data.startswith("j:"):
        session_id = int(data.split(":")[1])
        session = db.get_session(session_id)
        if not session or session["status"] != "joining":
            await q.answer("زمان ثبت‌نام برای این آزمون تموم شده.", show_alert=True)
            return True
        added = db.add_participant(session_id, user.id, user.full_name, user.username)
        if added:
            await q.answer("ثبت شدی ✅ منتظر شروع بمون.")
        else:
            await q.answer("قبلاً ثبت‌نام کردی 😉")
        quiz = db.get_quiz(session["quiz_id"])
        count = db.count_participants(session_id)
        await q.edit_message_text(
            f"🎯 آزمون: {quiz['name']}\n\n"
            f"{MEMBERS_CALL_NAME}، هرکی می‌خواد شرکت کنه دکمه‌ی «من هستم» رو بزنه 🙋\n"
            f"⚠️ بعد از شروع، دیگه کسی نمی‌تونه اضافه بشه.\n\n"
            f"👥 شرکت‌کننده‌ها: {count} نفر",
            reply_markup=kb.join_kb(session_id),
        )
        return True

    if data.startswith("go:"):
        session_id = int(data.split(":")[1])
        session = db.get_session(session_id)
        if not session or session["status"] != "joining":
            await q.answer("این آزمون قبلاً شروع شده.", show_alert=True)
            return True
        is_creator = user.id == session["started_by"]
        if not (db.is_admin(user.id) or is_creator):
            await q.answer("⛔️ فقط ادمین یا سازنده‌ی آزمون می‌تونه شروع کنه.", show_alert=True)
            return True
        if db.count_participants(session_id) == 0:
            await q.answer("هنوز کسی ثبت‌نام نکرده!", show_alert=True)
            return True
        db.set_session_status(session_id, "running")
        db.set_session_index(session_id, 0)
        await q.answer("آزمون شروع شد 🚀")
        await _send_question(
            context, session["chat_id"], session["message_id"], session_id, session["quiz_id"], 0
        )
        return True

    if data.startswith("a:"):
        _, session_id, q_index, opt_index = data.split(":")
        session_id, q_index, opt_index = int(session_id), int(q_index), int(opt_index)
        session = db.get_session(session_id)
        if not session or session["status"] != "running":
            await q.answer("این آزمون فعال نیست.", show_alert=True)
            return True
        if q_index != session["current_index"]:
            await q.answer("این سوال قبلاً رد شده.", show_alert=True)
            return True
        if not db.is_participant(session_id, user.id):
            await q.answer("تو توی این آزمون ثبت‌نام نکردی!", show_alert=True)
            return True
        questions = db.get_questions(session["quiz_id"])
        qdata = questions[q_index]
        if db.has_answered(session_id, qdata["id"], user.id):
            await q.answer("قبلاً به این سوال جواب دادی ✅", show_alert=True)
            return True
        db.record_answer(session_id, qdata["id"], user.id, opt_index)
        await q.answer("جوابت ثبت شد ✅ (تا آخر آزمون به کسی نشون داده نمیشه)", show_alert=True)

        # update visible answered-count without revealing choices
        await _send_question(
            context, session["chat_id"], session["message_id"], session_id, session["quiz_id"], q_index
        )

        if db.count_answers(session_id, qdata["id"]) >= db.count_participants(session_id):
            await _advance(context, db.get_session(session_id))
        return True

    if data.startswith("skip:"):
        session_id = int(data.split(":")[1])
        session = db.get_session(session_id)
        if not session or session["status"] != "running":
            await q.answer("این آزمون فعال نیست.", show_alert=True)
            return True
        is_creator = user.id == session["started_by"]
        if not (db.is_admin(user.id) or is_creator):
            await q.answer("⛔️ فقط ادمین یا سازنده‌ی آزمون می‌تونه رد کنه.", show_alert=True)
            return True
        await q.answer("رفتیم سوال بعدی ⏭")
        await _advance(context, session)
        return True

    return False
