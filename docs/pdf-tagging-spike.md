# PDF tagging spike (issue #238, Part B)

Measured 2026-09-13. This is the evidence for the Part B decision between
**3a (partial tagging with containment)** and **3b (package replacement)**.
It is not part of the book build.

## TL;DR

**Option 3a works on TeX Live 2026 without replacing any package.** With
the containment in `main_tagged.tex` (about 40 lines of hooks, none of
which touch the default build), the full book builds tagged with:

| Gate | Result (full book, 392 pages) |
|---|---|
| B1 tagpdf errors | **0** (TeX errors 0; 17 warnings: 16 Part→MC relations at the epigraphs, 1 "no unicode-math") |
| B2 structure | Tagged, PDF 2.0, `/Lang en-US`; **48/48 content `/Figure` elements carry `/Alt`**, 47/48 equal to the source `alt=`; the duck is an **artifact**, not a `/Figure` |
| B3 veraPDF PDF/UA-2 | 1724 rules pass, **3 fail** (14 checks); **no figure/alt rule fails**. Two of the three are metadata and go away with `pdfstandard=ua-2` (measured on one chapter); the third is the embedded Charter font's glyph widths |
| B4a same TL, tagged vs untagged | same page count (392 = 392); words differ in 25 places: 18 × "Chapter" (fncychap is dropped), 7 page numbers one lower; everything else is the same words in a different extraction order |

Without containment, one chapter alone (malloc) gave 422 tagpdf errors and
the full preamble did not compile (titlesec). The price of 3a is visible
in B4a: **the tagged build loses fncychap's chapter style**, shifts seven
page references by one, and code listings are one `/Code` block each
(readable text, but no per-line structure).

The one `/Alt` mismatch is a real bug the check found: at
`introc/c_memory_model.tex:96` the alt text contains `\textbackslash 0`,
which tagging passes through literally, so a screen reader would say
"backslash textbackslash 0".

**Recommendation: 3a**, as the next step. It delivers all 48 alt texts
now, and 3b can be done later package by package if the lost chapter
style matters; the containment and the checks carry over. Details and the
remaining gaps are below.

## Setup

| | Version |
|---|---|
| TeX Live (tagged build, CI job) | **TeX Live 2026**, `texlive/texlive:latest@sha256:1a1b8588…d134` (tlmgr r79639) |
| tagpdf / latex-lab | tagpdf 1.0c (2026-05-17), latex-lab firstaid 0.85x (2026-06-08), graphicx 1.2e, listings 1.11b, titlesec 2.17 |
| TeX Live (default build, current CI) | TeX Live 2023 from Ubuntu 24.04 apt (tagpdf 0.98v) |
| veraPDF | `verapdf/cli:v1.30.2`, profile PDF/UA-2 (ISO 14289-2:2024) |
| Engine | LuaLaTeX (as the Makefile) |

`\DocumentMetadata` keys were re-checked against TL2026's
`documentmetadata-support.ltx`: `testphase={phase-III,firstaid}` is still
valid (phase-III implies the newer `tagging=on`), `lang` and `pdfversion`
unchanged.

## What was built

* `make pdf TAGGED=1` (also `chapters`, `debug`, single chapter PDFs) goes
  through `main_tagged.tex`, which puts `\DocumentMetadata` first and then
  `\input`s `main_wrapper.tex`. Tagged targets depend on a `FORCE` target
  and their PDFs are backdated to 1970, so switching modes in either
  direction never reuses the other mode's PDF. (The `debug` recipe is
  untouched and keeps its existing quirks: it runs pdfLaTeX, not
  LuaLaTeX, and its `mv $(PDF_TEX)-debug` names a file latexmk never
  writes. `TAGGED=1` inherits both.)
* **Default build unchanged:** `make -n -B pdf debug` prints the same 134
  lines on master and on this branch; a full TL2023 build of master and of
  this branch gives the same 392 pages, identical `pdftotext` output and
  the same file size (2,298,238 bytes). pandoc 2.7.3's AST of `main.tex`
  (the EPUB path) is byte-identical before and after the `title.tex` change.
* **Duck (B4):** `title.tex` uses `\includegraphics[artifact,…]` when
  graphicx knows the key (`\KV@Gin@artifact`, graphicx 2024-12+) and the
  old call otherwise. TL2023 takes the old branch (checked); the
  `\ifdefined` form was chosen because `\ifcsname …\endcsname` leaked the
  text "KV@Gin@artifact" into pandoc's EPUB.
* **CI:** `.github/workflows/tagged-pdf.yaml`, two `continue-on-error` jobs:
  `build` (pinned TL2026 container: tagged + untagged PDF, B4a, uploads
  PDFs and logs) and `check` (B2 with pikepdf, B3 with the pinned veraPDF
  image; uploads reports).
* **Checks** in `_scripts/`: `check_pdf_tags.py` (B2), `check_verapdf.sh` +
  `verapdf_summary.py` (B3), `compare_pdf_text.sh` (B4a).

## Per-package results (minimal documents, TL2026, phase-III + firstaid)

Each row is a minimal `book` document with only that package and a typical
use, built twice with LuaLaTeX. "Errors" are `tagpdf Error` counts;
every document also has one harmless warning (no unicode-math, so no
MathML).

| Package / construct | Uses in book | Status page (TL2026 data) | Uncontained | Containment | Contained |
|---|---|---|---|---|---|
| listings `lstlisting` | 492 | currently-incompatible | 2 errors (para hooks differ) | one `/Code` element per listing, para tagging off inside, end para, re-enable, clear `\@doendpe` | **0** |
| listings in `\item`, followed by `\item` / text | many | | 2 errors | same | **0** |
| minted emulation (`\lstnewenvironment` + `minipage`) | 7 | (minted: incompatible) | 2 errors | same, `\par` before re-enabling (it ends in horizontal mode) | **0** |
| `\lstinputlisting` | 1 (AUTHORS.md) | | 1 error | hook `\lst@InputListing` (cmd hooks on `\lstinputlisting` break its catcodes: 30 TeX errors) | **0** |
| epigraph (book's minipage redefinition) | 16 | partially-compatible | 1 error | one `/BlockQuote` per epigraph | **0** |
| titlesec easy forms (`\titleformat*`, `\titlespacing*`) | 8 calls | currently-incompatible | 11 TeX errors, fatal | give titlesec full `\titleformat`s (book defaults) when it loads | **0** |
| `proof` environment (prelude.tex) | 4 | — | "Command \proof already defined" (latex-lab block module) | `\let\proof\relax` before the prelude | **0** |
| framed `shaded*` (proof boxes) | 2 | currently-incompatible | 0 | none needed | 0 |
| mdframed | **0 (loaded, unused)** | no-support | 2 errors *when used*; loading it unused costs nothing (the full book, which loads it, has 0 errors) | a `/Div` wrapper crashes the PDF backend | not needed |
| wrapfig | **0 (loaded, unused)** | currently-incompatible | 0 | — | 0 |
| fncychap `[Bjornstrup]` | every chapter | currently-incompatible | 0 errors, **but the style is silently dropped** (see below) | — | — |
| float `[H]` + figure + `alt` | 46 | currently-incompatible | 0 (firstaid patches `[H]`) | — | 0 |
| glossaries | loaded, `\gls` unused | unchecked | 0 | — | 0 |
| mathdesign (Charter) | body font | unchecked | 0 | — | 0 (see veraPDF font rule) |
| chapterbib + natbib | every chapter | partially-compatible / compatible | 0 | — | 0 |
| tocloft | ToC/LoF/LoT | currently-incompatible | 0 | — | 0 |
| longtable, tabular, verbatim, hyperref `\href`, `\cite[..]` | various | | 0 | — | 0 |

The status page (the TL2026 `latex-tagging-status.ltx`) lists tocloft and
titlesec as *currently-incompatible*, not compatible as the issue's table
says; mdframed is *no-support*.

### Visual changes in the tagged build (not errors)

* **fncychap is overridden.** latex-lab's sectioning code replaces
  `\@makechapterhead`, so tagged chapters get the plain book heading
  ("Chapter 1 / Memory Allocators") instead of the Bjornstrup box. This is
  also the one word B4a finds: the tagged text has an extra "Chapter".
* **Link boxes.** The `hidelinks` class option no longer reaches hyperref
  with `\DocumentMetadata`; `main_tagged.tex` now sets it explicitly.
* **Paragraph after a listing** without a blank line is indented (the
  containment drops listings' `\@doendpe`).
* Section headings come from the titlesec shim (book defaults + main.tex's
  own sizes and spacing), so they should match, but were only checked by
  eye on one chapter.

## Single chapter (malloc, 10 figures), TL2026

| Measure | Result |
|---|---|
| tagpdf errors | 422 (no containment) → 2 (listings only) → **0** (final `main_tagged.tex`) |
| TeX errors | **0** |
| tagpdf warnings | 2 (no unicode-math; one Part→MC relation at the epigraph) |
| B2 | Tagged, `/Lang en-US`, PDF 2.0; **10/10 `/Figure` with `/Alt`**, all 10 equal to the source `alt=` text |
| B3 veraPDF PDF/UA-2 | 1724 rules pass, **3 fail**: 8.4.5.6-1 font glyph widths (9 checks), 5-1 no PDF/UA identification in XMP (1), 8.11.2-1 no `DisplayDocTitle` (1). **No figure/alt rule fails.** |
| B3 with `pdfstandard=ua-2` + `pdfdisplaydoctitle` | only 8.4.5.6-1 fails (9 checks) |
| B4a (same TL) | same page count (17 = 17); words 5934 vs 5935, the only difference is the added "Chapter" |

## Full book, TL2026

| Measure | Untagged | Tagged (final `main_tagged.tex`) |
|---|---|---|
| Build time (amd64 emulated on arm64, so slow) | 91 s | 269 s (about 3×) |
| TeX errors / tagpdf errors | 0 / – | **0 / 0** |
| tagpdf warnings | – | 17 (16 × `Part --> MC` at the 16 epigraphs; 1 no unicode-math) |
| Pages | 392 | 392 |
| Structure elements | – | 3528 P, 509 Code, 48 Figure, 63 Caption, 18 H1, 20 Sect, 15 Table, 460 TOCI, 250 Link, 27 BlockQuote, 248 Formula |
| B2 | – | 48/48 `/Figure` with `/Alt`; 47/48 match source (`\textbackslash` leak); duck is an `/Artifact` |
| B3 | – | 3 rules fail: 8.4.5.6-1 font widths ×12, 8.11.2-1 DisplayDocTitle ×1, 5-1 PDF/UA id ×1 |

Evolution of the full-book count, which shows where the errors came from:

| `main_tagged.tex` variant | tagpdf errors |
|---|---|
| metadata only | fatal: titlesec, then `\proof` already defined |
| + proof + titlesec shim | fatal/hundreds (one chapter: 422) |
| + listings as `/Code`, para tagging left off after the first listing | 2, but 556 vs 598 unbalanced paragraphs: most text untagged (a false zero) |
| + para tagging restored, `\@doendpe` cleared | 549 (minted emulation and `\lstinputlisting` still broken) |
| + minted `\par` fix + `\lst@InputListing` hook (final) | **0** |

B2 was also checked in the negative: in a test document with the duck
included without `artifact`, the checker fails with "title page has a
/Figure" (and tagging had given it the alt text "duck.png", the file
name).

### Per chapter (the deployed chapter PDFs), TL2026

`make TAGGED=1 <chapter>.pdf` for all 18 chapters in `order.yaml`:
**0 tagpdf errors and 0 TeX errors in every chapter**; 1–2 warnings each
(the epigraph relation and the unicode-math notice). Build times 9–42 s
each under emulation.

## TeX Live 2023 (current CI)

A tagged build on TL2023 is not viable: its tagpdf 0.98v does not know the
`para/tagging` key the containment uses (86 TeX errors on malloc), and the
tagging code predates most of the fixes above. The tagged CI job therefore
pins TL2026; the default build stays on TL2023 until CI moves.

## What 3a achieves, and what remains

**Achieved (3a, TL2026):** B1 passes (0 tagpdf errors, full book and every
chapter); B2 passes except the one genuine alt-text bug; B3 passes the
figure/alt rules; B4a has the same page count.

**Remains, in rough order of cost:**

1. **Alt text bug:** `introc/c_memory_model.tex:96` uses
   `\textbackslash 0` inside `alt=`; write it in words (e.g. "the
   terminating null byte") or as a plain character sequence. B2 flags it.
2. **Metadata (2 of 3 veraPDF rules):** add `pdfstandard=ua-2` to
   `\DocumentMetadata` and `\hypersetup{pdfdisplaydoctitle=true,
   pdftitle=…}`. Measured on malloc: veraPDF then fails only the font
   rule. Not done here because the issue fixes the metadata keys; it is a
   one-line decision.
3. **Font widths (8.4.5.6-1, 12 checks):** the embedded Type 1 Charter
   (mathdesign) has width tables that disagree with the font dictionary.
   Needs a font change (an OpenType Charter such as XCharter with
   `unicode-math`, which would also fix the MathML warning) — that is a
   3b-style change to the body font and changes every page.
4. **fncychap style lost** in tagged output (latex-lab owns chapter
   headings). Either accept the plain heading in the tagged PDF, or
   restyle chapters with a tagging-aware method (latex-lab's heading
   templates, or `titlesec`'s full `\titleformat{\chapter}`), which is a
   visual redesign of the chapter opener.
5. **B4a is not word-identical:** 18 × "Chapter" (item 4) and 7 page
   numbers one lower. If the gate stays "word-identical", it has to allow
   these, or item 4 has to be solved.
6. **Listings have no inner structure:** each is one `/Code` element with
   one marked-content block; a reader gets the code as text, which is what
   PDF/UA asks for, but no line structure. The containment also indents a
   paragraph that continues straight after a listing (tagged build only).
7. **Warnings:** 16 `Part --> MC` relations at epigraphs (the epigraph
   sits in a text-unit); harmless for validators today.
8. **CI:** TL2023 cannot build the tagged PDF (tagpdf 0.98v lacks
   `para/tagging`), so "make tagging the default" also means moving the
   main CI from Ubuntu's TL2023 to a pinned TL2026 container, which is the
   issue's own precondition.
9. The containment relies on internals: `\lst@InputListing`,
   `\lst@doendpe`, `\@endpefalse`, and titlesec loading after latex-lab.
   The CI job catches breakage when the pin moves.

## Rough effort for 3b (replacement)

Status codes from TL2026's own data for plausible replacements: fancyvrb
*partially-compatible*, fvextra / piton / minted *currently-incompatible*,
tcolorbox *partially-compatible*, titleps **compatible**, sectsty
*partially-compatible*, kernel `verbatim` *partially-compatible*. So there
is **no fully compatible drop-in for listings with syntax highlighting**
in TL2026; 3b would trade listings for another partially supported
package.

| Work item | Size in this book | Estimate |
|---|---|---|
| Replace listings (e.g. fancyvrb/`Verbatim` or piton) and re-create the C/bash styles and `literate` braces | 492 `lstlisting` (396 C, 65 bash, 23 plain, 3 Go, 3 x86 asm, 2 other), 7 `minted`, 1 `\lstinputlisting`, in 24 files; plus the EPUB/wiki pandoc path, which reads `lstlisting` today | 3–5 days, plus pandoc filter changes and review of ~500 blocks for line breaking and page breaks |
| Replace fncychap with a tagging-aware chapter style | 18 chapters, one style | 0.5–1 day, visual review |
| Remove unused wrapfig and mdframed from the preamble | 0 uses each | minutes (safe in either option) |
| titlesec (currently-incompatible): replace with titleps/kernel `\section` hooks or keep the shim | 8 format calls | 0.5 day |
| Visual diff review of all 392 pages (issue requires it) | | 1 day |
| **Total 3b** | | **about 1–2 weeks**, and it still depends on partially compatible packages |

3a, by contrast, is done: what is left from the list above is items 1–2
(minutes), deciding on 4–5, and the CI move in 8.

## Adversarial review

GLM (`lumen/glm-5.3-flash` via opencode) reviewed the diff. Every finding
was checked against the code and the measurements.

Accepted and fixed:

1. A plain `make` after `make TAGGED=1` kept the tagged `main.pdf` (FORCE
   only covered untagged → tagged). Tagged outputs are now backdated.
2. The duck check failed on chapter PDFs, which have no title page; it now
   skips a page with no images.
3. `compare_pdf_text.sh` said OK when poppler was missing or the PDFs were
   unreadable; it now checks tools, page counts, non-empty text, and that
   the first PDF is untagged and the second tagged.
4. `verapdf_summary.py` crashed on a `null` `validationResult`.
5. `tee` without `pipefail` hid step failures; both CI jobs now use
   `shell: bash` (`-eo pipefail`).
6. The build step could stop before writing its summary when no PDF was
   produced; copies and counts are guarded.
7. The comment on Form XObjects claimed more than the code did; forms are
   now labelled as opaque.
8. `check_pdf_tags.py` used a private pikepdf attribute and crashed on an
   `/MCR` without `/MCID`; it also now resolves named `/Properties`.
10. The untagged PDF is now asserted to be untagged before B4a.
11. The mdframed row was unclear about loaded-but-unused.

Rejected:

9. "Hard-fail B2 when `_scripts/alt_lint.py` is missing." It comes from
   Part C on another branch, and the task is to accept a JSON file until
   then; CI now emits a warning instead of failing.

The review output was cut off at the start of a twelfth finding (about
`main_tagged.tex`); two further runs (one on the fallback model
`nvidia/z-ai/glm-5.3-flash`) returned no findings, so that item is
unknown.

## How to reproduce

```sh
python3 _scripts/gen_order.py order.yaml > order.tex
make TAGGED=1 malloc/malloc.pdf          # or: make pdf TAGGED=1
python3 _scripts/check_pdf_tags.py malloc/malloc.pdf --duck-page 0 \
    --expected alt.json --expected-filter malloc/
bash _scripts/check_verapdf.sh malloc/malloc.pdf
bash _scripts/compare_pdf_text.sh untagged.pdf tagged.pdf
```
