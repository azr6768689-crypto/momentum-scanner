"""Tests for Polygon provider retry boundaries."""

from __future__ import annotations

import pytest

from src.data.base import RateLimitError
from src.data.polygon_provider import PolygonProvider


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, headers: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = "fake response"

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def get(self, *args, **kwargs) -> _FakeResponse:
        self.calls += 1
        if not self._responses:
            raise AssertionError("unexpected extra request")
        return self._responses.pop(0)


def _provider(tmp_path, responses: list[_FakeResponse]) -> tuple[PolygonProvider, _FakeSession]:
    provider = PolygonProvider(
        "test-key",
        tmp_path,
        cache_enabled=False,
        rate_limit_max_attempts=2,
        rate_limit_max_sleep=0,
    )
    session = _FakeSession(responses)
    provider._session = session
    return provider, session


def test_ticker_news_rate_limit_is_bounded(tmp_path):
    provider, session = _provider(
        tmp_path,
        [_FakeResponse(429), _FakeResponse(429)],
    )

    with pytest.raises(RateLimitError):
        provider.get_ticker_news("AAPL")

    assert session.calls == 2


def test_ticker_details_can_recover_after_rate_limit(tmp_path):
    provider, session = _provider(
        tmp_path,
        [
            _FakeResponse(429, headers={"Retry-After": "0"}),
            _FakeResponse(200, {"results": {"ticker": "AAPL", "name": "Apple"}}),
        ],
    )

    details = provider.get_ticker_details("AAPL")

    assert details["ticker"] == "AAPL"
    assert session.calls == 2


def test_ticker_list_rate_limit_is_bounded(tmp_path):
    provider, session = _provider(
        tmp_path,
        [_FakeResponse(429), _FakeResponse(429)],
    )

    with pytest.raises(RateLimitError):
        provider.list_us_stock_tickers()

    assert session.calls == 2
