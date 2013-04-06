angular.module('codeviewer', ['services'])
    .config(function($routeProvider) {
        $routeProvider
            .when('/sources', {
                controller: SourcesListCtrl,
                templateUrl: 'tpl/sources.html'})
            .when('/sources/:sourceId', {
                controller: SourceViewCtrl,
                templateUrl: 'tpl/sources.html'})
            .otherwise({redirectTo:'/sources'});
    })
    ;

function SourcesListCtrl($scope, Sources) {
    $scope.sources = Sources.query();
}

var entityMap = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': '&quot;',
    "'": '&#39;',
    "/": '&#x2F;'
};

function escapeHtml(string) {
    return String(string).replace(/[&<>"'\/]/g, function (s) {
        return entityMap[s];
    });
}

function generateEscapeHtmlAnnotations(lines) {
    var annotations = [];
    for (var i = 0; i < lines.length; i++) {
        curline = lines[i];
        linelen = curline.length;
        for(html in entityMap) {
            var pos = curline.indexOf(html);
            while (pos != -1) {
                annotations.push({
                    line: i,
                    col: pos,
                    replace: entityMap[html],
                    len: html.length
                });
                pos = curline.indexOf(html, pos+1);
            }
        }
    }
    return annotations;
}

// Convert token objects to insertions at specified
// lines and columns.
function tokensToAnnotations(tokens) {
    if (!tokens) {
        return [];
    }
    var kindToClass = {
        "KEYWORD": "codeview-keyword",
        "COMMENT": "codeview-comment",
        "LITERAL": "codeview-literal"
    };
    var annotations = [];
    tokens.forEach(function(token) {
        start = token.extent.start;
        end = token.extent.end;
        if (token.kind in kindToClass) {
            css_class = kindToClass[token.kind];

            annotations.push({
                line: start.line-1,
                col: start.column-1,
                insert: '<span class="' + css_class + '">'
            });
            annotations.push({
                line: end.line-1,
                col: end.column-1,
                insert: '</span>'
            });
        }
    });
    return annotations;
}

// Sorts annotations in descending (line, col).
function sortAnnotations(annotations) {
    annotations.sort(function(a, b) {
        if (a.line != b.line) {
            return b.line - a.line;
        }
        if (a.col != b.col) {
            return b.col - a.col;
        }
        // Do replacements before insertions, so we don't
        // replace the insertion!
        if ("insert" in a != "insert" in b) {
            return ("insert" in a) - ("insert" in b);
        }
        return 0;
    });
    return annotations;
}

function formatSource(src, tokens) {
    var lines = src.split(/\r?\n/);

    var token_annotations = tokensToAnnotations(tokens);
    var html_annotations = generateEscapeHtmlAnnotations(lines);

    annotations = sortAnnotations(token_annotations.concat(html_annotations));

    annotations.forEach(function(annotation) {
        line_idx = annotation.line;
        col_idx = annotation.col;
        if (line_idx < lines.length) {
            curline = lines[line_idx];

            if ("insert" in annotation) {
                insertion = annotation.insert;

                newline = curline.slice(0, col_idx) + insertion +
                          curline.slice(col_idx);
                lines[line_idx] = newline;
            } else if ("replace" in annotation) {
                replacement = annotation.replace;
                remove_len = annotation.len;

                newline = curline.slice(0, col_idx) + replacement +
                          curline.slice(col_idx+remove_len);
                lines[line_idx] = newline;
            }
        }
    });

    fmt = '';
    for (var i = 0; i < lines.length; i++) {
        fmt += lines[i] + '<br />\n';
    }

    fmt = '<div class="codeview">' + fmt + '</span>';
    return fmt;
}

function SourceViewCtrl($scope, $location, $routeParams, Sources) {
    $scope.sources = Sources.query();
    Sources.get({id: $routeParams.sourceId}, function(source) {
        $scope.source = source;
        $scope.formattedSource = formatSource(
            source.contents, source.tokens);
    });
}
