"""REST API for the user-facing H2O ML Studio."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, File, Query, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from h2o_framework import ExperimentConfig

from ..services import ml as ml_service


router = APIRouter(prefix="/ml", tags=["H2O ML Studio"])


class CreateExperimentRequest(BaseModel):
    """Validated website request for one AutoML experiment."""

    session_id: str = "default"
    dataset_id: str = Field(min_length=1)
    target: str = Field(min_length=1)
    task: Literal["classification", "regression"]
    metric: str = "AUTO"
    time_budget: int = Field(default=300, ge=10, le=86_400)
    max_models: int | None = Field(default=None, ge=1, le=10_000)
    nfolds: int = Field(default=5, ge=0, le=20)
    train_ratio: float = Field(default=0.70, ge=0.5, lt=1)
    validation_ratio: float = Field(default=0.15, gt=0, lt=0.5)
    seed: int = 42
    balance_classes: bool = False
    ignored_columns: list[str] = Field(default_factory=list)
    include_algos: list[
        Literal["DRF", "GLM", "XGBoost", "GBM", "DeepLearning", "StackedEnsemble"]
    ] = Field(default_factory=list)
    distribution: Literal[
        "AUTO", "bernoulli", "multinomial", "gaussian", "poisson", "gamma",
        "tweedie", "laplace", "quantile", "huber"
    ] = "AUTO"
    stopping_metric: Literal[
        "AUTO", "logloss", "AUC", "AUCPR", "misclassification",
        "mean_per_class_error", "deviance", "RMSE", "MSE", "MAE", "RMSLE", "R2"
    ] = "AUTO"
    max_runtime_per_model: int | None = Field(default=None, ge=1, le=86_400)
    preprocessing: list[Literal["target_encoding"]] = Field(default_factory=list)


class PredictRequest(BaseModel):
    """Dataset selection for batch scoring."""

    session_id: str = "default"
    dataset_id: str = Field(min_length=1)


@router.get("/health")
async def health(connect: bool = Query(False)):
    """Inspect H2O availability; optionally start/connect to its cluster."""

    return await run_in_threadpool(ml_service.experiment_manager.runtime.health, connect=connect)


@router.get("/datasets")
async def datasets(session_id: str = Query("default")):
    return {"datasets": ml_service.list_datasets(session_id)}


@router.post("/datasets/upload")
async def upload_datasets(
    files: list[UploadFile] = File(...),
    session_id: str = Query("default"),
):
    """Upload data for ML Studio without touching the chat Agent or notebook kernel."""

    return await ml_service.upload_datasets(session_id, files)


@router.get("/datasets/{dataset_id}")
async def dataset_schema(dataset_id: str, session_id: str = Query("default")):
    return ml_service.get_dataset(session_id, dataset_id)


@router.post("/experiments", status_code=202)
async def create_experiment(request: CreateExperimentRequest):
    config = ExperimentConfig(
        target=request.target,
        task=request.task,
        metric=request.metric,
        time_budget=request.time_budget,
        max_models=request.max_models,
        nfolds=request.nfolds,
        train_ratio=request.train_ratio,
        validation_ratio=request.validation_ratio,
        seed=request.seed,
        balance_classes=request.balance_classes,
        ignored_columns=tuple(request.ignored_columns),
        include_algos=tuple(request.include_algos),
        distribution=request.distribution,
        stopping_metric=request.stopping_metric,
        max_runtime_per_model=request.max_runtime_per_model,
        preprocessing=tuple(request.preprocessing),
    )
    return ml_service.create_experiment(
        session_id=request.session_id,
        dataset_id=request.dataset_id,
        config=config,
    )


@router.get("/experiments")
async def experiments(
    session_id: str = Query("default"),
    limit: int = Query(50, ge=1, le=200),
):
    return {"experiments": ml_service.list_experiments(session_id, limit=limit)}


@router.get("/experiments/{experiment_id}")
async def experiment(experiment_id: str, session_id: str = Query("default")):
    return ml_service.get_experiment(session_id, experiment_id)


@router.post("/experiments/{experiment_id}/predict")
async def predict(experiment_id: str, request: PredictRequest):
    return await run_in_threadpool(
        ml_service.predict,
        session_id=request.session_id,
        experiment_id=experiment_id,
        dataset_id=request.dataset_id,
    )
