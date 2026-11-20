from unittest.mock import Mock, patch

import pytest
import requests

from healthcheck import check_mbta, check_open_meteo


def make_response(payload):
    response = Mock()
    response.json.return_value = payload
    return response


def test_mbta_returns_alert_count():
    response = make_response({"data": [{"id": "alert-1"}]})

    with patch("healthcheck.requests.get", return_value=response) as get:
        result = check_mbta()

    assert result == "1 alert record(s) returned"
    get.assert_called_once()
    response.raise_for_status.assert_called_once()


def test_mbta_rejects_unexpected_response_shape():
    response = make_response({"data": None})

    with patch("healthcheck.requests.get", return_value=response):
        with pytest.raises(ValueError, match="data list"):
            check_mbta()


def test_open_meteo_returns_current_time():
    response = make_response({"current": {"time": "2026-11-19T23:45"}})

    with patch("healthcheck.requests.get", return_value=response) as get:
        result = check_open_meteo()

    assert result == "current weather returned for 2026-11-19T23:45"
    get.assert_called_once()
    response.raise_for_status.assert_called_once()


def test_open_meteo_rejects_unexpected_response_shape():
    response = make_response({"current": None})

    with patch("healthcheck.requests.get", return_value=response):
        with pytest.raises(ValueError, match="current conditions"):
            check_open_meteo()


def test_mbta_http_error_is_propagated():
    response = make_response({"data": []})
    response.raise_for_status.side_effect = requests.HTTPError("server error")

    with patch("healthcheck.requests.get", return_value=response):
        with pytest.raises(requests.HTTPError):
            check_mbta()
