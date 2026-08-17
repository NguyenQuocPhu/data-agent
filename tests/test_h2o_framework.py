"""Contract tests for the standalone, user-facing H2O framework."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from h2o_framework.errors import InvalidExperimentError
from h2o_framework.experiment import ExperimentConfig, ExperimentResult, H2OExperiment
from h2o_framework.manager import ExperimentManager


def test_config_always_reserves_an_independent_test_set():
    with pytest.raises(InvalidExperimentError, match="test set"):
        ExperimentConfig(
            target="label",
            task="classification",
            train_ratio=0.8,
            validation_ratio=0.2,
        ).validate()


def test_config_rejects_target_as_ignored_column():
    with pytest.raises(InvalidExperimentError, match="Target"):
        ExperimentConfig(
            target="label",
            task="classification",
            ignored_columns=("label",),
        ).validate()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"include_algos": ("NotAnAlgo",)}, "Thuật toán"),
        ({"include_algos": ("StackedEnsemble",)}, "thuật toán nền"),
        ({"distribution": "bernoulli"}, "Distribution"),
        ({"stopping_metric": "AUC"}, "Stopping metric"),
        ({"preprocessing": ("scale_everything",)}, "Preprocessing"),
    ],
)
def test_config_rejects_invalid_native_automl_options(overrides, message):
    with pytest.raises(InvalidExperimentError, match=message):
        ExperimentConfig(target="value", task="regression", **overrides).validate()


def test_manager_persists_job_state_and_survives_a_new_manager(tmp_path, monkeypatch):
    dataset = tmp_path / "data.csv"
    dataset.write_text("x,label\n1,0\n", encoding="utf-8")
    output_root = tmp_path / "Experiments"

    def fake_fit(self, dataset_path, output_dir):
        model = Path(output_dir) / "model.bin"
        model.write_text("fake", encoding="utf-8")
        return ExperimentResult(
            leader_model_id="leader",
            metrics={"auc": 0.9},
            leaderboard=[{"model_id": "leader", "auc": 0.9}],
            variable_importance=[],
            row_counts={"all": 100, "train": 70, "validation": 15, "test": 15},
            artifacts={"binary_model": str(model)},
        )

    monkeypatch.setattr(H2OExperiment, "fit", fake_fit)
    manager = ExperimentManager(max_workers=1)
    submitted = manager.submit(
        dataset_path=dataset,
        output_root=output_root,
        config=ExperimentConfig(target="label", task="classification", time_budget=10),
        dataset_id="abc",
        dataset_name="data.csv",
        session_id="default",
    )

    deadline = time.time() + 2
    current = submitted
    while current["status"] in {"queued", "running"} and time.time() < deadline:
        time.sleep(0.01)
        current = manager.get(output_root, submitted["id"])

    assert current["status"] == "completed"
    assert current["result"]["metrics"] == {"auc": 0.9}
    assert current["result"]["artifacts"]["binary_model"] == "model.bin"
    assert "dataset_path" not in current

    # State is read from disk rather than depending on in-process Python objects.
    reloaded = ExperimentManager(max_workers=1).get(output_root, submitted["id"])
    assert reloaded["status"] == "completed"
    assert reloaded["result"]["leader_model_id"] == "leader"


class _FakeTable:
    def __init__(self, records):
        self.records = records

    def head(self, rows=10):
        return _FakeTable(self.records[:rows])

    def as_data_frame(self, use_multi_thread=False):
        return self

    def to_dict(self, orient="records"):
        assert orient == "records"
        return self.records


class _FakeColumn:
    def asfactor(self):
        return self

    def nlevels(self):
        return [2]


class _FakeFrame:
    names = ["feature", "unused", "label"]
    types = {"feature": "real", "unused": "real", "label": "int"}

    def __init__(self, rows=100):
        self.nrows = rows

    def __getitem__(self, key):
        return _FakeColumn()

    def __setitem__(self, key, value):
        return None

    def split_frame(self, ratios, seed):
        assert ratios == [0.7, 0.15]
        assert seed == 42
        return _FakeFrame(70), _FakeFrame(15), _FakeFrame(15)


class _FakePerformance:
    def auc(self):
        return 0.91

    def aucpr(self):
        return 0.88

    def logloss(self):
        return 0.2

    def mean_per_class_error(self):
        return [[0.42, 0.1]]

    def accuracy(self):
        return [[0.42, 0.9]]

    def f1(self):
        return [[0.42, 0.88]]

    def precision(self):
        return [[0.42, 0.87]]

    def recall(self):
        return [[0.42, 0.89]]

    def rmse(self):
        return 0.3

    def mse(self):
        return 0.09


class _FakeLeader:
    model_id = "fake_leader"

    def model_performance(self, test_data):
        assert test_data.nrows == 15
        return _FakePerformance()

    def varimp(self, use_pandas=True):
        return _FakeTable([{"variable": "feature", "relative_importance": 1.0}])

    def predict(self, frame):
        return _FakeFrame(frame.nrows)

    def download_mojo(self, path, get_genmodel_jar=False):
        target = Path(path) / "leader.zip"
        target.write_text("mojo", encoding="utf-8")
        return str(target)


class _FakeAutoML:
    last_kwargs = None
    last_train_kwargs = None

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs
        self.leader = _FakeLeader()
        self.leaderboard = _FakeTable([{"model_id": "fake_leader", "auc": 0.91}])

    def train(self, **kwargs):
        type(self).last_train_kwargs = kwargs


class _FakeH2O:
    def import_file(self, path, **kwargs):
        return _FakeFrame()

    def save_model(self, model, path, force=True):
        target = Path(path) / "fake_leader"
        target.write_text("binary", encoding="utf-8")
        return str(target)

    def download_csv(self, frame, filename):
        Path(filename).write_text("predict\n0\n", encoding="utf-8")


def test_h2o_experiment_uses_features_not_ignored_columns_and_keeps_test_out_of_selection(
    tmp_path, monkeypatch
):
    automl_module = ModuleType("h2o.automl")
    automl_module.H2OAutoML = _FakeAutoML
    monkeypatch.setitem(sys.modules, "h2o.automl", automl_module)
    dataset = tmp_path / "data.csv"
    dataset.write_text("feature,unused,label\n1,2,0\n", encoding="utf-8")
    runtime = SimpleNamespace(client=lambda: _FakeH2O())
    config = ExperimentConfig(
        target="label",
        task="classification",
        time_budget=10,
        ignored_columns=("unused",),
        include_algos=("GBM", "GLM", "StackedEnsemble"),
        distribution="bernoulli",
        stopping_metric="AUC",
        max_runtime_per_model=5,
        preprocessing=("target_encoding",),
    )

    result = H2OExperiment(config, runtime=runtime).fit(dataset, tmp_path / "run")

    assert _FakeAutoML.last_train_kwargs["x"] == ["feature"]
    assert "leaderboard_frame" not in _FakeAutoML.last_train_kwargs
    assert _FakeAutoML.last_train_kwargs["training_frame"].nrows == 70
    assert _FakeAutoML.last_train_kwargs["validation_frame"].nrows == 15
    assert _FakeAutoML.last_kwargs["include_algos"] == ["GBM", "GLM", "StackedEnsemble"]
    assert _FakeAutoML.last_kwargs["distribution"] == "bernoulli"
    assert _FakeAutoML.last_kwargs["stopping_metric"] == "AUC"
    assert _FakeAutoML.last_kwargs["max_runtime_secs_per_model"] == 5
    assert _FakeAutoML.last_kwargs["preprocessing"] == ["target_encoding"]
    assert result.row_counts == {"all": 100, "train": 70, "validation": 15, "test": 15}
    assert result.metrics["auc"] == 0.91
    assert result.metrics["mean_per_class_error"] == 0.1
    assert result.metrics["f1"] == 0.88
    assert Path(result.artifacts["binary_model"]).exists()
    assert Path(result.artifacts["mojo"]).exists()
