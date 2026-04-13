import sqlite3
from config import DATABASE_PATH


def get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            inn TEXT,
            tax_system TEXT DEFAULT 'usn6',
            ip_closed_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS income (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            year INTEGER,
            quarter INTEGER,
            amount REAL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            year INTEGER,
            quarter INTEGER,
            payment_type TEXT,  -- 'advance_usn', 'insurance_fixed', 'insurance_1pct'
            amount REAL,
            payment_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            reminder_text TEXT,
            remind_date TEXT,
            is_sent INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );
    """)

    conn.commit()
    conn.close()


def save_user(user_id, username, full_name):
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
        (user_id, username, full_name)
    )
    conn.commit()
    conn.close()


def update_user_field(user_id, field, value):
    conn = get_connection()
    conn.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()


def get_user(user_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_income(user_id, year, quarter, amount, description=""):
    conn = get_connection()
    conn.execute(
        "INSERT INTO income (user_id, year, quarter, amount, description) VALUES (?, ?, ?, ?, ?)",
        (user_id, year, quarter, amount, description)
    )
    conn.commit()
    conn.close()


def get_income(user_id, year):
    conn = get_connection()
    rows = conn.execute(
        "SELECT quarter, SUM(amount) as total FROM income WHERE user_id = ? AND year = ? GROUP BY quarter ORDER BY quarter",
        (user_id, year)
    ).fetchall()
    conn.close()
    return {row["quarter"]: row["total"] for row in rows}


def save_payment(user_id, year, quarter, payment_type, amount, payment_date=""):
    conn = get_connection()
    conn.execute(
        "INSERT INTO payments (user_id, year, quarter, payment_type, amount, payment_date) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, year, quarter, payment_type, amount, payment_date)
    )
    conn.commit()
    conn.close()


def get_payments(user_id, year):
    conn = get_connection()
    rows = conn.execute(
        "SELECT quarter, payment_type, SUM(amount) as total FROM payments WHERE user_id = ? AND year = ? GROUP BY quarter, payment_type",
        (user_id, year)
    ).fetchall()
    conn.close()
    result = {}
    for row in rows:
        q = row["quarter"]
        if q not in result:
            result[q] = {}
        result[q][row["payment_type"]] = row["total"]
    return result


def save_chat_message(user_id, role, content):
    conn = get_connection()
    conn.execute(
        "INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)",
        (user_id, role, content)
    )
    conn.commit()
    conn.close()


def get_chat_history(user_id, limit=20):
    conn = get_connection()
    rows = conn.execute(
        "SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    conn.close()
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]


def clear_chat_history(user_id):
    conn = get_connection()
    conn.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def save_reminder(user_id, reminder_text, remind_date):
    conn = get_connection()
    conn.execute(
        "INSERT INTO reminders (user_id, reminder_text, remind_date) VALUES (?, ?, ?)",
        (user_id, reminder_text, remind_date)
    )
    conn.commit()
    conn.close()


def get_pending_reminders(date_str):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM reminders WHERE remind_date <= ? AND is_sent = 0",
        (date_str,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def mark_reminder_sent(reminder_id):
    conn = get_connection()
    conn.execute("UPDATE reminders SET is_sent = 1 WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()
