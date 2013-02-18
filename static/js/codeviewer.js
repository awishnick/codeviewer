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
    });

function SourcesListCtrl($scope, Sources) {
    $scope.sources = Sources.query();
}

function SourceViewCtrl($scope, $location, $routeParams, Sources) {
    $scope.sources = Sources.query();
    Sources.get({id: $routeParams.sourceId}, function(source) {
        $scope.source = source;
    });
}
