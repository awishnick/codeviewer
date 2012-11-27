#!/usr/bin/env python

import sys
import clang.cindex as cindex
from string import Template
import bisect
import unittest
import pdb

class OffsetList:
    """Compute offsets from original positions in text to rewritten ones."""
    def __init__(self):
        """Initialize with no changes."""
        # The insertions map from positions to the lengths of the insertion at
        # the given position.
        self.insertions = {}

    def insert(self, pos, length):
        """Insert some data at the given position."""
        if pos in self.insertions:
            self.insertions[pos] += length
        else:
            self.insertions[pos] = length

    def get_rewritten_pos(self, pos):
        """Return the rewritten position given an original position."""
        offset = 0
        for key_pos in self.insertions:
            if key_pos > pos:
                break
            offset += self.insertions[key_pos]
        return offset + pos

class TestOffsetList(unittest.TestCase):
    def test_insert(self):
        ol = OffsetList()

        # Inserting before the beginning should offset everything.
        # ____01234
        ol.insert(0, 4)
        for i in range(5):
            self.assertEqual(ol.get_rewritten_pos(i), i+4)

        # ____01_234
        ol.insert(2, 1)
        for i in range(2):
            self.assertEqual(ol.get_rewritten_pos(i), i+4)
        for i in range(2, 5):
            self.assertEqual(ol.get_rewritten_pos(i), i+5)

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
        self.lines[line] = theline[:col] + text + theline[col:]
        col_off.insert(col, len(text))

    @property
    def lines(self):
        """Return the rewritten lines."""
        return self.lines

class TestRewriter(unittest.TestCase):
    def test_single_line(self):
        rw = Rewriter("test")
        rw.insert_before(line=0, col=2, text="_")
        self.assertEqual(rw.lines[0], "te_st")

        # Now inserting after where we already did should be properly offset.
        rw.insert_before(line=0, col=3, text="$$")
        self.assertEqual(rw.lines[0], "te_s$$t")

        # Now try inserting before either point.
        rw.insert_before(line=0, col=1, text="%%%")
        self.assertEqual(rw.lines[0], "t%%%e_s$$t")

        # Now try the very end.
        rw.insert_before(line=0, col=4, text="!")
        self.assertEqual(rw.lines[0], "t%%%e_s$$t!")

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
