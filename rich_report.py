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

logger = logging.getLogger(__name__)

MAX_RICH_HTML = 25_000

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
      <table bordered striped compact> ...
      <h2> per-question </h2>
      <table> per question ...
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
            "<table bordered striped compact>"
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
            "<table bordered striped compact>"
            "<tr><th></th><th>گزینه</th><th>درصد</th><th>تعداد</th></tr>"
            + "".join(opt_rows)
            + "</table>"
        )
        not_answered = total_participants - len(answers)
        if not_answered > 0:
            block += f"<blockquote expandable>⏳ جواب ندادن: {not_answered} نفر</blockquote>"

        # اگه با اضافه کردن این سوال از سقف رد میشیم، چانک فعلی رو ببند و یکی جدید باز کن
        if len(cur) + 1 + len(block) > MAX_RICH_HTML:
            _flush()
            cur = block
        else:
            cur = cur + "\n" + block if cur else block

    _flush()
    return [c for c in chunks if c.strip()]


async def send_rich_chunks(bot_token: str, chat_id: int, html_chunks: list, reply_to_message_id=None) -> bool:
    """Sends html chunks via raw Bot API `sendRichMessage`. Returns True on success.

    Returns False on any error so the caller can fall back to plain text.
    """
    if not html_chunks or not bot_token:
        return False

    payloads = []
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
        payloads.append(payload)
        reply_to_message_id = None  # فقط پیام اول ریپلای میشه تا اسپم نشه

    url = f"https://api.telegram.org/bot{bot_token}/sendRichMessage"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=20) as client:
            for payload in payloads:
                resp = await client.post(url, json=payload)
                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                if resp.status_code != 200 or not data.get("ok", False):
                    logger.warning("sendRichMessage ناموفق بود: %s %s", resp.status_code, str(data)[:500])
                    return False
        return True
    except ImportError:
        pass  # فالبک به urllib پایین
    except Exception:
        logger.exception("ارسال Rich Message ناموفق بود؛ فالبک به متن ساده.")
        return False

    # فالبک بدون httpx (با urllib استاندارد، چون PTB همیشه httpx نداره تو همه محیط‌ها)
    try:
        import asyncio
        import json as _json
        import urllib.request as _urlopen

        def _post(payload):
            req = _urlopen.Request(
                url,
                data=_json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            with _urlopen.urlopen(req, timeout=20) as resp:
                return _json.loads(resp.read().decode("utf-8"))

        for payload in payloads:
            data = await asyncio.to_thread(_post, payload)
            if not data.get("ok", False):
                logger.warning("sendRichMessage ناموفق بود: %s", str(data)[:500])
                return False
        return True
    except Exception:
        logger.exception("ارسال Rich Message ناموفق بود؛ فالبک به متن ساده.")
        return False
