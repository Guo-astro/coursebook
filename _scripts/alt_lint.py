#!/usr/bin/env python3
"""
alt_lint.py -- Part C of issue #238: keep the alt-text invariant true.

Scans every .tex file for `\\includegraphics[...]{...}` and checks that
each one that is a real content figure (see ALLOWLIST below) carries a
non-empty `alt=` key. This is deliberately independent of Parts A and B:
it only reads the LaTeX source, never runs pandoc or builds anything, so
it's cheap enough to run on every PR.

Stable interface (other parts of #238 import/parse this):
    python3 _scripts/alt_lint.py [--json] [--root DIR]

    --json prints a JSON array (stdout) of content figures, in book order
    where order.yaml is available, else sorted by path. Each element:
        {"file": relpath, "line": int, "path": <graphic path as written>,
         "alt": <raw alt source text>, "caption": <raw caption text or null>}
    Allow-listed items (see below) are excluded from this list, as are
    malformed includes: there is no path to report for them, and for a
    truncated option list not even the alt text (they still fail the run,
    so checking the exit status is enough).

    Without --json, a short human summary (count, pass/fail) is printed.

    Warnings always go to stderr, regardless of --json.

    scan(root) -> list[dict] is also importable, returning the same dicts
    `--json` prints (plus internal bookkeeping fields prefixed with `_`,
    which callers should ignore).

Exit codes: 0 if every content figure has non-empty alt text, is written as
a well-formed `\\includegraphics`, and sits in a file the book actually
builds; 1 otherwise. Warnings (see WARN checks below) never affect the exit
code.

The three failures, in the order they were added:
  * missing/empty alt text -- the original invariant;
  * a malformed include: an unterminated `[...]` option list, an
    unterminated `{path}` group, or options followed by no `{path}` at all.
    These used to be skipped in silence, which hid the figure from this gate
    rather than failing it;
  * a figure in a .tex file nothing the book builds reaches, so no output
    contains it. The entry points are main.tex (which \\include's title.tex
    and \\input's prelude.tex and glossary.tex) and order.yaml's chapters.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# Allow-list
# ---------------------------------------------------------------------------
#
# title.tex has two things that are NOT content figures and must not be
# scanned as such:
#
#  1. The title-page duck (title.tex, `_images/duck-alpha-cropped.png`).
#     Part B of #238 marks this as a PDF `/Figure` artifact (decorative),
#     not a tagged content figure, so it never needs `alt=`.
#  2. The `\let`/`\renewcommand` epub hacks that blank out `\includegraphics`
#     for the titlepage (`\let\oldgraphics\includegraphics`,
#     `\renewcommand{\includegraphics}[2][]{}`, and the `\let\includegraphics
#     \oldgraphics` that restores it). These contain the literal substring
#     "includegraphics" but are never `\includegraphics[...]{...}` *calls*,
#     so the brace-aware scanner never actually matches them as includes --
#     they're listed here only for documentation/tests, not because the
#     scanner needs help skipping them.
#
# We key the duck allow-list entry on (file, graphic path) rather than a
# bare line number: title.tex's line numbers have already drifted once
# since the issue was filed (the duck moved from line 29 in the issue text
# to wherever it is now after edits), so a path-based key survives future
# line shifts in a way `title.tex:29` would not.
ALLOWLIST_FILE = "title.tex"
ALLOWLIST_PATHS = {
    "_images/duck-alpha-cropped.png",
}

GENERIC_ALT_WORDS = {"diagram", "figure", "image", "picture", "graph"}

# LaTeX escapes that render as one plain character in every output: the
# tagged PDF's /Alt (measured with TeX Live 2026, tagpdf 1.0c) and pandoc's
# EPUB and wiki. `\_` (as in `c\_str`) is one. Anything else starting with
# a backslash is warned about: a formatting macro (\textbf, \emph, ...), a
# custom book macro or math may not come out as plain text.
#
# \textbackslash, \textasciitilde and \textasciicircum are deliberately NOT
# here: tagging copies them into /Alt as typed, so a screen reader says
# "backslash textbackslash 0". Write the character's name in words instead
# ("the terminating null byte").
SAFE_LATEX_ESCAPES = {
    r"\_", r"\%", r"\&", r"\$", r"\#", r"\{", r"\}",
    r"\ldots", r"\dots",
}

# TeX input conventions that are not escapes but still reach /Alt as typed
# (TeX Live 2026): the quote and dash ligatures and inline math.
TEX_LITERAL_LEAKS = (
    (re.compile(r"``|''"), "TeX quotes (`` or '')"),
    (re.compile(r"--"), "a TeX dash (-- or ---)"),
    (re.compile(r"(?<!\\)\$"), "inline math ($...$)"),
)

TEX_GLOB_DIRS_SKIP = {".git", "_scripts", "out", "build"}


# ---------------------------------------------------------------------------
# Brace-aware tokenizing helpers
# ---------------------------------------------------------------------------

# Environments whose body is literal text, not LaTeX to be interpreted --
# code listings and verbatim blocks can legitimately contain the string
# "\includegraphics" (e.g. an example showing how graphicx is used) without
# that being a real figure. `comment` behaves the same way for our purposes:
# its body is inert. Blanking all of these the same way, before scanning,
# keeps a documentation snippet from being mistaken for a real figure.
VERBATIM_LIKE_ENVS = ("comment", "verbatim", "lstlisting", "minted")


def _strip_percent_comments(text: str) -> str:
    """Strip `%...` LaTeX comments (but not escaped `\\%`), char by char,
    keeping the newline so line numbers are unaffected."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            # Copy the escape pair verbatim (handles \%, \\, etc.) so a
            # following % isn't mistaken as escaped when it isn't.
            out.append(c)
            out.append(text[i + 1])
            i += 2
            continue
        if c == "%":
            # Comment runs to end of line; keep the newline itself.
            j = text.find("\n", i)
            if j == -1:
                i = n
            else:
                out.append("\n")
                i = j + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def strip_comments(text: str) -> str:
    """Remove `%...` LaTeX comments (but not escaped `\\%`) and
    verbatim-like environment bodies (`comment`, `verbatim`, `lstlisting`,
    `minted`), preserving line numbers (and hence line count) so later
    line-number bookkeeping stays correct. Blanked characters are replaced
    with spaces; blanked blocks keep their newlines.

    `%` comments are stripped FIRST, before the environment blanking: a
    `\\begin{comment}` that is itself commented out with a leading `%` (a
    dead marker, not a live environment) must not be treated as opening a
    real comment block that then swallows real content until the next
    `\\end{comment}`, live or not.
    """
    text = _strip_percent_comments(text)

    def blank_keep_newlines(m: re.Match) -> str:
        s = m.group(0)
        return "".join(c if c == "\n" else " " for c in s)

    env_alt = "|".join(VERBATIM_LIKE_ENVS)
    text = re.sub(
        r"\\begin\{(?:" + env_alt + r")\}.*?\\end\{(?:" + env_alt + r")\}",
        blank_keep_newlines,
        text,
        flags=re.DOTALL,
    )
    return text


def find_matching_brace(text: str, open_pos: int) -> int:
    """Given the index of a `{`, return the index of its matching `}`,
    honoring nested braces. Returns -1 if unmatched."""
    assert text[open_pos] == "{"
    depth = 0
    i = open_pos
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def find_matching_bracket(text: str, open_pos: int) -> int:
    """Given the index of a `[`, return the index of the matching `]`,
    honoring nested `{...}` groups (so a `]` inside `alt={...}` braces
    doesn't end the option group early) but NOT nested `[...]`, since
    LaTeX optional-argument brackets don't nest. Returns -1 if unmatched."""
    assert text[open_pos] == "["
    i = open_pos + 1
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            i += 2
            continue
        if c == "{":
            close = find_matching_brace(text, i)
            if close == -1:
                return -1
            i = close + 1
            continue
        if c == "]":
            return i
        i += 1
    return -1


def split_top_level_options(opts: str) -> list[str]:
    """Split a `key=value,key2={a,b}` options string on top-level commas,
    i.e. commas not inside a `{...}` group."""
    parts = []
    depth = 0
    cur = []
    i = 0
    n = len(opts)
    while i < n:
        c = opts[i]
        if c == "\\" and i + 1 < n:
            cur.append(c)
            cur.append(opts[i + 1])
            i += 2
            continue
        if c == "{":
            depth += 1
            cur.append(c)
        elif c == "}":
            depth -= 1
            cur.append(c)
        elif c == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    parts.append("".join(cur))
    return parts


_KEY_RE_CACHE: dict[str, re.Pattern] = {}


def extract_key(opts: str, key: str) -> Optional[str]:
    """Find `key=...` among top-level options and return its raw value.
    A `{...}`-braced value has the outer braces stripped; a bare value
    (no braces) runs to the next top-level comma.

    Matches keyval/xkeyval semantics on two points that graphicx itself
    follows: any amount of whitespace is allowed around `=` (`alt  ={x}`
    is legal), and if a key is given more than once, the LAST occurrence
    wins (keyval processes options left to right, each assignment
    overwriting the last)."""
    pattern = _KEY_RE_CACHE.get(key)
    if pattern is None:
        pattern = re.compile(r"^" + re.escape(key) + r"\s*=")
        _KEY_RE_CACHE[key] = pattern
    found = None
    for part in split_top_level_options(opts):
        part_stripped = part.strip()
        m = pattern.match(part_stripped)
        if m:
            val = part_stripped[m.end():].strip()
            if val.startswith("{") and val.endswith("}"):
                # Only strip if these are a genuinely matching outer pair
                # (they always are here, since split_top_level_options
                # only splits on depth-0 commas, so a braced value's
                # braces are balanced within `part`).
                val = val[1:-1]
            found = val  # last occurrence wins, so keep scanning
    return found


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def iter_tex_files(root: str) -> Iterable[str]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in TEX_GLOB_DIRS_SKIP and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".tex"):
                yield os.path.relpath(os.path.join(dirpath, fn), root)


def find_includegraphics(text: str):
    """Yield (match_start_char_index, opts_text, path_text, problem) for each
    `\\includegraphics[...]{...}` in text (brace/bracket-aware).
    Also matches the starred `\\includegraphics*` form (graphicx allows the
    star to suppress clipping-to-bounding-box; it doesn't change the
    alt-text contract).

    `problem` is None for a well-formed include. For a malformed one it is a
    short description of what is wrong, and `path` is "": the scanner used to
    skip these silently, which hid a figure from the gate instead of failing
    it (a truncated `[` option list swallows the alt= key, so the figure
    would simply never be checked).

    Two forms are deliberately not includes at all, and are skipped without
    being reported:
      * a definition or alias of the macro rather than a call to it
        (`\\let\\includegraphics\\oldgraphics`,
        `\\renewcommand{\\includegraphics}[2][]{}` and the unbraced
        `\\newcommand\\includegraphics[2][]{}`) -- title.tex does this for
        the epub titlepage, and the `[2]` of such a definition is an arity,
        not an option list;
      * a bare `\\includegraphics` followed by neither an option list nor a
        path group.
    A call that opens `[` or `{` and never closes it, or that passes options
    and then no path at all, is a real defect."""
    for m in re.finditer(r"\\includegraphics(?![A-Za-z@])", text):
        # \newcommand\includegraphics[2][]{} defines the macro; the [2] is
        # its argument count. Reading that as a call reports the definition
        # as a malformed include and fails the build on valid LaTeX.
        if _DEFINING_COMMAND_RE.search(text[max(0, m.start() - 60):m.start()]):
            continue
        i = m.end()
        n = len(text)
        # Skip whitespace/newlines between the macro and its arguments --
        # LaTeX allows `\includegraphics\n[opts]{path}`.
        while i < n and text[i].isspace():
            i += 1
        # The starred form. LaTeX's \@ifstar skips spaces before the star, so
        # `\includegraphics *[opts]{path}` is a legal call; matching the star
        # only when it is adjacent let that form through unscanned.
        if i < n and text[i] == "*":
            i += 1
            while i < n and text[i].isspace():
                i += 1
        opts = ""
        had_opts = False
        if i < n and text[i] == "[":
            close = find_matching_bracket(text, i)
            if close == -1:
                yield m.start(), "", "", "unterminated [...] option list"
                continue
            had_opts = True
            opts = text[i + 1:close]
            i = close + 1
            while i < n and text[i].isspace():
                i += 1
        if i >= n or text[i] != "{":
            if had_opts:
                yield m.start(), opts, "", "no {path} group after the options"
            # Otherwise it is a mention, not a call: see the docstring.
            continue
        close = find_matching_brace(text, i)
        if close == -1:
            yield m.start(), opts, "", "unterminated {path} group"
            continue
        path = text[i + 1:close]
        yield m.start(), opts, path, None


def find_captions(text: str, start: int, end: int) -> list[tuple[int, str]]:
    """Find every `\\caption[...]{...}` or `\\caption{...}` between `start`
    and `end`. Returns a list of (position of the `\\caption`, raw long-form
    caption text) pairs, in order of appearance. Handles an optional
    `\\caption[short]{long}` short-title argument (using the long form) and
    arbitrary whitespace before the braces (`\\caption {...}`)."""
    out = []
    for cap_m in re.finditer(r"\\caption\b", text[start:end]):
        cap_pos = start + cap_m.start()
        i = start + cap_m.end()
        n = end
        while i < n and text[i].isspace():
            i += 1
        if i < n and text[i] == "[":
            close = find_matching_bracket(text, i)
            if close == -1 or close >= n:
                continue
            i = close + 1
            while i < n and text[i].isspace():
                i += 1
        if i >= n or text[i] != "{":
            continue
        close = find_matching_brace(text, i)
        if close == -1 or close > n:
            continue
        out.append((cap_pos, text[i + 1:close]))
    return out


def find_enclosing_caption(text: str, pos: int) -> Optional[str]:
    """Look for the \\caption{...} associated with the \\includegraphics at
    `pos`, within the same \\begin{figure}...\\end{figure} environment.
    A figure can (rarely, not in this book today) hold more than one
    \\includegraphics/\\caption pair -- e.g. a multi-panel figure -- so
    among the captions in the enclosing figure we pick the one that
    immediately follows `pos` (the usual "image then its caption" layout),
    falling back to the closest one before `pos` if none follows. Returns
    raw caption text, or None if not found (or not inside a figure)."""
    fig_start = None
    for m in re.finditer(r"\\begin\{figure\*?\}", text):
        if m.start() <= pos:
            fig_start = m
        else:
            break
    if fig_start is None:
        return None
    # Find this figure's matching \end{figure}.
    end_m = re.search(r"\\end\{figure\*?\}", text[fig_start.end():])
    fig_end = fig_start.end() + end_m.start() if end_m else len(text)
    if pos > fig_end:
        return None  # pos isn't actually inside this figure

    captions = find_captions(text, fig_start.end(), fig_end)
    if not captions:
        return None
    after = [c for c in captions if c[0] >= pos]
    if after:
        return min(after, key=lambda c: c[0])[1]
    return max(captions, key=lambda c: c[0])[1]


def line_number_at(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


# A command that defines or aliases the next macro instead of calling it.
# Anchored at the end, so it only matches immediately before the macro.
_DEFINING_COMMAND_RE = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand|DeclareRobustCommand"
    r"|newrobustcmd|renewrobustcmd)\*?\s*\{?\s*$"
    r"|\\(?:def|let|gdef|edef|xdef)\s*\{?\s*$"
)

# The other entry point into the book, besides order.yaml's chapters.
BUILD_ROOT_TEX = "main.tex"


def _expand_book_order(root: str, relfile: str, visited: set, out: list) -> None:
    """DFS-expand `relfile`'s own \\input/\\include targets, depth first,
    in the order they appear, so a chapter file like introc/introc.tex
    contributes its sub-files (introc/c_memory_model.tex, etc.) in their
    real book position instead of them falling back to alphabetical order
    (which is what a flat order.yaml lookup gives them, since order.yaml
    only lists one file per chapter)."""
    if relfile in visited:
        return
    visited.add(relfile)
    abspath = os.path.join(root, relfile)
    try:
        with open(abspath, encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        # A listed file that is not there contributes nothing. Recording it
        # anyway would put a name in the order, and in the reachable set,
        # that no real file matches -- so one mis-read order.yaml entry
        # would make every real figure in that chapter look unreachable.
        return
    out.append(relfile)
    text = strip_comments(raw)
    for m in re.finditer(r"\\(?:input|include)\{([^}]*)\}", text):
        target = m.group(1).strip()
        if not target:
            continue
        if not target.endswith(".tex"):
            target += ".tex"
        _expand_book_order(root, target, visited, out)


def load_book_order(root: str) -> list[str]:
    """Read order.yaml (a flat list of `dir/basename` entries, one per
    line as `- dir/basename`) without requiring PyYAML, then expand each
    chapter's own \\input/\\include chain (see _expand_book_order) so
    files pulled in with \\input still land in book order rather than
    falling back to a sorted-path tiebreak. Returns the list of `.tex`
    file relpaths in book order.

    This reads order.yaml by hand to keep the lint stdlib-only, so it has to
    tolerate the YAML the real file is allowed to contain: a trailing
    `# comment`, a quoted entry, and an entry that already ends in `.tex`.
    Taking any of those literally would invent a chapter name no file
    matches, which the reachability check would then blame on the real
    files."""
    order_path = os.path.join(root, "order.yaml")
    chapter_roots = []
    try:
        with open(order_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("- "):
                    continue
                entry = line[2:].strip()
                if "#" in entry:
                    entry = entry.split("#", 1)[0].strip()
                if len(entry) >= 2 and entry[0] == entry[-1] and entry[0] in "\"'":
                    entry = entry[1:-1].strip()
                if not entry:
                    continue
                if not entry.endswith(".tex"):
                    entry += ".tex"
                chapter_roots.append(entry)
    except OSError:
        return []
    visited: set = set()
    out: list = []
    for chapter_root in chapter_roots:
        _expand_book_order(root, chapter_root, visited, out)
    return out


def load_reachable(root: str, order: list[str]) -> set[str]:
    """Every .tex file the book pulls in, from both of its entry points.

    order.yaml's chapters are one. main.tex is the other: it \\include's
    title.tex and \\input's prelude.tex and glossary.tex, which no chapter
    reaches. A figure in one of those really is in the PDF and the EPUB, so
    counting only order.yaml would report a figure readers can see as
    orphaned.

    main.tex also \\input's the generated order.tex, which a clean checkout
    does not have; that is why order.yaml's chapters are expanded as well
    instead of relying on main.tex alone."""
    visited: set = set()
    out: list = []
    if os.path.isfile(os.path.join(root, BUILD_ROOT_TEX)):
        _expand_book_order(root, BUILD_ROOT_TEX, visited, out)
    return set(order) | set(out)


def scan(root: str) -> list[dict]:
    """Scan every .tex file under `root` for \\includegraphics calls.
    Returns a list of dicts for content figures only (allow-listed
    entries, like the title-page duck, are excluded), each with:
        file, line, path, alt, caption
    plus internal fields `_missing_alt` (bool), `_malformed` (str or None),
    `_unreachable` (str or None) and `_warnings` (list[str]) that --json
    output does not print but the CLI/tests use.
    Order: book order from order.yaml when available, falling back to
    sorted file path, then by line number within a file.
    """
    results = []
    tex_file_count = 0
    for relfile in iter_tex_files(root):
        tex_file_count += 1
        abspath = os.path.join(root, relfile)
        with open(abspath, encoding="utf-8") as f:
            raw = f.read()
        text = strip_comments(raw)

        for start, opts, path, problem in find_includegraphics(text):
            line = line_number_at(text, start)
            if problem is not None:
                # A malformed include is a failure, not a figure: we cannot
                # know its path or its alt text, so it gets no caption or
                # warning checks and never matches the allow-list.
                results.append({
                    "file": relfile,
                    "line": line,
                    "path": "",
                    "alt": "",
                    "caption": None,
                    "_missing_alt": False,
                    "_malformed": problem,
                    "_unreachable": None,
                    "_warnings": [],
                })
                continue

            path = path.strip()
            if relfile == ALLOWLIST_FILE and path in ALLOWLIST_PATHS:
                continue

            alt = extract_key(opts, "alt")
            caption = find_enclosing_caption(text, start)

            warnings = []
            missing_alt = alt is None or alt.strip() == ""

            if not missing_alt:
                alt_stripped = alt.strip()
                if caption is not None and alt_stripped == caption.strip():
                    warnings.append(
                        f"{relfile}:{line}: alt text equals the figure caption "
                        f"verbatim ({alt_stripped!r})"
                    )
                if alt_stripped.lower() in GENERIC_ALT_WORDS:
                    warnings.append(
                        f"{relfile}:{line}: alt text is just the generic word "
                        f"{alt_stripped!r}"
                    )
                for esc_match in re.finditer(r"\\[A-Za-z]+|\\.", alt):
                    token = esc_match.group(0)
                    if token not in SAFE_LATEX_ESCAPES:
                        warnings.append(
                            f"{relfile}:{line}: alt text contains {token!r}, "
                            f"which may not render as plain text"
                        )
                for leak_re, what in TEX_LITERAL_LEAKS:
                    if leak_re.search(alt):
                        warnings.append(
                            f"{relfile}:{line}: alt text contains {what}, which "
                            f"reaches the tagged PDF's /Alt as typed"
                        )

            results.append({
                "file": relfile,
                "line": line,
                "path": path,
                "alt": alt if alt is not None else "",
                "caption": caption,
                "_missing_alt": missing_alt,
                "_malformed": None,
                "_unreachable": None,
                "_warnings": warnings,
            })

    if tex_file_count == 0:
        # Scanning zero .tex files "succeeds" vacuously (0 missing out of
        # 0 figures) unless we say something: that's indistinguishable from
        # a real pass and would silently no-op the whole gate if --root (or
        # cwd, for a plain `cd _scripts && python3 alt_lint.py` run) ever
        # points somewhere that isn't the repo.
        raise RuntimeError(f"no .tex files found under {root!r}; is --root correct?")

    order = load_book_order(root)
    if order:
        order_index = {f: i for i, f in enumerate(order)}

        # Reachability. A figure in a .tex file that nothing the book builds
        # reaches (directly or through an \input/\include chain) is in no
        # output at all. Its alt text can pass this lint forever while no
        # reader ever sees the figure, and a figure meant to be in the book
        # is silently orphaned instead. Only checked once order.yaml has
        # yielded at least one real chapter file; without that there is
        # nothing to be reachable from.
        reachable = load_reachable(root, order)
        for item in results:
            if item["file"] not in reachable:
                item["_unreachable"] = (
                    f"{item['file']}:{item['line']}: neither {BUILD_ROOT_TEX} nor "
                    f"any chapter in order.yaml reaches this file, so the figure "
                    f"is in no output"
                )

        def sort_key(item):
            return (order_index.get(item["file"], len(order)), item["file"], item["line"])
    else:
        def sort_key(item):
            return (item["file"], item["line"])

    results.sort(key=sort_key)
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true", help="print content figures as JSON to stdout")
    parser.add_argument("--root", default=".", help="repository root to scan (default: cwd)")
    args = parser.parse_args(argv)

    try:
        results = scan(args.root)
    except RuntimeError as e:
        print(f"alt_lint: error: {e}", file=sys.stderr)
        return 1

    failed = [r for r in results if r["_missing_alt"]]
    for r in failed:
        print(f"FAIL {r['file']}:{r['line']}: missing alt text for \\includegraphics{{{r['path']}}}", file=sys.stderr)

    malformed = [r for r in results if r["_malformed"]]
    for r in malformed:
        print(f"FAIL {r['file']}:{r['line']}: malformed \\includegraphics: {r['_malformed']}",
              file=sys.stderr)

    unreachable = [r for r in results if r["_unreachable"]]
    for r in unreachable:
        print(f"FAIL {r['_unreachable']}", file=sys.stderr)

    for r in results:
        for w in r["_warnings"]:
            print(f"WARN {w}", file=sys.stderr)

    if args.json:
        # Only well-formed figures: a malformed include has no path or alt
        # text to report. It still fails the run, so a consumer that checks
        # the exit status (CI does) never reads a list that quietly omits it.
        public = [
            {"file": r["file"], "line": r["line"], "path": r["path"], "alt": r["alt"], "caption": r["caption"]}
            for r in results if not r["_malformed"]
        ]
        print(json.dumps(public, indent=2))
    else:
        total_warnings = sum(len(r["_warnings"]) for r in results)
        print(f"alt_lint: {len(results) - len(malformed)} content figure(s) scanned, "
              f"{len(failed)} missing alt text, {len(malformed)} malformed, "
              f"{len(unreachable)} unreachable, {total_warnings} warning(s).")

    return 1 if (failed or malformed or unreachable) else 0


if __name__ == "__main__":
    sys.exit(main())
