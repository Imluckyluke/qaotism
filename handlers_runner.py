import asyncio
import logging
import time
import uuid

from telegram import (
    Update,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from telegram.error import BadRequest, NetworkError, RetryAfter, TelegramError
from telegram.ext import ContextTypes

import database as db
import keyboards as kb
import rich_report
from config import BOT_TOKEN, MAX_POINTS, MEMBERS_CALL_NAME, MIN_POINTS, QUESTION_TIME_LIMIT, RICH_RESULTS

logger = logging.getLogger(__name__)

# ---------------- امتیاز و زمان ----------------

def calc_points(elapsed: float, limit: float = QUESTION_TIME_LIMIT) -> int:
    """امتیاز جواب درست: هرچی زودتر، بیشتر (خطی از MAX_POINTS تا MIN_POINTS)."""
    if limit <= 0:
        return MAX_POINTS
    ratio = min(max(elapsed / limit, 0.0), 1.0)
    return round(MAX_POINTS - (MAX_POINTS - MIN_POINTS) * ratio)


def _fmt_limit() -> str:
    if QUESTION_TIME_LIMIT % 60 == 0:
        return f"{QUESTION_TIME_LIMIT // 60} دقیقه"
    return f"{QUESTION_TIME_LIMIT} ثانیه"


# برای جلوگیری از تداخل «تایمر تموم شد» با «آخرین نفر جواب داد» با «ادمین رد کرد»
_locks = {}


def _lock_for(session_id: int) -> asyncio.Lock:
    lock = _locks.get(session_id)
    if lock is None:
        lock = _locks[session_id] = asyncio.Lock()
    return lock


def _timer_name(session_id: int, q_index: int) -> str:
    return f"qtimer:{session_id}:{q_index}"


def _schedule_timeout(job_queue, session_id: int, q_index: int, delay: float):
    _cancel_timeout(job_queue, session_id, q_index)
    job_queue.run_once(
        _timeout_job,
        when=max(delay, 0.5),
        name=_timer_name(session_id, q_index),
        data={"session_id": session_id, "q_index": q_index},
    )


def _cancel_timeout(job_queue, session_id: int, q_index: int):
    for job in job_queue.get_jobs_by_name(_timer_name(session_id, q_index)):
        job.schedule_removal()


RETRY_DELAY = 5  # ثانیه؛ اگه رفتن به سوال بعد خطا داد، تایمر بعد از این مدت دوباره تلاش می‌کنه


async def _timeout_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    try:
        await advance_question(context, data["session_id"], data["q_index"])
    except TelegramError:
        # نذار سوال گم بشه: سوال فعلی همچنان فعاله و دوباره تلاش می‌کنیم
        logger.exception("رفتن به سوال بعد ناموفق بود؛ %s ثانیه دیگه دوباره تلاش میشه", RETRY_DELAY)
        _schedule_timeout(context.job_queue, data["session_id"], data["q_index"], RETRY_DELAY)


async def recover_running_sessions(application):
    """بعد از ری‌استارت ربات، تایمر آزمون‌های در حال اجرا رو دوباره برقرار می‌کنه."""
    for s in db.get_running_sessions():
        started = s["question_started_at"] or time.time()
        remaining = QUESTION_TIME_LIMIT - (time.time() - started)
        _schedule_timeout(application.job_queue, s["id"], s["current_index"], remaining)
        logger.info("تایمر آزمون %s (سوال %s) بازیابی شد.", s["id"], s["current_index"] + 1)


async def _retry(func, attempts: int = 3):
    """ارسال پیام با چندبار تلاش مجدد برای خطاهای موقت (فشار تلگرام / قطعی شبکه)."""
    for i in range(attempts):
        try:
            return await func()
        except RetryAfter as e:
            if i == attempts - 1:
                raise
            await asyncio.sleep(e.retry_after + 1)
        except BadRequest:
            raise  # خطای دائمی (مثلاً نبود اجازه‌ی ارسال)؛ تکرارش فایده‌ای نداره
        except NetworkError:
            if i == attempts - 1:
                raise
            await asyncio.sleep(1)


# ---------------- Inline query ----------------

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
        if not r["qcount"]:
            continue
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


# ---------------- ارسال / ویرایش سوال ----------------

async def _edit_session_message(context, session, text, reply_markup=None):
    """Edits the quiz message whether it's a normal group message or one
    sent via an inline query result (which only has an inline_message_id)."""
    if session["inline_message_id"]:
        await context.bot.edit_message_text(
            inline_message_id=session["inline_message_id"],
            text=text,
            reply_markup=reply_markup,
        )
    else:
        await context.bot.edit_message_text(
            chat_id=session["chat_id"],
            message_id=session["message_id"],
            text=text,
            reply_markup=reply_markup,
        )


def _question_text(session_id, qdata, q_index, total):
    return (
        f"❓ سوال {q_index + 1} از {total}\n"
        f"⏱ مهلت پاسخ: {_fmt_limit()}\n\n"
        f"{qdata['text']}\n\n"
        f"👥 {db.count_participants(session_id)} نفر شرکت کننده — "
        f"{db.count_answers(session_id, qdata['id'])} نفر جواب دادن"
    )


async def _send_question(context, session, q_index):
    """سوال q_index رو نمایش میده، لحظه‌ی شروع رو ثبت می‌کنه و تایمر رو راه میندازه."""
    session_id = session["id"]
    questions = db.get_questions(session["quiz_id"])
    qdata = questions[q_index]
    text = _question_text(session_id, qdata, q_index, len(questions))
    markup = kb.question_kb(session_id, q_index, qdata["options"])
    await _retry(lambda: _edit_session_message(context, session, text, markup))

    # از همین لحظه که سوال دیده میشه، ساعت می‌افته
    db.set_question_state(session_id, time.time())
    _schedule_timeout(context.job_queue, session_id, q_index, QUESTION_TIME_LIMIT)


async def _refresh_question(context, session, qdata, q_index, total):
    """شمارنده‌ی جواب‌ها رو به‌روز می‌کنه. خطاهای بی‌اهمیت نادیده گرفته میشن."""
    text = _question_text(session["id"], qdata, q_index, total)
    markup = kb.question_kb(session["id"], q_index, qdata["options"])
    try:
        await _edit_session_message(context, session, text, markup)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.warning("ویرایش پیام سوال ناموفق بود: %s", e)
    except TelegramError as e:
        logger.warning("ویرایش پیام سوال ناموفق بود: %s", e)


_MEDALS = {0: "🥇", 1: "🥈", 2: "🥉"}

# کاراکترهای کنترل جهت متن (Unicode bidi) برای اینکه آی‌دی انگلیسی
# وسط جمله‌ی فارسی باعث بهم‌ریختگی چیدمان نشه.
RLM = "\u200f"   # شروع خط با جهت راست‌به‌چپ
FSI = "\u2068"   # ایزوله‌کردن اسم (جهتش خودکار تشخیص داده میشه)
PDI = "\u2069"   # پایان ایزوله
SEP = "━━━━━━━━━━━━━━"


def _user_label(row):
    """اسم/آی‌دی کاربر، ایزوله‌شده تا با متن فارسی قاطی نشه."""
    label = row["username"] and f"@{row['username']}" or (row["full_name"] or str(row["user_id"]))
    return f"{FSI}{label}{PDI}"


def _build_leaderboard_section(session_id, total_questions):
    board = db.get_leaderboard(session_id)
    lines = [f"{RLM}🏆 رتبه‌بندی نهایی", SEP]
    if not board:
        lines.append(f"{RLM}کسی شرکت نکرد.")
        return "\n".join(lines)
    for i, p in enumerate(board):
        rank = _MEDALS.get(i, f"{i+1}.")
        title = "اوتیسمی کیری خفن: " if i == 0 else ""
        lines.append(
            f"{RLM}{rank} {title}{_user_label(p)}{RLM} — {p['points']} امتیاز "
            f"({p['correct']} از {total_questions} درست)"
        )
    return "\n".join(lines)


def _build_final_report(quiz, questions, session_id):
    total_participants = db.count_participants(session_id)
    lines = [
        f"{RLM}🏁 نتایج آزمون: {quiz['name']}",
        f"{RLM}👥 شرکت‌کننده‌ها: {total_participants} نفر",
        "",
        _build_leaderboard_section(session_id, len(questions)),
        "",
        f"{RLM}📊 آمار سوال‌ها",
        SEP,
    ]
    for i, qdata in enumerate(questions, 1):
        answers = db.get_answers_for_question(session_id, qdata["id"])
        counts = {j: 0 for j in range(len(qdata["options"]))}
        for a in answers:
            counts[a["option_index"]] = counts.get(a["option_index"], 0) + 1

        lines.append(f"{RLM}❓ سوال {i}: {qdata['text']}")
        for j, opt in enumerate(qdata["options"]):
            n = counts.get(j, 0)
            pct = (n / total_participants * 100) if total_participants else 0
            icon = "✅" if j == qdata["correct_option"] else "▫️"
            lines.append(f"{RLM}{icon} {j+1}) {opt} — {pct:.0f}٪ ({n} نفر)")
        not_answered = total_participants - len(answers)
        if not_answered > 0:
            lines.append(f"{RLM}⏳ جواب ندادن: {not_answered} نفر")
        lines.append("")
    return "\n".join(lines).rstrip()


async def _finish_quiz(context, session):
    session_id = session["id"]
    quiz_id = session["quiz_id"]
    quiz = db.get_quiz(quiz_id)
    questions = db.get_questions(quiz_id)
    db.set_session_status(session_id, "finished")
    _locks.pop(session_id, None)
    if not quiz or not questions:
        await _edit_session_message(context, session, "این آزمون توسط ادمین حذف شده، پس همین‌جا تمومش می‌کنیم.")
        return

    if session["inline_message_id"]:
        # Inline-sent messages have no known chat_id, so the message itself
        # is edited -- first try a Rich edit, then fall back to plain text.
        if RICH_RESULTS and BOT_TOKEN:
            try:
                html_chunks = rich_report.build_rich_chunks(quiz, questions, session_id)
                combined = "\n".join(html_chunks)
                if len(combined) <= 30_000:
                    ok, reason = await rich_report.edit_rich_inline(
                        BOT_TOKEN, session["inline_message_id"], combined
                    )
                    if ok:
                        return
                    logger.warning("Rich Message نشد (%s)؛ فالبک به متن ساده.", reason)
            except Exception:
                logger.exception("ساخت/ارسال Rich Message ناموفق بود؛ فالبک به متن ساده.")
        report = _build_final_report(quiz, questions, session_id)
        if len(report) > 4000:
            report = report[:3950] + "\n\n… (نتیجه طولانی بود و خلاصه شد)"
        await _edit_session_message(context, session, report)
        return

    # نتیجه‌ی Rich (به سبک telegram-rich-writer): تیتر + جدول، با فالبک به متن ساده.
    if RICH_RESULTS and session["chat_id"]:
        try:
            html_chunks = rich_report.build_rich_chunks(quiz, questions, session_id)
            ok, reason = await rich_report.send_rich_chunks(
                BOT_TOKEN, session["chat_id"], html_chunks,
                reply_to_message_id=session["message_id"],
            )
            if ok:
                await _edit_session_message(
                    context, session,
                    f"🏁 نتایج آزمون «{quiz['name']}» 👇",
                )
                return
            logger.warning("Rich Message نشد (%s)؛ فالبک به متن ساده.", reason)
        except Exception:
            logger.exception("ساخت/ارسال Rich Message ناموفق بود؛ فالبک به متن ساده.")
        # اگه به هر دلیلی Rich نشد، ادامه بده با متن ساده (کد قبلی)

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

    await _edit_session_message(context, session, chunks[0])
    for extra in chunks[1:]:
        await context.bot.send_message(chat_id=session["chat_id"], text=extra)


async def _advance_locked(context, session):
    """رفتن به سوال بعد (یا پایان آزمون). فراخوان باید قفل سشن رو گرفته باشه.

    ترتیب مهمه: اول سوال بعدی باید *با موفقیت* نمایش داده بشه، بعد ایندکس عوض میشه.
    اگه ارسال خطا بده، هیچی عوض نمیشه و سوال فعلی با تایمرش سر جاش می‌مونه
    (تایمر یا دکمه‌ی ادمین دوباره تلاش می‌کنن)؛ پس سوالی گم نمیشه."""
    session_id = session["id"]
    idx = session["current_index"]
    next_index = idx + 1
    questions = db.get_questions(session["quiz_id"])
    if not questions or next_index >= len(questions):
        _cancel_timeout(context.job_queue, session_id, idx)
        await _finish_quiz(context, session)
        return
    await _send_question(context, session, next_index)  # اگه خطا بده، همین‌جا قطع میشه
    db.set_session_index(session_id, next_index)
    _cancel_timeout(context.job_queue, session_id, idx)


async def advance_question(context, session_id: int, expected_index: int) -> bool:
    """رفتن به سوال بعد، به شرط اینکه هنوز روی سوال expected_index باشیم
    (برای اینکه تایمر/رد کردن/جواب آخرین نفر باعث دوبار پریدن نشن)."""
    async with _lock_for(session_id):
        session = db.get_session(session_id)
        if not session or session["status"] != "running" or session["current_index"] != expected_index:
            return False
        await _advance_locked(context, session)
        return True


def _intro_text(quiz, count):
    return (
        f"🎯 آزمون: {quiz['name']}\n\n"
        f"{MEMBERS_CALL_NAME}، هرکی می‌خواد شرکت کنه دکمه‌ی «من یک اوتیسمی پایه هستم» رو بزنه 🙋\n"
        f"⏱ هر سوال {_fmt_limit()} وقت داره.\n"
        f"⚡️ جواب درست هرچی سریع‌تر باشه امتیاز بیشتری داره ({MIN_POINTS} تا {MAX_POINTS} امتیاز).\n"
        f"⚠️ بعد از شروع، دیگه کسی نمی‌تونه اضافه بشه.\n\n"
        f"👥 شرکت‌کننده‌ها: {count} نفر"
    )


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
        if not db.get_questions(quiz_id):
            await q.answer("این آزمون هیچ سوالی نداره و قابل اجرا نیست.", show_alert=True)
            return True

        if q.message is not None:
            # normal message (e.g. sent directly in the group)
            session_id = db.create_session(
                quiz_id, user.id, chat_id=q.message.chat.id, message_id=q.message.message_id
            )
        else:
            # message sent via inline query result -> only inline_message_id is known
            session_id = db.create_session(
                quiz_id, user.id, inline_message_id=q.inline_message_id
            )

        await q.answer()
        await q.edit_message_text(_intro_text(quiz, 0), reply_markup=kb.join_kb(session_id))
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
        try:
            await q.edit_message_text(_intro_text(quiz, count), reply_markup=kb.join_kb(session_id))
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                raise
        return True

    if data.startswith("go:"):
        session_id = int(data.split(":")[1])
        async with _lock_for(session_id):
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
            session = db.get_session(session_id)
            try:
                await _send_question(context, session, 0)
            except TelegramError as e:
                logger.exception("شروع آزمون ناموفق بود")
                db.set_session_status(session_id, "joining")
                await q.answer(
                    f"ارسال سوال ناموفق بود ({e}). مطمئن شو ربات اجازه‌ی ویرایش پیام رو داره.",
                    show_alert=True,
                )
                return True
        await q.answer("آزمون شروع شد 🚀")
        return True

    if data.startswith("a:"):
        _, session_id, q_index, opt_index = data.split(":")
        session_id, q_index, opt_index = int(session_id), int(q_index), int(opt_index)
        async with _lock_for(session_id):
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
            if not 0 <= opt_index < len(qdata["options"]):
                await q.answer("گزینه نامعتبره.", show_alert=True)
                return True
            if db.has_answered(session_id, qdata["id"], user.id):
                await q.answer("قبلاً به این سوال جواب دادی ✅", show_alert=True)
                return True

            now = time.time()
            elapsed = max(0.0, now - (session["question_started_at"] or now))
            if elapsed >= QUESTION_TIME_LIMIT:
                # تایمر هنوز نرسیده اجرا بشه، ولی مهلت تموم شده
                await q.answer("⏰ وقت این سوال تموم شده.", show_alert=True)
                try:
                    await _advance_locked(context, session)
                except TelegramError:
                    logger.exception("رفتن به سوال بعد ناموفق بود؛ %s ثانیه دیگه دوباره تلاش میشه", RETRY_DELAY)
                    _schedule_timeout(context.job_queue, session_id, q_index, RETRY_DELAY)
                return True

            is_correct = opt_index == qdata["correct_option"]
            points = calc_points(elapsed) if is_correct else 0
            db.record_answer(session_id, qdata["id"], user.id, opt_index, elapsed, points, is_correct)
            # ثبت سایلنت: هیچ پاپ‌آپی روی صفحه‌ی کاربر نمیاد (فقط اسپینر دکمه می‌ایسته)
            await q.answer()

            # update visible answered-count without revealing choices
            await _refresh_question(context, session, qdata, q_index, len(questions))

            if db.count_answers(session_id, qdata["id"]) >= db.count_participants(session_id):
                try:
                    await _advance_locked(context, db.get_session(session_id))
                except TelegramError:
                    logger.exception("رفتن به سوال بعد ناموفق بود؛ %s ثانیه دیگه دوباره تلاش میشه", RETRY_DELAY)
                    _schedule_timeout(context.job_queue, session_id, q_index, RETRY_DELAY)
        return True

    if data.startswith("skip:"):
        parts = data.split(":")
        session_id = int(parts[1])
        session = db.get_session(session_id)
        if not session or session["status"] != "running":
            await q.answer("این آزمون فعال نیست.", show_alert=True)
            return True
        is_creator = user.id == session["started_by"]
        if not (db.is_admin(user.id) or is_creator):
            await q.answer("⛔️ فقط ادمین یا سازنده‌ی آزمون می‌تونه رد کنه.", show_alert=True)
            return True
        expected = int(parts[2]) if len(parts) > 2 else session["current_index"]
        try:
            moved = await advance_question(context, session_id, expected)
        except TelegramError:
            logger.exception("رد کردن سوال ناموفق بود؛ %s ثانیه دیگه دوباره تلاش میشه", RETRY_DELAY)
            _schedule_timeout(context.job_queue, session_id, expected, RETRY_DELAY)
            await q.answer("ارسال سوال بعدی ناموفق بود؛ چند ثانیه دیگه دوباره تلاش میشه.", show_alert=True)
            return True
        if moved:
            await q.answer("رفتیم سوال بعدی ⏭")
        else:
            await q.answer("این سوال قبلاً رد شده.", show_alert=True)
        return True

    return False
