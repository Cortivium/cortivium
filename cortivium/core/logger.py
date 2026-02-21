"""Logging configuration."""

import logging
import sys


def setup_logging(level: str = "info") -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger("cortivium")
    root.setLevel(numeric_level)
    root.addHandler(handler)
    root.propagate = False

    # Quiet uvicorn access logs
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
