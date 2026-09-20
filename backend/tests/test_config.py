"""Fedeltà del porting di src/server/config.ts: lettura tollerante, merge-patch, precedenza."""

from __future__ import annotations

from app.core import config


def test_read_config_file_corrotto_restituisce_vuoto(tmp_path):
    bad = tmp_path / "config.json"
    bad.write_text("{ non json", encoding="utf-8")
    assert config.read_config_file(str(bad)) == {}
    assert config.read_config_file(str(tmp_path / "assente.json")) == {}


def test_update_config_merge_patch_e_cancellazione(tmp_path, monkeypatch):
    path = str(tmp_path / "config.json")
    monkeypatch.setattr(config, "CONFIG_PATH", path)

    config.update_config({"model": "qwen3:8b", "backend": "skipped"}, path)
    assert config.read_config_file(path) == {"model": "qwen3:8b", "backend": "skipped"}

    # merge: le chiavi non toccate restano
    config.update_config({"baseUrl": "http://127.0.0.1:9999/v1"}, path)
    assert config.read_config_file(path)["model"] == "qwen3:8b"

    # chiave None esplicita CANCELLA (in TS: key: undefined → JSON.stringify la dropa)
    config.update_config({"model": None}, path)
    assert config.read_config_file(path) == {"backend": "skipped", "baseUrl": "http://127.0.0.1:9999/v1"}
    # niente file .tmp residui: write atomica tmp + rename
    assert not (tmp_path / "config.json.tmp").exists()


def test_llm_model_precedenza_env_poi_config_poi_default(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert config.llm_model() == "qwen3:8b"
    monkeypatch.setenv("LLM_MODEL", "llama3:latest")
    assert config.llm_model() == "llama3:latest"


def test_has_custom_env_sola_presenza(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    assert config.has_custom_env() is False
    monkeypatch.setenv("LLM_BASE_URL", "")
    assert config.has_custom_env() is True  # conta la presenza, non la verità


def test_env_pin_blocca_local_mode(monkeypatch):
    """ANILIST_FIXTURES pina la local mode: setLocalMode è ignorato per tutto il processo."""
    monkeypatch.setattr(config, "_local_mode", False)
    monkeypatch.setattr(config, "_auto_fallback", True)

    monkeypatch.setattr(config, "ANILIST_FIXTURES", "fixtures")
    config.set_local_mode(True)
    assert config.local_mode_on() is False  # il pin vince, sempre

    monkeypatch.setattr(config, "ANILIST_FIXTURES", "")
    config.set_local_mode(True)
    assert config.local_mode_on() is True  # senza pin la transizione passa

    # disabling auto = try live again right away
    config.set_auto_fallback(False)
    assert config.auto_fallback_on() is False
    assert config.local_mode_on() is False
