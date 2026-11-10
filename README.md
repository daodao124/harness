# Mock Payment Service

A local FastAPI payment simulation for monitoring and operations workflows. SQLite stores durable service state, status history, payment records, faults, and structured logs. No real payment provider is contacted.

## Run

    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    export DEMO_ADMIN_API_KEY=local-demo-secret
    uvicorn app.main:app --reload --port 8001

OpenAPI UI: http://localhost:8001/docs. Configuration comes from environment variables; see .env.example.

## API

- GET /health: API liveness, available even when simulated payments are down.
- GET /status: simulated operational state.
- POST /payments: JSON body {"order_id":"ORDER-001","amount":150,"currency":"USD"}.
- GET /logs?limit=100&level=ERROR&start_time=...&end_time=...: structured logs.
- GET /metrics: payment totals, successes, failures, error rate and state.
- POST /demo/simulate-failure: set status and reason, for example {"status":"down","reason":"Database connection failure"}.
- POST /demo/recover: restore healthy state.
- POST /demo/reset: reset state and clear generated logs, payments and faults.
- POST /demo/inject-fault: JSON {"fault_type":"high_latency","duration_seconds":10}. Other types: database_connection_error, service_unavailable, intermittent_failure.

All demo controls require the X-Demo-Admin-Key header matching DEMO_ADMIN_API_KEY. Supported statuses are healthy, degraded, down. Supported currencies are USD, EUR, GBP, CAD, AUD, JPY. Degraded mode deterministically samples failures at DEGRADED_FAILURE_RATE (default 0.5). Faults expire automatically. High latency is asynchronous and only affects payment requests.

Example outage:

    curl -X POST localhost:8001/demo/simulate-failure -H 'Content-Type: application/json' -H 'X-Demo-Admin-Key: local-demo-secret' -d '{"status":"down","reason":"Database connection failure"}'
    curl localhost:8001/health
    curl localhost:8001/status
    curl -X POST localhost:8001/demo/recover -H 'X-Demo-Admin-Key: local-demo-secret'

## Future Agent Harness

Use GET endpoints with monitoring credentials. Keep the demo key reserved for authorized simulation controls. Request IDs are included in payment logs for correlation.

## Tests

    pytest -q
