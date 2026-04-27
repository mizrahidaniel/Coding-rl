def parse_csv(text: str, config: dict | None = None) -> list[dict[str, str]]:
    delimiter = (config or {}).get("delimiter", ",")
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return []
    headers = lines[0].split(delimiter)
    rows = []
    for line in lines[1:]:
        vals = line.split(delimiter)
        rows.append(dict(zip(headers, vals)))
    return rows


def export_csv(rows: list[dict[str, str]], delimiter: str = ",") -> str:
    if not rows:
        return ""
    headers = list(rows[0].keys())
    out = [delimiter.join(headers)]
    for row in rows:
        out.append(delimiter.join(str(row.get(h, "")) for h in headers))
    return "\n".join(out) + "\n"


def filter_rows(rows: list[dict[str, str]], key: str, value: str) -> list[dict[str, str]]:
    return [r for r in rows if r.get(key) == value]
