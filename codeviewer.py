#!/usr/bin/env python

import sys
import clang.cindex as cindex
from string import Template
import bisect
import unittest

class OffsetList:
    """Hold offsets from original positions in text to rewritten ones."""
    def __init__(self):
        """Initialize with no changes."""
        # The list of offsets is a map from original position to rewritten
        # position.
        self.offs = [(0, 0)]

    def lower_bound(self, pos):
        """Return the index of the  largest original position op such that
        op <= pos"""
        return bisect.bisect_left(self.offs, (pos, 0))

    def insert_before(self, pos, length):
        """Insert some data before the given position."""
        idx = self.lower_bound(pos)
        off = self.offs[min(idx, len(self.offs)-1)]
        if off[0] == pos:
            self.offs[idx] = (pos, off[1]+length)
        else:
            self.offs.insert(idx, (pos, pos-off[0]+off[1]+length))

    def get_rewritten_pos(self, pos):
        """Return the rewritten position given an original position."""
        idx = self.lower_bound(pos)
        off = self.offs[min(idx, len(self.offs)-1)]
        return pos - off[0] + off[1]

class TestOffsetList(unittest.TestCase):
    def test_insert_before(self):
        ol = OffsetList()

        # Inserting before the beginning should offset everything.
        # ____01234
        ol.insert_before(0, 4)
        self.assertEqual(ol.offs[0], (0, 4))

        # ____01_234
        ol.insert_before(2, 1)
        self.assertEqual(ol.offs[0], (0, 4))
        self.assertEqual(ol.offs[1], (2, 7))

class Rewriter:
    """Rewrite buffers of text, using line/column coordinates.
    """

    def __init__(self, buf):
        """Initialize with the initial buffer."""
        self.lines = buf.splitlines()
        self.col_offs = [OffsetList()] * len(self.lines)

    def insert_before(self, line, col, text):
        """Insert text before the given line/column."""
        theline = self.lines[line]
        col_off = self.col_offs[line]
        col = col_off.get_rewritten_pos(col)
        self.lines[line] = theline[:col-1] + text + theline[col-1:]

    @property
    def lines(self):
        """Return the rewritten lines."""
        return self.lines

class TestRewriter(unittest.TestCase):
    def test_single_line(self):
        rw = Rewriter("test")
        rw.insert_before(0, 3, "_")
        self.assertEqual(rw.lines[0], "te_st")

        # Now inserting after where we already did should be properly offset.
        rw.insert_before(0, 4, "$$")
        #self.assertEqual(rw.lines[0], "te_s$$t")

def find_cursor_kind(node, kind):
    """Return a list of all nodex with the given cursor kind.
    """
    def visitor(node, parent, found):
        if node.kind == kind:
            found.append(node)
        return 2

    found = []
    cindex.Cursor_visit(node,
                        cindex.Cursor_visit_callback(visitor),
                        found)

    return found

def format_source(src_filename, src, tu, tpl_filename):
    """Format source code as HTML using the given template file.
    """
    with open(tpl_filename, 'r') as tpl_file:
        tpl = Template(tpl_file.read())

    lines = [line + '<br/>' for line in src.splitlines()]

    fn_decls = [node for node in
                find_cursor_kind(tu.cursor, cindex.CursorKind.FUNCTION_DECL) 
                if node.location.file.name == src_filename]
    print(fn_decls)

    code = ''.join(lines)

    return tpl.substitute(filename=src_filename,
                          code=code)

def main(argv):
    src_filename = argv[1]

    index = cindex.Index.create()
    tu = index.parse(src_filename)

    with open(src_filename, 'r') as src_file:
        src = src_file.read()

    with open('{}.html'.format(src_filename), 'w') as html_file:
        html_file.write(format_source(src_filename,
                                      src,
                                      tu,
                                      'templates/source.html'))
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv))
