"""Run a tiny real H2O AutoML experiment for deployment smoke testing."""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from h2o_framework import ExperimentConfig, H2OExperiment, H2ORuntime


def main() -> None:
    """Train one small model and verify that evidence/model artifacts are created."""

    runtime = H2ORuntime()
    with tempfile.TemporaryDirectory(prefix="h2o-framework-smoke-") as directory:
        root = Path(directory)
        dataset = root / "binary.csv"
        with dataset.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["x1", "x2", "segment", "label"])
            for index in range(160):
                x1 = index % 17
                x2 = (index * 7) % 23
                segment = ("north", "central", "south")[index % 3]
                label = int(x1 + x2 > 18)
                writer.writerow([x1, x2, segment, label])

        result = H2OExperiment(
            ExperimentConfig(
                target="label",
                task="classification",
                metric="AUC",
                time_budget=15,
                max_models=1,
                nfolds=2,
                include_algos=("GBM", "GLM"),
                distribution="bernoulli",
                stopping_metric="AUC",
                max_runtime_per_model=10,
                preprocessing=("target_encoding",),
            ),
            runtime=runtime,
        ).fit(dataset, root / "experiment")

        assert result.leader_model_id
        assert result.leaderboard
        assert result.row_counts["test"] > 0
        assert Path(result.artifacts["binary_model"]).exists()
        print(
            {
                "leader": result.leader_model_id,
                "metrics": result.metrics,
                "rows": result.row_counts,
                "artifacts": sorted(result.artifacts),
            }
        )

    # The script owns this short-lived cluster. The web service deliberately keeps its
    # shared cluster alive between requests instead.
    runtime.client().cluster().shutdown(prompt=False)


if __name__ == "__main__":
    main()
