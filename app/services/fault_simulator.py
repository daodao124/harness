import time
from app.storage.database import connection, now_iso, log
def active_faults() -> set[str]:
    now = time.time()
    with connection() as db:
        db.execute("DELETE FROM faults WHERE expires_at <= ?", (now,))
        return {row[0] for row in db.execute("SELECT DISTINCT fault_type FROM faults WHERE expires_at > ?", (now,))}
def inject(fault_type: str, duration: int):
    with connection() as db:
        db.execute("INSERT INTO faults(fault_type,expires_at,created_at) VALUES(?,?,?)", (fault_type, time.time()+duration, now_iso()))
    log("WARNING", "fault_injected", f"Fault {fault_type} injected for {duration}s", error_code=fault_type.upper(), details={"fault_type": fault_type, "duration_seconds": duration})
def clear():
    with connection() as db:
        cleared = db.execute("DELETE FROM faults").rowcount
    log("INFO", "faults_cleared", "All injected faults cleared", details={"cleared": cleared})
