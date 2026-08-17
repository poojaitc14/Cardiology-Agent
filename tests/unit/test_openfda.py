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


class SequencedFakeClient:
    """Returns/raises a different outcome on each successive call -- for testing retries."""

    def __init__(self, outcomes: list[FakeResponse | Exception]):
        self.outcomes = list(outcomes)
        self.call_count = 0
        self.params = None

    def get(self, url, *, params, timeout):
        self.params = params
        outcome = self.outcomes[min(self.call_count, len(self.outcomes) - 1)]
        self.call_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def server_error_response(payload=None):
    request = httpx.Request("GET", "https://example.test")
    error = httpx.HTTPStatusError("provider detail", request=request, response=httpx.Response(500, request=request))
    return FakeResponse(payload or {}, error)


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
    result = OpenFDAService(client=FakeClient(error=httpx.TimeoutException("private detail")), retry_backoff_seconds=0).search_drug_label("Warfarin")
    assert not result.available and "private detail" not in result.user_message


def test_404_is_reported_as_not_found_not_unavailable():
    """OpenFDA returns 404, not 200-with-empty-results, when a search term
    doesn't match anything -- this is 'not found,' not an outage, and matters
    more now that drug-name extraction isn't capped at a known-good list."""
    request = httpx.Request("GET", "https://example.test")
    error = httpx.HTTPStatusError("not found", request=request, response=httpx.Response(404, request=request))
    result = OpenFDAService(client=FakeClient(FakeResponse({}, error)), retry_backoff_seconds=0).search_drug_label("metmorphin")
    assert result.available
    assert not result.found
    assert result.user_message == "No matching drug-label information was found in OpenFDA."


def test_404_is_not_retried():
    request = httpx.Request("GET", "https://example.test")
    error = httpx.HTTPStatusError("not found", request=request, response=httpx.Response(404, request=request))
    client = SequencedFakeClient([FakeResponse({}, error), FakeResponse(LABEL_PAYLOAD)])
    OpenFDAService(client=client, retry_backoff_seconds=0).search_drug_label("metmorphin")
    assert client.call_count == 1


def test_http_error_is_hidden_from_user():
    result = OpenFDAService(client=FakeClient(FakeResponse({}, httpx.HTTPStatusError("provider detail", request=httpx.Request("GET", "https://example.test"), response=httpx.Response(500, request=httpx.Request("GET", "https://example.test"))))), retry_backoff_seconds=0).search_drug_label("Warfarin")
    assert not result.available and "provider detail" not in result.user_message


class TestRetryBehavior:
    def test_retries_after_a_transient_server_error_then_succeeds(self):
        client = SequencedFakeClient([server_error_response(), FakeResponse(LABEL_PAYLOAD)])
        result = OpenFDAService(client=client, retry_backoff_seconds=0).search_drug_label("Warfarin")
        assert result.found
        assert client.call_count == 2

    def test_gives_up_after_exhausting_retries_on_repeated_server_errors(self):
        client = SequencedFakeClient([server_error_response(), server_error_response(), server_error_response()])
        result = OpenFDAService(client=client, max_retries=2, retry_backoff_seconds=0).search_drug_label("Warfarin")
        assert not result.available
        assert client.call_count == 3  # 1 initial attempt + 2 retries

    def test_does_not_retry_a_client_error(self):
        request = httpx.Request("GET", "https://example.test")
        error = httpx.HTTPStatusError("bad request", request=request, response=httpx.Response(400, request=request))
        client = SequencedFakeClient([FakeResponse({}, error), FakeResponse(LABEL_PAYLOAD)])
        result = OpenFDAService(client=client, retry_backoff_seconds=0).search_drug_label("Warfarin")
        assert not result.available
        assert client.call_count == 1  # never reaches the second (would-be-successful) outcome

    def test_retries_after_a_timeout_then_succeeds(self):
        client = SequencedFakeClient([httpx.TimeoutException("slow"), FakeResponse(LABEL_PAYLOAD)])
        result = OpenFDAService(client=client, retry_backoff_seconds=0).search_drug_label("Warfarin")
        assert result.found
        assert client.call_count == 2
