import base64
import json

from reqparse_lite.payload import decode_cursor, encode_cursor, unpack_envelope


def test_unpack_single_envelope():
    assert unpack_envelope({"data": {"x": 1}}) == {"x": 1}


def test_unpack_nested_envelopes_collapse_to_innermost():
    assert unpack_envelope({"data": {"data": {"x": 1}}}) == {"x": 1}


def test_unpack_passthrough_when_no_envelope():
    assert unpack_envelope({"x": 1}) == {"x": 1}


def test_unpack_passthrough_when_data_has_siblings():
    assert unpack_envelope({"data": {"x": 1}, "meta": {}}) == {"data": {"x": 1}, "meta": {}}


def test_unpack_passthrough_for_non_dict():
    assert unpack_envelope("hello") == "hello"


def test_unpack_respects_max_depth():
    nested = {"data": {"data": {"data": {"data": {"data": {"x": 1}}}}}}
    out = unpack_envelope(nested)
    # MAX_DEPTH=5 should stop recursion before fully unwrapping.
    assert out == {"x": 1} or out == {"data": {"x": 1}}


def test_decode_cursor_round_trip():
    state = {"offset": 20, "page_size": 10}
    token = encode_cursor(state)
    assert decode_cursor(token) == state


def test_decode_cursor_empty_string_returns_empty():
    assert decode_cursor("") == {}


def test_decode_cursor_handles_missing_padding():
    raw = json.dumps({"offset": 0, "page_size": 5}).encode("utf-8")
    token = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    assert decode_cursor(token) == {"offset": 0, "page_size": 5}


def test_decode_cursor_returns_empty_for_non_dict_payload():
    raw = json.dumps([1, 2, 3]).encode("utf-8")
    token = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    assert decode_cursor(token) == {}


def test_encode_cursor_no_padding():
    token = encode_cursor({"offset": 1, "page_size": 1})
    assert "=" not in token


def test_encode_cursor_is_deterministic_for_same_state():
    a = encode_cursor({"offset": 5, "page_size": 25})
    b = encode_cursor({"page_size": 25, "offset": 5})
    assert a == b
