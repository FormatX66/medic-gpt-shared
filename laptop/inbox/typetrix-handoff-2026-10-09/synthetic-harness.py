#!/usr/bin/env python3
"""
15-case synthetic harness for the TypeTrix conservative ranker.
All strings are synthetic; no real user typing. Deterministic.
Run: python3 synthetic-harness.py
Exit 0 iff all 15 decisions match the specified rule.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ranker_repro import choose_obvious_correction

# (typed, [provider candidates], expected decision, optional feedback kwargs)
CASES = [
    # obvious typos: transpositions -> SELECT
    ("teh", ["the"], "SELECT", {}),
    ("adn", ["and"], "SELECT", {}),
    ("thier", ["their"], "SELECT", {}),
    ("recieve", ["receive"], "SELECT", {}),
    ("exmaple", ["example"], "SELECT", {}),
    # obvious typos: duplicate-letter removals -> SELECT
    ("occured", ["occurred"], "SELECT", {}),
    # correct words -> NOT_SUITABLE
    ("the", ["the"], "NOT_SUITABLE", {}),
    ("correct", ["correct"], "NOT_SUITABLE", {}),
    ("hello", ["hello"], "NOT_SUITABLE", {}),
    # non-words with no valid candidate -> NOT_SUITABLE
    ("xyzzy", ["xyzzy"], "NOT_SUITABLE", {}),
    # uppercase source ineligible -> NOT_SUITABLE
    ("The", ["The"], "NOT_SUITABLE", {}),
    # no provider candidates -> NOT_SUITABLE
    ("teh", [], "NOT_SUITABLE", {}),
    # feedback block: 3 undos, 0 accepts -> NOT_SUITABLE
    ("teh", ["the"], "NOT_SUITABLE", {"undone": 3, "accepted": 0}),
    # near-misses correctly REJECTED (dist==1 but not transposition/duplicate):
    # seperate->separate is a substitution; wich->which is a non-duplicate insertion
    ("seperate", ["separate"], "NOT_SUITABLE", {}),
    ("wich", ["which"], "NOT_SUITABLE", {}),
]


def main():
    failures = 0
    for typed, cands, expected, kw in CASES:
        decision, detail = choose_obvious_correction(typed, cands, **kw)
        ok = decision == expected
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {typed!r:12} -> {decision:13} (expected {expected})")
        if not ok:
            print(f"       detail: {detail}")
    print(f"\n{len(CASES) - failures}/{len(CASES)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
