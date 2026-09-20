"""Porting della parte unit di ``tests/setup.test.ts`` (suggestModel, needsSetupVersion,
hardware, extra-id chat) + risoluzione lms/omlx e chiavi oMLX.

Lo scenario TS "config precedence" è già coperto da test_config.py (lettura tollerante
+ merge-patch); gli scenari e2e con fake lms stanno in test_setup_e2e.py.
"""

from __future__ import annotations

import json
import platform

from app.adapters.llm import setup as llm_setup
from app.adapters.system import setup
from app.api.routes import chat_extra_ids
from app.core import config


def hw(**over) -> dict:
    base = {"os": "mac", "chip": "Apple M3 Pro", "ramGb": 36, "appleSilicon": True}
    base.update(over)
    return base


def test_suggest_model_ram_threshold_32gb():
    assert "Qwen3.6" in setup.suggest_model(hw(ramGb=32))["model"]
    assert "Qwen3.6" in setup.suggest_model(hw(ramGb=64))["model"]
    assert "gemma-4" in setup.suggest_model(hw(ramGb=24))["model"]
    assert "gemma-4" in setup.suggest_model(hw(ramGb=8))["model"]
    assert setup.suggest_model(hw(ramGb=64))["sizeGb"] == 21.5
    assert setup.suggest_model(hw(ramGb=16))["sizeGb"] == 8.1
    # id ESATTI del catalogo (il wizard scarica quello che gli status suggerisce)
    assert setup.suggest_model(hw(ramGb=64))["model"] == "lmstudio-community/Qwen3.6-35B-A3B-GGUF"
    assert setup.suggest_model(hw(ramGb=16))["model"] == "unsloth/gemma-4-12b-it-GGUF"


def test_suggest_model_mlx_solo_apple_silicon():
    assert "mlx" in setup.suggest_model(hw(appleSilicon=True))["mlx"]["model"]
    assert setup.suggest_model(hw(appleSilicon=False))["mlx"] is None
    assert setup.suggest_model(hw(appleSilicon=False))["mlxLms"] is None


def test_suggest_model_pack_mlx_per_engine_su_entrambi_i_tier():
    hi = setup.suggest_model(hw(ramGb=64, appleSilicon=True))
    assert hi["mlx"]["model"] == "mlx-community/Qwen3.6-35B-A3B-4bit", "oMLX gets the mlx-community pack"
    assert hi["mlxLms"]["model"] == "lmstudio-community/Qwen3.6-35B-A3B-MLX-4bit", "LM Studio gets its own pack"
    lo = setup.suggest_model(hw(ramGb=16, appleSilicon=True))
    assert lo["mlx"]["model"] == "mlx-community/gemma-4-12B-it-4bit"
    assert lo["mlxLms"]["model"] == "lmstudio-community/gemma-4-12B-it-MLX-4bit"


def test_needs_setup_version_wizard_reopens_on_app_update(monkeypatch):
    assert setup.needs_setup_version({}, "0.5.4") is True, "no marker yet"
    assert setup.needs_setup_version({"setupVersion": "0.5.3"}, "0.5.4") is True, "older marker"
    assert setup.needs_setup_version({"setupVersion": "0.5.4"}, "0.5.4") is False, "acked"
    assert setup.needs_setup_version({"setupVersion": "0.5.3"}, None) is False, "dev: no APP_VERSION"
    # default = APP_VERSION del processo
    monkeypatch.setattr(config, "APP_VERSION", "0.5.4")
    assert setup.needs_setup_version({"setupVersion": "0.5.3"}) is True
    assert setup.needs_setup_version({"setupVersion": "0.5.4"}) is False
    monkeypatch.setattr(config, "APP_VERSION", None)
    assert setup.needs_setup_version({"setupVersion": "0.5.3"}) is False


def test_catalogo_id_esatti_e_downloadable():
    assert list(setup.MODELS) == ["qwen36", "gemma4"]
    assert setup.MODELS["qwen36"]["gguf"]["sizeGb"] == 21.5
    assert setup.MODELS["qwen36"]["ollama"] == "hf.co/lmstudio-community/Qwen3.6-35B-A3B-GGUF:Q4_K_M"
    assert setup.MODELS["gemma4"]["mlx"]["sizeGb"] == 6.3
    # whitelist chiusa degli pack mlx scaricabili dal wizard (setup.ts righe 384-387)
    assert list(setup.OMLX_DOWNLOADABLE) == [
        "mlx-community/Qwen3.6-35B-A3B-4bit",
        "mlx-community/gemma-4-12B-it-4bit",
    ]


def test_detect_hardware_forma_e_coerenza():
    out = setup.detect_hardware()
    assert set(out) == {"os", "chip", "ramGb", "appleSilicon"}
    assert out["os"] in ("mac", "win", "linux")
    assert isinstance(out["ramGb"], int) and out["ramGb"] > 0
    assert isinstance(out["appleSilicon"], bool) and out["chip"]
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        assert out["os"] == "mac" and out["appleSilicon"] is True
        assert "Apple" in out["chip"], "su mac il chip è il brand_string (≈ cpus()[0].model)"


def test_model_key_re_regex_ts():
    ok = ["a", "A9", "org/repo", "org/repo.model_1-x/y", "1a/b"]
    bad = ["", ".hidden", "..", "-x", "a b", "a/b ", "sp ace", "name!"]
    for m in ok:
        assert setup.MODEL_KEY_RE.match(m), m
    for m in bad:
        assert not setup.MODEL_KEY_RE.match(m), m


def test_read_omlx_key_e_porta_da_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("OMLX_API_KEY", raising=False)
    # config di processo isolato: llm_auth_headers non deve leggere data/config.json reale
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(config, "_file_config", {})
    assert llm_setup.read_omlx_key() is None
    assert llm_setup.read_omlx_port() is None
    assert llm_setup.omlx_auth_headers() == {}, "wizard: senza chiave nessuna probe autenticata"

    omlx_dir = tmp_path / ".omlx"
    omlx_dir.mkdir()
    (omlx_dir / "settings.json").write_text(
        json.dumps({"server": {"port": 3399}, "auth": {"api_key": "sk-test"}}), encoding="utf-8"
    )
    assert llm_setup.read_omlx_key() == "sk-test"
    assert llm_setup.read_omlx_port() == "3399"
    assert llm_setup.omlx_auth_headers() == {"authorization": "Bearer sk-test"}, "mai solo quando il config dice omlx"
    assert llm_setup.llm_auth_headers() == {}, "backend non ancora 'omlx' → nessun header"
    # env vince sul file
    monkeypatch.setenv("OMLX_API_KEY", "sk-env")
    assert llm_setup.read_omlx_key() == "sk-env"


def test_omlx_base_runtime_da_settings(monkeypatch, tmp_path):
    monkeypatch.delenv("OMLX_BASE_URL", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert setup.omlx_base() == "http://127.0.0.1:8080/v1", "nessuna settings → porta default"
    (tmp_path / ".omlx").mkdir()
    (tmp_path / ".omlx" / "settings.json").write_text(json.dumps({"server": {"port": 3399}}), encoding="utf-8")
    assert setup.omlx_base() == "http://127.0.0.1:3399/v1", "legge la porta: niente probe sulla porta sbagliata"
    monkeypatch.setenv("OMLX_BASE_URL", "http://127.0.0.1:5/v1")
    assert setup.omlx_base() == "http://127.0.0.1:5/v1"


def test_resolve_lms_precedenza_env_config_default(monkeypatch, tmp_path):
    custom = tmp_path / "custom-lms"
    custom.write_text("#!/bin/sh\nexit 0\n")
    custom.chmod(0o755)
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", str(config_path))
    monkeypatch.delenv("LMS_PATH", raising=False)

    monkeypatch.setenv("LMS_PATH", str(custom))
    assert setup.resolve_lms() == str(custom), "env LMS_PATH vince"

    monkeypatch.delenv("LMS_PATH", raising=False)
    config.update_config({"lmsPath": str(custom)}, str(config_path))
    assert setup.resolve_lms() == str(custom), "config.lmsPath esistente su disco"

    config.update_config({"lmsPath": str(tmp_path / "assente")}, str(config_path))
    assert setup.resolve_lms() != str(tmp_path / "assente"), "lmsPath inesistente è ignorato"


def test_chat_extra_ids_filtro_e_slice():
    class R:
        def __init__(self, id: int) -> None:
            self.media = type("M", (), {"id": id})()

    recos = [R(1), R(2)]
    # numeri non presenti nelle recos, slice(0,5), SENZA dedup (api.ts righe 176-179)
    assert chat_extra_ids([3, 4, 5, 6, 7, 8, 3], recos) == [3, 4, 5, 6, 7]
    assert chat_extra_ids([1, "x", True, 2.0, 9], recos) == [9], "in-recos, non-numeri e bool scartati"
    assert chat_extra_ids([], recos) == []
