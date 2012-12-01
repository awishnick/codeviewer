#!/usr/bin/env python

import argparse
import sys
import clang.cindex as cindex
from string import Template
import bisect
import unittest
import re
import os
import shutil
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

    Each diagnostic is a tuple of (diag_class, message). Diagnostics appearing
    outside of the source file corresponding to this translation unit are
    filtered out, as are diagnostics without any location.
    """
    diags = {}
    for diag in tu.diagnostics:
        if diag.location.file is None:
            continue
        if diag.location.file.name != tu.spelling:
            continue
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

def sanitize_code_as_html(rewriter):
    """Rewrite all whitespace, <>, etc, so that it's valid HTML."""
    # Generate a list of whitespace, <>, etc, to rewrite, and do it all at once.
    # This is because we're searching by position in the rewriter's buffer,
    # which will get changed once we rewrite it.
    replacements = []
    for (line, text) in enumerate(rewriter.lines):
        for col in [m.start() for m in re.finditer('<', text)]:
            replacements.append(("&lt;", line, col, line, col+1))
        for col in [m.start() for m in re.finditer('>', text)]:
            replacements.append(("&gt;", line, col, line, col+1))

    for (text, from_line, from_col, to_line, to_col) in replacements:
        rewriter.replace(text, from_line, from_col, to_line, to_col)

def highlight_diagnostics(tu, rewriter):
    """Highlight all diagnostics in the translation unit."""
    for (line, diags) in get_line_diagnostics(tu).iteritems():
        used_classes = set()
        messages = '<br />'.join([diag[0] + ': ' + diag[1] for diag in diags])
        for (diag_class, message) in diags:
            if diag_class in used_classes:
                continue
            used_classes.add(diag_class)
            span_tag = '<span class="{}" title="{}">'.format(diag_class,
                                                             messages)
            rewriter.insert_before(span_tag, line-1, 0)
            rewriter.insert_after('</span>', line-1, -1)

def format_source(src_filename, src, tu, tpl_filename, webpath):
    """Format source code as HTML using the given template file.
    """
    with open(tpl_filename, 'r') as tpl_file:
        tpl = Template(tpl_file.read())

    rw = Rewriter(src)

    sanitize_code_as_html(rw)
    highlight_diagnostics(tu, rw)

    # Link declarations without definitions to their definition.
    fn_decls = [node for node in
                find_cursor_kind(tu.cursor, cindex.CursorKind.FUNCTION_DECL) 
                if node.location.file.name == src_filename]
    for fd in fn_decls:
        if fd.is_definition():
            continue

        defn = fd.get_definition()
        if defn is None:
            continue
        if defn.location.file.name != src_filename:
            continue
        target_hash = defn.hash
        
        start = fd.extent.start
        end = fd.extent.end
        a_tag = '<a class="function_decl" href="#{}">'.format(target_hash)
        rw.insert_before(a_tag,
                         start.line-1,
                         start.column-1)
        rw.insert_after('</a>', end.line-1, end.column-1)

        start = defn.extent.start
        end = defn.extent.end
        rw.insert_before('<a id="{}">'.format(target_hash),
                         start.line-1,
                         start.column-1)
        rw.insert_after('</a>', end.line-1, end.column-1)

    code = '\n'.join(rw.lines)

    return tpl.substitute(filename=src_filename,
                          webpath=webpath,
                          code=code)

def split_args(args):
    """Split our arguments into (our_args, clang_args).

    The sets of arguments are separated by '--'. We use our_args, and pass along
    clang_args to clang.
    """
    double_dash_pos = [i for i,x in enumerate(args) if x == '--']
    if not double_dash_pos:
        return (args, [])
    else:
        double_dash_pos = double_dash_pos[0]
        return (args[:double_dash_pos], args[double_dash_pos+1:])

class TestSplitArgs(unittest.TestCase):
    def test_no_args(self):
        self.assertEqual(split_args([]), ([], []))

    def test_both_args(self):
        our_args = ['--a', 'foo']
        clang_args = ['-Wall', '-Wextra', '--', 'bar']
        self.assertEqual(split_args(our_args + ['--'] + clang_args),
                         (our_args, clang_args))

    def test_no_clang_args(self):
        our_args = ['--a', 'foo']
        self.assertEqual(split_args(our_args), (our_args, []))
        self.assertEqual(split_args(our_args + ['--']), (our_args, []))

def get_source_file_list(dir):
    """Recursively find all source files in the given directory."""
    extensions = ['h', 'c', 'cc', 'cpp', 'm', 'mm']
    extensions = tuple(['.' + x for x in extensions])

    files = set()
    for (dirpath, dirnames, filenames) in os.walk(dir):
        files.update([os.path.join(dirpath, name) for name in filenames if
                      name.endswith(extensions)])

    return files

def copy_web_resources(output_dir):
    """Copy all the resources in our 'web' directory to the output path."""
    mypath = os.path.dirname(os.path.realpath(__file__))
    webpath = os.path.join(mypath, 'web')

    for (dirpath, dirnames, filenames) in os.walk(webpath):
        relpath = os.path.relpath(dirpath, webpath)
        tgtpath = os.path.join(output_dir, relpath)
        if not os.path.exists(tgtpath):
            os.makedirs(tgtpath)

        for file in [os.path.join(dirpath, filename) for filename in filenames]:
            shutil.copy(file, tgtpath)            

def generate_outputs(input_dir, output_dir, clang_args):
    """Read the source files and generate the formatted output."""

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    copy_web_resources(output_dir)

    input_files = get_source_file_list(input_dir)

    index = cindex.Index.create()

    tus = {}
    for src_filename in input_files:
        rel_src = os.path.relpath(src_filename, input_dir)
        print('Parsing ' + rel_src)

        tu = index.parse(src_filename, args=clang_args)
        tus[src_filename] = tu

    for src_filename in input_files:
        rel_src = os.path.relpath(src_filename, input_dir)
        print('Outputting ' + rel_src)

        tu = tus[src_filename]

        with open(src_filename, 'r') as src_file:
            src = src_file.read()

        output_filename = os.path.join(output_dir,
                                       '{}.html'.format(rel_src))
        output_path = os.path.dirname(output_filename)
        if not os.path.exists(output_path):
            os.makedirs(output_path)

        webpath = os.path.relpath(output_dir, output_path)

        with open(output_filename, 'w') as html_file:
            html_file.write(format_source(src_filename,
                                          src,
                                          tu,
                                          'templates/source.html',
                                          webpath))

def main(argv):
    (our_args, clang_args) = split_args(argv[1:])

    parser = argparse.ArgumentParser()
    parser.add_argument('--input-dir',
                        type=str,
                        required=True,
                        help='the directory to search for source files.')
    parser.add_argument('--output-dir',
                        type=str,
                        required=True,
                        help='the directory to write formatted sources to.')
    args = parser.parse_args(our_args)

    generate_outputs(os.path.abspath(args.input_dir),
                     os.path.abspath(args.output_dir),
                     clang_args)

    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv))
