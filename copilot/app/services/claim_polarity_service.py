"""Small deterministic helper for distinguishing claims from safe negation."""

from __future__ import annotations

import re


_NEGATED_BEFORE = re.compile(
    r"(?:(?:目前|暂时|尚|仍|还)?(?:无法|不能|未能|尚未).{0,8}?"
    r"(?:确认|证实|判断|保证)(?:是否)?|"
    r"不代表|并不代表|不能确认(?:是否)?|无法确认(?:是否)?|尚无法确认(?:是否)?|"
    r"暂时无法确认(?:是否)?|没有|没|暂无|尚无|并非|不是|未确认|缺少|"
    r"不保证|不能|无法|不会|"
    r"不能证明|无法证明).{0,4}$"
)

_NEGATED_AFTER = re.compile(
    r"^(?:这一点|这点|该项|这项)?(?:仍|还|目前|暂时|尚)?(?:无法确认|不能确认|"
    r"尚未确认|未确认|不确定|没有依据|暂无依据|缺少依据|无法证实|不能证明|"
    r"需要(?:按.{0,8})?(?:确认|核实)|还需要(?:按.{0,8})?(?:确认|核实))"
)

_CLAUSE_BOUNDARY = re.compile(r"[。！？；\n]")
_UNCERTAIN_SCOPE_BEFORE = re.compile(r"是否.{0,24}$")
_UNCERTAIN_PREDICATE_AFTER = re.compile(
    r"(?:目前|暂时|尚|仍|还)?(?:无法|不能|未能|尚未).{0,18}?"
    r"(?:确认|证实|判断|保证)|(?:不确定|没有依据|暂无依据|缺少依据)"
    r"|(?:没有|暂无|缺少).{0,12}?(?:资料|依据).{0,12}?"
    r"(?:确认|证实|判断|保证)"
    r"|(?:现有|当前)?(?:资料|依据).{0,8}?"
    r"(?:无法|不能|不足以).{0,8}?(?:确认|证实|判断|保证)"
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
        clause_start = max(
            (boundary.end() for boundary in _CLAUSE_BOUNDARY.finditer(value, 0, match.start())),
            default=0,
        )
        boundary_after = _CLAUSE_BOUNDARY.search(value, match.end())
        clause_end = boundary_after.start() if boundary_after else len(value)
        clause_prefix = value[clause_start:match.start()]
        clause_suffix = value[match.end():clause_end]
        if (
            _UNCERTAIN_SCOPE_BEFORE.search(clause_prefix)
            and _UNCERTAIN_PREDICATE_AFTER.search(clause_suffix)
        ):
            continue
        return True
    return False
