"""Domain errors returned by the H2O framework."""


class H2OFrameworkError(RuntimeError):
    """Base exception for errors safe to surface through the ML API."""


class H2ONotAvailableError(H2OFrameworkError):
    """Raised when the H2O Python client or Java runtime is unavailable."""


class InvalidExperimentError(H2OFrameworkError):
    """Raised when a dataset or experiment configuration is invalid."""
