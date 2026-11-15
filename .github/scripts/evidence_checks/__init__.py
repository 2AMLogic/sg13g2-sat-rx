"""Stdlib-only implementation of .github/scripts/check_evidence_formats.py (issue #163).

Mechanical split of the former single-file checker; no rule changed.
common (Problems, shared helpers), native, kaband, passive_p1, mixer_nf,
mixer_cm, mixer_pra, mixer_feas, lna_match, lna_core, lna_linearity, lna_headroom,
readmes, reuse_masters (check_reuse_masters, issue #277), spec_rows,
core (check_format, check_append_only, check_row_coverage, main).
"""
