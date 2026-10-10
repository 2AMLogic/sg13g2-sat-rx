"""Shared plumbing for the per-study ``klt sim`` drivers.

The Ka-band, LNA S-parameter/NF and mixer-topology studies each express their
grid as ``klt sim`` requests and ingest the returned logs. The mechanical
helpers below were hand-copied into each driver; they live here once so a fix
(e.g. to ``stage_model_inputs`` / ``runner_version_check`` handling) cannot
drift between studies. Study-specific parts (the body text, the sentinel
name/node, ``MODEL_FILES``, how corners are named) stay in the drivers, which
keep their historical function names as thin call sites.

Generated request JSON and body text are evidence inputs (their hashes are
cited in ``records/``): changing anything here must keep them byte-identical.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from . import pdkartifact
from .pdk import PdkConfigError, PdkNotFound, find_pdk


def body_supply(body: Path) -> float:
    """The ``.param vdd_val=`` supply a generated klt body was written for."""
    for line in body.read_text().splitlines():
        if line.startswith(".param vdd_val="):
            return float(line.split("=", 1)[1])
    raise SystemExit(f"error: no .param vdd_val in {body}")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_pdk_or_exit(sim_dir: Path, *, require_artifact: bool = False):
    """``find_pdk`` with a clean ``SystemExit``; optionally run the pinned-model
    integrity gate (``pdkartifact.require``) before any simulator launches."""
    try:
        pdk = find_pdk(sim_dir)
    except (PdkNotFound, PdkConfigError) as exc:
        raise SystemExit(f"error: {exc}")
    if require_artifact:
        pdkartifact.require(pdk, sim_dir)
    return pdk


def klt_request(body_name: str, corner_names: Iterable[str], temps: Iterable[float], backend: str,
                timeout_s: int, *, sentinel_name: str, sentinel_node: str,
                stage_models: bool = True, runner_version_check: str = "") -> dict:
    """One klt sim request. klt's own trailing analysis is a 2 ps transient
    whose only purpose is a sentinel ``.meas tran`` of the supply rail, so klt
    grades every corner on a real value (and the request stays valid for older
    klt clients/runners). The body's own deck does the study."""
    req = {
        "netlist": body_name,
        "backend": backend,
        "models": {"pdk": "ihp-sg13g2", "lib": "libs.tech/ngspice/models/cornerHBT.lib"},
        "corners": {"process": list(corner_names), "temperature_c": list(temps)},
        "analysis": {"kind": "tran", "args": "1p 2p"},
        "measurements": [
            {"name": sentinel_name,
             "spice": f".meas tran {sentinel_name} FIND {sentinel_node} AT=2p", "unit": "V"},
        ],
        "options": {"timeout_s": timeout_s, "keep_artifacts": True},
    }
    if stage_models:
        req["options"]["stage_model_inputs"] = True
    if backend == "batch" and runner_version_check:
        req["batch"] = {"runner_version_check": runner_version_check}
    return req


def pdk_provenance(pdk, model_files: Iterable[str]) -> dict:
    """Where the models came from: variant path, install marker, model hashes."""
    models_dir = pdk.model_lib.parent
    prov = {
        "variant_path": str(pdk.path),
        "fetched_version_file": None,
        "model_sha256": {name: sha256_file(models_dir / name) for name in model_files
                         if (models_dir / name).is_file()},
    }
    fv = pdk.path / ".fetched-version"
    if fv.is_file():
        prov["fetched_version_file"] = fv.read_text().strip()
    return prov
