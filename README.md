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

## Operations agent harness

Install the project and harness dependencies in the active virtual environment:

    python -m pip install -r requirements.txt

The agent can use either the OpenAI API or a local Ollama model. Select the provider with `LLM_PROVIDER` in the process environment:

- `LLM_PROVIDER=api` uses `OPENAI_MODEL` and `OPENAI_API_KEY`. Set `OPENAI_BASE_URL` only for an OpenAI-compatible API endpoint.
- `LLM_PROVIDER=local` uses `OLLAMA_MODEL` and `OLLAMA_BASE_URL`. Install/start Ollama and pull a model that supports tool calling, for example `ollama pull qwen3:8b`.

The same choice can be passed directly as `OperationsAgent(llm_provider="api")` or `OperationsAgent(llm_provider="local")`; `model=` overrides the provider's model name. Passing `llm=` continues to accept a custom LangChain chat model instance. Set `AGENT_MAX_EXECUTION_SECONDS` (default `120`) to limit the total run time, including time spent waiting for a human approval.

### Tools and agent loop

The registry in `harness/core/registry.py` defines each tool's description, Pydantic input and output schemas, timeout, and whether approval is required:

| Tool | Purpose | Approval |
| --- | --- | --- |
| `get_service_status` | Read payment service status | No |
| `get_error_logs` | Read and filter payment service logs | No |
| `search_knowledge_base` | Search local runbooks and, when needed, Milvus | No |
| `create_incident` | Create an incident record | Yes |

The loop sends the objective and conversation to the selected chat model. It executes one returned tool call at a time, appends the validated result to the conversation and tool history, then asks the model for the next action or a final answer. It stops on a final answer, a failure, the configured maximum tool steps (default `8`), or the total execution deadline. The graph uses an in-memory checkpointer by default; callers can provide another LangGraph checkpointer.

The status and error-log tools call the local payment service at `http://127.0.0.1:8001`, so start that service before using them. Knowledge-base search first uses the local BM25 runbooks and can fall back to semantic retrieval through Sentence Transformers and Milvus. `create_incident` pauses for explicit approval before writing; the approval grant is one-time and bound to the validated tool arguments.

### Validation and error handling

Tool inputs are validated before execution; unknown fields are rejected and each tool's constraints are enforced. Tool results are validated against their output schema before they are returned to the model. Failures are returned with codes such as `UNKNOWN_TOOL`, `INVALID_ARGUMENTS`, `TOOL_TIMEOUT`, `INVALID_TOOL_OUTPUT`, or `TOOL_EXECUTION_FAILED`. The loop also handles LLM request timeouts, malformed response types, and invalid or multiple tool calls by ending the run with a failure state.

Read-tool retries remain configured for up to three total attempts with a 0.5-second initial interval for recognized transient error codes. The executor currently maps many underlying network exceptions to the generic `TOOL_EXECUTION_FAILED` code, so those errors do not trigger the retry policy unless a tool returns one of the configured retry codes. Each tool also has its own timeout; the agent-wide deadline bounds the full run.

### Observability and history

Each tool call is stored in `tool_history` with its arguments and result, and the graph state keeps the message sequence, step count, and status. Tool calls and approval decisions create LangSmith spans when tracing is enabled with `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY`. Tool spans record the tool name, call ID, outcome, error code, and duration without including raw arguments or approval tokens. Python logging records LLM and tool execution exceptions.

Run an objective from the command line with:

    python -m harness.cli "Check the payment service status"

Choose the provider per run with `--provider local` or `--provider api`; `--model MODEL_NAME` overrides the selected provider's default model. Set a per-run limit with `--max-seconds 60`. If the agent proposes creating an incident, the CLI asks for approval before resuming.

## Tests

Run the harness tests:

    python -m pytest -q tests/test_agent_harness.py

Run all project tests:

    python -m pytest -q
