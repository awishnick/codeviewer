angular.module('codeviewer', ['services'])
    .config(function($routeProvider) {
        $routeProvider
            .when('/sources', {
                controller: SourcesListCtrl,
                templateUrl: 'tpl/sources.html'})
            .when('/sources/:sourceId', {
                controller: SourceViewCtrl,
                templateUrl: 'tpl/source_view.html'})
            .otherwise({redirectTo:'/sources'});
    });

function SourcesListCtrl($scope, Sources) {
    $scope.sources = Sources.query();
}

function SourceViewCtrl($scope, $location, $routeParams, Sources) {
    Sources.get({id: $routeParams.sourceId}, function(source) {
        $scope.source = source;
    });
}
