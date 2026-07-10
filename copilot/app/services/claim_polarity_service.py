"""Small deterministic helper for distinguishing claims from safe negation."""

from __future__ import annotations

import re


_NEGATED_BEFORE = re.compile(
    r"(?:不代表|并不代表|不能确认(?:是否)?|无法确认(?:是否)?|尚无法确认(?:是否)?|"
    r"暂时无法确认(?:是否)?|没有|没|暂无|尚无|并非|不是|未确认|缺少|不保证|"
    r"不能证明|无法证明).{0,4}$"
)

_NEGATED_AFTER = re.compile(
    r"^(?:这一点|这点|该项|这项)?(?:仍|还|目前|暂时|尚)?(?:无法确认|不能确认|"
    r"尚未确认|未确认|不确定|没有依据|暂无依据|缺少依据|无法证实|不能证明)"
)


def contains_asserted_claim(text: str, claim: str) -> bool:
    """Return True when at least one occurrence is an affirmative assertion."""

    value = str(text or "")
    term = str(claim or "").strip()
    if not value or not term:
        return False
    for match in re.finditer(re.escape(term), value, flags=re.IGNORECASE):
        prefix = value[max(0, match.start() - 18):match.start()]
        suffix = value[match.end():min(len(value), match.end() + 18)]
        if _NEGATED_BEFORE.search(prefix) or _NEGATED_AFTER.search(suffix):
            continue
        return True
    return False
