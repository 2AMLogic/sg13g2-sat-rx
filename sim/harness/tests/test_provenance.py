"""Tests for the shared provenance helpers (issue #144).

The three mixer probe drivers and the lna-linearity CI assertion used to
carry per-file copies of the provenance plumbing; they now import one module.
These tests pin the behavior those records depend on: helper output shapes
must stay byte-compatible with existing append-only records, the record-id
format and its collision checks are frozen, and no driver re-defines a local
copy again. No PDK, no simulator.
"""

from __future__ import annotations

import ast
import datetime as _dt
import hashlib
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SIM = Path(__file__).resolve().parents[2]
if str(SIM) not in sys.path:
    sys.path.insert(0, str(SIM))

from harness import klt_driver, pdkartifact, provenance  # noqa: E402
from harness.pdk import REPO_ROOT  # noqa: E402

FROZEN = _dt.datetime(2026, 10, 11, 12, 34, 56, tzinfo=_dt.timezone.utc)
SHORT = "deadbee"


# ---- hashing: one implementation, three former copies ---------------------------------------


def test_sha256_matches_hashlib_across_chunk_boundaries(tmp_path):
    data = b"\x00" * (2 * (1 << 20) + 17) + b"tail"
    p = tmp_path / "blob.bin"
    p.write_bytes(data)
    assert provenance.sha256_file(p) == hashlib.sha256(data).hexdigest()


def _reads_own_param(node: ast.AST, params: set[str]) -> bool:
    """True when *node* is a call that reads data from one of *params*.

    ``open(<param>, ...)`` or ``<param>.open() / .read_bytes() / .read_text()``
    -- the two shapes the harness's file hashers use to reach the bytes.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return (func.id == "open" and bool(node.args)
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id in params)
    if isinstance(func, ast.Attribute):
        return (func.attr in {"open", "read_bytes", "read_text"}
                and isinstance(func.value, ast.Name)
                and func.value.id in params)
    return False


def _hashlib_import_aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Names *tree*'s imports bind to the ``hashlib`` module and to
    ``hashlib.sha256`` directly.

    Covers ``import hashlib``, ``import hashlib as hl``, ``from hashlib
    import sha256`` and ``from hashlib import sha256 as h``. A plain
    assignment (``sha256 = sha256_file``) is not an import, so it binds
    nothing here.
    """
    modules: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "hashlib":
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "hashlib":
            for alias in node.names:
                if alias.name == "sha256":
                    names.add(alias.asname or alias.name)
    return modules, names


def _calls_sha256(nodes, modules: set[str], names: set[str]) -> bool:
    """True when any of *nodes* is a call reaching ``hashlib.sha256``.

    Both spellings count: the attribute form ``hashlib.sha256(...)`` (or any
    module alias of it) and the bare-name form ``sha256(...)`` when ``sha256``
    was imported from hashlib.
    """
    for n in nodes:
        if not isinstance(n, ast.Call):
            continue
        func = n.func
        if isinstance(func, ast.Attribute):
            if (func.attr == "sha256" and isinstance(func.value, ast.Name)
                    and func.value.id in modules):
                return True
        elif isinstance(func, ast.Name) and func.id in names:
            return True
    return False


def _hashes_own_param(node, modules: set[str], names: set[str]) -> bool:
    """True when *node* (a def) hashes data read from its own parameters."""
    params = {a.arg for a in [*node.args.posonlyargs, *node.args.args,
                              *node.args.kwonlyargs]}
    params -= {"self", "cls"}
    if not params:
        return False
    body = list(ast.walk(node))
    return (any(_reads_own_param(n, params) for n in body)
            and _calls_sha256(body, modules, names))


def _sha256_file_hashers(path: Path) -> set[str]:
    """Def names in *path* that hash data read from their own params.

    Module-level defs *and* class methods are candidates (the def's params
    for a method are its parameters minus ``self``/``cls``, so a ``@property``
    digest with only ``self`` is not one). The body may reach the digest
    through any import spelling of ``hashlib.sha256`` -- see
    :func:`_hashlib_import_aliases`. Nested defs' own parameters are not the
    enclosing def's, so a nested helper hashing its own argument is not
    attributed here.
    """
    tree = ast.parse(path.read_text())
    modules, names = _hashlib_import_aliases(tree)
    defs: list = []
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.append(stmt)
        elif isinstance(stmt, ast.ClassDef):
            defs.extend(s for s in stmt.body
                        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)))
    return {d.name for d in defs
            if _hashes_own_param(d, modules, names)}


def test_sha256_is_the_single_definition_in_the_harness():
    assert provenance.sha256 is provenance.sha256_file
    assert pdkartifact.sha256_file is provenance.sha256_file
    assert klt_driver.sha256_file is provenance.sha256_file
    # Every harness module, not a hardcoded trio: the canonical definition
    # lives in provenance, and evidence_store may carry its own because its
    # manifests record the byte count beside the digest. Any other module
    # defining sha256_file fails here instead of hiding beside the name.
    harness_dir = Path(provenance.__file__).resolve().parent
    definitions = {
        p.name for p in harness_dir.glob("*.py")
        if "def sha256_file(" in p.read_text()
    }
    assert definitions == {"provenance.py", "evidence_store.py"}
    # The name needle above is blind to a second file hasher under any
    # other name, so this AST check also requires: no harness module
    # defines a module-level def or class method that hashes data read
    # from its own parameter, whatever it is called and however hashlib
    # is imported. The two survivors are exactly the allow-listed pair;
    # everything else is excluded structurally: the inline digests of
    # literals (evidence_store's empty-bytes constant and uri-scheme
    # probe) read no parameter, the @property netlist/manifest digests
    # keep only ``self`` once self/cls are subtracted from a method's
    # parameters, and frozen_dut.sha256_path delegates without ever
    # touching hashlib. A plain assignment (``provenance.sha256 =
    # sha256_file``) is not a hashlib import, so it binds no bare-name
    # alias for the detector.
    hashers = {
        (p.name, name)
        for p in harness_dir.glob("*.py")
        for name in _sha256_file_hashers(p)
    }
    assert hashers == {("provenance.py", "sha256_file"),
                       ("evidence_store.py", "sha256_file")}


# ---- git provenance: the probe record shape is exactly {"commit", "dirty"} -------------------


def test_git_info_shape_matches_the_probe_record_contract():
    info = provenance.git_info(REPO_ROOT)
    assert set(info) == {"commit", "dirty"}
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()
    assert info["commit"] == head
    assert isinstance(info["dirty"], bool)


def test_git_out_strips_subprocess_stdout(tmp_path):
    (tmp_path / "x").write_text("x")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "x"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
                   cwd=tmp_path, check=True)
    direct = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=tmp_path,
                            capture_output=True, text=True, check=True).stdout
    assert provenance.git_out("rev-parse", "--abbrev-ref", "HEAD", cwd=tmp_path) == direct.strip()
    assert provenance.git_out("status", "--porcelain", cwd=tmp_path) == ""


# ---- record ids: format frozen, probe collision set (records glob + extra log dirs) ----------


def test_new_record_id_format():
    rid = provenance.new_record_id(SHORT, REPO_ROOT / "records", when=FROZEN)
    assert rid == f"20261011-123456-{SHORT}"
    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{7,40}", rid)


def test_new_record_id_avoids_record_glob_and_log_dirs(tmp_path):
    records, logs = tmp_path / "records", tmp_path / "probe-logs"
    records.mkdir()
    logs.mkdir()
    # a same-second record file (any status suffix) blocks the id via the records glob ...
    (records / f"20261011-123456-{SHORT}-PASS.json").write_text("")
    rid = provenance.new_record_id(SHORT, records, logs, when=FROZEN)
    assert rid == f"20261011-123457-{SHORT}"
    # ... and a same-second probe-log directory blocks it via the extra dir ...
    (logs / rid).mkdir()
    rid = provenance.new_record_id(SHORT, records, logs, when=FROZEN)
    assert rid == f"20261011-123458-{SHORT}"
    # ... while a different-second record never collides and the clock is not consumed.
    (records / f"20261011-123458-{SHORT}-FAIL.md").write_text("")
    assert provenance.new_record_id(SHORT, records, logs, when=FROZEN) == f"20261011-123459-{SHORT}"
    assert provenance.new_record_id("ffffff", records, logs, when=FROZEN) == f"20261011-123456-ffffff"


# ---- simulator / PDK / manifest identity ------------------------------------------------------


@pytest.fixture()
def fake_ngspice(tmp_path):
    exe = tmp_path / "ngspice-fake"
    exe.write_text("#!/bin/sh\necho ' * ngspice-46 : Circuit level simulation program'\n")
    exe.chmod(0o755)
    return exe


def test_ngspice_info_parses_a_fake_executable(fake_ngspice):
    info = provenance.ngspice_info(str(fake_ngspice))
    assert set(info) == {"path", "version", "major", "sha256"}
    assert info["path"] == str(fake_ngspice)
    assert info["version"] == "ngspice-46 : Circuit level simulation program"
    assert info["major"] == 46
    assert info["sha256"] == hashlib.sha256(fake_ngspice.resolve().read_bytes()).hexdigest()


def test_ngspice_info_reports_unknown_version_as_major_none(tmp_path):
    exe = tmp_path / "not-ngspice"
    exe.write_text("#!/bin/sh\necho 'whatever'\n")
    exe.chmod(0o755)
    info = provenance.ngspice_info(str(exe))
    assert info["version"] == "unknown"
    assert info["major"] is None


def test_pdk_info_shape_is_byte_compatible(tmp_path, monkeypatch):
    pdk_root = tmp_path / "pdk"
    models = pdk_root / "libs" / "models"
    models.mkdir(parents=True)
    (pdk_root / ".fetched-version").write_text("9.9.9-test\n")
    corner, hbt_mod = models / "cornerHBT.lib", models / "sg13g2_hbt_mod.lib"
    corner.write_text("* corner")
    hbt_mod.write_text("* hbt")

    class FakePdk:
        path = pdk_root
        model_lib = corner

    monkeypatch.setattr(sys.modules["harness.pdk"], "find_pdk", lambda sim_dir: FakePdk())
    info = provenance.pdk_info(tmp_path)
    assert set(info) == {"path", "fetched_version", "model_lib", "section", "sha256", "device"}
    assert info["fetched_version"] == "9.9.9-test"
    assert info["section"] == "hbt_typ"
    assert info["sha256"] == {"cornerHBT.lib": hashlib.sha256(corner.read_bytes()).hexdigest(),
                              "sg13g2_hbt_mod.lib": hashlib.sha256(hbt_mod.read_bytes()).hexdigest()}


def test_pdk_info_fetched_version_read_is_frozen(tmp_path, monkeypatch):
    """The probe read stays byte-compatible with the pre-#155 records.

    Two deliberate divergences from ``Pdk.version`` are pinned: the parent
    dir's marker wins over the variant dir's, and an absent marker reports
    the literal ``"unknown"`` even when a ``SOURCES`` file could supply a
    value. Delegating to ``Pdk.version`` would silently change what existing
    append-only records recorded.
    """
    pdk_root = tmp_path / "pdk"
    models = pdk_root / "libs" / "models"
    models.mkdir(parents=True)
    corner = models / "cornerHBT.lib"
    corner.write_text("* corner")
    (models / "sg13g2_hbt_mod.lib").write_text("* hbt")

    class FakePdk:
        path = pdk_root
        model_lib = corner

    monkeypatch.setattr(sys.modules["harness.pdk"], "find_pdk", lambda sim_dir: FakePdk())

    # Marker present in BOTH the parent dir and the variant dir: parent wins.
    (tmp_path / ".fetched-version").write_text("parent-marker\n")
    (pdk_root / ".fetched-version").write_text("variant-marker\n")
    assert provenance.pdk_info(tmp_path)["fetched_version"] == "parent-marker"

    # Marker absent everywhere but SOURCES exists: literal "unknown", never
    # the SOURCES value (that fallback belongs to Pdk.version, not records).
    (tmp_path / ".fetched-version").unlink()
    (pdk_root / ".fetched-version").unlink()
    (pdk_root / "SOURCES").write_text("sources-line\n")
    assert provenance.pdk_info(tmp_path)["fetched_version"] == "unknown"


def test_pinned_major_reads_the_artifact_manifest(tmp_path):
    artifact = tmp_path / "pdk-artifact.json"
    artifact.write_text('{"ngspice": {"major": 46}}')
    assert provenance.pinned_major(artifact) == 46
    with pytest.raises(OSError):
        provenance.pinned_major(tmp_path / "missing.json")


# ---- exclusive-create writes -------------------------------------------------------------------


def test_write_excl_creates_parents_and_never_overwrites(tmp_path):
    target = tmp_path / "a" / "b" / "record.md"
    provenance.write_excl(target, "first\n")
    assert target.read_text() == "first\n"
    with pytest.raises(FileExistsError):
        provenance.write_excl(target, "second\n")
    assert target.read_text() == "first\n"


# ---- the drivers import, never redefine (regression against copy-paste return) -----------------


_DRIVER_FILES = (
    "mixer-cm-interface-probe/run_probe.py",
    "mixer-pumped-rf-admittance/run_probe.py",
    "mixer-nf-method/run_probe.py",
    "lna-linearity/ci_assert.py",
    "mixer-cm-interface-probe/ci_assert.py",
    "mixer-pumped-rf-admittance/ci_assert.py",
)

_COPIED_HELPERS = ("sha256", "sha256_file", "ngspice_info", "pdk_info", "git_info",
                   "new_record_id", "write_excl", "pinned_major")


@pytest.mark.parametrize("rel", _DRIVER_FILES)
def test_drivers_do_not_redefine_the_shared_helpers(rel):
    text = (SIM / rel).read_text()
    defined = [name for name in _COPIED_HELPERS if f"def {name}(" in text]
    assert not defined, f"{rel} redefines {defined}; import from harness.provenance instead"
    if rel.endswith("run_probe.py"):
        assert "from harness.provenance import" in text


def test_parse_marks_rejects_non_finite_and_non_numeric():
    from harness.provenance import finite_float, parse_marks
    out = "noise\nMARK a=1.5 b=inf c=nan d=x e=\nMARK a=2\nMARK done\n"
    assert parse_marks(out) == {"a": 2.0, "b": None, "c": None, "d": None, "e": None}
    assert finite_float(None) is None and finite_float("-1e3") == -1000.0


def test_pdk_integrity_gate_string_names_require_ngspice(monkeypatch):
    from harness import pdk, pdkartifact
    from harness.provenance import pdk_integrity
    seen = {}

    def fake_verify(p, sim_dir, banner=None, require_ngspice=False):
        seen.update(banner=banner, req=require_ngspice)
        return SimpleNamespace(ok=True, problems=[], notes=["n"])

    monkeypatch.setattr(pdk, "find_pdk", lambda d: "PDK")
    monkeypatch.setattr(pdkartifact, "verify", fake_verify)
    rec = pdk_integrity(SIM, "b", require_ngspice=True)
    assert rec == {"gate": "sim/harness/pdkartifact.py verify(require_ngspice=True)", "ok": True,
                   "problems": [], "notes": ["n"]}
    assert seen == {"banner": "b", "req": True}
    assert "require_ngspice=False" in pdk_integrity(SIM, require_ngspice=False)["gate"]
