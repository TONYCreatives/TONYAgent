"""Find every animation in styles.css that the reduced-motion block misses.

The stylesheet cancels motion in one `@media (prefers-reduced-motion: reduce)`
block that lists selectors by hand. A selector that drifts out of that list means
somebody who asked their operating system to stop moving things still gets
movement, with nothing indicating it -- a preference silently ignored, which is
the block's own stated reason for repeating `[data-state]` rather than using
`!important`.

So the list is checked against the stylesheet rather than trusted: every rule
that sets `animation` is extracted, its selector compared against the ones the
block cancels, and anything left over is printed. Comments are stripped first,
because this stylesheet documents the rules by mentioning their selectors.

Run:  python scripts/audit_reduced_motion.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

STYLESHEET = Path(__file__).resolve().parent.parent / "app" / "src" / "styles.css"
MEDIA_QUERY = "prefers-reduced-motion: reduce"


def strip_comments(css: str) -> str:
    """Remove CSS comments.

    This stylesheet explains each rule in a comment that names the very selector
    it documents, so a comment left in place is read as part of the selector it
    sits above -- and the rule after it becomes invisible to the audit.
    """
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def top_level_rules(css: str) -> list[tuple[str, str]]:
    """Every `selector { body }` in the file, ignoring brace nesting.

    Nested rules (the ones inside `@media`) are still returned, because those are
    exactly the ones worth auditing; only the braces themselves are stepped
    over.
    """
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)]


def selectors_of(block: str) -> list[str]:
    return [s.strip() for s in block.split(",") if s.strip()]


def animation_name(body: str) -> str | None:
    """The animation shorthand's name, or None if the rule sets no animation."""
    match = re.search(r"(?<![\w-])animation:\s*([^;]+)", body)
    return match.group(1).strip() if match else None


def attribute_value(selector: str) -> str | None:
    """The value in a selector's only attribute selector, if it has one.

    `.rowmenu[data-state="open"]` -> `"open"`, `.rowmenu[data-state]` -> None.
    The distinction is the whole reason the block is written the way it is: a
    selector with no value matches both states at once.
    """
    values = re.findall(r"\[[\w-]+=(\"[^\"]*\"|'[^']*')\]", selector)
    return values[0].strip("\"'") if len(values) == 1 else None


def base_selector(selector: str) -> str:
    """The selector with its attribute conditions removed.

    `.modal-backdrop[data-state="open"] > .modal` -> `.modal-backdrop > .modal`.
    """
    return re.sub(r"\[[^\]]*\]", "", selector)


def specificity(selector: str) -> int:
    """Classes plus attribute selectors, which is all these selectors use.

    The block's comment says the repeated `[data-state]` halves exist to match
    the specificity of the rule each one overrides, so specificity is the whole
    point of the comparison and it cannot be skipped.
    """
    return len(re.findall(r"\.[\w-]+", selector)) + len(re.findall(r"\[[^\]]*\]", selector))


def covers(outer: str, inner: str) -> bool:
    """Whether an animated rule is genuinely out of the block's reach.

    The block is written in two idioms, and both have to be understood or the
    audit cries wolf on twelve rules that are in fact covered:

    * It names the selector outright (`.chatrow`, `.thinking-live`).
    * It names the selector with the attribute *value* dropped --
      `.rowmenu[data-state]` for `.rowmenu[data-state="open"]` -- which matches
      both states at once and wins the tie on source order, because the media
      block is declared later.

    Specificity is compared rather than assumed, since the block's own comment
    says the repeated `[data-state]` halves exist precisely to match it. Two
    value-specific selectors for *different* states do not cover each other, so
    a disagreeing value is rejected explicitly.
    """
    if inner == outer:
        return True
    if base_selector(outer) != base_selector(inner):
        return False
    outer_value, inner_value = attribute_value(outer), attribute_value(inner)
    if outer_value is not None and inner_value is not None and outer_value != inner_value:
        return False
    return specificity(outer) >= specificity(inner)


def covered_by(selector: str, cancelled: set[str]) -> bool:
    return any(covers(candidate, selector) for candidate in cancelled)


def main() -> int:
    css = strip_comments(STYLESHEET.read_text(encoding="utf-8"))

    # Isolate the reduced-motion block, and everything outside it.
    inside: list[tuple[str, str]] = []
    outside: list[tuple[str, str]] = []
    cursor = 0
    for match in re.finditer(r"@media[^{]*" + re.escape(MEDIA_QUERY) + r"[^{]*\{", css):
        # Everything before this block, up to the previous block's end.
        outside.extend(top_level_rules(css[cursor : match.start()]))
        # Find the matching close brace by counting depth from here.
        depth, index = 1, match.end()
        while depth and index < len(css):
            if css[index] == "{":
                depth += 1
            elif css[index] == "}":
                depth -= 1
            index += 1
        inside.extend(top_level_rules(css[match.end() : index - 1]))
        cursor = index
    outside.extend(top_level_rules(css[cursor:]))

    cancelled: set[str] = set()
    for block, body in inside:
        if "animation" in body and "none" in body:
            cancelled.update(selectors_of(block))

    animated: list[tuple[str, str]] = []
    for block, body in outside:
        name = animation_name(body)
        if name and name != "none":
            animated.append((block, name))

    print(f"reduced-motion block cancels {len(cancelled)} selector(s):")
    for selector in sorted(cancelled):
        print(f"  - {selector}")

    print(f"\n{len(animated)} animated rule(s) outside it:")
    missed: list[tuple[str, str]] = []
    for block, name in animated:
        selectors = selectors_of(block)
        uncovered = [s for s in selectors if not covered_by(s, cancelled)]
        flag = "OK " if not uncovered else "MISS"
        print(f"  [{flag}] {block} -> {name}")
        if uncovered:
            missed.append((block, uncovered))

    if missed:
        print(f"\n{len(missed)} rule(s) still animate under reduced motion:")
        for block, uncovered in missed:
            print(f"  ! {block}")
            for selector in uncovered:
                print(f"      not cancelled: {selector}")
        return 1

    print("\nevery animated selector is cancelled under prefers-reduced-motion: reduce")
    return 0


if __name__ == "__main__":
    sys.exit(main())
