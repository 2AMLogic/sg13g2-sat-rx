#!/usr/bin/env python3
"""Run a command under a wall-clock limit and an optional process-tree RSS limit.

Records measured wall time and peak memory (summed RSS of the whole process tree,
sampled from /proc; plus the largest single child's ru_maxrss).  The command is
started in its own session so a timeout or RSS breach kills the whole tree.

Usage:
    limited_run.py --timeout S [--rss-max-mb M] [--json OUT] [--] CMD [ARG...]

Exit status: the command's, except
    124  wall-clock timeout (tree killed)
    125  RSS limit exceeded (tree killed)
    127  command could not be started
The JSON (if requested) is always written, including on those exits.  Stdlib only.
"""
import argparse
import json
import os
import resource
import signal
import subprocess
import sys
import time


def tree_rss_kb(root_pid):
    """Sum of VmRSS (kB) over root_pid and all descendants (Linux /proc)."""
    children = {}
    rss = {}
    for ent in os.listdir("/proc"):
        if not ent.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % ent) as fh:
                stat = fh.read()
            ppid = int(stat.rsplit(")", 1)[1].split()[1])
            children.setdefault(ppid, []).append(int(ent))
            with open("/proc/%s/status" % ent) as fh:
                for line in fh:
                    if line.startswith("VmRSS:"):
                        rss[int(ent)] = int(line.split()[1])
                        break
        except (OSError, ValueError, IndexError):
            continue
    total, stack = 0, [root_pid]
    while stack:
        pid = stack.pop()
        total += rss.get(pid, 0)
        stack.extend(children.get(pid, []))
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, required=True)
    ap.add_argument("--rss-max-mb", type=float, default=0.0)
    ap.add_argument("--json")
    ap.add_argument("--poll", type=float, default=0.25)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
    if not cmd:
        ap.error("no command")

    t0 = time.monotonic()
    peak_kb, verdict, rc = 0, "completed", None
    try:
        proc = subprocess.Popen(cmd, start_new_session=True)
    except OSError as exc:
        print("limited_run: cannot start %r: %s" % (cmd[0], exc), file=sys.stderr)
        rc, verdict, proc = 127, "not_started", None

    def kill_tree():
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass

    while proc is not None:
        try:
            rc = proc.wait(timeout=a.poll)
            break
        except subprocess.TimeoutExpired:
            pass
        peak_kb = max(peak_kb, tree_rss_kb(proc.pid))
        if time.monotonic() - t0 > a.timeout:
            kill_tree(); proc.wait(); rc, verdict = 124, "timeout"
            print("limited_run: TIMEOUT after %.1f s (limit %.1f s)" % (time.monotonic() - t0, a.timeout), file=sys.stderr)
            break
        if a.rss_max_mb and peak_kb / 1024.0 > a.rss_max_mb:
            kill_tree(); proc.wait(); rc, verdict = 125, "rss_limit"
            print("limited_run: RSS %.0f MB exceeds limit %.0f MB" % (peak_kb / 1024.0, a.rss_max_mb), file=sys.stderr)
            break
    wall = time.monotonic() - t0
    child_max_kb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    peak_kb = max(peak_kb, 0)
    info = {
        "command": cmd, "verdict": verdict, "exit_status": rc,
        "wall_s": round(wall, 3), "timeout_s": a.timeout,
        "peak_tree_rss_mb": round(peak_kb / 1024.0, 1),
        "largest_child_maxrss_mb": round(child_max_kb / 1024.0, 1),
        "rss_limit_mb": a.rss_max_mb or None, "poll_s": a.poll,
        "note": "peak_tree_rss is sampled; a sub-poll-interval spike can be missed, largest_child_maxrss is exact for the biggest single process",
    }
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(info, fh, indent=2); fh.write("\n")
    sys.exit(rc)


if __name__ == "__main__":
    main()
