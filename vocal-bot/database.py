"""
База данных SQLite для бота записи на занятия.

Таблицы:
- users: информация о клиентах
- appointments: записи на приём (дата, время, статус)
"""

import sqlite3
from datetime import datetime, timedelta
from config import DATABASE_PATH


def get_db() -> sqlite3.Connection:
    """Подключение к базе с поддержкой dict-строк."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Создание таблиц при первом запуске."""
    conn = get_db()
    conn.executescript("""
        -- Пользователи
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,         -- Telegram user_id
            name TEXT NOT NULL,             -- Полное имя
            username TEXT                   -- @username
        );

        -- Записи на приём
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,       -- Кто записан
            date TEXT NOT NULL,             -- Дата (YYYY-MM-DD)
            time TEXT NOT NULL,             -- Время (HH:MM)
            status TEXT DEFAULT 'active',   -- active / cancelled
            reminded INTEGER DEFAULT 0,     -- Напоминание отправлено (0/1)
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)
    conn.commit()
    conn.close()


# === Пользователи ===

def save_user(user_id: int, name: str, username: str | None):
    """Сохранить или обновить пользователя."""
    conn = get_db()
    conn.execute(
        """INSERT INTO users (id, name, username) VALUES (?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET name=?, username=?""",
        (user_id, name, username, name, username),
    )
    conn.commit()
    conn.close()


def get_user(user_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# === Расписание ===

DAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
WORK_HOURS = list(range(10, 18))  # 10:00 — 17:00 (последний слот)


def get_available_dates() -> list[dict]:
    """Ближайшие 7 рабочих дней (пн-сб)."""
    today = datetime.now()
    dates = []
    for i in range(1, 10):  # с запасом, чтобы набрать 7 рабочих
        day = today + timedelta(days=i)
        if day.weekday() == 6:  # воскресенье — пропускаем
            continue
        dates.append({
            "date": day.strftime("%Y-%m-%d"),
            "label": f"{DAY_NAMES[day.weekday()]} {day.strftime('%d.%m')}",
        })
        if len(dates) == 7:
            break
    return dates


def get_available_slots(date_str: str) -> list[str]:
    """Свободные часовые слоты на дату."""
    conn = get_db()
    # Какие слоты уже заняты
    booked = conn.execute(
        "SELECT time FROM appointments WHERE date=? AND status='active'",
        (date_str,),
    ).fetchall()
    conn.close()

    booked_times = {row["time"] for row in booked}
    # Все рабочие часы минус занятые
    return [f"{h:02d}:00" for h in WORK_HOURS if f"{h:02d}:00" not in booked_times]


# === Записи ===

def create_appointment(user_id: int, date_str: str, time_str: str) -> int:
    """Создать запись. Возвращает id записи."""
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO appointments (user_id, date, time) VALUES (?, ?, ?)",
        (user_id, date_str, time_str),
    )
    conn.commit()
    appt_id = cursor.lastrowid
    conn.close()
    return appt_id


def get_user_appointments(user_id: int) -> list[dict]:
    """Активные записи пользователя (будущие)."""
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM appointments
           WHERE user_id=? AND status='active' AND date >= date('now')
           ORDER BY date, time""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def cancel_appointment(appt_id: int) -> dict | None:
    """Отменить запись. Возвращает данные отменённой записи."""
    conn = get_db()
    row = conn.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
    if row:
        conn.execute(
            "UPDATE appointments SET status='cancelled' WHERE id=?", (appt_id,)
        )
        conn.commit()
    conn.close()
    return dict(row) if row else None


def get_appointment(appt_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# === Напоминания ===

def get_appointments_to_remind() -> list[dict]:
    """Записи, до которых осталось меньше 1 часа и напоминание не отправлено."""
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM appointments
           WHERE status='active'
             AND reminded=0
             AND datetime(date || ' ' || time) > datetime('now')
             AND datetime(date || ' ' || time) <= datetime('now', '+1 hour')"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_reminded(appt_id: int):
    """Пометить, что напоминание отправлено."""
    conn = get_db()
    conn.execute("UPDATE appointments SET reminded=1 WHERE id=?", (appt_id,))
    conn.commit()
    conn.close()


# === Статистика (для админа) ===

def get_appointments_for_date(date_str: str) -> list[dict]:
    """Все записи на дату (для админа)."""
    conn = get_db()
    rows = conn.execute(
        """SELECT a.*, u.name, u.username
           FROM appointments a JOIN users u ON a.user_id = u.id
           WHERE a.date=? AND a.status='active'
           ORDER BY a.time""",
        (date_str,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
