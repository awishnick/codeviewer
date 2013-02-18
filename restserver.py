#!/usr/bin/env python
from flask import Flask, Response, json
from codeviewer import split_args, get_source_file_list, is_header, \
    find_all_usrs
import argparse
import sys
import os.path
import clang.cindex as cindex

app = Flask('codeviewer')
codeviewer = None


class CodeViewer:
    def __init__(self, input_dir, clang_args):
        self.input_dir = input_dir
        self.index = cindex.Index.create()
        self.tus = {}

        self.abs_sources = get_source_file_list(self.input_dir)
        self.sources = [os.path.relpath(f, self.input_dir)
                        for f in self.abs_sources]

        self.tus = {rel: self.index.parse(src, args=clang_args)
                    for rel, src in zip(self.sources, self.abs_sources)
                    if not is_header(rel)}

        self.usrs = find_all_usrs(self.tus, self.sources)


@app.route('/sources')
def api_sources():
    js = json.dumps({'sources': codeviewer.sources})
    resp = Response(js, mimetype='application/json')
    return resp


@app.route('/usrs')
def api_usrs():
    usrs = {usr: node.displayname for usr, node in codeviewer.usrs.iteritems()}
    js = json.dumps({'usrs': usrs})
    resp = Response(js, mimetype='application/json')
    return resp


@app.route('/usrs/usr/<usr>')
def show_usr(usr):
    class ClangEncoder(json.JSONEncoder):
        rel_dir = codeviewer.input_dir

        def default(self, obj):
            if isinstance(obj, cindex.SourceRange):
                return {
                    'start': self.default(obj.start),
                    'end': self.default(obj.end),
                }
            if isinstance(obj, cindex.SourceLocation):
                return {
                    'filename': os.path.relpath(obj.file.name,
                                                ClangEncoder.rel_dir),
                    'line': obj.line,
                    'column': obj.column,
                }

            return json.JSONEncoder.default(self, obj)
    node = codeviewer.usrs[usr]
    nodeobj = {
        'usr': usr,
        'displayname': node.displayname,
        'extent': node.extent
    }
    js = json.dumps({'node': nodeobj}, cls=ClangEncoder)
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
    args = parser.parse_args(our_args)

    if not os.path.exists(args.input_dir):
        errmsg = 'Error: The input directory, "{}", does not exist.\n'
        sys.stderr.write(errmsg.format(args.input_dir))
        return -1

    global codeviewer
    codeviewer = CodeViewer(args.input_dir, clang_args)

    app.debug = True
    app.run()

if __name__ == '__main__':
    sys.exit(main(sys.argv))
