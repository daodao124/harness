import random
from app.core.config import DEGRADED_FAILURE_RATE, RANDOM_SEED
from app.storage.database import connection, now_iso, log
rng = random.Random(RANDOM_SEED)
def state():
    with connection() as db:
        return db.execute("SELECT status,updated,message FROM service_state WHERE id=1").fetchone()
def set_state(status: str, reason: str):
    timestamp = now_iso()
    message = reason if status != "healthy" else "Payment service operating normally"
    with connection() as db:
        db.execute("UPDATE service_state SET status=?,updated=?,message=? WHERE id=1", (status,timestamp,message))
        db.execute("INSERT INTO status_history(status,reason,timestamp) VALUES(?,?,?)", (status,reason,timestamp))
    ev = {"down":"service_outage","degraded":"service_degraded","healthy":"service_recovered"}[status]
    log("ERROR" if status == "down" else "WARNING" if status == "degraded" else "INFO", ev, reason)
def reset():
    global rng
    rng = random.Random(RANDOM_SEED)
    with connection() as db:
        db.execute("DELETE FROM payments"); db.execute("DELETE FROM logs"); db.execute("DELETE FROM status_history")
        db.execute("UPDATE service_state SET status='healthy',updated=?,message='Payment service operating normally' WHERE id=1", (now_iso(),))
        db.execute("INSERT INTO status_history(status,reason,timestamp) VALUES('healthy','Demo reset',?)",(now_iso(),))
def process_payment(order_id: str, amount: float, currency: str, request_id: str):
    current = state()["status"]
    if current == "down":
        log("ERROR","payment_failed","Payment rejected because service is unavailable",request_id)
        return False, "Service unavailable"
    if current == "degraded" and rng.random() < DEGRADED_FAILURE_RATE:
        log("ERROR","payment_failed","Payment processing failed during degraded operation",request_id)
        return False, "Simulated processing failure"
    with connection() as db:
        db.execute("INSERT INTO payments(order_id,amount,currency,timestamp) VALUES(?,?,?,?)",(order_id,amount,currency,now_iso()))
    log("INFO","payment_succeeded","Payment processed successfully",request_id)
    return True, "Payment processed successfully"
