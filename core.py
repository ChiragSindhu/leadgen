"""Shared state and helpers used by every route module."""
import os, threading
import pipeline as P

BASE = os.path.dirname(os.path.abspath(__file__))
OUTREACH = ("new", "messaged", "replied", "interested", "not_interested", "bad_number", "do_not_contact")


class Job(dict):
    """Progress state. Every real change bumps 'v' so clients can ask 'anything new since v?' and get an empty reply."""
    def __setitem__(self, k, val):
        if k != "v" and self.get(k) != val: super().__setitem__("v", self.get("v", 0) + 1)
        super().__setitem__(k, val)

    def update(self, *a, **kw):
        for k, val in dict(*a, **kw).items(): self[k] = val


JOB = Job(running=False, msg="idle", v=0)   # find / search job
SJ = Job(running=False, msg="idle", v=0)    # WhatsApp send job

# ---- global execution lock: only ONE of find/send may run at a time
_LOCK = threading.Lock()


def claim(kind):
    """Atomically claim the single execution slot. Returns an error string if busy, else None."""
    with _LOCK:
        if JOB["running"]: return "A search is already running. Wait for it to finish."
        if SJ["running"]: return "A WhatsApp send is already running. Stop it or wait for it to finish."
        (JOB if kind == "find" else SJ)["running"] = True
    return None


def busy_state():
    return "find" if JOB["running"] else "send" if SJ["running"] else None


def rows(sql, *a):
    c = P.db(); r = [dict(x) for x in c.execute(sql, a)]; c.close(); return r


def clamp(v, lo, hi): return max(lo, min(hi, v))


def num(v, lo, hi, name):
    try: n = int(v)
    except (TypeError, ValueError): n = lo - 1
    if not lo <= n <= hi: raise ValueError(f"{name} must be a number from {lo} to {hi}")
    return n
