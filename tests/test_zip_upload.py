"""A .zip upload must become the data inside it, or fail loudly.

Before this, an archive was stored verbatim and then silently ignored — load_dataset()
only reads tabular extensions, so the analysis quietly ran on whatever OTHER dataset was
newest while the user believed they had supplied theirs. Observed live: a marketing
dataset sat unread inside `archive (1).zip` for two days.

A zip is untrusted input, so the extraction guards are tested as security properties, not
as niceties.
"""
import io
import json
import zipfile

import pytest

from api.services.workspace import extract_tabular_from_zip

_CSV = b"a,b\n1,2\n3,4\n"


def _zip(entries, compresslevel=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries:
            z.writestr(name, data)
    return buf.getvalue()


def test_extracts_a_plain_csv():
    extracted, skipped = extract_tabular_from_zip(_zip([("marketing_campaign.csv", _CSV)]))
    assert extracted == [("marketing_campaign.csv", _CSV)]
    assert skipped == []


def test_flattens_nested_directories():
    """Directory structure is irrelevant once the file is registered by file_id."""
    extracted, _ = extract_tabular_from_zip(_zip([("data/2024/sales.csv", _CSV)]))
    assert extracted[0][0] == "sales.csv"


def test_ignores_non_tabular_members_quietly():
    extracted, skipped = extract_tabular_from_zip(
        _zip([("README.md", b"# hi"), ("logo.png", b"\x89PNG"), ("d.csv", _CSV)])
    )
    assert [n for n, _ in extracted] == ["d.csv"]
    assert skipped == []  # a README is not a problem worth reporting


def test_extracts_several_datasets():
    extracted, _ = extract_tabular_from_zip(_zip([("a.csv", _CSV), ("b.tsv", _CSV)]))
    assert sorted(n for n, _ in extracted) == ["a.csv", "b.tsv"]


# --- security properties -------------------------------------------------------------

@pytest.mark.parametrize("evil", ["../../../etc/passwd.csv", "/etc/shadow.csv"])
def test_rejects_path_traversal(evil):
    """Zip slip: a member must never be able to name a path outside the workspace."""
    extracted, skipped = extract_tabular_from_zip(_zip([(evil, _CSV)]))
    assert extracted == []
    assert any("không an toàn" in s for s in skipped)


def test_rejects_a_zip_bomb_by_compression_ratio():
    """A tiny archive that expands enormously is refused before it is written to disk."""
    bomb = _zip([("bomb.csv", b"0" * (20 * 1024 * 1024))])
    assert len(bomb) < 200_000  # highly compressible
    extracted, skipped = extract_tabular_from_zip(bomb)
    assert extracted == []
    assert any("zip bomb" in s for s in skipped)


def test_caps_the_number_of_members():
    extracted, _ = extract_tabular_from_zip(_zip([(f"f{i}.csv", _CSV) for i in range(50)]))
    assert len(extracted) <= 20


def test_a_corrupt_archive_reports_instead_of_raising():
    extracted, skipped = extract_tabular_from_zip(b"this is not a zip file at all")
    assert extracted == []
    assert skipped and "hỏng" in skipped[0]


def test_an_archive_with_no_data_files_yields_nothing_to_register():
    """The caller turns this into a visible rejection rather than storing a dead file."""
    extracted, skipped = extract_tabular_from_zip(_zip([("notes.txt", b"hello")]))
    assert extracted == []
    assert skipped == []


# --- separator detection -------------------------------------------------------------

def test_sniff_detects_tab_separated_csv(tmp_path):
    """A ".csv" that is really tab-separated is common (this exact file shipped inside the
    user's zip). Read with the comma default it yields ONE column named after the whole
    header line, which left the DatasetProfile with zero features and every persona
    unnamed — a failure that only surfaced three layers downstream."""
    from api.services.workspace import sniff_separator

    p = tmp_path / "marketing.csv"
    p.write_text("ID\tYear\tIncome\n1\t1980\t50000\n2\t1990\t60000\n", encoding="utf-8")
    assert sniff_separator(p) == "\t"


def test_sniff_leaves_ordinary_csv_alone(tmp_path):
    from api.services.workspace import sniff_separator

    p = tmp_path / "plain.csv"
    p.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    assert sniff_separator(p) == ","


def test_sniff_detects_semicolon(tmp_path):
    from api.services.workspace import sniff_separator

    p = tmp_path / "euro.csv"
    p.write_text("a;b;c\n1;2;3\n", encoding="utf-8")
    assert sniff_separator(p) == ";"


def test_sniff_falls_back_to_comma_on_a_single_column_file(tmp_path):
    from api.services.workspace import sniff_separator

    p = tmp_path / "one.csv"
    p.write_text("only\n1\n2\n", encoding="utf-8")
    assert sniff_separator(p) == ","


def test_stored_separator_prefers_metadata_over_extension(tmp_path):
    """The extension is only a fallback; what was measured at upload time wins."""
    from api.services.profile_provider import stored_separator

    (tmp_path / "Metadata").mkdir()
    (tmp_path / "Metadata" / "x.json").write_text(json.dumps({"separator": "\t"}), encoding="utf-8")
    info = {"metadata_file": "Metadata/x.json"}
    assert stored_separator(str(tmp_path), info, ".csv") == "\t"


def test_stored_separator_falls_back_when_nothing_recorded(tmp_path):
    from api.services.profile_provider import stored_separator

    assert stored_separator(str(tmp_path), {}, ".csv") == ","
    assert stored_separator(str(tmp_path), {}, ".tsv") == "\t"
