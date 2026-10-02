# Find all tex files one directory down
TEX=$(shell find . -path "./.git*" -prune -o -type f -iname "*.tex" -print)
# The PDFs (main book, chapter PDFs, debug) are tagged for accessibility
# by default (issue #238, Part B): main_tagged.tex puts \DocumentMetadata
# in front of main_wrapper.tex. `make pdf TAGGED=0` builds the same book
# untagged, straight from main_wrapper.tex, which is quicker and easier to
# debug; it needs the same TeX Live as the tagged build (2026, see
# .github/workflows/build.yaml), because cs341code.sty and cs341book.sty
# assume a current LaTeX.
TAGGED ?= 1
ifeq ($(TAGGED),0)
MAIN_TEX=main_wrapper.tex
else
MAIN_TEX=main_tagged.tex
endif
# The PDFs depend on this stamp, which changes only when TAGGED does, so
# switching modes rebuilds them instead of keeping the other mode's PDF.
PDF_MODE=.pdf-mode
# Every PDF, the chapter PDFs included, also depends on the preamble.
PREAMBLE=main.tex main_wrapper.tex main_tagged.tex prelude.tex title.tex glossary.tex \
	cs341code.sty cs341book.sty $(PDF_MODE)
MAIN_TEX_SOURCE=main.tex
PDF_TEX=$(patsubst %.tex,%.pdf,$(MAIN_TEX))
MAIN_OUT=main.pdf
MAIN_EPUB=main.epub
BASE=$(patsubst %.tex,%,$(MAIN_TEX))
OTHER_FILES=$(addprefix $(BASE),.aux .log .synctex.gz .toc .out .blg .bbl .glg .gls .ist .glo)
BIBS=$(shell find . -maxdepth 2 -mindepth 2 -path "./.git*" -prune -o -type f -iname "*.bib" -print)
OTHER=$$(find . -iname *aux) $$(find . -iname *bbl) $$(find . -iname *blg)
ORDER_TEX=order.tex
ORDER_TEX_DEP=order.yaml

# order.yaml has CRLF line ends; $(shell) turns CRLF into a space, like LF.
TEX_ORDER=$(shell sh -c "cat order.yaml | sed 's/^- //'")
CHAPTER_PDF=$(patsubst %,%.pdf,$(TEX_ORDER))

.PHONY: all
all: pdf epub
	-@latexmk -c
	-@rm *aux *bbl *glg *glo *gls *ist *latexmk *fls
	-@rm **/*aux **/*bbl **/*glg **/*glo **/*gls **/*ist **/*latexmk **/*fls

.PHONY: pdf
pdf: $(MAIN_OUT) chapters

.PHONY: chapters
chapters: $(CHAPTER_PDF)

.PHONY: debug
debug: $(MAIN_OUT)-debug

.PHONY: epub
epub: $(MAIN_EPUB)

# Needs pandoc >= 3.1.12 (see _scripts/install.sh). --citeproc must come
# before the filter: pandoc 3 runs citeproc and filters in command-line
# order. --mathml is explicit because pandoc 3.10's EPUB writer otherwise
# leaves \frac and \sum\limits formulas as raw TeX (25 of the book's 248).
# epub_cover_alt.py gives the generated cover page alt text, which pandoc
# has no option for.
$(MAIN_EPUB): $(ORDER_TEX) $(MAIN_TEX_SOURCE) _scripts/epub_metadata.yaml _scripts/epub_redefinitions.tex \
		_images/cover.png _scripts/pandoc_epub_filter.py _scripts/alt_text.py _scripts/epub_cover_alt.py
	pandoc --toc -s -f latex -t epub --mathml --citeproc --filter _scripts/pandoc_epub_filter.py --metadata-file _scripts/epub_metadata.yaml -M link-citations=true -M lang=en-US --epub-cover-image _images/cover.png -M author="B. Venkatesh, L. Angrave, et Al." -o $(MAIN_EPUB) _scripts/epub_redefinitions.tex $(MAIN_TEX_SOURCE)
	python3 _scripts/epub_cover_alt.py $(MAIN_EPUB)

$(ORDER_TEX): $(ORDER_TEX_DEP)
	python3 _scripts/gen_order.py $^ > $@

# order.tex is generated, and main.tex \input's it, so a chapter build from
# a clean tree needs it too. Note $< rather than $^: the recipe wants only
# the chapter's own .tex here, not every prerequisite.
$(CHAPTER_PDF): %.pdf: %.tex $(ORDER_TEX) $(PREAMBLE)
	echo '\\let\\cleardoublepage\\clearpage' > $@.tmp
	echo "\includeonly{$(basename $<)}\input{$(MAIN_TEX)}" >> $@.tmp
	@latexmk -interaction=nonstopmode -quiet -pdflatex=lualatex -pdf -jobname="$@" $@.tmp \
		|| { echo "*** latexmk failed for $@"; grep -n -A3 '^! ' $@.log 2>/dev/null; rm -f $@.tmp; false; }
	@mv $@.pdf $@
	@ls $@ > /dev/null
	-@rm $@.tmp

$(MAIN_OUT): $(TEX) $(PREAMBLE) $(BIBS) Makefile $(ORDER_TEX)
	@latexmk -quiet -pdflatex=lualatex -interaction=nonstopmode -pdf $(MAIN_TEX) \
		|| { echo "*** latexmk failed"; grep -n -A3 '^! ' $(basename $(MAIN_TEX)).log 2>/dev/null; false; }
	@ls $(PDF_TEX) > /dev/null
	@mv $(PDF_TEX) $(MAIN_OUT)
	@echo "Finished"

# The stamp's recipe runs every time (FORCE) but rewrites the file only when
# TAGGED differs from the last build's, so only then are the PDFs out of
# date. (A rule, not a $(shell) at parse time, so that make -n or make
# clean does not touch it.)
$(PDF_MODE): FORCE
	@echo "$(TAGGED)" | cmp -s - $@ || echo "$(TAGGED)" > $@

.PHONY: FORCE
FORCE:

# Like $(MAIN_OUT), but carries on past TeX errors (latexmk -f) and keeps
# its output in latexmk.out, to see how far a broken build gets. Same
# engine as the real build.
$(MAIN_OUT)-debug: $(TEX) $(PREAMBLE) $(BIBS) Makefile $(ORDER_TEX)
	-@rm -f $(PDF_TEX)
	-@latexmk -pdflatex=lualatex -interaction=nonstopmode -f -pdf $(MAIN_TEX) > latexmk.out
	@test -f $(PDF_TEX) && mv $(PDF_TEX) $(MAIN_OUT) || { echo "*** no PDF; see latexmk.out"; false; }

.PHONY: clean
clean:
	-@rm $(PDF_TEX) $(OTHER_FILES) $(OTHER) $(PDF_MODE)



