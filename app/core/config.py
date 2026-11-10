import os
DATABASE_PATH = os.getenv("DATABASE_PATH", "./payment_service.db")
DEMO_ADMIN_API_KEY = os.getenv("DEMO_ADMIN_API_KEY", "change-me")
DEGRADED_FAILURE_RATE = min(1.0, max(0.0, float(os.getenv("DEGRADED_FAILURE_RATE", "0.5"))))
RANDOM_SEED = int(os.getenv("RANDOM_SEED", "7"))
MAX_FAULT_DURATION_SECONDS = int(os.getenv("MAX_FAULT_DURATION_SECONDS", "3600"))
