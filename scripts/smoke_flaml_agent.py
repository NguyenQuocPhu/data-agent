"""Smoke-test the FLAML capability exposed to the Agent's notebook environment."""

from __future__ import annotations

from flaml import AutoML
from sklearn.datasets import make_regression
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import train_test_split


def main() -> None:
    """Fit a tiny notebook-style regression and verify inference works."""

    features, target = make_regression(
        n_samples=600,
        n_features=12,
        n_informative=8,
        noise=2.0,
        random_state=42,
    )
    train_x, test_x, train_y, test_y = train_test_split(
        features,
        target,
        test_size=0.2,
        random_state=42,
    )
    automl = AutoML()
    automl.fit(
        X_train=train_x,
        y_train=train_y,
        task="regression",
        metric="rmse",
        time_budget=3,
        estimator_list=["lgbm", "xgboost", "rf", "extra_tree"],
        n_jobs=2,
        seed=42,
        verbose=0,
    )
    predictions = automl.predict(test_x)
    rmse = mean_squared_error(test_y, predictions) ** 0.5
    assert len(predictions) == len(test_y)
    assert automl.best_estimator
    print(
        {
            "best_estimator": automl.best_estimator,
            "best_config": automl.best_config,
            "test_rmse": rmse,
        }
    )


if __name__ == "__main__":
    main()
