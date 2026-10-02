# Scripts

* `__init__.py` Init to make a python package
* `deploy.sh` Script to run in travis deploy stage
* `script.sh` Script to run in travis script stages
* `install.sh` Script to run in travis install stage
* `gen_order.py` Generates the latex order file from the yaml file
* `gen_wiki.py` Generates a wiki given an order file and output directory
* `pandoc_header_filter.py` Outputs a yaml block to stderr given the metadata of the file
* `pandoc_wiki_filter.py` Filters a latex wiki page with additional add ons: figures become `![alt](url)` plus an italic caption
* `pandoc_epub_filter.py` Filter for `make epub`: alt text, `.eps` to `.png`
* `alt_text.py` Alt-text logic shared by the filters (alt= key, else the figure caption; no alt fails the build)
* `epub_metadata.yaml` The EPUB's accessibility metadata, with the reasons for each claim
* `epub_redefinitions.tex` EPUB-only macro overrides, read by pandoc before `main.tex`
* `epub_cover_alt.py` Gives the EPUB's generated cover page alt text
* `alt_lint.py` Checks every content figure's `\includegraphics` has alt text (issue #238 C1)
* `epub_check.py`, `wiki_check.py` Check the built EPUB / wiki carry each figure's alt text (issue #238 A2, A3); also run after deploy
* `alt_check_common.py` Shared by the two checks
* `compare_pandoc_ast.py` Reports the element-count change between two pandoc JSON ASTs, and checks the wiki's citations rendered (issue #238 A4)
* `test_pandoc_filters.py`, `test_alt_lint.py` Unit tests (`python3 -m unittest _scripts.test_pandoc_filters`)

The EPUB and wiki need pandoc 3.10.2 and panflute 2.3.1; `install.sh` pins both and explains why.
* `push_to_wiki.sh` Script to run in the push to wiki stage
* `site_cleanup.sh` Script to clean up pushing to the site
* `site_deploy.sh` Script to deploy to the site
* `site_retry.sh` Script to retry
