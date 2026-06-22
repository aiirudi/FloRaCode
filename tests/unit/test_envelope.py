from __future__ import annotations

import pytest
from pydantic import ValidationError

from flora_claude.core.bus.envelope import (
    JsonRpcRequest,
    JsonRpcSuccess,
    make_error,
    PARSE_ERROR
)

def test_request_roundtrip() -> None:
    req1 = JsonRpcRequest(method="core.ping", id="1", params={"client": "test"})
    req2 = JsonRpcRequest.model_validate_json(req1.model_dump_json())
    assert req2.id == "1"
    assert req2.method == "core.ping"
    assert req2.params == {"client": "test"}

def test_request_default_params() -> None:
    req = JsonRpcRequest(method="x", id="1")
    assert req.params == {}

def test_request_missing_id_raises() -> None:
    with pytest.raises(ValidationError):
        JsonRpcRequest.model_validate({"jsonrpc": "2.0", "method":"x"})

def test_request_wrong_version_raises() -> None:
    with pytest.raises(ValidationError):
        JsonRpcRequest.model_validate({
            "jsonrpc":"1.0", "id":1, "method":"x"
        })

def test_success_roundtrip() -> None:
    resp = JsonRpcSuccess(id="1", result={"key": "value"})
    resp2 = JsonRpcSuccess.model_validate_json(resp.model_dump_json())

    assert resp2.id == "1"
    assert resp2.result == {"key": "value"}

def test_mask_error_sets_code() -> None:
    err = make_error(id="1", code=PARSE_ERROR, message="Parse error")
    assert err.id == "1"
    assert err.error.code == PARSE_ERROR
    assert err.error.data is None

def test_mask_error_null_id() -> None:
    err = make_error(None, PARSE_ERROR, message="bad json")
    assert err.id is None
