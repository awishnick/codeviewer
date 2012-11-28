#!/usr/bin/env python

import sys
import clang.cindex as cindex
from string import Template
import bisect
import unittest
import re
import pdb

class OffsetList:
    """Compute offsets from original positions in text to rewritten ones."""
    def __init__(self):
        """Initialize with no changes."""
        # The insertions map from positions to the lengths of the insertion at
        # the given position.
        self.insertions = {}

        # The removals map from positions where the removal begins to the length
        # of the text that was removed.
        self.removals = {}

    def __repr__(self):
        return str('insertions = {}, removals = {}'.format(self.insertions,
                                                           self.removals))

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

        for key_pos in self.removals:
            if key_pos >= pos:
                break
            offset -= self.removals[key_pos]

        return max(offset + pos, 0)

    def get_insertion_length(self, pos):
        """Return the length of the data inserted at pos."""
        if pos in self.insertions:
            return self.insertions[pos]
        return 0

    def remove(self, pos, length):
        """Remove some data from the given position."""
        if pos in self.removals:
            self.removals[pos] += length
        else:
            self.removals[pos] = length

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

    def test_remove(self):
        ol = OffsetList()

        # Remove two characters from the beginning.
        # 234
        ol.remove(0, 2)
        for i in range(2):
            self.assertEqual(ol.get_rewritten_pos(i), 0)
        for i in range(2, 5):
            self.assertEqual(ol.get_rewritten_pos(i), i-2)

class Rewriter:
    """Rewrite buffers of text, using line/column coordinates.
    """

    def __init__(self, buf):
        """Initialize with the initial buffer."""
        self.lines = buf.splitlines()
        self.col_offs = [OffsetList() for i in range(len(self.lines))]
        self.col_lens = [len(line) for line in self.lines]

    def __repr__(self):
        return str(self.col_offs)

    def insert_before(self, text, line, col):
        """Insert text at the given line/column.
        
        If text has already been inserted there, the new text will go at the
        beginning of the existing text.
        """
        col = self.canonicalize_column_index(line, col)
        col_off = self.col_offs[line]
        adj_col = (col_off.get_rewritten_pos(col) -
                col_off.get_insertion_length(col))
        theline = self.lines[line]
        self.lines[line] = theline[:adj_col] + text + theline[adj_col:]
        col_off.insert(col, len(text))

    def insert_after(self, text, line, col):
        """Insert text at the given line/column.
        
        If text has already been inserted there, the new text will go at the
        end of the existing text.
        """
        col = self.canonicalize_column_index(line, col)
        col_off = self.col_offs[line]
        adj_col = col_off.get_rewritten_pos(col)
        theline = self.lines[line]
        self.lines[line] = theline[:adj_col] + text + theline[adj_col:]
        col_off.insert(col, len(text))

    def remove(self, from_line, from_col, to_line, to_col):
        """Remove the given range of text."""
        assert from_line == to_line
        from_col = self.canonicalize_column_index(from_line, from_col)
        to_col = self.canonicalize_column_index(to_line, to_col)

        col_off = self.col_offs[from_line]
        adj_from_col = col_off.get_rewritten_pos(from_col)
        adj_to_col = col_off.get_rewritten_pos(to_col)
        theline = self.lines[from_line]
        self.lines[from_line] = theline[:adj_from_col] + theline[adj_to_col:]
        col_off.remove(from_col, to_col-from_col)

    def replace(self, text, from_line, from_col, to_line, to_col):
        """Replace the given range of text."""
        self.remove(from_line, from_col, to_line, to_col)
        self.insert_after(text, from_line, from_col)

    def canonicalize_column_index(self, line, col):
        """If the column index is negative, wrap it around to be positive."""
        if col < 0:
            col += self.col_lens[line] + 1
        assert col >= 0
        return col

    @property
    def lines(self):
        """Return the rewritten lines."""
        return self.lines

class TestRewriter(unittest.TestCase):
    def test_single_line(self):
        rw = Rewriter("test")
        rw.insert_before("_", line=0, col=2)
        self.assertEqual(rw.lines[0], "te_st")

        # Now inserting after where we already did should be properly offset.
        rw.insert_before("$$", line=0, col=3)
        self.assertEqual(rw.lines[0], "te_s$$t")

        # Now try inserting before either point.
        rw.insert_before("%%%", line=0, col=1)
        self.assertEqual(rw.lines[0], "t%%%e_s$$t")

        # Now try the very end.
        rw.insert_before("!", line=0, col=4)
        self.assertEqual(rw.lines[0], "t%%%e_s$$t!")

    def test_before_after(self):
        rw = Rewriter("0123")
        rw.insert_before("b", line=0, col=2)
        self.assertEqual(rw.lines[0], "01b23")
        
        rw.insert_before("a", line=0, col=2)
        self.assertEqual(rw.lines[0], "01ab23")

        rw.insert_after("c", line=0, col=2)
        self.assertEqual(rw.lines[0], "01abc23")

    def test_negative_col(self):
        rw = Rewriter("0123")
        rw.insert_before("4", line=0, col=-1)
        self.assertEqual(rw.lines[0], "01234")

    def test_remove(self):
        rw = Rewriter("012345")
        rw.remove(from_line=0, from_col=2, to_line=0, to_col=4)
        self.assertEqual(rw.lines[0], "0145")

    def test_replace(self):
        rw = Rewriter("01xx45")
        rw.replace("23", from_line=0, from_col=2, to_line=0, to_col=4)
        self.assertEqual(rw.lines[0], "012345")

    def test_two_replacements(self):
        rw = Rewriter("#include <iostream>")
        rw.replace("&lt;", 0, 9, 0, 10)
        self.assertEqual(rw.lines[0], "#include &lt;iostream>")
        rw.replace("&gt;", 0, 18, 0, 19)
        self.assertEqual(rw.lines[0], "#include &lt;iostream&gt;")

    def test_two_consecutive_replacements(self):
        rw = Rewriter('  std::cout << "Hello, world!";')
        rw.replace("&lt;", 0, 12, 0, 13)
        self.assertEqual(rw.lines[0], '  std::cout &lt;< "Hello, world!";')
        rw.replace("&lt;", 0, 13, 0, 14)
        self.assertEqual(rw.lines[0], '  std::cout &lt;&lt; "Hello, world!";')

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

def get_line_diagnostics(tu):
    """Return a dictionary mapping line numbers to a list of diagnostics.

    Each diagnostic is a tuple of (diag_class, message).
    """
    diags = {}
    for diag in tu.diagnostics:
        if diag.severity < cindex.Diagnostic.Warning:
            continue

        if diag.severity >= cindex.Diagnostic.Error:
            diag_class = 'error'
        else:
            diag_class = 'warning'

        diag_tup = (diag_class, diag.spelling)
        line = diag.location.line

        if line in diags:
            diags[line].append(diag_tup)
        else:
            diags[line] = [diag_tup]

    return diags

def format_source(src_filename, src, tu, tpl_filename):
    """Format source code as HTML using the given template file.
    """
    with open(tpl_filename, 'r') as tpl_file:
        tpl = Template(tpl_file.read())

    rw = Rewriter(src)

    # Generate a list of whitespace, <>, etc, to rewrite, and do it all at once.
    # This is because we're searching by position in the rewriter's buffer,
    # which will get changed once we rewrite it.
    replacements = []
    for (line, text) in enumerate(rw.lines):
        for col in [m.start() for m in re.finditer('<', text)]:
            replacements.append(("&lt;", line, col, line, col+1))
        for col in [m.start() for m in re.finditer('>', text)]:
            replacements.append(("&gt;", line, col, line, col+1))

    for (text, from_line, from_col, to_line, to_col) in replacements:
        rw.replace(text, from_line, from_col, to_line, to_col)

    for (line, diags) in get_line_diagnostics(tu).iteritems():
        used_classes = set()
        messages = '<br />'.join([diag[1] for diag in diags])
        for (diag_class, message) in diags:
            if diag_class in used_classes:
                continue
            used_classes.add(diag_class)
            rw.insert_before('<span class="{}" title="{}">'.format(diag_class,
                                                                  messages),
                             line-1,
                             0)
            rw.insert_after('</span>', line-1, -1)


    fn_decls = [node for node in
                find_cursor_kind(tu.cursor, cindex.CursorKind.FUNCTION_DECL) 
                if node.location.file.name == src_filename]
    for fd in fn_decls:
        if not fd.is_definition():
            continue
        
        start = fd.extent.start
        end = fd.extent.end
        rw.insert_before('<span class="function_decl">',
                         start.line-1,
                         start.column-1)
        rw.insert_after('</span>', end.line-1, end.column-1)

    code = '\n'.join(rw.lines)

    return tpl.substitute(filename=src_filename,
                          webpath='web',
                          code=code)

def main(argv):
    src_filename = argv[1]

    index = cindex.Index.create()
    clang_args = ['-Wall', '-Wextra']
    tu = index.parse(src_filename, args=clang_args)

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
