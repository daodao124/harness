import logging
import os
logger = logging.getLogger("payment-service")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if os.getenv("LOG_FILE"):
        handler = logging.FileHandler(os.environ["LOG_FILE"], encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
