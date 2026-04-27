from reqparse_lite.headers import header_score, normalise_header, parse_content_type


def test_normalise_lowercase_dash():
    assert normalise_header("content-type") == "Content-Type"


def test_normalise_underscore_to_dash():
    assert normalise_header("x_api_key") == "X-Api-Key"


def test_normalise_uppercase_acronym():
    assert normalise_header("X-API-KEY") == "X-Api-Key"


def test_normalise_empty_returns_empty():
    assert normalise_header("") == ""


def test_normalise_drops_consecutive_dashes():
    assert normalise_header("a--b") == "A-B"


def test_parse_content_type_basic():
    assert parse_content_type("application/json") == {"type": "application", "subtype": "json"}


def test_parse_content_type_with_charset():
    assert parse_content_type("application/json; charset=utf-8") == {
        "type": "application",
        "subtype": "json",
        "charset": "utf-8",
    }


def test_parse_content_type_strips_quotes_in_param():
    assert parse_content_type('text/plain; q="0.5"') == {
        "type": "text",
        "subtype": "plain",
        "q": "0.5",
    }


def test_parse_content_type_lowercases_param_names():
    assert parse_content_type("application/json; CHARSET=utf-8") == {
        "type": "application",
        "subtype": "json",
        "charset": "utf-8",
    }


def test_parse_content_type_handles_missing_subtype():
    assert parse_content_type("application") == {"type": "application", "subtype": ""}


def test_parse_content_type_empty_returns_empty():
    assert parse_content_type("") == {}


def test_header_score_counts_core_headers():
    assert header_score({"content-type": "x", "accept": "y"}) == 2


def test_header_score_zero_for_unrelated_headers():
    assert header_score({"x-foo": "y"}) == 0


def test_header_score_treats_normalised_dupes_as_one():
    # both keys normalise to "Content-Type"; score must still be 1
    assert header_score({"content-type": "a", "Content-Type": "b"}) == 1
