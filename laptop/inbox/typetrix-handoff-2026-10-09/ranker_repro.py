#!/usr/bin/env python3
"""
Faithful Python port of TypeTrix conservative ranker decision logic.
Source: FormatX66/TypeTriX (private), fetched 2026-10-09.
  - core/typing_assistant.cpp @ 3ef85ae0:
      SuggestionEngine::edit_distance            (line 177)
      SuggestionEngine::is_lowercase_word         (line ~205)
      SuggestionEngine::is_obvious_typo_edit      (line 215)
      SuggestionEngine::normalized                (line 137)
      SuggestionEngine::choose_obvious_correction (line 290)
  - core/future_branch.cpp @ 2f926a4b:
      SuggestionEngine::rank_branches, Suggest threshold 0.68 (line 65)

Isolated: no live system, no Windows, no TSF. Deterministic.
ASCII-only simplification of the wstring logic (behavior identical on ASCII input).
"""

K_MAX_TOKEN = 64  # EphemeralContext::kMaxTokenCharacters (representative)


def edit_distance(left: str, right: str) -> int:
    """Damerau-Levenshtein with adjacent transposition. Mirrors C++ exactly."""
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    current = [0] * (len(right) + 1)
    before_previous = [0] * (len(right) + 1)
    for row in range(1, len(left) + 1):
        current[0] = row
        for col in range(1, len(right) + 1):
            sub = previous[col - 1] + (0 if left[row - 1] == right[col - 1] else 1)
            current[col] = min(previous[col] + 1, current[col - 1] + 1, sub)
            if (row > 1 and col > 1
                    and left[row - 1] == right[col - 2]
                    and left[row - 2] == right[col - 1]):
                current[col] = min(current[col], before_previous[col - 2] + 1)
        before_previous, previous, current = previous, current, before_previous
    return previous[len(right)]


def is_lowercase_word(value: str) -> bool:
    return bool(value) and all(c.isalpha() and c.islower() for c in value)


def normalized(value: str) -> str:
    return value.lower()


def _removes_duplicate(longer: str, shorter: str) -> bool:
    if len(longer) != len(shorter) + 1:
        return False
    removed = 0
    while removed < len(shorter) and longer[removed] == shorter[removed]:
        removed += 1
    duplicate_neighbor = (
        (removed > 0 and longer[removed] == longer[removed - 1])
        or (removed + 1 < len(longer) and longer[removed] == longer[removed + 1])
    )
    if not duplicate_neighbor:
        return False
    return longer[removed + 1:] == shorter[removed:]


def is_obvious_typo_edit(source: str, candidate: str) -> bool:
    """Transposition or duplicate-letter removal only. Mirrors C++ exactly."""
    if len(source) == len(candidate) and len(source) >= 2:
        m = 0
        while m < len(source) and source[m] == candidate[m]:
            m += 1
        if (m + 1 < len(source)
                and source[m] == candidate[m + 1]
                and source[m + 1] == candidate[m]
                and source[m + 2:] == candidate[m + 2:]):
            return True
    return _removes_duplicate(source, candidate) or _removes_duplicate(candidate, source)


def choose_obvious_correction(source, provider_candidates, undone=0, accepted=0):
    """
    Mirrors SuggestionEngine::choose_obvious_correction.
    Returns (decision, detail); decision in {'SELECT', 'NOT_SUITABLE'}.
    feedback.confidence_adjustment() modeled as 0.0 (neutral).
    """
    if not (3 <= len(source) <= K_MAX_TOKEN) or not is_lowercase_word(source):
        return ('NOT_SUITABLE', 'source not a lowercase word of length 3..64')
    if undone >= 3 and undone > accepted:
        return ('NOT_SUITABLE', f'feedback block: undone={undone} accepted={accepted}')
    if not provider_candidates:
        return ('NOT_SUITABLE', 'provider returned no candidates')
    src_n = normalized(source)
    for raw in provider_candidates:
        if not raw or len(raw) > K_MAX_TOKEN or any(c.isspace() for c in raw):
            continue
        # match_case() is identity when source is all-lowercase (our case)
        cand_n = normalized(raw)
        if (cand_n == src_n or not is_lowercase_word(raw)
                or edit_distance(src_n, cand_n) != 1
                or not is_obvious_typo_edit(src_n, cand_n)):
            continue
        conf = min(1.0, max(0.0, 0.98))  # 0.98 + feedback.confidence_adjustment()
        return ('SELECT', f'{source!r} -> {raw!r} (dist=1, obvious typo, conf={conf:.2f})')
    return ('NOT_SUITABLE', 'no provider candidate is an obvious typo (dist==1 + transposition/duplicate)')


SHOW_SUGGEST_THRESHOLD = 0.68  # future_branch.cpp:65


def rank_popup(source, provider_candidates, friction_confidence=0.9):
    """
    Simplified rank_branches: best branch reaching Suggest (>=0.68), else None.
    Mirrors the confidence formula: 0.75*friction.confidence + 0.25*similarity.
    """
    src_n = normalized(source)
    best = None
    for raw in provider_candidates:
        if not raw or any(c.isspace() for c in raw):
            continue
        cand_n = normalized(raw)
        if cand_n == src_n:
            continue
        d = edit_distance(src_n, cand_n)
        longest = max(len(src_n), len(cand_n))
        allowed = 1 if longest <= 4 else min(3, longest // 3 + 1)
        if d == 0 or d > allowed:
            continue
        sim = 1.0 - d / longest
        conf = max(0.0, min(1.0, 0.75 * friction_confidence + 0.25 * sim))
        if conf >= SHOW_SUGGEST_THRESHOLD and (best is None or conf > best[1]):
            best = (raw, conf, d)
    return best
