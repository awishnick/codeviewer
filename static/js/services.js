angular.module('services', ['ngResource'])
    .factory('Sources', function($resource) {
        var Sources = $resource('/api/sources/:id', {}, {
        });

        return Sources;
    });
