#!/usr/bin/env python3
"""B2 structure check for the tagged PDF (issue #238, Part B).

Checks, with pikepdf:
  * the PDF is tagged (/MarkInfo /Marked true and a /StructTreeRoot);
  * every /Figure structure element has a non-empty /Alt;
  * no /Figure uses the title-page duck image (it must be an artifact);
  * optionally, with --expected FILE (the JSON from
    `python3 _scripts/alt_lint.py --json`, a list of
    {file, line, path, alt, caption}), that the /Figure /Alt texts match
    the source alt= texts, as a multiset after whitespace normalisation.

A chapter PDF holds only that chapter's figures, so --expected-filter
PREFIX keeps only the entries whose "file" starts with PREFIX
(e.g. malloc/).

Exit status: 0 all checks pass, 1 a check failed, 2 usage/IO error.
--report-only always exits 0 (for the non-blocking CI job's summary).
"""
import argparse
import collections
import json
import re
import sys

try:
    import pikepdf
except ImportError:  # pragma: no cover
    sys.exit("check_pdf_tags.py needs pikepdf (pip install pikepdf)")

DUCK = "duck-alpha-cropped"


def norm(text):
    """Collapse whitespace; alt text in the source is often wrapped."""
    return re.sub(r"\s+", " ", str(text)).strip()


# How LaTeX renders the escapes that appear in the book's alt= texts.
_LATEX_ESCAPES = [
    (r"\\textbackslash\s*(\{\})?", "\\\\"),
    (r"\\textasciitilde\s*(\{\})?", "~"),
    (r"\\textasciicircum\s*(\{\})?", "^"),
    (r"\\([_%&#$])", r"\1"),
    (r"\\[{}]", lambda m: m.group()[1]),
    (r"(?<!\\)~", " "),
    (r"``|''", '"'),
]


def source_to_text(alt):
    """Normalise a source alt= value to the text tagpdf puts in /Alt."""
    s = str(alt)
    for pat, rep in _LATEX_ESCAPES:
        s = re.sub(pat, rep, s)
    return norm(s)


LEAK = re.compile(r"\\[A-Za-z]+")


def pdf_text(obj):
    if obj is None:
        return None
    try:
        return str(obj)
    except Exception:  # noqa: BLE001
        return repr(obj)


def role_map(pdf):
    root = pdf.Root.get("/StructTreeRoot")
    rm = {}
    if root is not None and "/RoleMap" in root:
        for k, v in root.RoleMap.items():
            rm[str(k)] = str(v)
    return rm


def resolve_role(s_type, rm):
    """Follow the RoleMap (PDF 2.0 namespaces are ignored: LaTeX maps its
    own names onto the standard ones there too)."""
    seen = set()
    while s_type in rm and s_type not in seen:
        seen.add(s_type)
        s_type = rm[s_type]
    return s_type


def iter_struct(node, depth=0):
    """Yield every structure element dictionary below node."""
    stack = [node]
    visited = set()
    while stack:
        n = stack.pop()
        if isinstance(n, pikepdf.Array):
            stack.extend(reversed(list(n)))
            continue
        if not isinstance(n, pikepdf.Dictionary):
            continue
        key = n.objgen if n.is_indirect else None
        if key is not None:
            if key in visited:
                continue
            visited.add(key)
        if "/S" in n:
            yield n
        kids = n.get("/K")
        if kids is not None:
            stack.append(kids)


def mcids_of(elem):
    """(page objgen, mcid) pairs directly owned by elem."""
    out = []
    kids = elem.get("/K")
    if kids is None:
        return out
    items = list(kids) if isinstance(kids, pikepdf.Array) else [kids]
    pg = elem.get("/Pg")
    for k in items:
        if isinstance(k, int) or (isinstance(k, pikepdf.Object)
                                  and k._type_code == pikepdf.ObjectType.integer):
            if pg is not None:
                out.append((pg.objgen, int(k)))
        elif isinstance(k, pikepdf.Dictionary) and k.get("/Type") == "/MCR":
            p = k.get("/Pg", pg)
            if p is not None:
                out.append((p.objgen, int(k.MCID)))
    return out


def images_by_mcid(pdf):
    """Map (page objgen, mcid) -> set of image XObject names drawn inside it,
    and collect names of images drawn outside any marked content or inside
    /Artifact."""
    result = collections.defaultdict(set)
    artifact_imgs = []
    for page in pdf.pages:
        xobjs = page.Resources.get("/XObject", {}) if "/Resources" in page else {}
        stack = []  # entries: ("mcid", n) | ("artifact",) | ("other",)
        try:
            ops = pikepdf.parse_content_stream(page)
        except Exception:  # noqa: BLE001
            continue
        for operands, op in ops:
            op = str(op)
            if op in ("BDC", "BMC"):
                tag = str(operands[0])
                mcid = None
                if op == "BDC" and len(operands) > 1:
                    props = operands[1]
                    if isinstance(props, pikepdf.Dictionary) and "/MCID" in props:
                        mcid = int(props.MCID)
                if tag == "/Artifact":
                    stack.append(("artifact",))
                elif mcid is not None:
                    stack.append(("mcid", mcid))
                else:
                    stack.append(("other",))
            elif op == "EMC":
                if stack:
                    stack.pop()
            elif op == "Do":
                name = str(operands[0])
                xo = xobjs.get(name)
                if xo is None or xo.get("/Subtype") != "/Image":
                    # Form XObjects wrap included PDFs/EPS; count them too.
                    if xo is None:
                        continue
                label = image_label(xo, name)
                inner = next((s for s in reversed(stack)
                              if s[0] in ("mcid", "artifact")), None)
                if inner is None:
                    artifact_imgs.append(("untagged", label))
                elif inner[0] == "artifact":
                    artifact_imgs.append(("artifact", label))
                else:
                    result[(page.objgen, inner[1])].add(label)
    return result, artifact_imgs


def image_label(xo, name):
    """Best-effort identification: size of the image; the duck is the only
    PNG with an SMask (alpha) on the title page."""
    w = xo.get("/Width")
    h = xo.get("/Height")
    smask = "/SMask" in xo
    return f"{name}:{w}x{h}{':alpha' if smask else ''}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--expected", help="alt_lint.py --json output file")
    ap.add_argument("--expected-filter", default="",
                    help="only compare expected entries whose file starts with this")
    ap.add_argument("--duck-page", type=int, default=1,
                    help="1-based page holding the title-page duck (0: none)")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--json-out", help="write the findings here as JSON")
    args = ap.parse_args(argv)

    try:
        pdf = pikepdf.open(args.pdf)
    except Exception as e:  # noqa: BLE001
        print(f"cannot open {args.pdf}: {e}", file=sys.stderr)
        return 2

    failures = []
    mark = pdf.Root.get("/MarkInfo")
    marked = bool(mark is not None and mark.get("/Marked", False))
    tree = pdf.Root.get("/StructTreeRoot")
    print(f"Tagged (MarkInfo/Marked): {'yes' if marked else 'no'}")
    print(f"StructTreeRoot: {'yes' if tree is not None else 'no'}")
    print(f"PDF version: {pdf.pdf_version}   pages: {len(pdf.pages)}")
    lang = pdf.Root.get("/Lang")
    print(f"Catalog /Lang: {pdf_text(lang)}")
    if not marked:
        failures.append("PDF is not marked as tagged")
    if tree is None:
        failures.append("no StructTreeRoot")
        return finish(failures, args, {})

    rm = role_map(pdf)
    counts = collections.Counter()
    figures = []
    for el in iter_struct(tree.get("/K")):
        s = str(el.S)
        std = resolve_role(s, rm)
        counts[std] += 1
        if std == "/Figure":
            figures.append(el)

    img_map, loose = images_by_mcid(pdf)
    page_index = {p.objgen: i for i, p in enumerate(pdf.pages, 1)}
    fig_info = []
    for el in figures:
        alt = el.get("/Alt")
        keys = list(mcids_of(el))
        # Also look further down (LaTeX may nest the MC in a child).
        for child in iter_struct(el.get("/K")):
            keys.extend(mcids_of(child))
        imgs = set()
        for key in keys:
            imgs |= img_map.get(key, set())
        # The page: /Pg on the element if present, else the page of its
        # first marked content (LaTeX puts /Pg on the kids, not the
        # /Figure, so without this every page would be unknown).
        pg = el.get("/Pg")
        page_no = page_index.get(pg.objgen) if pg is not None else None
        if page_no is None and keys:
            page_no = page_index.get(keys[0][0])
        fig_info.append({"alt": norm(alt) if alt is not None else None,
                         "page": page_no, "images": sorted(imgs)})

    no_alt = [f for f in fig_info if not f["alt"]]
    print(f"/Figure elements: {len(fig_info)}   with /Alt: "
          f"{len(fig_info) - len(no_alt)}   without: {len(no_alt)}")
    for f in no_alt:
        failures.append(f"/Figure without /Alt on page {f['page']} ({f['images']})")
    no_page = [f for f in fig_info if f["page"] is None]
    if no_page:
        failures.append(f"{len(no_page)} /Figure element(s) with no marked "
                        "content on any page (cannot locate them)")
    for f in fig_info:
        if f["alt"] and LEAK.search(f["alt"]):
            failures.append(f"LaTeX markup leaked into /Alt on page {f['page']}: "
                            f"{LEAK.search(f['alt']).group()!r} in {f['alt'][:70]!r}")

    # The duck: an alpha PNG on the title page. It must not be inside a
    # /Figure; it should sit in an /Artifact.
    if args.duck_page:
        duck_figs = [f for f in fig_info if f["page"] == args.duck_page]
        if duck_figs:
            failures.append(f"title page (page {args.duck_page}) has a /Figure: "
                            f"{duck_figs}")
        duck_page = pdf.pages[args.duck_page - 1]
        page_loose = [l for l in images_on_page(pdf, duck_page, loose)]
        print(f"title page images outside structure: {page_loose}")
        if not any(kind == "artifact" for kind, _ in page_loose):
            failures.append("title-page duck is not drawn inside an /Artifact")

    print("Structure element counts (standard role):")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k:14s} {v}")

    if args.expected:
        try:
            with open(args.expected) as fh:
                expected = json.load(fh)
        except (OSError, ValueError) as e:
            print(f"cannot read {args.expected}: {e}", file=sys.stderr)
            return 2
        exp = [source_to_text(e["alt"]) for e in expected
               if str(e.get("file", "")).startswith(args.expected_filter)]
        got = [f["alt"] for f in fig_info if f["alt"]]
        missing = collections.Counter(exp) - collections.Counter(got)
        extra = collections.Counter(got) - collections.Counter(exp)
        print(f"expected alt texts: {len(exp)}   matched: "
              f"{len(exp) - sum(missing.values())}")
        for a in missing.elements():
            failures.append(f"expected /Alt not found: {a[:90]!r}")
        for a in extra.elements():
            failures.append(f"/Alt not in the source list: {a[:90]!r}")

    return finish(failures, args, {"figures": fig_info, "counts": dict(counts)})


def images_on_page(pdf, page, loose):
    """Re-scan one page and return (kind, label) for images outside MCIDs."""
    out = []
    xobjs = page.Resources.get("/XObject", {}) if "/Resources" in page else {}
    stack = []
    for operands, op in pikepdf.parse_content_stream(page):
        op = str(op)
        if op in ("BDC", "BMC"):
            tag = str(operands[0])
            has_mcid = (op == "BDC" and len(operands) > 1
                        and isinstance(operands[1], pikepdf.Dictionary)
                        and "/MCID" in operands[1])
            stack.append("artifact" if tag == "/Artifact"
                         else "mcid" if has_mcid else "other")
        elif op == "EMC" and stack:
            stack.pop()
        elif op == "Do":
            name = str(operands[0])
            xo = xobjs.get(name)
            if xo is None:
                continue
            inner = next((s for s in reversed(stack) if s != "other"), None)
            if inner != "mcid":
                out.append((inner or "untagged", image_label(xo, name)))
    return out


def finish(failures, args, data):
    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump({"failures": failures, **data}, fh, indent=1)
    if failures:
        print(f"\nFAIL: {len(failures)} problem(s)")
        for f in failures[:200]:
            print(f"  - {f}")
    else:
        print("\nOK: all structure checks passed")
    return 0 if (args.report_only or not failures) else 1


if __name__ == "__main__":
    sys.exit(main())
