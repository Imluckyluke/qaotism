from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import JOIN_BUTTON_TEXT


def main_panel_kb(is_owner: bool):
    rows = [
        [InlineKeyboardButton("➕ ساخت آزمون جدید", callback_data="mk_new")],
        [InlineKeyboardButton("📋 لیست آزمون‌ها", callback_data="mk_list")],
    ]
    if is_owner:
        rows.append([InlineKeyboardButton("👥 مدیریت ادمین‌ها", callback_data="adm_menu")])
    rows.append([InlineKeyboardButton("❌ بستن", callback_data="close")])
    return InlineKeyboardMarkup(rows)


def back_close_kb(back_cb="mk_panel"):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 بازگشت", callback_data=back_cb),
          InlineKeyboardButton("❌ بستن", callback_data="close")]]
    )


def option_collect_kb():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ پایان گزینه‌ها", callback_data="bopt_done")],
            [InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="mk_panel")],
        ]
    )


def choose_correct_kb(options):
    rows = []
    for i, opt in enumerate(options):
        label = opt if len(opt) <= 40 else opt[:37] + "..."
        rows.append([InlineKeyboardButton(f"{i+1}) {label}", callback_data=f"bcorrect:{i}")])
    return InlineKeyboardMarkup(rows)


def after_question_kb():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ سوال بعدی", callback_data="bq_more")],
            [InlineKeyboardButton("✅ پایان و ذخیره آزمون", callback_data="bq_finish")],
        ]
    )


def quiz_list_kb(rows, prefix="qv"):
    kb = []
    for r in rows:
        kb.append(
            [InlineKeyboardButton(f"📝 {r['name']} ({r['qcount']} سوال)", callback_data=f"{prefix}:{r['id']}")]
        )
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="mk_panel")])
    return InlineKeyboardMarkup(kb)


def quiz_detail_kb(quiz_id):
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ ویرایش آزمون", callback_data=f"qedit:{quiz_id}")],
            [InlineKeyboardButton("🗑 حذف آزمون", callback_data=f"qdel:{quiz_id}")],
            [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="mk_list")],
        ]
    )


def quiz_edit_menu_kb(quiz_id):
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📝 تغییر اسم آزمون", callback_data=f"qedit_name:{quiz_id}")],
            [InlineKeyboardButton("❓ مدیریت سوال‌ها", callback_data=f"qedit_qs:{quiz_id}")],
            [InlineKeyboardButton("➕ افزودن سوال جدید", callback_data=f"qedit_addq:{quiz_id}")],
            [InlineKeyboardButton("🔙 بازگشت به آزمون", callback_data=f"qv:{quiz_id}")],
        ]
    )


def quiz_edit_questions_kb(quiz_id, questions):
    rows = []
    for i, qs in enumerate(questions, 1):
        label = qs["text"] if len(qs["text"]) <= 40 else qs["text"][:37] + "..."
        rows.append(
            [InlineKeyboardButton(f"{i}. {label}", callback_data=f"qedit_q:{qs['id']}")]
        )
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"qedit:{quiz_id}")])
    return InlineKeyboardMarkup(rows)


def question_edit_kb(question_id, quiz_id):
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📝 ویرایش متن سوال", callback_data=f"qedit_qtext:{question_id}")],
            [InlineKeyboardButton("🔤 ویرایش گزینه‌ها", callback_data=f"qedit_opts:{question_id}")],
            [InlineKeyboardButton("✅ تغییر جواب درست", callback_data=f"qedit_qcorr:{question_id}")],
            [InlineKeyboardButton("🗑 حذف این سوال", callback_data=f"qedit_qdel:{question_id}")],
            [InlineKeyboardButton("🔙 بازگشت به سوال‌ها", callback_data=f"qedit_qs:{quiz_id}")],
        ]
    )


def question_delete_confirm_kb(question_id, quiz_id):
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ بله، حذف کن", callback_data=f"qedit_qdelok:{question_id}")],
            [InlineKeyboardButton("↩️ انصراف", callback_data=f"qedit_q:{question_id}")],
        ]
    )


def option_edit_list_kb(question_id, options):
    rows = []
    for i, opt in enumerate(options):
        label = opt if len(opt) <= 40 else opt[:37] + "..."
        rows.append(
            [InlineKeyboardButton(f"{i+1}) {label}", callback_data=f"qedit_opt:{question_id}:{i}")]
        )
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"qedit_q:{question_id}")])
    return InlineKeyboardMarkup(rows)


def edit_choose_correct_kb(question_id, options):
    rows = []
    for i, opt in enumerate(options):
        label = opt if len(opt) <= 40 else opt[:37] + "..."
        rows.append(
            [InlineKeyboardButton(f"{i+1}) {label}", callback_data=f"ecorrect:{question_id}:{i}")]
        )
    rows.append([InlineKeyboardButton("🔙 انصراف", callback_data=f"qedit_q:{question_id}")])
    return InlineKeyboardMarkup(rows)


def edit_option_collect_kb():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ پایان گزینه‌ها", callback_data="eopt_done")]]
    )


def quiz_delete_confirm_kb(quiz_id):
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ بله، حذف کن", callback_data=f"qdelok:{quiz_id}")],
            [InlineKeyboardButton("↩️ انصراف", callback_data=f"qv:{quiz_id}")],
        ]
    )


def admin_menu_kb():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ افزودن ادمین", callback_data="adm_add")],
            [InlineKeyboardButton("📋 لیست ادمین‌ها", callback_data="adm_list")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="mk_panel")],
        ]
    )


def admin_list_kb(rows):
    kb = []
    for r in rows:
        label = r["username"] or str(r["user_id"])
        kb.append(
            [InlineKeyboardButton(f"➖ {label}", callback_data=f"adm_rm:{r['user_id']}")]
        )
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="adm_menu")])
    return InlineKeyboardMarkup(kb)


# ---------------- In-group quiz session keyboards ----------------

def init_quiz_kb(quiz_id):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🚀 شروع آزمون", callback_data=f"init:{quiz_id}")]]
    )


def join_kb(session_id):
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(JOIN_BUTTON_TEXT, callback_data=f"j:{session_id}")],
            [InlineKeyboardButton("🚀 بزن بریم شروع کنیم! (فقط ادمین/سازنده)", callback_data=f"go:{session_id}")],
        ]
    )


def question_kb(session_id, q_index, options):
    rows = []
    for i, opt in enumerate(options):
        label = opt if len(opt) <= 60 else opt[:57] + "..."
        rows.append([InlineKeyboardButton(f"{i+1}) {label}", callback_data=f"a:{session_id}:{q_index}:{i}")])
    rows.append([InlineKeyboardButton("⏭ سوال بعدی (فقط ادمین/سازنده)", callback_data=f"skip:{session_id}:{q_index}")])
    return InlineKeyboardMarkup(rows)
