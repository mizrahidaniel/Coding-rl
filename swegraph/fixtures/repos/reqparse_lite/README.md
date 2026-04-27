# reqparse_lite

A small but realistic request-parsing utility used as a v3 ingestion target.

Modules:
- `query.py` — query-string parser with type coercion and list flattening.
- `headers.py` — header normalisation and content-type parsing.
- `payload.py` — envelope unpacking, paging cursor decoding, depth limits.

The module pretends to be a real Python package: ~250 LOC of source plus a
real-shaped pytest suite (~200 LOC). The SWEGraph ingest pipeline runs an
AST-based procedural mutator over each non-test module, classifies mutants
as survived vs killed against the test suite, and turns each surviving
mutant into a SWEGraph task with a public/hidden test split.
