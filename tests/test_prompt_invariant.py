import re
from triadic_dgm.prompts import prompts


def _v2_body() -> str:
    src = open(prompts.__file__, encoding="utf-8").read()
    m = re.search(r"PROGRAMMER_PROMPT_V2 = '''(.*?)'''", src, re.S)
    assert m, "PROGRAMMER_PROMPT_V2 triple-single-quoted block not found"
    return m.group(1)


def test_programmer_prompt_braces_balanced_and_doubled():
    body = _v2_body()
    # The raw prompt convention: every brace is doubled. Counts must match and be non-trivial.
    assert body.count("{{") == body.count("}}")
    assert body.count("{{") >= 50  # guards against an accidental single-brace edit


def test_programmer_prompt_documents_generic_default():
    # Soft-steering assertion: the mode block now names GENERIC as the default.
    assert "GENERIC" in _v2_body()
