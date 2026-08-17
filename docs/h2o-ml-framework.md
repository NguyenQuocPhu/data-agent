# H2O ML Studio (PoC)

H2O ML Studio is a user-facing tabular ML framework. H2O-3 is its only training engine;
it is intentionally separate from the chat Agent and persona pipeline.

## Scope

- Binary and multiclass classification
- Regression
- H2O AutoML with time/model budgets and 5-fold CV by default
- Native AutoML controls for algorithm selection, distribution, stopping metric,
  per-model runtime and experimental target encoding
- Optional class balancing for classification
- An untouched final test split
- Persistent experiment manifests, leaderboard, metrics and variable importance
- H2O binary model and MOJO export when supported
- Batch prediction from a completed experiment

The default split is 70% train, 15% validation and 15% final test. When cross-validation
is enabled, H2O selects the leader from CV metrics. When it is disabled, the validation
frame becomes the leaderboard frame. The final test frame is never used for selection.

## Website

Start the existing application and open:

```text
http://localhost:3014/ml
```

From there a user can upload a CSV/TSV/Parquet/Excel file, select the target and task,
start a background experiment, inspect the final-test metrics/leaderboard and download
the artifacts. Experiment state is stored under:

```text
workspace/<session_id>/Experiments/H2O/<experiment_id>/
```

## Python API

```python
from h2o_framework import ExperimentConfig, H2OExperiment

config = ExperimentConfig(
    target="churn",
    task="classification",
    metric="AUC",
    time_budget=300,
    balance_classes=True,
    include_algos=("GBM", "XGBoost", "DRF", "GLM", "StackedEnsemble"),
    stopping_metric="AUC",
    max_runtime_per_model=60,
    preprocessing=("target_encoding",),
)

result = H2OExperiment(config).fit(
    "workspace/default/Files/customers.csv",
    "workspace/default/Experiments/manual-run",
)

print(result.metrics)
print(result.leaderboard[:5])
```

## REST API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/ml/health` | Check whether the Python client/cluster is ready |
| `GET` | `/ml/health?connect=true` | Start/connect the configured H2O cluster |
| `GET` | `/ml/datasets` | List compatible workspace datasets and schemas |
| `POST` | `/ml/datasets/upload` | Upload ML data without invoking the chat Agent |
| `POST` | `/ml/experiments` | Queue an AutoML experiment |
| `GET` | `/ml/experiments` | List persisted experiments |
| `GET` | `/ml/experiments/{id}` | Poll one experiment |
| `POST` | `/ml/experiments/{id}/predict` | Batch-score another workspace dataset |

Example request:

```json
{
  "session_id": "default",
  "dataset_id": "59aebed1",
  "target": "churn",
  "task": "classification",
  "metric": "AUC",
  "time_budget": 300,
  "max_models": null,
  "nfolds": 5,
  "train_ratio": 0.7,
  "validation_ratio": 0.15,
  "seed": 42,
  "balance_classes": false,
  "ignored_columns": [],
  "include_algos": ["GBM", "XGBoost", "DRF", "GLM", "StackedEnsemble"],
  "distribution": "AUTO",
  "stopping_metric": "AUC",
  "max_runtime_per_model": 60,
  "preprocessing": ["target_encoding"]
}
```

An empty `include_algos` list leaves algorithm choice to H2O. The only preprocessing
step currently accepted by H2O AutoML 3.46 is the experimental `target_encoding` option;
the framework does not perform an additional preprocessing pass.

## Runtime configuration

By default the backend starts one local H2O Java cluster lazily on port 54321. To connect
to a separately hosted cluster, set `H2O_URL`.

```dotenv
H2O_URL=
H2O_MAX_MEM_SIZE=4G
H2O_NTHREADS=-1
H2O_MAX_CONCURRENT_EXPERIMENTS=1
```

The PoC defaults to one concurrent AutoML experiment because an individual H2O job already
uses multiple cores and concurrent searches can exhaust the JVM heap.
