import asyncio
import uuid
from datetime import datetime
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from app.core.config import DEMO_ADMIN_API_KEY
from app.models.schemas import FailureRequest, FaultRequest, PaymentRequest
from app.storage.database import init_db, connection, log
from app.services import payment_service, fault_simulator

app = FastAPI(title="Mock Payment Service", version="1.0.0")
@app.on_event("startup")
def startup(): init_db()
@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    code = "UNAUTHORIZED" if exc.status_code == 401 else "SERVICE_UNAVAILABLE" if exc.status_code == 503 else "HTTP_ERROR"
    return JSONResponse(status_code=exc.status_code, content={"error":{"code":code,"message":str(exc.detail),"details":{}}})
def admin(key: str | None):
    if not key or key != DEMO_ADMIN_API_KEY: raise HTTPException(401, "Valid demo admin API key required")
def status_body():
    row=payment_service.state()
    return {"service_name":"payment-service","status":row["status"],"last_updated":row["updated"],"message":row["message"]}
@app.get("/health")
def health(): return {"status":"ok","service":"mock-payment-api"}
@app.get("/status")
def status(): return status_body()
@app.post("/demo/simulate-failure")
def simulate_failure(body: FailureRequest, x_demo_admin_key: str | None = Header(default=None)):
    admin(x_demo_admin_key); payment_service.set_state(body.status,body.reason); return status_body()
@app.post("/demo/recover")
def recover(x_demo_admin_key: str | None = Header(default=None)):
    admin(x_demo_admin_key); payment_service.set_state("healthy","Payment service recovered"); return status_body()
@app.post("/demo/reset")
def reset(x_demo_admin_key: str | None = Header(default=None)):
    admin(x_demo_admin_key); payment_service.reset(); fault_simulator.clear(); return status_body()
@app.post("/demo/inject-fault")
def inject_fault(body: FaultRequest, x_demo_admin_key: str | None = Header(default=None)):
    admin(x_demo_admin_key); fault_simulator.inject(body.fault_type,body.duration_seconds)
    return {"fault_type":body.fault_type,"expires_in_seconds":body.duration_seconds,"active":True}
@app.post("/payments")
async def payments(body: PaymentRequest, request: Request):
    request_id=request.headers.get("x-request-id","req-"+uuid.uuid4().hex[:12])
    faults=fault_simulator.active_faults()
    if "high_latency" in faults: await asyncio.sleep(2)
    if payment_service.state()["status"]=="down" or faults.intersection({"service_unavailable","database_connection_error"}):
        dbfault="database_connection_error" in faults
        log("ERROR","database_connection_failed" if dbfault else "payment_failed","Unable to connect to payment database" if dbfault else "Payment service unavailable",request_id)
        raise HTTPException(503,"Payment service unavailable")
    if "intermittent_failure" in faults:
        from app.services.payment_service import rng
        if rng.randrange(2)==0:
            log("ERROR","payment_failed","Intermittent simulated payment failure",request_id)
            raise HTTPException(503,"Intermittent simulated failure")
    ok,message=payment_service.process_payment(body.order_id,body.amount,body.currency,request_id)
    if not ok: raise HTTPException(503,message)
    return {"status":"succeeded","message":message,"order_id":body.order_id,"request_id":request_id}
@app.get("/logs")
def logs(limit:int=Query(100,ge=1,le=1000),level:str|None=None,start_time:datetime|None=None,end_time:datetime|None=None):
    clauses=[]; params=[]
    if level: clauses.append("level=?"); params.append(level.upper())
    if start_time: clauses.append("timestamp>=?"); params.append(start_time.isoformat().replace("+00:00","Z"))
    if end_time: clauses.append("timestamp<=?"); params.append(end_time.isoformat().replace("+00:00","Z"))
    sql="SELECT timestamp,level,service,event,message,request_id FROM logs"+(" WHERE "+" AND ".join(clauses) if clauses else "")+" ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with connection() as db: rows=db.execute(sql,params).fetchall()
    return {"logs":[dict(r) for r in rows]}
@app.get("/metrics")
def metrics():
    with connection() as db:
        total=db.execute("SELECT COUNT(*) FROM logs WHERE event IN ('payment_succeeded','payment_failed')").fetchone()[0]
        success=db.execute("SELECT COUNT(*) FROM logs WHERE event='payment_succeeded'").fetchone()[0]
    failed=total-success
    return {"total_payment_requests":total,"successful_payments":success,"failed_payments":failed,"error_rate":failed/total if total else 0.0,"status":payment_service.state()["status"]}
