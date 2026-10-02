# Current
* [Name] [Change]
* [Lawrence Angrave] Figure alt text now reaches readers in all three outputs (#238): the PDF is tagged and carries each figure's /Alt, pandoc 3 delivers the `alt=` key to the EPUB and the wiki, and CI keeps every content figure's alt text in place.
* [Wu Shuwen] Alt-text lint: fail when a figure sits in a `.tex` file that no chapter in `order.yaml` reaches, so a figure orphaned out of the book is caught instead of passing unnoticed.
* [Lawrence Angrave, Cay Zhang] Deadlock: replace the resource allocation graph cycle detection snippet with a correct directed graph DFS, and explain why the "already seen" shortcut reports deadlocks that do not exist.

# Previous
