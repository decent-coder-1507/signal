"""Config loader: reads config/*.yaml, validates, fails fast with a readable error."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from signal_core.config.schemas import (
    AppConfig,
    BudgetCfg,
    PlatformsCfg,
    ProfileCfg,
    RoutinesCfg,
    ScoringCfg,
    SkillsCfg,
    SourcesCfg,
    VoiceCfg,
)

FILES: dict[str, type[BaseModel]] = {
    "profile": ProfileCfg,
    "sources": SourcesCfg,
    "scoring": ScoringCfg,
    "routines": RoutinesCfg,
    "voice": VoiceCfg,
    "platforms": PlatformsCfg,
    "budget": BudgetCfg,
    "skills": SkillsCfg,
}


class ConfigError(RuntimeError):
    """Raised at startup when a config file is missing or invalid."""


def _read(path: Path) -> Any:
    if not path.exists():
        raise ConfigError(f"Config file missing: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"{path.name}: not valid YAML: {e}") from e
    if isinstance(data, list):  # sources.yaml may be a bare list
        key = "sources" if path.stem == "sources" else path.stem
        data = {key: data}
    return data


def load_config(config_dir: Path) -> AppConfig:
    parsed: dict[str, BaseModel] = {}
    errors: list[str] = []
    for name, model in FILES.items():
        path = config_dir / f"{name}.yaml"
        try:
            parsed[name] = model.model_validate(_read(path))
        except ConfigError as e:
            errors.append(str(e))
        except ValidationError as e:
            for err in e.errors():
                loc = ".".join(str(p) for p in err["loc"]) or "(root)"
                errors.append(f"{name}.yaml → {loc}: {err['msg']}")
    if errors:
        raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(errors))
    return AppConfig.model_validate({k: v.model_dump() for k, v in parsed.items()})


@lru_cache
def get_config() -> AppConfig:
    from signal_core.settings import get_settings

    return load_config(get_settings().config_dir)
