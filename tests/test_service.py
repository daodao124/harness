from fastapi.testclient import TestClient
import time
def setup_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH",str(tmp_path/"test.db"))
    monkeypatch.setenv("DEMO_ADMIN_API_KEY","test-key")
    from app.core import config
    config.DATABASE_PATH=str(tmp_path/"test.db")
    from app.storage import database
    database.DATABASE_PATH=config.DATABASE_PATH
    from app import main
    main.startup()
    return TestClient(main.app)
def test_service_workflow(tmp_path,monkeypatch):
    c=setup_app(tmp_path,monkeypatch); h={"X-Demo-Admin-Key":"test-key"}
    assert c.get("/status").json()["status"]=="healthy"
    assert c.post("/demo/simulate-failure",headers=h,json={"status":"down","reason":"db down"}).status_code==200
    assert c.get("/health").status_code==200
    assert c.post("/payments",json={"order_id":"x","amount":5,"currency":"USD"}).status_code==503
    assert c.get("/logs").json()["logs"]
    assert c.post("/demo/recover",headers=h).json()["status"]=="healthy"
    assert c.post("/payments",json={"order_id":"y","amount":5,"currency":"USD"}).status_code==200
    assert c.get("/metrics").json()["successful_payments"]==1
    assert c.post("/demo/reset",headers=h).status_code==200
def test_fault_auth_validation(tmp_path,monkeypatch):
    c=setup_app(tmp_path,monkeypatch)
    assert c.post("/demo/recover").status_code==401
    h={"X-Demo-Admin-Key":"test-key"}
    assert c.post("/demo/inject-fault",headers=h,json={"fault_type":"high_latency","duration_seconds":1}).status_code==200
    assert c.post("/payments",json={"order_id":"x","amount":-1,"currency":"USD"}).status_code==422
def test_fault_applies_and_expires(tmp_path,monkeypatch):
    c=setup_app(tmp_path,monkeypatch); h={"X-Demo-Admin-Key":"test-key"}
    assert c.post("/demo/inject-fault",headers=h,json={"fault_type":"service_unavailable","duration_seconds":1}).status_code==200
    body={"order_id":"faulty","amount":1,"currency":"USD"}
    assert c.post("/payments",json=body).status_code==503
    time.sleep(1.05)
    assert c.post("/payments",json=body).status_code==200
def test_state_survives_database_reinitialization(tmp_path,monkeypatch):
    c=setup_app(tmp_path,monkeypatch); h={"X-Demo-Admin-Key":"test-key"}
    c.post("/demo/simulate-failure",headers=h,json={"status":"degraded","reason":"partial outage"})
    from app.storage.database import init_db
    init_db()
    assert c.get("/status").json()["status"]=="degraded"
