# SPDX-License-Identifier: Apache-2.0
"""Declared numeric limits of the p1 campaign (issue #25). numpy-free on purpose
so the unavailable-tool record can be written on a host without numpy."""

BAND_HZ = (17.7e9, 19.45e9, 21.2e9)
L_BUDGET_PCT = 5.0       # mesh / margin comparison, L
Q_BUDGET_PCT = 10.0      # mesh / margin comparison, Q
FIT_BUDGET_PCT = 5.0     # |Zfit - ZEM| / |ZEM| at each band frequency
CTRL_L_TOL_PCT = 1.0     # synthetic known-answer: L and complex Z
SRF_CEILING_HZ = 30e9    # source sweep upper end (601 samples, 0..30 GHz)
EXPECTED_NUMFREQ = 601
Q_LOSSLESS_RTOL = 1e-9   # |Re Z| <= this * |Im Z|  ->  Q reported as +inf
# near-zero denominators (absolute floors) that invalidate a comparison
MIN_L_H = 1e-15
MIN_Q = 1e-3
S_PASSIVITY_MAX = 1.05   # |Sij| above this is non-physical, not FFT ripple


