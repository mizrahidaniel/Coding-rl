from reqparse_lite.query import flatten_singletons, parse_query


def test_parse_empty_returns_empty_dict():
    assert parse_query("") == {}


def test_parse_strips_leading_question_mark():
    assert parse_query("?a=1") == {"a": [1]}


def test_parse_repeated_keys_collect_into_list():
    assert parse_query("a=1&a=2&a=3") == {"a": [1, 2, 3]}


def test_parse_coerces_int():
    assert parse_query("n=42") == {"n": [42]}


def test_parse_coerces_float():
    assert parse_query("ratio=0.5") == {"ratio": [0.5]}


def test_parse_coerces_bool_true():
    assert parse_query("flag=true") == {"flag": [True]}


def test_parse_coerces_bool_false_case_insensitive():
    assert parse_query("flag=False") == {"flag": [False]}


def test_parse_coerces_none_when_value_missing():
    assert parse_query("nope=") == {"nope": [None]}


def test_parse_skips_empty_pairs():
    assert parse_query("a=1&&b=2") == {"a": [1], "b": [2]}


def test_parse_strips_whitespace():
    assert parse_query("  a  =  1  ") == {"a": [1]}


def test_parse_disable_coerce_returns_raw_strings():
    assert parse_query("n=42", coerce=False) == {"n": ["42"]}


def test_flatten_collapses_singletons():
    assert flatten_singletons({"a": [1], "b": [1, 2]}) == {"a": 1, "b": [1, 2]}


def test_flatten_handles_empty():
    assert flatten_singletons({}) == {}


def test_parse_handles_key_only_pair():
    assert parse_query("flag") == {"flag": [None]}


def test_parse_negative_int():
    assert parse_query("n=-3") == {"n": [-3]}


def test_parse_scientific_notation():
    assert parse_query("x=1e2") == {"x": [100.0]}
