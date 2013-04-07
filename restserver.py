#!/usr/bin/env python
from flask import Flask, Response, json
from werkzeug.exceptions import NotFound
from codeviewer import split_args, get_source_file_list, is_header, \
    find_all_usrs
import argparse
import sys
import os.path
import clang.cindex as cindex

app = Flask('codeviewer')
codeviewer = None


class CodeViewer:
    def __init__(self, input_dir, clang_args, libclang_path=None):
        if libclang_path:
            cindex.Config.set_library_path(libclang_path)

        self.input_dir = input_dir
        self.index = cindex.Index.create()
        self.tus = {}

        self.abs_sources = get_source_file_list(self.input_dir)
        self.sources = [os.path.relpath(f, self.input_dir)
                        for f in self.abs_sources]
        self.filenames_to_ids = {src: i for i, src in enumerate(self.sources)}
        self.ids = set(range(len(self.sources)))

        def parse_tu(src):
            if not is_header(src):
                return self.index.parse(src, args=clang_args)
            return self.index.parse(
                src, args=clang_args,
                options=cindex.TranslationUnit.PARSE_INCOMPLETE)

        self.tus = {rel: parse_tu(src)
                    for rel, src in zip(self.sources, self.abs_sources)}

        self.usrs = find_all_usrs(self.tus, self.sources)

    def id_to_filename(self, idx):
        return self.sources[idx]

    def filename_to_id(self, idx):
        return self.filenames_to_ids[idx]

    def read_source(self, src):
        """Return the contents of the given source file."""
        with open(os.path.join(self.input_dir, src), 'r') as f:
            return f.read()

    def get_tu_from_id(self, idx):
        return self.tus[self.id_to_filename(idx)]

    def id_to_abs_filename(self, idx):
        return self.abs_sources[idx]

    def get_all_diagnostics(self):
        """Collect all diagnostics across translation units.

        The return value is a dictionary mapping from file ID to a set of
        Diagnostic objects. Diagnostics occurring in files that are not indexed
        are ignored. Duplicate diagnostics are ignored.
        """

        diags = {}
        for tu in self.tus.itervalues():
            for diag in tu.diagnostics:
                if diag.location.file is None:
                    continue

                filename = diag.location.file.name
                if filename not in self.abs_sources:
                    continue

                if filename not in diags:
                    diags[filename] = set()
                diags[filename].add(diag)

        return diags


class ClangEncoder(json.JSONEncoder):
    """JSON encoder for clang cindex objects."""
    def __init__(self, rel_dir):
        json.JSONEncoder.__init__(self)
        self.rel_dir = rel_dir

    def default(self, obj):
        if isinstance(obj, cindex.File):
            return os.path.relpath(obj.name, self.rel_dir)

        if isinstance(obj, cindex.SourceRange):
            return {
                'start': self.default(obj.start),
                'end': self.default(obj.end),
            }

        if isinstance(obj, cindex.SourceLocation):
            return {
                'file': self.default(obj.file),
                'line': obj.line,
                'column': obj.column,
            }

        if isinstance(obj, cindex.Diagnostic):
            severity_strs = {
                cindex.Diagnostic.Ignored: 'Ignored',
                cindex.Diagnostic.Note: 'Note',
                cindex.Diagnostic.Warning: 'Warning',
                cindex.Diagnostic.Error: 'Error',
                cindex.Diagnostic.Fatal: 'Fatal',
            }
            js = {
                'severity': severity_strs[obj.severity],
                'location': self.default(obj.location),
                'spelling': obj.spelling
            }

            ranges = [self.default(r) for r in obj.ranges]
            if ranges:
                js['ranges'] = ranges

            return js

        return json.JSONEncoder.default(self, obj)


@app.route('/api/sources')
def api_sources():
    sources = [{'id': codeviewer.filename_to_id(f), 'filename': f}
               for f in codeviewer.sources]
    js = json.dumps(sources)
    resp = Response(js, mimetype='application/json')
    return resp


@app.route('/api/sources/<idx>')
def api_show_source(idx):
    idx = int(idx)
    try:
        filename = codeviewer.id_to_filename(idx)
    except:
        raise NotFound()

    obj = {
        'filename': filename,
        'id': idx,
        'contents': codeviewer.read_source(filename),
    }

    abs_filename = codeviewer.id_to_abs_filename(idx)
    try:
        diags = list(codeviewer.get_all_diagnostics()[abs_filename])
    except KeyError:
        diags = []
    if diags:
        obj['diagnostics'] = diags

    try:
        tu = codeviewer.get_tu_from_id(idx)
    except KeyError:
        tu = None

    if tu:
        extent = tu.get_extent(abs_filename, (0, len(obj['contents'])))
        tokens = []
        for token in tu.get_tokens(extent=extent):
            tokens.append({
                'extent': token.extent,
                'spelling': token.spelling,
                'kind': token.kind.name,
            })
        obj['tokens'] = tokens

    js = ClangEncoder(codeviewer.input_dir).encode(obj)
    resp = Response(js, mimetype='application/json')
    return resp


@app.route('/api/usrs')
def api_usrs():
    usrs = {usr: node.displayname for usr, node in codeviewer.usrs.iteritems()}
    js = json.dumps({'usrs': usrs})
    resp = Response(js, mimetype='application/json')
    return resp


@app.route('/api/usrs/usr/<usr>')
def api_show_usr(usr):
    node = codeviewer.usrs[usr]
    nodeobj = {
        'usr': usr,
        'displayname': node.displayname,
        'extent': node.extent
    }
    js = ClangEncoder(codeviewer.input_dir).encode({'node': nodeobj})
    resp = Response(js, mimetype='application/json')
    return resp


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
    parser.add_argument('--clang-path',
                        type=str,
                        help='the directory where libclang lives.',
                        default=None)
    args = parser.parse_args(our_args)

    if not os.path.exists(args.input_dir):
        errmsg = 'Error: The input directory, "{}", does not exist.\n'
        sys.stderr.write(errmsg.format(args.input_dir))
        return -1

    global codeviewer
    codeviewer = CodeViewer(args.input_dir, clang_args, args.clang_path)

    app.debug = True
    app.run()

if __name__ == '__main__':
    sys.exit(main(sys.argv))
