"""Porting di tests/update.test.ts (cmp_version) + ramo available e memo del check."""

from __future__ import annotations

import time

import pytest

from app.adapters.system import update
from app.core import config

RELEASES_URL = update.RELEASES_URL
REL = "https://github.com/LookUpMark/osusume/releases/tag/v1.2.0"


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


def test_cmp_version_numerico_non_lessicografico():
    assert _sign(update.cmp_version("v0.4.1", "0.4.0")) == 1
    assert _sign(update.cmp_version("0.10.0", "v0.9.9")) == 1  # 10 > 9, non "10" < "9"
    assert _sign(update.cmp_version("v0.3.0", "0.3.0")) == 0
    assert _sign(update.cmp_version("0.2.9", "0.3.0")) == -1
    # suffisso ignorato — la 4ª parte è trattata come 0
    assert _sign(update.cmp_version("0.3.1", "0.3.1-beta")) == 0


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"tag_name": "v1.2.0", "html_url": REL}


class _FakeClient:
    """Sostituisce httpx.AsyncClient dentro update: registra le chiamate, zero rete."""

    calls: list[str] = []

    def __init__(self, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def get(self, url: str, headers=None) -> _FakeResponse:
        _FakeClient.calls.append(url)
        return _FakeResponse()


@pytest.fixture
def fake_net(monkeypatch):
    _FakeClient.calls = []
    monkeypatch.setattr(update.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(update, "_memo", (None, None))
    monkeypatch.setattr(update, "_memo_at", float("-inf"))
    return _FakeClient.calls


async def test_primo_check_non_fresh_colpisce_la_rete_poi_memo(fake_net):
    # il bug era _memo_at = 0.0: con monotonic() di un processo appena avviato il
    # primo check senza fresh avrebbe saltato GitHub (il TS con Date.now() non può)
    assert update._memo_at == float("-inf")
    a = await update.latest_release()
    b = await update.latest_release()  # entro 5 min: nessuna seconda chiamata
    assert fake_net == [RELEASES_URL]
    assert a == b == ("v1.2.0", REL)


async def test_fresh_bypassa_il_memo(fake_net):
    await update.latest_release()
    await update.latest_release(fresh=True)  # il pulsante "check now" DEVE colpire GitHub
    assert fake_net == [RELEASES_URL, RELEASES_URL]


async def test_fallimento_memoizzato_come_nessuna_info(monkeypatch):
    class Boom:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def get(self, url, headers=None):
            raise OSError("rete giù")

    monkeypatch.setattr(update.httpx, "AsyncClient", Boom)
    monkeypatch.setattr(update, "_memo", (None, None))
    monkeypatch.setattr(update, "_memo_at", float("-inf"))
    # offline / rate-limited → "no update info", MAI un errore
    assert await update.latest_release() == (None, None)


async def test_available_con_tag_piu_nuova(monkeypatch):
    monkeypatch.setattr(config, "APP_VERSION", "1.1.0")
    monkeypatch.setattr(update, "_memo", ("v1.2.0", REL))
    monkeypatch.setattr(update, "_memo_at", time.monotonic())  # memo caldo: zero rete
    assert await update.app_update_status() == {
        "current": "1.1.0",
        "latest": "v1.2.0",
        "url": REL,
        "available": True,
    }


async def test_non_available_a_parita(monkeypatch):
    monkeypatch.setattr(config, "APP_VERSION", "1.2.0")
    monkeypatch.setattr(update, "_memo", ("v1.2.0", REL))
    monkeypatch.setattr(update, "_memo_at", time.monotonic())
    res = await update.app_update_status()
    assert res["available"] is False  # prerelease/suffix inclusi: mai "nuova" a parità


async def test_senza_app_version_zero_rete(monkeypatch):
    monkeypatch.setattr(config, "APP_VERSION", None)
    assert await update.app_update_status() == {
        "current": None,
        "latest": None,
        "url": None,
        "available": False,
    }
