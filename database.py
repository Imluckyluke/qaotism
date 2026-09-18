import sqlite3
from contextlib import contextmanager
from config import DB_PATH, OWNER_ID

SCHEMA = """
CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    added_by INTEGER,
    added_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS quizzes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    creator_id INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    correct_option INTEGER NOT NULL,
    FOREIGN KEY(quiz_id) REFERENCES quizzes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id INTEGER NOT NULL,
    chat_id INTEGER,
    message_id INTEGER,
    status TEXT NOT NULL DEFAULT 'joining',
    current_index INTEGER NOT NULL DEFAULT 0,
    started_by INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    full_name TEXT,
    username TEXT,
    UNIQUE(session_id, user_id)
);

CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    option_index INTEGER NOT NULL,
    UNIQUE(session_id, question_id, user_id)
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# ---------------- Admins ----------------

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def is_admin(user_id: int) -> bool:
    if is_owner(user_id):
        return True
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,)).fetchone()
        return row is not None


def add_admin(user_id: int, username: str, added_by: int) -> bool:
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO admins (user_id, username, added_by) VALUES (?,?,?)",
                (user_id, username, added_by),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def remove_admin(user_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
        return cur.rowcount > 0


def list_admins():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM admins ORDER BY added_at DESC").fetchall()


# ---------------- Quizzes ----------------

def create_quiz(name: str, creator_id: int) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO quizzes (name, creator_id) VALUES (?,?)", (name, creator_id)
        )
        return cur.lastrowid


def delete_quiz(quiz_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM quizzes WHERE id=?", (quiz_id,))


def list_quizzes(search: str = None):
    with get_conn() as conn:
        if search:
            rows = conn.execute(
                """SELECT q.*, (SELECT COUNT(*) FROM questions WHERE quiz_id=q.id) as qcount
                   FROM quizzes q WHERE name LIKE ? ORDER BY created_at DESC""",
                (f"%{search}%",),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT q.*, (SELECT COUNT(*) FROM questions WHERE quiz_id=q.id) as qcount
                   FROM quizzes q ORDER BY created_at DESC"""
            ).fetchall()
        return rows


def get_quiz(quiz_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()


def add_question(quiz_id: int, text: str, order_index: int, correct_option: int) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO questions (quiz_id, text, order_index, correct_option) VALUES (?,?,?,?)",
            (quiz_id, text, order_index, correct_option),
        )
        return cur.lastrowid


def add_option(question_id: int, text: str, order_index: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO options (question_id, text, order_index) VALUES (?,?,?)",
            (question_id, text, order_index),
        )


def get_questions(quiz_id: int):
    """Returns list of dicts: {id, text, correct_option, options: [text,...]}"""
    with get_conn() as conn:
        qrows = conn.execute(
            "SELECT * FROM questions WHERE quiz_id=? ORDER BY order_index ASC", (quiz_id,)
        ).fetchall()
        result = []
        for q in qrows:
            orows = conn.execute(
                "SELECT text FROM options WHERE question_id=? ORDER BY order_index ASC",
                (q["id"],),
            ).fetchall()
            result.append(
                {
                    "id": q["id"],
                    "text": q["text"],
                    "correct_option": q["correct_option"],
                    "options": [o["text"] for o in orows],
                }
            )
        return result


def get_question(question_id: int):
    with get_conn() as conn:
        q = conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
        if not q:
            return None
        orows = conn.execute(
            "SELECT text FROM options WHERE question_id=? ORDER BY order_index ASC",
            (question_id,),
        ).fetchall()
        return {
            "id": q["id"],
            "quiz_id": q["quiz_id"],
            "text": q["text"],
            "correct_option": q["correct_option"],
            "options": [o["text"] for o in orows],
        }


# ---------------- Sessions ----------------

def create_session(quiz_id: int, chat_id: int, started_by: int) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sessions (quiz_id, chat_id, started_by) VALUES (?,?,?)",
            (quiz_id, chat_id, started_by),
        )
        return cur.lastrowid


def set_session_message(session_id: int, message_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE sessions SET message_id=? WHERE id=?", (message_id, session_id))


def get_session(session_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()


def set_session_status(session_id: int, status: str):
    with get_conn() as conn:
        conn.execute("UPDATE sessions SET status=? WHERE id=?", (status, session_id))


def set_session_index(session_id: int, idx: int):
    with get_conn() as conn:
        conn.execute("UPDATE sessions SET current_index=? WHERE id=?", (idx, session_id))


def add_participant(session_id: int, user_id: int, full_name: str, username: str) -> bool:
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO participants (session_id, user_id, full_name, username) VALUES (?,?,?,?)",
                (session_id, user_id, full_name, username),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def get_participants(session_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM participants WHERE session_id=?", (session_id,)
        ).fetchall()


def is_participant(session_id: int, user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM participants WHERE session_id=? AND user_id=?",
            (session_id, user_id),
        ).fetchone()
        return row is not None


def count_participants(session_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM participants WHERE session_id=?", (session_id,)
        ).fetchone()
        return row["c"]


def record_answer(session_id: int, question_id: int, user_id: int, option_index: int) -> bool:
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO answers (session_id, question_id, user_id, option_index) VALUES (?,?,?,?)",
                (session_id, question_id, user_id, option_index),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def has_answered(session_id: int, question_id: int, user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM answers WHERE session_id=? AND question_id=? AND user_id=?",
            (session_id, question_id, user_id),
        ).fetchone()
        return row is not None


def count_answers(session_id: int, question_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM answers WHERE session_id=? AND question_id=?",
            (session_id, question_id),
        ).fetchone()
        return row["c"]


def get_answers_for_question(session_id: int, question_id: int):
    """Returns list of rows: user_id, option_index, full_name, username"""
    with get_conn() as conn:
        return conn.execute(
            """SELECT a.user_id, a.option_index, p.full_name, p.username
               FROM answers a
               JOIN participants p ON p.session_id=a.session_id AND p.user_id=a.user_id
               WHERE a.session_id=? AND a.question_id=?""",
            (session_id, question_id),
        ).fetchall()


def get_leaderboard(session_id: int):
    """Returns list of dicts sorted by score desc: {user_id, full_name, username, score}"""
    with get_conn() as conn:
        participants = conn.execute(
            "SELECT * FROM participants WHERE session_id=?", (session_id,)
        ).fetchall()
        score_rows = conn.execute(
            """SELECT a.user_id, COUNT(*) as score
               FROM answers a
               JOIN questions q ON q.id = a.question_id
               WHERE a.session_id=? AND a.option_index = q.correct_option
               GROUP BY a.user_id""",
            (session_id,),
        ).fetchall()
        score_map = {r["user_id"]: r["score"] for r in score_rows}
        result = [
            {
                "user_id": p["user_id"],
                "full_name": p["full_name"],
                "username": p["username"],
                "score": score_map.get(p["user_id"], 0),
            }
            for p in participants
        ]
        result.sort(key=lambda x: -x["score"])
        return result
