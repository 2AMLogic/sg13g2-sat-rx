"""evidence.py: the base extension slot and its manifest parsing."""

import pytest

from harness import evidence as E


def test_default_is_a_valid_corner_matrix_record():
    ext = E.BaseExtensions()
    ext.validate()
    assert ext.record_kind == "corner-matrix" and not ext.is_characterization


def test_characterization_requires_provenance():
    with pytest.raises(E.EvidenceFormatError, match="data_provenance"):
        E.BaseExtensions(record_kind="characterization").validate()
    E.BaseExtensions(record_kind="characterization", data_provenance="simulated").validate()


def test_unknown_kind_rejected():
    with pytest.raises(E.EvidenceFormatError, match="record kind"):
        E.BaseExtensions(record_kind="vibes").validate()


def test_manifest_unknown_key_rejected():
    with pytest.raises(E.EvidenceFormatError, match="bogus"):
        E.from_manifest({"bogus": 1})


def test_manifest_round_trip_and_string_note():
    ext = E.from_manifest({"data_provenance": "simulated", "notes": "one note", "extra": {"K": "v"}})
    assert ext.notes == ["one note"]
    assert ext.as_dict()["extra"] == {"K": "v"}


def test_none_block_gives_defaults():
    assert E.from_manifest(None) == E.BaseExtensions()


def test_render_lines_order_provenance_extra_notes():
    ext = E.BaseExtensions(data_provenance="simulated", extra={"K": "v"}, notes=["n1", "n2"])
    assert ext.render_lines() == [
        "- **Data provenance**: simulated", "- **K**: v", "- **Note**: n1", "- **Note**: n2",
    ]
    assert E.BaseExtensions().render_lines() == []
