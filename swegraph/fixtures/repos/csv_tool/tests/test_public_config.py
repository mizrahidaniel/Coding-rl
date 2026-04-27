from csv_tool.core import parse_csv


def test_parse_csv_with_delimiter_key():
    cfg = {"delimiter": ";"}
    rows = parse_csv("a;b\n1;2\n", config=cfg)
    assert rows == [{"a": "1", "b": "2"}]
