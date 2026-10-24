"""ML training entry-point: generate synthetic data, train forecast + health models."""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Generating synthetic dataset...")

    from app.ml.simulator import generate_dataset
    df = generate_dataset(n_runs=200)
    logger.info("Dataset: %d rows, %d runs", len(df), df["run_id"].nunique())

    logger.info("Training forecast model...")
    from app.ml.forecast import train as train_forecast
    forecast_results = train_forecast(df)
    logger.info("Forecast results: %s", forecast_results)

    logger.info("Training health model...")
    from app.ml.health import train_health
    health_results = train_health(df)
    logger.info("Health results: %s", health_results)

    logger.info("✓ Training complete. Models saved to /app/models/")


if __name__ == "__main__":
    main()
