# SPDX-License-Identifier: Apache-2.0
"""Analysis chain for the bounded p1-only passive campaign (issue #25).

This module is NEW to this repo (it is not an adaptation of a sibling file); it
builds on `emlib.py`, which is a verbatim copy of the sg13g2-vco module of the
same name (see ../INPUTS.json for the pinned source commit and hashes).

What it adds over emlib, and why
--------------------------------
1. A STRICT Touchstone reader.  `emlib.read_snp` trusts its input; a NaN, a
   truncated row or a non-monotonic grid would flow straight into an L/Q
   number.  `read_snp_strict` raises `DataError` instead, so a malformed file
   can never produce successful evidence.
2. Impedance extraction that works for a lossless series element.  A pure
   series two-port has a singular Z matrix (the S->Z route divides by zero),
   but its driving-point impedance is still well defined from Y:
   Z_se = 1/Y11.  `impedances()` uses the Z route when the data admit it (the
   only route that supports port de-embedding) and the Y route otherwise.
3. L, Q, SRF reporting with explicit "lossless" and "no crossing" outcomes
   instead of silent division errors or fabricated numbers.
4. Budget evaluation (mesh / margin / fit residual) with the exact rules the
   issue declares.

Port / impedance conventions (unchanged from the sibling method)
----------------------------------------------------------------
Port 1 = terminal LA, port 2 = terminal LB, both referenced to the local
substrate ground patch (the subcircuit's `sub` node), z0 from the Touchstone
header.
  Z_se   = Z11 - Z12*Z21/Z22  (= 1/Y11)   LA driven, LB and sub grounded.
  Z_diff = Z11 - Z12 - Z21 + Z22           LA/LB differential.
  L = Im(Z)/omega ;  Q = Im(Z)/Re(Z) ;  SRF = first downward zero crossing of
  Im(Z).  De-embedding removes the lumped-port series inductance
  (Terman flat ribbon) from the diagonal of Z, as in emlib.deembed_series_L.
"""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emlib  # noqa: E402

from limits import *  # noqa: E402,F401,F403  (declared limits live in limits.py)


class DataError(Exception):
    """Input data is malformed / non-physical; no evidence may be produced."""


# ----------------------------------------------------------------- touchstone
_UNITS = {"HZ": 1.0, "KHZ": 1e3, "MHZ": 1e6, "GHZ": 1e9}


def read_snp_strict(path, nports=2):
    """Read a 2-port Touchstone v1 file, rejecting anything suspicious.

    Returns (f, S, z0); S has shape (nf, 2, 2) in [row, col] = [i, j] order
    (the file's S11 S21 S12 S22 column order is undone).
    """
    try:
        with open(path) as fh:
            text = fh.read()
    except OSError as exc:
        raise DataError("cannot read %s: %s" % (path, exc))
    mult = fmt = None
    z0 = None
    rows = []
    for ln, line in enumerate(text.splitlines(), 1):
        line = line.split("!")[0].strip()
        if not line:
            continue
        if line.startswith("#"):
            if mult is not None:
                raise DataError("%s:%d: second option line" % (path, ln))
            tok = [t.upper() for t in line[1:].split()]
            if len(tok) < 5 or tok[0] not in _UNITS or tok[1] != "S" or "R" not in tok:
                raise DataError("%s:%d: unsupported option line %r" % (path, ln, line))
            mult = _UNITS[tok[0]]
            fmt = tok[2]
            if fmt not in ("RI", "MA", "DB"):
                raise DataError("%s:%d: unsupported format %r" % (path, ln, fmt))
            try:
                z0 = float(tok[tok.index("R") + 1])
            except (ValueError, IndexError):
                raise DataError("%s:%d: bad reference impedance" % (path, ln))
            if not (math.isfinite(z0) and z0 > 0):
                raise DataError("%s:%d: reference impedance %r not positive finite" % (path, ln, z0))
            continue
        if mult is None:
            raise DataError("%s:%d: data before option line" % (path, ln))
        try:
            vals = [float(x) for x in line.split()]
        except ValueError:
            raise DataError("%s:%d: non-numeric token in %r" % (path, ln, line[:60]))
        rows.append((ln, vals))
    if mult is None:
        raise DataError("%s: no option line" % path)
    want = 1 + 2 * nports * nports
    if len(rows) < 2:
        raise DataError("%s: fewer than 2 data rows" % path)
    for ln, vals in rows:
        if len(vals) != want:
            raise DataError("%s:%d: %d columns, expected %d (truncated/corrupt row)"
                            % (path, ln, len(vals), want))
    a = np.array([v for _, v in rows], dtype=float)
    if not np.all(np.isfinite(a)):
        raise DataError("%s: non-finite value (NaN/Inf) in data" % path)
    f = a[:, 0] * mult
    if np.any(f < 0) or np.any(np.diff(f) <= 0):
        raise DataError("%s: frequency grid not strictly increasing / negative" % path)
    body = a[:, 1:]
    if fmt == "RI":
        c = body[:, 0::2] + 1j * body[:, 1::2]
    elif fmt == "MA":
        c = body[:, 0::2] * np.exp(1j * np.deg2rad(body[:, 1::2]))
    else:
        c = 10 ** (body[:, 0::2] / 20.0) * np.exp(1j * np.deg2rad(body[:, 1::2]))
    S = c.reshape(len(f), nports, nports).transpose(0, 2, 1)  # undo S11 S21 S12 S22
    if np.max(np.abs(S)) > S_PASSIVITY_MAX:
        raise DataError("%s: |S| = %.3g exceeds passivity sanity bound %.2f"
                        % (path, np.max(np.abs(S)), S_PASSIVITY_MAX))
    return f, S, z0


def write_snp(path, f, S, z0=50.0, comments=()):
    emlib.write_snp(path, np.asarray(f), np.asarray(S), z0, comments)


# --------------------------------------------------------------- conversions
def s2y(S, z0):
    """Y = (I - S)(I + S)^-1 / z0.  Raises DataError if I+S is singular."""
    n = S.shape[1]
    I = np.eye(n)[None, :, :]
    A = I + S
    if np.any(np.linalg.cond(A) > 1e12):
        raise DataError("I+S singular: Y representation does not exist")
    return np.linalg.solve(np.transpose(A, (0, 2, 1)), np.transpose(I - S, (0, 2, 1))).transpose(0, 2, 1) / z0


def y2s(Y, z0):
    n = Y.shape[1]
    I = np.eye(n)[None, :, :]
    A = I * 1.0 + z0 * Y
    return np.linalg.solve(np.transpose(A, (0, 2, 1)), np.transpose(I - z0 * Y, (0, 2, 1))).transpose(0, 2, 1)


def z_route_ok(S):
    return bool(np.all(np.linalg.cond(np.eye(S.shape[1])[None] - S) < 1e12))


def lq(f, Z):
    """L = Im Z/w and Q = Im Z/Re Z with explicit lossless handling.

    Q is +inf (lossless) where |Re Z| <= Q_LOSSLESS_RTOL*|Im Z| and Im Z > 0;
    NaN where undefined (Im Z == 0 with Re Z == 0, or Re Z < 0, i.e. an active
    or numerically meaningless impedance).  No division error is raised.
    """
    f = np.asarray(f, dtype=float)
    Z = np.asarray(Z, dtype=complex)
    w = 2 * np.pi * f
    L = np.full(f.shape, np.nan)
    Q = np.full(f.shape, np.nan)
    pos = w > 0
    L[pos] = Z.imag[pos] / w[pos]
    re, im = Z.real, Z.imag
    lossless = np.abs(re) <= Q_LOSSLESS_RTOL * np.abs(im)
    Q[lossless & (im > 0)] = np.inf
    ok = (~lossless) & (re > 0)
    Q[ok] = im[ok] / re[ok]
    return L, Q


def srf(f, Z, ceiling=SRF_CEILING_HZ):
    """Return dict(found, hz, lower_bound_hz): first downward Im(Z) crossing.

    No crossing at or below the sweep ceiling means the SRF is ABOVE the
    ceiling: reported as a lower bound (the highest swept frequency), never as
    a fabricated number.
    """
    f = np.asarray(f, dtype=float)
    im = np.imag(Z)
    ok = np.isfinite(im) & (f > 0)
    fi, imi = f[ok], im[ok]
    for i in range(len(fi) - 1):
        if imi[i] > 0 and imi[i + 1] <= 0:
            t = imi[i] / (imi[i] - imi[i + 1])
            return {"found": True, "hz": float(fi[i] + t * (fi[i + 1] - fi[i])),
                    "lower_bound_hz": None, "search_ceiling_hz": float(ceiling)}
    return {"found": False, "hz": None,
            "lower_bound_hz": float(fi[-1]) if len(fi) else None,
            "search_ceiling_hz": float(ceiling)}


def at(f, y, f0):
    y = np.asarray(y)
    if np.iscomplexobj(y):
        return np.interp(f0, f, y.real) + 1j * np.interp(f0, f, y.imag)
    return float(np.interp(f0, f, y))


# -------------------------------------------------------------- impedances
def impedances(f, S, z0, Lport=(0.0, 0.0)):
    """De-embedded single-ended and differential impedance vs frequency.

    The DC point (f <= 0) is dropped: L and Q are undefined there.  Returns
    (f, Zse, Zdiff, route) with route 'Z' or 'Y'.  With nonzero Lport the Z
    route is mandatory (the port parasitic is subtracted in the Z domain).
    """
    f = np.asarray(f)
    keep = f > 0
    f, S = f[keep], S[keep]
    Lport = np.asarray(Lport, dtype=float)
    if z_route_ok(S):
        Z = emlib.s2z(S, z0)
        Zd = emlib.deembed_series_L(f, Z, Lport) if np.any(Lport != 0) else Z
        return f, emlib.z_single_ended(Zd), emlib.z_differential(Zd), "Z"
    if np.any(Lport != 0):
        raise DataError("S->Z singular but port de-embedding needs Z")
    Y = s2y(S, z0)
    zse = 1.0 / Y[:, 0, 0]
    # symmetric reciprocal two-port: Z_diff = 2/(Y11 - Y12)
    asym = np.max(np.abs(Y[:, 0, 0] - Y[:, 1, 1]) / (np.abs(Y[:, 0, 0]) + 1e-30))
    zdi = 2.0 / (Y[:, 0, 0] - Y[:, 0, 1]) if asym < 1e-6 else np.full(f.shape, np.nan + 0j)
    return f, zse, zdi, "Y"


def deembedded_S(f, S, z0, Lport):
    """S of the de-embedded two-port (Z route only)."""
    keep = f > 0
    f, S = f[keep], S[keep]
    Z = emlib.deembed_series_L(f, emlib.s2z(S, z0), np.asarray(Lport, dtype=float))
    return f, emlib.z2s(Z, z0)


def band_table(f, S, z0, Lport=(0.0, 0.0)):
    """Everything reported at the three band frequencies, from one S file."""
    f, zse, zdi, route = impedances(f, S, z0, Lport)
    Lse, Qse = lq(f, zse)
    Ldi, Qdi = lq(f, zdi)
    rows = []
    for f0 in BAND_HZ:
        if not (f[0] <= f0 <= f[-1]):
            raise DataError("band frequency %.4g Hz outside swept range [%.4g, %.4g]"
                            % (f0, f[0], f[-1]))
        rows.append({
            "f_hz": f0,
            "zse": at(f, zse, f0), "l_se_h": at(f, Lse, f0), "q_se": _q_at(f, Qse, f0),
            "zdiff": at(f, zdi, f0), "l_diff_h": at(f, Ldi, f0), "q_diff": _q_at(f, Qdi, f0),
        })
    return {"route": route, "rows": rows,
            "srf_se": srf(f, zse), "srf_diff": srf(f, zdi),
            "f": f, "zse": zse, "zdiff": zdi, "L_se": Lse, "Q_se": Qse}


def _q_at(f, Q, f0):
    """Q at f0 without letting inf/nan poison the interpolation."""
    i = int(np.searchsorted(f, f0))
    cand = [j for j in (i - 1, i) if 0 <= j < len(f)]
    vals = [Q[j] for j in cand]
    if any(np.isposinf(v) for v in vals):
        return float("inf")
    if any(not np.isfinite(v) for v in vals):
        return float("nan")
    return at(f, Q, f0)


# ------------------------------------------------------------- budgets
def rel_delta_pct(coarse, fine, floor):
    """(coarse - fine)/fine in percent, or None if the denominator is invalid
    (non-finite, nonpositive, or below the absolute floor)."""
    if fine is None or not np.isfinite(fine) or fine <= 0 or abs(fine) < floor:
        return None
    if coarse is None or not np.isfinite(coarse):
        return None
    return 100.0 * (coarse - fine) / fine


def compare_variants(base_rows, fine_rows):
    """Per-band L and Q deltas, denominator = the finer / larger-domain result.

    Returns (entries, ok, invalid).  `ok` only if every delta is valid and
    within budget; an invalid delta (bad denominator) invalidates the whole
    comparison, per the issue.  Single-ended is the gated quantity (it is the
    quantity ngspice is compared against); differential is reported alongside.
    """
    entries, ok, invalid = [], True, False
    for b, fr in zip(base_rows, fine_rows):
        dl = rel_delta_pct(b["l_se_h"], fr["l_se_h"], MIN_L_H)
        dq = rel_delta_pct(b["q_se"], fr["q_se"], MIN_Q)
        dld = rel_delta_pct(b["l_diff_h"], fr["l_diff_h"], MIN_L_H)
        dqd = rel_delta_pct(b["q_diff"], fr["q_diff"], MIN_Q)
        e = {"f_hz": b["f_hz"], "dL_se_pct": dl, "dQ_se_pct": dq,
             "dL_diff_pct": dld, "dQ_diff_pct": dqd}
        if dl is None or dq is None:
            invalid = True
            e["status"] = "INVALID_DENOMINATOR"
        elif abs(dl) > L_BUDGET_PCT or abs(dq) > Q_BUDGET_PCT:
            ok = False
            e["status"] = "EXCEEDED"
        else:
            e["status"] = "WITHIN"
        entries.append(e)
    return entries, (ok and not invalid), invalid


# ----------------------------------------------------------- residuals
def zse_residuals(f_model, zse_model, f_em, zse_em):
    """|Zmodel - ZEM|/|ZEM| at the three band frequencies and RMS/max over
    17.7-21.2 GHz (EM grid points inside the band)."""
    out = {"at_band": [], "band_hz": [BAND_HZ[0], BAND_HZ[-1]]}
    zm = np.interp(f_em, f_model, zse_model.real) + 1j * np.interp(f_em, f_model, zse_model.imag)
    rel = np.abs(zm - zse_em) / np.abs(zse_em)
    for f0 in BAND_HZ:
        z_em = at(f_em, zse_em, f0)
        z_m = at(f_em, zm, f0)
        out["at_band"].append({"f_hz": f0, "rel_err_pct": 100.0 * abs(z_m - z_em) / abs(z_em),
                               "z_em": z_em, "z_model": z_m})
    m = (f_em >= BAND_HZ[0] - 1) & (f_em <= BAND_HZ[-1] + 1)
    r = rel[m] * 100.0
    out["n_points_in_band"] = int(m.sum())
    out["rms_pct"] = float(np.sqrt(np.mean(r ** 2))) if m.any() else None
    out["max_pct"] = float(np.max(r)) if m.any() else None
    return out


def s_residuals(f_model, S_model, f_em, S_em):
    """Complex two-port S residuals over 17.7-21.2 GHz, same z0 and ports."""
    m = (f_em >= BAND_HZ[0] - 1) & (f_em <= BAND_HZ[-1] + 1)
    res = {}
    for (i, j), name in (((0, 0), "S11"), ((1, 0), "S21"), ((0, 1), "S12"), ((1, 1), "S22")):
        mod = (np.interp(f_em, f_model, S_model[:, i, j].real)
               + 1j * np.interp(f_em, f_model, S_model[:, i, j].imag))
        d = np.abs(mod - S_em[:, i, j])[m]
        res[name] = {"rms_abs": float(np.sqrt(np.mean(d ** 2))), "max_abs": float(np.max(d))}
    return res


# ------------------------------------------------------------- ngspice
def ngspice_two_port(subckt_file, subckt_name, f, workdir, params="", z0=50.0):
    """Two-port Y(f)/S(f) of `.subckt <name> la lb sub` (sub grounded) via
    one local `ngspice -b` AC run on a uniform grid f[0]..f[-1].

    Port convention = the EM one: LA/LB are ports 1/2, `sub` is the common
    reference (node 0).  Y columns come from two excitations placed in ONE
    deck (A: LA driven, LB grounded; B: the reverse), each through a 0 V/1 V
    source whose branch current gives the port current.
    """
    import subprocess
    f = np.asarray(f, dtype=float)
    d = np.diff(f)
    if len(f) < 2 or np.max(np.abs(d - d[0])) > 1e-6 * d[0]:
        raise DataError("ngspice comparison needs a uniform frequency grid")
    os.makedirs(workdir, exist_ok=True)
    out = os.path.join(workdir, "y.csv")
    deck = os.path.join(workdir, "tb_two_port.spice")
    lines = [
        "* two-port Y extraction of %s (LA=port1, LB=port2, sub=0)" % subckt_name,
        '.include "%s"' % os.path.abspath(subckt_file),
        "VA1 a1 0 dc 0 ac 1", "VA2 a2 0 dc 0 ac 0",
        "XA a1 a2 0 %s %s" % (subckt_name, params),
        "VB1 b1 0 dc 0 ac 0", "VB2 b2 0 dc 0 ac 1",
        "XB b1 b2 0 %s %s" % (subckt_name, params),
        ".control", "set wr_singlescale", "set wr_vecnames",
        "ac lin %d %.12g %.12g" % (len(f), f[0], f[-1]),
        "let y11r = -real(i(VA1))", "let y11i = -imag(i(VA1))",
        "let y21r = -real(i(VA2))", "let y21i = -imag(i(VA2))",
        "let y12r = -real(i(VB1))", "let y12i = -imag(i(VB1))",
        "let y22r = -real(i(VB2))", "let y22i = -imag(i(VB2))",
        "wrdata %s y11r y11i y21r y21i y12r y12i y22r y22i" % out,
        ".endc", ".end",
    ]
    with open(deck, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    r = subprocess.run(["ngspice", "-b", deck], cwd=workdir, capture_output=True, text=True)
    if not os.path.isfile(out):
        raise DataError("ngspice produced no output:\n%s\n%s" % (r.stdout[-800:], r.stderr[-800:]))
    a = np.genfromtxt(out, names=True)
    names = a.dtype.names
    fg = a[names[0]]
    if len(fg) != len(f) or np.max(np.abs(fg - f)) > 1e-3 * d[0]:
        raise DataError("ngspice frequency grid mismatch")
    if not all(np.all(np.isfinite(a[n])) for n in names):
        raise DataError("ngspice returned non-finite values")
    Y = np.zeros((len(f), 2, 2), dtype=complex)
    Y[:, 0, 0] = a["y11r"] + 1j * a["y11i"]
    Y[:, 1, 0] = a["y21r"] + 1j * a["y21i"]
    Y[:, 0, 1] = a["y12r"] + 1j * a["y12i"]
    Y[:, 1, 1] = a["y22r"] + 1j * a["y22i"]
    return fg, Y, y2s(Y, z0), deck
