from unittest.mock import Mock, patch

import pytest
import requests
import json
import ingest


def test_fetch_json_returns_valid_payload():
    payload = {"data": [{"id": "alert-1"}]}
    response = Mock()
    response.json.return_value = payload

    with patch("ingest.requests.get", return_value=response):
        result = ingest.fetch_json(ingest.SOURCES["mbta_alerts"])

    assert result == payload
    response.raise_for_status.assert_called_once()

def test_fetch_json_rejects_invalid_payload():
    response = Mock()
    response.json.return_value = {"data": None}

    with patch("ingest.requests.get", return_value=response):
        with pytest.raises(ValueError, match="expected data"):
            ingest.fetch_json(ingest.SOURCES["mbta_alerts"])

def test_save_json_writes_payload(tmp_path, monkeypatch):
    output_dir = tmp_path / "raw"
    monkeypatch.setattr(ingest, "OUTPUT_DIR", output_dir)
    payload = {"current": {"temperature_2m": 12.5}}

    path = ingest.save_json("weather", payload, "20261120T120000Z")

    assert path.exists()
    assert path.name == "weather_20261120T120000Z.json"
    assert json.loads(path.read_text(encoding="utf-8")) == payload