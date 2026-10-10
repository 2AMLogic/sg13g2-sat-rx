"""Integrity-gate tests on temporary fixture installs (no PDK, no simulator)."""

import hashlib
import json

import pytest

from harness import pdkartifact
from harness.pdk import Pdk


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


COMMIT = "a" * 40


@pytest.fixture
def env(tmp_path):
    """A fake install + sim dir whose manifest matches the install."""
    root = tmp_path / "pdk" / "ihp"
    models = root / "libs.tech" / "ngspice" / "models"
    models.mkdir(parents=True)
    top = b".LIB typ\n.include sub.lib\n.ENDL typ\n"
    sub = b"* model\n"
    (models / "top.lib").write_bytes(top)
    (models / "sub.lib").write_bytes(sub)
    (root / ".fetched-version").write_text("9.9\n")
    sim = tmp_path / "sim"
    sim.mkdir()
    rel = "libs.tech/ngspice/models/"
    manifest = {
        "upstream": {"commit": COMMIT},
        "install_marker": {"value": "9.9"},
        "files": {rel + "top.lib": _sha(top), rel + "sub.lib": _sha(sub)},
        "ngspice": {"major": 46},
    }
    (sim / "pdk-artifact.json").write_text(json.dumps(manifest))
    pdk = Pdk(name="x", path=root, variant="ihp", source="test", model_lib_rel=rel + "top.lib")
    return pdk, sim, models, manifest


def test_matching_install_passes(env):
    pdk, sim, *_ = env
    assert pdkartifact.verify(pdk, sim).ok


def test_tampered_model_fails(env):
    pdk, sim, models, _ = env
    (models / "sub.lib").write_bytes(b"* model\n.param evil=1\n")
    rep = pdkartifact.verify(pdk, sim)
    assert not rep.ok and "differs from the pin" in rep.format()


def test_missing_model_fails(env):
    pdk, sim, models, _ = env
    (models / "sub.lib").unlink()
    assert not pdkartifact.verify(pdk, sim).ok


def test_matching_marker_does_not_rescue_wrong_hashes(env):
    pdk, sim, models, _ = env
    (models / "top.lib").write_bytes(b".LIB typ\n.ENDL typ\n")
    assert (pdk.path / ".fetched-version").read_text().strip() == "9.9"
    assert not pdkartifact.verify(pdk, sim).ok


def test_unknown_marker_is_reported_not_trusted(env):
    pdk, sim, *_ = env
    (pdk.path / ".fetched-version").unlink()
    rep = pdkartifact.verify(pdk, sim)
    assert rep.ok and "marker unknown" in rep.format()  # hashes alone decided
    assert pdk.version == "unknown"


def test_unknown_marker_with_wrong_hashes_fails(env):
    pdk, sim, models, _ = env
    (pdk.path / ".fetched-version").unlink()
    (models / "sub.lib").write_bytes(b"x")
    assert not pdkartifact.verify(pdk, sim).ok


def test_conflicting_marker_fails_even_with_good_hashes(env):
    pdk, sim, *_ = env
    (pdk.path / ".fetched-version").write_text("1.0\n")
    assert not pdkartifact.verify(pdk, sim).ok


def test_unhashed_include_fails(env):
    pdk, sim, models, manifest = env
    top = b".LIB typ\n.include sub.lib\n.include extra.lib\n.ENDL typ\n"
    (models / "top.lib").write_bytes(top)
    (models / "extra.lib").write_bytes(b"*\n")
    manifest["files"]["libs.tech/ngspice/models/top.lib"] = _sha(top)
    (sim / "pdk-artifact.json").write_text(json.dumps(manifest))
    rep = pdkartifact.verify(pdk, sim)
    assert not rep.ok and "not in the manifest" in rep.format()


def test_missing_or_bad_manifest_fails(env, tmp_path):
    pdk, sim, *_ = env
    (sim / "pdk-artifact.json").write_text("{not json")
    assert not pdkartifact.verify(pdk, sim).ok
    (sim / "pdk-artifact.json").unlink()
    assert not pdkartifact.verify(pdk, sim).ok


def test_short_commit_rejected(env):
    pdk, sim, _, manifest = env
    manifest["upstream"]["commit"] = "v0.3.0"
    (sim / "pdk-artifact.json").write_text(json.dumps(manifest))
    assert not pdkartifact.verify(pdk, sim).ok


def test_ngspice_version_policy(env):
    pdk, sim, *_ = env
    assert pdkartifact.verify(pdk, sim, "ngspice-46 : x", require_ngspice=True).ok
    assert not pdkartifact.verify(pdk, sim, "ngspice-45 : x", require_ngspice=True).ok
    assert not pdkartifact.verify(pdk, sim, None, require_ngspice=True).ok
    assert pdkartifact.verify(pdk, sim, "ngspice-45 : x").ok  # local: note only


def test_committed_manifest_is_well_formed():
    from harness.pdk import SIM_DIR
    m = pdkartifact.load_manifest(SIM_DIR)
    assert len(m["upstream"]["commit"]) == 40 and m["files"]


def test_verified_identity_on_markerless_install(env):
    pdk, sim, *_ = env
    (pdk.path / ".fetched-version").unlink()
    ident = pdkartifact.verified_identity(pdk, sim)
    assert ident["status"] == "verified" and ident["upstream_commit"] == COMMIT
    assert ident["manifest_sha256"] == _sha((sim / "pdk-artifact.json").read_bytes())
    assert ident["files_verified"] == 2 and pdk.version == "unknown"
    pdkartifact.validate_identity(ident)


def test_no_identity_for_tampered_or_missing_models_or_manifest(env):
    pdk, sim, models, _ = env
    (models / "sub.lib").write_bytes(b"tampered\n")
    with pytest.raises(pdkartifact.ArtifactNotVerified):
        pdkartifact.verified_identity(pdk, sim)
    (models / "sub.lib").unlink()
    with pytest.raises(pdkartifact.ArtifactNotVerified):
        pdkartifact.verified_identity(pdk, sim)
    (sim / "pdk-artifact.json").unlink()
    with pytest.raises(pdkartifact.ArtifactNotVerified):
        pdkartifact.verified_identity(pdk, sim)
