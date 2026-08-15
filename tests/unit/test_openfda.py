from __future__ import annotations

import httpx

from backend.services.openfda import OpenFDAService


class FakeResponse:
    def __init__(self, payload, error: Exception | None = None):
        self.payload = payload
        self.error = error

    def raise_for_status(self) -> None:
        if self.error:
            raise self.error

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, response: FakeResponse | None = None, error: Exception | None = None):
        self.response, self.error, self.params = response, error, None

    def get(self, url, *, params, timeout):
        self.params = params
        if self.error:
            raise self.error
        assert self.response is not None
        return self.response


LABEL_PAYLOAD = {"results": [{"openfda": {"generic_name": ["WARFARIN SODIUM"], "brand_name": ["COUMADIN"], "manufacturer_name": ["Synthetic Manufacturer"]}, "purpose": ["Synthetic purpose"], "warnings": ["Synthetic warning"]}]}


def test_search_warfarin_normalizes_label_and_uses_drug_name_search():
    client = FakeClient(FakeResponse(LABEL_PAYLOAD))
    result = OpenFDAService(client=client).search_drug_label("Warfarin")
    assert result.found and result.source == "OpenFDA"
    assert result.label is not None and result.label.generic_names == ("WARFARIN SODIUM",)
    assert "Warfarin" in client.params["search"]


def test_search_atorvastatin_works():
    client = FakeClient(FakeResponse(LABEL_PAYLOAD))
    result = OpenFDAService(client=client).search_drug_label("Atorvastatin")
    assert result.found and "Atorvastatin" in client.params["search"]


def test_empty_result_is_handled():
    result = OpenFDAService(client=FakeClient(FakeResponse({"results": []}))).search_drug_label("Unknown")
    assert not result.found and result.available
    assert result.user_message == "No matching drug-label information was found in OpenFDA."


def test_timeout_is_hidden_from_user():
    result = OpenFDAService(client=FakeClient(error=httpx.TimeoutException("private detail"))).search_drug_label("Warfarin")
    assert not result.available and "private detail" not in result.user_message


def test_http_error_is_hidden_from_user():
    request = httpx.Request("GET", "https://example.test")
    error = httpx.HTTPStatusError("provider detail", request=request, response=httpx.Response(500, request=request))
    result = OpenFDAService(client=FakeClient(FakeResponse({}, error))).search_drug_label("Warfarin")
    assert not result.available and "provider detail" not in result.user_message
