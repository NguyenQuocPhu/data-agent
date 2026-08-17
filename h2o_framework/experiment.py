"""One reproducible H2O AutoML experiment."""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from .errors import InvalidExperimentError
from .runtime import H2ORuntime


TaskType = Literal["classification", "regression"]

SUPPORTED_ALGORITHMS = frozenset(
    {"DRF", "GLM", "XGBoost", "GBM", "DeepLearning", "StackedEnsemble"}
)
CLASSIFICATION_DISTRIBUTIONS = frozenset({"AUTO", "bernoulli", "multinomial"})
REGRESSION_DISTRIBUTIONS = frozenset(
    {"AUTO", "gaussian", "poisson", "gamma", "tweedie", "laplace", "quantile", "huber"}
)
CLASSIFICATION_STOPPING_METRICS = frozenset(
    {"AUTO", "logloss", "AUC", "AUCPR", "misclassification", "mean_per_class_error"}
)
REGRESSION_STOPPING_METRICS = frozenset(
    {"AUTO", "deviance", "RMSE", "MSE", "MAE", "RMSLE", "R2"}
)
SUPPORTED_PREPROCESSING = frozenset({"target_encoding"})


@dataclass(frozen=True)
class ExperimentConfig:
    """Stable public configuration for an H2O experiment."""

    target: str
    task: TaskType
    metric: str = "AUTO"
    time_budget: int = 300
    max_models: int | None = None
    nfolds: int = 5
    train_ratio: float = 0.70
    validation_ratio: float = 0.15
    seed: int = 42
    balance_classes: bool = False
    ignored_columns: tuple[str, ...] = ()
    include_algos: tuple[str, ...] = ()
    distribution: str = "AUTO"
    stopping_metric: str = "AUTO"
    max_runtime_per_model: int | None = None
    preprocessing: tuple[str, ...] = ()

    def validate(self) -> None:
        """Validate values before an H2O job consumes resources."""

        if not self.target.strip():
            raise InvalidExperimentError("Target column không được để trống.")
        if self.task not in ("classification", "regression"):
            raise InvalidExperimentError("Task phải là classification hoặc regression.")
        if not 10 <= self.time_budget <= 86_400:
            raise InvalidExperimentError("time_budget phải nằm trong khoảng 10..86400 giây.")
        if self.max_models is not None and not 1 <= self.max_models <= 10_000:
            raise InvalidExperimentError("max_models phải nằm trong khoảng 1..10000.")
        if not 0 <= self.nfolds <= 20 or self.nfolds == 1:
            raise InvalidExperimentError("nfolds phải là 0 hoặc nằm trong khoảng 2..20.")
        if not 0.5 <= self.train_ratio < 1:
            raise InvalidExperimentError("train_ratio phải nằm trong khoảng 0.5..<1.")
        if not 0 < self.validation_ratio < 0.5:
            raise InvalidExperimentError("validation_ratio phải nằm trong khoảng 0..<0.5.")
        if self.train_ratio + self.validation_ratio >= 1:
            raise InvalidExperimentError("Phải chừa lại một test set độc lập.")
        if self.target in self.ignored_columns:
            raise InvalidExperimentError("Target không thể đồng thời là ignored column.")
        unknown_algorithms = set(self.include_algos) - SUPPORTED_ALGORITHMS
        if unknown_algorithms:
            raise InvalidExperimentError(
                "Thuật toán H2O không được hỗ trợ: " + ", ".join(sorted(unknown_algorithms))
            )
        if len(set(self.include_algos)) != len(self.include_algos):
            raise InvalidExperimentError("include_algos không được chứa thuật toán trùng nhau.")
        if self.include_algos and not (set(self.include_algos) - {"StackedEnsemble"}):
            raise InvalidExperimentError(
                "StackedEnsemble cần ít nhất một thuật toán nền trong include_algos."
            )
        allowed_distributions = (
            CLASSIFICATION_DISTRIBUTIONS
            if self.task == "classification"
            else REGRESSION_DISTRIBUTIONS
        )
        if self.distribution not in allowed_distributions:
            raise InvalidExperimentError(
                f"Distribution '{self.distribution}' không hợp lệ cho {self.task}."
            )
        allowed_stopping_metrics = (
            CLASSIFICATION_STOPPING_METRICS
            if self.task == "classification"
            else REGRESSION_STOPPING_METRICS
        )
        if self.stopping_metric not in allowed_stopping_metrics:
            raise InvalidExperimentError(
                f"Stopping metric '{self.stopping_metric}' không hợp lệ cho {self.task}."
            )
        if self.max_runtime_per_model is not None and not 1 <= self.max_runtime_per_model <= 86_400:
            raise InvalidExperimentError(
                "max_runtime_per_model phải nằm trong khoảng 1..86400 giây."
            )
        unknown_preprocessing = set(self.preprocessing) - SUPPORTED_PREPROCESSING
        if unknown_preprocessing:
            raise InvalidExperimentError(
                "Preprocessing H2O không được hỗ trợ: "
                + ", ".join(sorted(unknown_preprocessing))
            )
        if len(set(self.preprocessing)) != len(self.preprocessing):
            raise InvalidExperimentError("preprocessing không được chứa bước trùng nhau.")


@dataclass(frozen=True)
class ExperimentResult:
    """Serializable result shared by Python callers and the website."""

    leader_model_id: str
    metrics: dict[str, Any]
    leaderboard: list[dict[str, Any]]
    variable_importance: list[dict[str, Any]]
    row_counts: dict[str, int]
    artifacts: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""

        return _json_safe(asdict(self))


class H2OExperiment:
    """Train, evaluate and persist one H2O AutoML run."""

    def __init__(self, config: ExperimentConfig, runtime: H2ORuntime | None = None) -> None:
        config.validate()
        self.config = config
        self.runtime = runtime or H2ORuntime()

    def fit(self, dataset_path: str | Path, output_dir: str | Path) -> ExperimentResult:
        """Run AutoML and evaluate its leader on a never-selected test split.

        Args:
            dataset_path: CSV, TSV, Parquet or Excel input file.
            output_dir: Directory receiving model and evidence artifacts.

        Returns:
            A normalized experiment result.
        """

        source = Path(dataset_path).resolve()
        if not source.exists() or not source.is_file():
            raise InvalidExperimentError(f"Dataset không tồn tại: {source}")

        output = Path(output_dir).resolve()
        output.mkdir(parents=True, exist_ok=True)
        h2o = self.runtime.client()
        frame = self._import_frame(h2o, source)

        if self.config.target not in frame.names:
            raise InvalidExperimentError(
                f"Không tìm thấy target '{self.config.target}'. Các cột hiện có: "
                + ", ".join(frame.names[:30])
            )
        if frame.nrows < 20:
            raise InvalidExperimentError("Dataset cần ít nhất 20 dòng để tạo ba tập dữ liệu.")

        if self.config.task == "classification":
            frame[self.config.target] = frame[self.config.target].asfactor()
            class_count = int(frame[self.config.target].nlevels()[0])
            if class_count < 2:
                raise InvalidExperimentError("Target classification cần ít nhất hai lớp.")
        else:
            target_type = str(frame.types.get(self.config.target, ""))
            if target_type not in {"int", "real", "numeric"}:
                raise InvalidExperimentError("Target regression phải là cột số.")

        train, validation, test = frame.split_frame(
            ratios=[self.config.train_ratio, self.config.validation_ratio],
            seed=self.config.seed,
        )
        if min(train.nrows, validation.nrows, test.nrows) == 0:
            raise InvalidExperimentError("Một data split bị rỗng; hãy dùng dataset lớn hơn.")

        from h2o.automl import H2OAutoML

        automl_kwargs: dict[str, Any] = {
            "max_runtime_secs": self.config.time_budget,
            "nfolds": self.config.nfolds,
            "seed": self.config.seed,
            "sort_metric": self.config.metric,
            "stopping_metric": self.config.stopping_metric,
            "distribution": self.config.distribution,
            "balance_classes": (
                self.config.balance_classes if self.config.task == "classification" else False
            ),
            "project_name": f"website_ml_{output.name.replace('-', '_')}",
        }
        if self.config.max_models is not None:
            automl_kwargs["max_models"] = self.config.max_models
        if self.config.max_runtime_per_model is not None:
            automl_kwargs["max_runtime_secs_per_model"] = self.config.max_runtime_per_model
        if self.config.include_algos:
            automl_kwargs["include_algos"] = list(self.config.include_algos)
        if self.config.preprocessing:
            automl_kwargs["preprocessing"] = list(self.config.preprocessing)

        automl = H2OAutoML(**automl_kwargs)
        feature_columns = [
            column
            for column in frame.names
            if column != self.config.target and column not in self.config.ignored_columns
        ]
        if not feature_columns:
            raise InvalidExperimentError("Không còn feature nào sau khi bỏ target/ignored columns.")
        train_kwargs: dict[str, Any] = {
            "x": feature_columns,
            "y": self.config.target,
            "training_frame": train,
            "validation_frame": validation,
        }
        # With CV disabled H2O needs a separate leaderboard frame. This is validation,
        # never the untouched final test set.
        if self.config.nfolds == 0:
            train_kwargs["leaderboard_frame"] = validation
        automl.train(**train_kwargs)

        leader = automl.leader
        if leader is None:
            raise InvalidExperimentError("H2O AutoML hoàn tất nhưng không tạo được model.")

        performance = leader.model_performance(test_data=test)
        metrics = self._extract_metrics(performance)
        leaderboard = self._frame_records(automl.leaderboard)
        variable_importance = self._variable_importance(leader)

        model_dir = output / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        binary_path = Path(h2o.save_model(model=leader, path=str(model_dir), force=True))
        artifacts: dict[str, str] = {"binary_model": str(binary_path)}
        try:
            mojo_path = Path(
                leader.download_mojo(path=str(model_dir), get_genmodel_jar=False)
            )
            artifacts["mojo"] = str(mojo_path)
        except Exception:
            # Some model types/configurations do not expose a MOJO. The binary model is
            # still a valid artifact and its H2O version is captured in metadata.
            pass

        predictions = leader.predict(test)
        predictions_path = output / "test_predictions.csv"
        h2o.download_csv(predictions, str(predictions_path))
        artifacts["test_predictions"] = str(predictions_path)

        result = ExperimentResult(
            leader_model_id=str(leader.model_id),
            metrics=metrics,
            leaderboard=leaderboard,
            variable_importance=variable_importance,
            row_counts={
                "all": int(frame.nrows),
                "train": int(train.nrows),
                "validation": int(validation.nrows),
                "test": int(test.nrows),
            },
            artifacts=artifacts,
        )
        (output / "result.json").write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return result

    @staticmethod
    def _import_frame(h2o: Any, source: Path) -> Any:
        suffix = source.suffix.lower()
        if suffix in {".csv", ".tsv", ".parquet"}:
            kwargs = {"sep": "\t"} if suffix == ".tsv" else {}
            return h2o.import_file(path=str(source), **kwargs)
        if suffix in {".xlsx", ".xls"}:
            # Excel is an input transport format, not an ML engine. Convert it at the
            # boundary while all model training remains entirely inside H2O.
            import pandas as pd

            return h2o.H2OFrame(pd.read_excel(source))
        raise InvalidExperimentError(
            "H2O Studio hiện hỗ trợ CSV, TSV, Parquet, XLSX và XLS."
        )

    @staticmethod
    def _frame_records(frame: Any, limit: int = 100) -> list[dict[str, Any]]:
        data = frame.head(rows=limit).as_data_frame(use_multi_thread=False)
        return _json_safe(data.to_dict(orient="records"))

    @staticmethod
    def _variable_importance(model: Any, limit: int = 50) -> list[dict[str, Any]]:
        try:
            table = model.varimp(use_pandas=True)
            if table is None:
                return []
            return _json_safe(table.head(limit).to_dict(orient="records"))
        except Exception:
            return []

    def _extract_metrics(self, performance: Any) -> dict[str, Any]:
        names = (
            (
                "auc",
                "aucpr",
                "logloss",
                "mean_per_class_error",
                "accuracy",
                "f1",
                "precision",
                "recall",
                "rmse",
                "mse",
            )
            if self.config.task == "classification"
            else ("rmse", "mse", "mae", "rmsle", "mean_residual_deviance", "r2")
        )
        metrics: dict[str, Any] = {}
        for name in names:
            method = getattr(performance, name, None)
            if name == "f1" and not callable(method):
                # H2O's binomial metrics API spells this one method with a capital F.
                method = getattr(performance, "F1", None)
            if not callable(method):
                continue
            try:
                value = method()
            except Exception:
                continue
            if value is not None:
                metrics[name] = _json_safe(_best_threshold_metric(value))
        return metrics


def _json_safe(value: Any) -> Any:
    """Recursively convert NumPy scalars, NaN and paths to strict JSON values."""

    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _best_threshold_metric(value: Any) -> Any:
    """Reduce H2O's ``[[threshold, value]]`` metric shape to the best value.

    Binomial helpers such as ``accuracy()`` and ``f1()`` return a threshold/value table,
    while AUC and regression metrics return scalars. The public framework exposes the
    metric value itself so website users do not have to understand H2O's internal shape.
    """

    if (
        isinstance(value, (list, tuple))
        and value
        and isinstance(value[0], (list, tuple))
        and len(value[0]) >= 2
    ):
        return value[0][1]
    return value
