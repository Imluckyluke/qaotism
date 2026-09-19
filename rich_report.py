"""Rich Message rendering for quiz results.

Inspired by https://github.com/mehrab1381pok/telegram-rich-writer
(render.ts / ai.ts deterministic layouts), but fully local:
no Cloudflare, no Workers AI — just deterministic tables.

Sends via raw Bot API `sendRichMessage` with `rich_message: {html, is_rtl}`.
If the Bot API / client doesn't support it, callers must fall back
to the plain-text report.
"""

import html
import logging

import database as db
from config import MEMBERS_CALL_NAME

logger = logging.getLogger(__name__)

MAX_RICH_HTML = 25_000
MAX_COMBINED_RICH_HTML = 30_000

_MEDALS = {0: "🥇", 1: "🥈", 2: "🥉"}


def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _user_label_html(row) -> str:
    label = row["username"] and f"@{row['username']}" or (row["full_name"] or str(row["user_id"]))
    return _esc(label)


def _short(text: str, limit: int = 500) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_rich_chunks(quiz, questions, session_id) -> list:
    """Builds one or more Rich-HTML chunks for the final report.

    Layout (mirrors rich-writer deterministic tables):
      <h1> title </h1>
      <p> meta </p>
      <h2> leaderboard </h2>
      <table bordered striped> ...
      <h2> per-question </h2>
      <table> per question ...

    NOTE: only long-supported attrs are used (bordered/striped).
    Newer attrs like `compact` (10.3) or `expandable` blockquotes are
    avoided on purpose: unknown attrs make the whole call fail with
    Bad Request on servers/clients that don't know them yet.
    """
    total_participants = db.count_participants(session_id)
    board = db.get_leaderboard(session_id)

    head = [
        f"<h1>🏁 نتایج آزمون: {_esc(quiz['name'])}</h1>",
        f"<p>👥 شرکت‌کننده‌ها: <b>{total_participants} نفر</b> | ❓ سوال‌ها: <b>{len(questions)}</b></p>",
        "<h2>🏆 رتبه‌بندی نهایی</h2>",
    ]
    if not board:
        head.append("<p>کسی شرکت نکرد.</p>")
    else:
        rows = []
        for i, p in enumerate(board):
            rank = _MEDALS.get(i, f"{i + 1}")
            name = _user_label_html(p)
            # نفر اول بولد میشه تا تو جدول بدرخشه
            if i == 0:
                name = f"<b>{name}</b>"
            rows.append(
                f"<tr><td>{_esc(rank)}</td><td>{name}</td>"
                f"<td>{int(p['points'])}</td><td>{int(p['correct'])} از {len(questions)}</td></tr>"
            )
        head.append(
            "<table bordered striped>"
            "<tr><th>رتبه</th><th>شرکت‌کننده</th><th>امتیاز</th><th>درست</th></tr>"
            + "".join(rows)
            + "</table>"
        )

    chunks = []
    cur = "\n".join(head)

    def _flush():
        nonlocal cur
        if cur.strip():
            chunks.append(cur)
        cur = ""

    for i, qdata in enumerate(questions, 1):
        answers = db.get_answers_for_question(session_id, qdata["id"])
        counts = {j: 0 for j in range(len(qdata["options"]))}
        for a in answers:
            counts[a["option_index"]] = counts.get(a["option_index"], 0) + 1

        opt_rows = []
        for j, opt in enumerate(qdata["options"]):
            n = counts.get(j, 0)
            pct = (n / total_participants * 100) if total_participants else 0
            icon = "✅" if j == qdata["correct_option"] else "▫️"
            opt_rows.append(
                f"<tr><td>{_esc(icon)}</td><td>{_esc(_short(opt, 200))}</td>"
                f"<td>{pct:.0f}٪</td><td>{n} نفر</td></tr>"
            )
        block = (
            f"<h2>❓ سوال {i}</h2>"
            f"<p><b>{_esc(_short(qdata['text'], 500))}</b></p>"
            "<table bordered striped>"
            "<tr><th></th><th>گزینه</th><th>درصد</th><th>تعداد</th></tr>"
            + "".join(opt_rows)
            + "</table>"
        )
        not_answered = total_participants - len(answers)
        if not_answered > 0:
            block += f"<blockquote>⏳ جواب ندادن: {not_answered} نفر</blockquote>"

        # اگه با اضافه کردن این سوال از سقف رد میشیم، چانک فعلی رو ببند و یکی جدید باز کن
        if len(cur) + 1 + len(block) > MAX_RICH_HTML:
            _flush()
            cur = block
        else:
            cur = cur + "\n" + block if cur else block

    _flush()
    return [c for c in chunks if c.strip()]


def sample_rich_html() -> str:
    """Minimal sample (only long-supported tags) for /testrich diagnostics."""
    return (
        "<h1>تست پیام غنی ✅</h1>"
        "<p>اگه این پیام رو با تیتر و جدول می‌بینی، sendRichMessage کار می‌کنه.</p>"
        "<table bordered striped>"
        "<tr><th>قابلیت</th><th>وضعیت</th></tr>"
        "<tr><td>Rich Message</td><td><b>فعال</b></td></tr>"
        "<tr><td>جدول</td><td>فعال</td></tr>"
        "</table>"
    )


# ---------------- Rich builders for bot screens ----------------

def panel_home_html() -> str:
    return (
        "<h1>🎛 پنل مدیریت آزمون</h1>"
        f"<p>سلام {MEMBERS_CALL_NAME}! 👋<br/>از دکمه‌های زیر استفاده کن.</p>"
    )


def quiz_list_html(quizzes) -> str:
    rows = []
    for r in quizzes:
        rows.append(
            f"<tr><td>{_esc(_short(r['name'], 120))}</td><td>{r['qcount']} سوال</td></tr>"
        )
    return (
        "<h1>📋 لیست آزمون‌ها</h1>"
        "<table bordered striped>"
        "<tr><th>آزمون</th><th>تعداد سوال</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def quiz_detail_html(quiz, questions) -> str:
    rows = []
    for i, qs in enumerate(questions, 1):
        opts = qs["options"]
        correct = opts[qs["correct_option"]] if 0 <= qs["correct_option"] < len(opts) else "—"
        rows.append(
            f"<tr><td>{i}</td><td>{_esc(_short(qs['text'], 150))}</td>"
            f"<td>{len(opts)} گزینه</td><td>{_esc(_short(correct, 80))}</td></tr>"
        )
    body = (
        f"<h1>📝 {_esc(_short(quiz['name'], 150))}</h1>"
        f"<p>تعداد سوالات: <b>{len(questions)}</b></p>"
    )
    if rows:
        body += (
            "<table bordered striped>"
            "<tr><th>#</th><th>سوال</th><th>گزینه‌ها</th><th>جواب درست</th></tr>"
            + "".join(rows)
            + "</table>"
        )
    else:
        body += "<p>هنوز سوالی نداره.</p>"
    return body


def intro_html(quiz_name, count, limit_text, min_points, max_points) -> str:
    return (
        f"<h1>🎯 آزمون: {_esc(_short(quiz_name, 150))}</h1>"
        f"<p>{MEMBERS_CALL_NAME}، هرکی می‌خواد شرکت کنه دکمه‌ی «من یک اوتیسمی پایه هستم» رو بزنه 🙋</p>"
        "<table bordered striped>"
        f"<tr><td>⏱ وقت هر سوال</td><td>{_esc(limit_text)}</td></tr>"
        f"<tr><td>⚡️ امتیاز جواب درست</td><td>{min_points} تا {max_points} (هرچی سریع‌تر، بیشتر)</td></tr>"
        f"<tr><td>👥 شرکت‌کننده‌ها</td><td>{count} نفر</td></tr>"
        "</table>"
        "<blockquote>⚠️ بعد از شروع، دیگه کسی نمی‌تونه اضافه بشه.</blockquote>"
    )


def question_html(qdata, q_index, total, limit_text, participants, answered) -> str:
    opts = []
    for i, opt in enumerate(qdata["options"]):
        opts.append(f"<tr><td>{i + 1}</td><td>{_esc(_short(opt, 200))}</td></tr>")
    return (
        f"<h1>❓ سوال {q_index + 1} از {total}</h1>"
        f"<p>⏱ مهلت پاسخ: {_esc(limit_text)}</p>"
        f"<p><b>{_esc(_short(qdata['text'], 500))}</b></p>"
        "<table bordered striped>"
        "<tr><th>#</th><th>گزینه (برای جواب روی دکمه‌ها بزن)</th></tr>"
        + "".join(opts)
        + "</table>"
        f"<p>👥 {participants} نفر شرکت‌کننده — {answered} نفر جواب دادن</p>"
    )


async def _api_post(bot_token: str, method: str, payload: dict) -> tuple:
    """Raw Bot API POST. Returns (True, data) or (False, reason)."""
    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(url, json=payload)
            try:
                data = resp.json()
            except Exception:
                data = {}
            if resp.status_code != 200 or not data.get("ok", False):
                return False, f"HTTP {resp.status_code}: {str(data)[:300]}"
            return True, data
    except ImportError:
        pass  # فالبک به urllib پایین
    except Exception as e:
        return False, f"transport error: {e}"

    # فالبک بدون httpx (با urllib استاندارد)
    try:
        import asyncio
        import json as _json
        import urllib.error as _urlerr
        import urllib.request as _urlopen

        def _post():
            req = _urlopen.Request(
                url,
                data=_json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            try:
                with _urlopen.urlopen(req, timeout=20) as resp:
                    return _json.loads(resp.read().decode("utf-8"))
            except _urlerr.HTTPError as e:
                try:
                    return _json.loads(e.read().decode("utf-8"))
                except Exception:
                    return {"ok": False, "description": f"HTTP {e.code}"}

        data = await asyncio.to_thread(_post)
        if not data.get("ok", False):
            return False, str(data.get("description", data))[:300]
        return True, data
    except Exception as e:
        return False, f"transport error: {e}"


async def try_edit_rich(
    bot_token: str,
    html: str,
    *,
    chat_id=None,
    message_id=None,
    inline_message_id=None,
    reply_markup_dict=None,
) -> tuple:
    """Edits a message to Rich via editMessageText. Returns (True, "") or (False, reason).

    Either (chat_id + message_id) or inline_message_id must be given.
    reply_markup_dict (already .to_dict()) is attached when given;
    pass {"inline_keyboard": []} to explicitly clear buttons.
    """
    if not html or not bot_token or (not inline_message_id and (chat_id is None or message_id is None)):
        return False, "missing params"
    payload = {"rich_message": {"html": html, "is_rtl": True}}
    if inline_message_id:
        payload["inline_message_id"] = inline_message_id
    else:
        payload["chat_id"] = chat_id
        payload["message_id"] = message_id
    if reply_markup_dict is not None:
        payload["reply_markup"] = reply_markup_dict
    ok, data = await _api_post(bot_token, "editMessageText", payload)
    if not ok:
        logger.warning("editMessageText rich ناموفق بود: %s", data)
    return (True, "") if ok else (False, data)


async def try_send_rich(
    bot_token: str,
    chat_id: int,
    html: str,
    *,
    reply_markup_dict=None,
    reply_to_message_id=None,
) -> tuple:
    """Sends one Rich message via sendRichMessage. Returns (True, "") or (False, reason)."""
    if not html or not bot_token or chat_id is None:
        return False, "missing params"
    payload = {"chat_id": chat_id, "rich_message": {"html": html, "is_rtl": True}}
    if reply_markup_dict is not None:
        payload["reply_markup"] = reply_markup_dict
    if reply_to_message_id:
        payload["reply_parameters"] = {
            "message_id": reply_to_message_id,
            "allow_sending_without_reply": True,
        }
    ok, data = await _api_post(bot_token, "sendRichMessage", payload)
    if not ok:
        logger.warning("sendRichMessage ناموفق بود: %s", data)
    return (True, "") if ok else (False, data)


async def edit_rich_inline(bot_token: str, inline_message_id: str, html: str) -> tuple:
    """Back-compat wrapper: rich-edit of an inline message, clearing buttons."""
    return await try_edit_rich(
        bot_token, html,
        inline_message_id=inline_message_id,
        reply_markup_dict={"inline_keyboard": []},
    )


async def send_rich_chunks(
    bot_token: str, chat_id: int, html_chunks: list, reply_to_message_id=None
) -> tuple:
    """Sends html chunks via raw Bot API `sendRichMessage`.

    Returns (True, "") on success, (False, reason) on any error so the
    caller can fall back to plain text (and /testrich can show the reason).
    """
    if not html_chunks:
        return False, "nothing to send"
    if not bot_token:
        return False, "BOT_TOKEN is empty"

    for chunk in html_chunks:
        payload = {
            "chat_id": chat_id,
            "rich_message": {"html": chunk, "is_rtl": True},
        }
        if reply_to_message_id:
            payload["reply_parameters"] = {
                "message_id": reply_to_message_id,
                "allow_sending_without_reply": True,
            }
            reply_to_message_id = None  # فقط پیام اول ریپلای میشه تا اسپم نشه
        ok, data = await _api_post(bot_token, "sendRichMessage", payload)
        if not ok:
            logger.warning("sendRichMessage ناموفق بود: %s", data)
            return False, data
    return True, ""
