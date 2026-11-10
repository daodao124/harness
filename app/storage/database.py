import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from app.core.config import DATABASE_PATH
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
@contextmanager
def connection():
    db = sqlite3.connect(DATABASE_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    finally:
        db.close()
def init_db():
    with connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS service_state (id INTEGER PRIMARY KEY CHECK(id=1), status TEXT NOT NULL, updated TEXT NOT NULL, message TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS status_history (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, reason TEXT NOT NULL, timestamp TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL, amount REAL NOT NULL, currency TEXT NOT NULL, timestamp TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, level TEXT NOT NULL, service TEXT NOT NULL, event TEXT NOT NULL, message TEXT NOT NULL, request_id TEXT);
        CREATE TABLE IF NOT EXISTS faults (id INTEGER PRIMARY KEY AUTOINCREMENT, fault_type TEXT NOT NULL, expires_at REAL NOT NULL, created_at TEXT NOT NULL);
        """)
        db.execute("INSERT OR IGNORE INTO service_state VALUES(1,'healthy',?,?)", (now_iso(), "Payment service operating normally"))
        db.execute("INSERT OR IGNORE INTO status_history(status,reason,timestamp) SELECT 'healthy','Initial state',? WHERE NOT EXISTS(SELECT 1 FROM status_history)", (now_iso(),))
def log(level: str, event: str, message: str, request_id: str | None = None):
    with connection() as db:
        db.execute("INSERT INTO logs(timestamp,level,service,event,message,request_id) VALUES(?,?,?,?,?,?)", (now_iso(), level, "payment-service", event, message, request_id))
