"""The base evidence-record extension slot, and where block-specific
evidence-schema fields attach.

GENERIC CORE: :data:`RECORD_KINDS` (a run is either a ``corner-matrix`` PVT
sweep checked against a pass/fail spec, or a ``characterization`` record
that states a measured value plus how it was obtained), and
:class:`BaseExtensions` -- an open, append-only-safe bag for whatever
record-level fields a block's own evidence convention needs beyond the base
fields already on ``testbench.Testbench`` (claim, netlist_provenance,
measure, checks, ...) and ``report.build_record``'s own fields (grid,
summary, sensitivity, environment). ``extra`` and ``notes`` round-trip
through a ``tb.json`` manifest's ``evidence`` block untouched, and render as
plain bullet lines in the Markdown record -- so a fresh block gets a working
evidence path with zero schema fields of its own before it has decided what
those fields are.

EXTENSION POINT -- once a block has ratified its own evidence convention
(the kind of methodology fields a spec doc names, e.g. "every FFT-derived
claim must state N samples, coherent bin, and window"), it should stop
routing that data through ``extra`` and instead subclass or replace
:class:`BaseExtensions` with a dataclass carrying named, *validated* fields
-- an unvalidated free-text field is exactly the footgun a ratified
convention exists to close. See
``gf180-sar-adc/sim/harness/evidence.py`` for a worked example: five
named extension groups (dynamic-test/FFT metadata, linearity methodology,
Monte Carlo convention, noise methodology, characterization provenance),
each with its own required-field and allowed-value validation, is what a
block's evidence.py grows into once its convention is ratified.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

#: A run is either checked against a pass/fail spec (the common case) or
#: states a measured value plus its provenance ("characterization" --
#: sim/harness/report.py's Markdown record renders the two differently).
RECORD_KINDS: tuple[str, ...] = ("corner-matrix", "characterization")


class EvidenceFormatError(ValueError):
    """A record would not conform to the (block-ratified) evidence schema."""


@dataclass
class BaseExtensions:
    """Generic-core evidence extension fields for one record.

    Everything beyond ``record_kind`` is deliberately unstructured: ``extra``
    is a flat string-keyed bag for whatever a block wants to record before it
    has ratified a schema for it, and ``notes`` is free-text. Neither is
    validated beyond the checks below -- once a block's evidence convention
    is ratified, replace this class (see the module docstring) rather than
    growing ``extra`` into an ad hoc schema no validator enforces.
    """

    record_kind: str = "corner-matrix"
    #: Required on a "characterization" record: how the measured value was
    #: obtained (e.g. "simulated", "foundry-documentation"). Left as free
    #: text here; a block's ratified convention should constrain this to a
    #: named tag set the way gf180-sar-adc's DATA_PROVENANCE_TAGS does.
    data_provenance: str = ""
    extra: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def is_characterization(self) -> bool:
        return self.record_kind == "characterization"

    def validate(self) -> None:
        """Raise :class:`EvidenceFormatError` if the record would not conform."""
        problems: list[str] = []
        if self.record_kind not in RECORD_KINDS:
            problems.append(
                f"record kind {self.record_kind!r} is not one of {', '.join(RECORD_KINDS)}"
            )
        if self.is_characterization and not self.data_provenance:
            problems.append(
                "a characterization record must state data_provenance "
                "(sim/harness/evidence.py: how the measured value was obtained)"
            )
        if problems:
            raise EvidenceFormatError(
                "record would not conform to the evidence schema:\n  - " + "\n  - ".join(problems)
            )

    def as_dict(self) -> dict:
        return asdict(self)

    def render_lines(self) -> list[str]:
        """Extension fields, as Markdown record bullets.

        Ordered to sit between the base fields (claim, statistical
        convention) and the result. A block replacing this class controls
        this ordering itself; see the module docstring.
        """
        lines: list[str] = []
        if self.data_provenance:
            lines.append(f"- **Data provenance**: {self.data_provenance}")
        for key, value in self.extra.items():
            lines.append(f"- **{key}**: {value}")
        for note in self.notes:
            lines.append(f"- **Note**: {note}")
        return lines


#: Manifest (``tb.json``) key -> :class:`BaseExtensions` attribute.
MANIFEST_KEYS: dict[str, str] = {
    "record_kind": "record_kind",
    "data_provenance": "data_provenance",
    "extra": "extra",
    "notes": "notes",
}


def from_manifest(block: dict | None) -> BaseExtensions:
    """Build :class:`BaseExtensions` from a ``tb.json`` ``evidence`` block.

    A block that has replaced :class:`BaseExtensions` with its own subclass
    should replace this function too (or wrap it), since the manifest keys
    it accepts are exactly this class's field set.
    """
    block = dict(block or {})
    unknown = sorted(set(block) - set(MANIFEST_KEYS))
    if unknown:
        raise EvidenceFormatError(
            f"unknown key(s) in the manifest's 'evidence' block: {', '.join(unknown)}; "
            f"known: {', '.join(sorted(MANIFEST_KEYS))}"
        )
    kwargs = {MANIFEST_KEYS[key]: value for key, value in block.items()}
    if "notes" in kwargs and isinstance(kwargs["notes"], str):
        kwargs["notes"] = [kwargs["notes"]]
    return BaseExtensions(**kwargs)
