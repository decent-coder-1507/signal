import shutil
from pathlib import Path

import pytest
import yaml

from signal_core.config import ConfigError, load_config

ROOT = Path(__file__).resolve().parents[2] / "config"


def copy_cfg(tmp_path: Path) -> Path:
    d = tmp_path / "config"
    shutil.copytree(ROOT, d)
    return d


def edit(d: Path, name: str, fn) -> None:  # type: ignore[no-untyped-def]
    data = yaml.safe_load((d / name).read_text(encoding="utf-8"))
    fn(data)
    (d / name).write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_repo_config_is_valid() -> None:
    cfg = load_config(ROOT)
    assert cfg.profile.brief.max_stories == 7
    assert set(cfg.budget.models) == {"fast", "balanced", "deep"}


def test_weights_must_sum_to_one(tmp_path: Path) -> None:
    d = copy_cfg(tmp_path)
    edit(d, "scoring.yaml", lambda c: c["weights"].update(relevance=0.9))
    with pytest.raises(ConfigError) as e:
        load_config(d)
    assert "scoring.yaml" in str(e.value) and "sum to 1.0" in str(e.value)


def test_bad_cron_and_missing_file_are_both_reported(tmp_path: Path) -> None:
    d = copy_cfg(tmp_path)
    edit(d, "routines.yaml", lambda c: c["routines"][0].update(cron="every morning"))
    (d / "budget.yaml").unlink()
    with pytest.raises(ConfigError) as e:
        load_config(d)
    msg = str(e.value)
    assert "invalid cron expression" in msg and "budget.yaml" in msg


def test_unknown_key_rejected(tmp_path: Path) -> None:
    d = copy_cfg(tmp_path)
    edit(d, "profile.yaml", lambda c: c["brief"].update(max_storys=3))
    with pytest.raises(ConfigError, match="max_storys"):
        load_config(d)


def test_budget_requires_price_for_each_tier_model(tmp_path: Path) -> None:
    d = copy_cfg(tmp_path)
    edit(d, "budget.yaml", lambda c: c["models"].update(deep="mystery-model"))
    with pytest.raises(ConfigError, match="no price for model 'mystery-model'"):
        load_config(d)


def test_invalid_timezone(tmp_path: Path) -> None:
    d = copy_cfg(tmp_path)
    edit(d, "profile.yaml", lambda c: c["owner"].update(timezone="Mars/Olympus"))
    with pytest.raises(ConfigError, match=r"profile.yaml"):
        load_config(d)
