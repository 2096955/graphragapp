from .backends import AnyJevBackend, CatalogueBackend, JevBackend, LayaBackend, UniformBackend
from .base import Answer, Backend, BackendUnavailable, DecisionError, DecisionResult, labels, validate_questions

__all__ = ["Answer", "AnyJevBackend", "Backend", "BackendUnavailable", "CatalogueBackend", "DecisionError", "DecisionResult",
           "JevBackend", "LayaBackend", "UniformBackend", "build_backends", "labels", "validate_questions"]


def build_backends(settings) -> dict[str, Backend]:
    """Backends named in settings.backends, in that order."""
    makers = {
        "jev": lambda: JevBackend(settings.typesafe_api_key, settings.typesafe_base_url, settings.jev_model,
                                  settings.jev_price_per_mtok),
        "laya": lambda: LayaBackend(settings.laya_checkpoint, settings.device),
        "laya-typed": lambda: LayaBackend("typed-decisions", settings.device, name="laya-typed",
                                          label="Laya typed-decisions"),
        "anyjev": lambda: AnyJevBackend(settings.anyjev_model, settings.device, settings.anyjev_dtype, settings.anyjev_level),
        "uniform": UniformBackend,
        "catalogue": CatalogueBackend,
    }
    out = {}
    for name in settings.backends:
        if name not in makers:
            raise ValueError(f"Unknown backend {name!r}; choose from {', '.join(makers)}")
        out[name] = makers[name]()
        if settings.calibration_dir and name not in ("uniform", "catalogue"):
            from pathlib import Path
            from ..calibration import Calibration
            path = Path(settings.calibration_dir) / f"{name}.json"
            if path.exists():
                out[name].calibration = Calibration(path, out[name].model)
    return out
