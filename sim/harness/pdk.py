"""Generic PDK discovery.

GENERIC CORE. No PDK path is ever hardcoded into a netlist or a testbench;
everything resolves through this module so the harness runs unchanged on a
developer box, a CI runner, or a fresh agent container. Unlike a
single-PDK harness, this module does not know the PDK's name, model file
names, or variant scheme in advance — those live in ``sim/pdk.json``, a
config file the block author writes once when bootstrapping (see
"EXTENSION POINT" below).

Resolution order (first hit wins):

1. ``<PDK_NAME_UPPER>_PDK_PATH`` -- absolute path to the *variant* directory
   itself, e.g. ``GF180_PDK_PATH=~/.volare/gf180mcuD`` when
   ``sim/pdk.json``'s ``"name"`` is ``"gf180"``.
2. ``PDK_ROOT`` (+ ``PDK``, default from config) -- the conventional
   open_pdks / volare / ciel / OpenLane environment.
3. ``sim/pdk.local.json`` -- machine-local override, git-ignored.
4. ``sim/pdk.json`` -- committed defaults: name, variant, search roots, and
   the relative paths to the files that make a variant directory "valid".
5. Built-in search roots -- volare store, ciel store, common install
   prefixes.

EXTENSION POINT -- ``sim/pdk.json`` (block-authored, not part of this core):

    {
      "name": "gf180",                          // required; drives the
                                                  // <NAME>_PDK_PATH env var
      "default_variant": "gf180mcuD",            // required
      "model_lib": "libs.tech/ngspice/sm141064.ngspice",   // required,
                                                  // relative to the variant
                                                  // dir -- the file
                                                  // corners.py's ``.lib``
                                                  // sections are read from
      "design_include": "libs.tech/ngspice/design.ngspice", // optional --
                                                  // global switches/params
                                                  // included ahead of the
                                                  // model library, if the
                                                  // PDK ships one
      "search_roots": ["/extra/pdk/store"]       // optional, prepended to
                                                  // the built-in roots
    }

A block with PDK-specific derived properties -- gf180-sar-adc's
``Pdk.mim_stack`` / ``Pdk.mim_subckt()``, which map a variant to the metal
pair its MIM capacitor model sits between -- adds them by subclassing
:class:`Pdk` or wrapping :func:`find_pdk`'s result, not by editing this
module. That is exactly the kind of block-specific derived data this core
has no way to know in advance.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
SIM_DIR = HARNESS_DIR.parent
REPO_ROOT = SIM_DIR.parent

CONFIG_FILENAME = "pdk.json"
LOCAL_CONFIG_FILENAME = "pdk.local.json"

# Search roots used when nothing else pins the PDK down. Each is a directory
# expected to *contain* variant directories.
BUILTIN_SEARCH_ROOTS: tuple[str, ...] = (
    "~/.volare",
    "~/.ciel",
    "/usr/share/pdk",
    "/usr/local/share/pdk",
    "~/share/pdk",
    "/opt/pdk",
)

INSTALL_HINT = """\
PDK not found (or sim/pdk.json is not configured yet).

sim/pdk.json must name the PDK and the model file this harness resolves
paths against, e.g.:

    {
      "name": "<pdk-name>",
      "default_variant": "<variant>",
      "model_lib": "path/relative/to/the/variant/dir/models.ngspice"
    }

Once configured, point the harness at an install with one of:

    export <NAME>_PDK_PATH=/path/to/<variant>       # exact variant dir
    # or the conventional pair:
    export PDK_ROOT=/path/to/pdk-root
    export PDK=<variant>

...or commit-free machine-local config in sim/pdk.local.json (same shape as
sim/pdk.json; local wins on every key).
"""


class PdkConfigError(RuntimeError):
    """``sim/pdk.json`` is missing a key this module cannot proceed without."""


class PdkNotFound(RuntimeError):
    """Raised when no usable PDK install can be located."""


@dataclass(frozen=True)
class Pdk:
    """A located PDK install."""

    name: str            # e.g. "gf180" -- from sim/pdk.json's "name"
    path: Path            # the resolved variant directory
    variant: str          # e.g. "gf180mcuD"
    source: str           # how it was found (for provenance)
    model_lib_rel: str    # relative path to the model .lib file, from config
    design_include_rel: str | None = None

    @property
    def model_lib(self) -> Path:
        """Model ``.lib`` file. ``corners.py`` sections are read from here."""
        return self.path / self.model_lib_rel

    @property
    def design_include(self) -> Path | None:
        """Global switches/params include, if the PDK config names one."""
        return (self.path / self.design_include_rel) if self.design_include_rel else None

    @property
    def version(self) -> str:
        """Best-effort install revision, if the PDK records one in SOURCES."""
        sources = self.path / "SOURCES"
        if sources.is_file():
            text = sources.read_text().strip()
            if text:
                return text.splitlines()[0].strip()
        return "unknown"

    def provenance(self) -> dict:
        return {
            "name": self.name,
            "path": str(self.path),
            "variant": self.variant,
            "version": self.version,
            "discovered_via": self.source,
        }


def _expand(path: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(path)))


def _load_config(sim_dir: Path) -> dict:
    """Merge ``sim/pdk.json`` with ``sim/pdk.local.json`` (local wins)."""
    config: dict = {}
    for name in (CONFIG_FILENAME, LOCAL_CONFIG_FILENAME):
        candidate = sim_dir / name
        if candidate.is_file():
            try:
                config.update(json.loads(candidate.read_text()))
            except json.JSONDecodeError as exc:  # pragma: no cover - config typo
                raise PdkConfigError(f"{candidate} is not valid JSON: {exc}") from exc
    return config


def _require_config(config: dict, key: str, path_hint: Path) -> str:
    value = config.get(key)
    if not value:
        raise PdkConfigError(
            f"{path_hint / CONFIG_FILENAME}: missing required key {key!r}.\n\n" + INSTALL_HINT
        )
    return value


def _is_valid_variant_dir(path: Path, model_lib_rel: str) -> bool:
    return (path / model_lib_rel).is_file()


def find_pdk(sim_dir: Path | None = None) -> Pdk:
    """Locate a PDK install, or raise :class:`PdkNotFound` / :class:`PdkConfigError`."""
    sim_dir = sim_dir or SIM_DIR
    config = _load_config(sim_dir)

    name = _require_config(config, "name", sim_dir)
    model_lib_rel = _require_config(config, "model_lib", sim_dir)
    design_include_rel = config.get("design_include")
    variant = os.environ.get("PDK") or config.get("variant") or config.get("default_variant")
    if not variant:
        raise PdkConfigError(
            f"{sim_dir / CONFIG_FILENAME}: missing 'default_variant' (or set $PDK)."
        )

    env_var = f"{name.upper()}_PDK_PATH"
    direct = os.environ.get(env_var)
    if direct:
        path = _expand(direct)
        if not _is_valid_variant_dir(path, model_lib_rel):
            raise PdkNotFound(
                f"${env_var}={direct} does not look like a {name} variant directory "
                f"(expected {path / model_lib_rel}).\n\n" + INSTALL_HINT
            )
        return Pdk(
            name=name, path=path, variant=path.name, source=env_var,
            model_lib_rel=model_lib_rel, design_include_rel=design_include_rel,
        )

    tried: list[str] = []

    pdk_root = os.environ.get("PDK_ROOT")
    if pdk_root:
        path = _expand(pdk_root) / variant
        tried.append(str(path))
        if _is_valid_variant_dir(path, model_lib_rel):
            return Pdk(
                name=name, path=path, variant=variant, source="PDK_ROOT",
                model_lib_rel=model_lib_rel, design_include_rel=design_include_rel,
            )

    roots = list(config.get("search_roots") or ()) + list(BUILTIN_SEARCH_ROOTS)
    for root in roots:
        path = _expand(root) / variant
        tried.append(str(path))
        if _is_valid_variant_dir(path, model_lib_rel):
            return Pdk(
                name=name, path=path, variant=variant, source=f"search_root:{root}",
                model_lib_rel=model_lib_rel, design_include_rel=design_include_rel,
            )

    raise PdkNotFound(
        "Looked for %s variant %r in:\n  %s\n\n%s"
        % (name, variant, "\n  ".join(tried), INSTALL_HINT)
    )


def pdk_available(sim_dir: Path | None = None) -> bool:
    try:
        find_pdk(sim_dir)
    except (PdkNotFound, PdkConfigError):
        return False
    return True
