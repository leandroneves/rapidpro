module.exports = function(grunt) {
    grunt.initConfig({
        cssmin: {
            options: {
                mergeIntoShorthands: false,
                roundingPrecision: -1
            },
            target: {
                files: [{
                    expand: true,
                    cwd: 'sitestatic/CACHE/css',
                    src: ['*.css', '!*.min.css'],
                    dest: 'sitestatic/CACHE/css',
                }]
            },
        },
        uglify: {
            'sitestatic/bower/jquery/jquery.js': ['sitestatic/bower/jquery/jquery.js'],
            'sitestatic/bower/jquery-migrate/jquery-migrate.min.js': ['sitestatic/bower/jquery-migrate/jquery-migrate.min.js'],
            'sitestatic/lib/angular-file-upload-1.6.12/angular-file-upload-shim.js': ['sitestatic/lib/angular-file-upload-1.6.12/angular-file-upload-shim.js'],
            'sitestatic/bower/angular/angular.js': ['sitestatic/bower/angular/angular.js'],
            'sitestatic/bower/angular-animate/angular-animate.js': ['sitestatic/bower/angular-animate/angular-animate.js'],
            'sitestatic/lib/angular-file-upload-1.6.12/angular-file-upload.js': ['sitestatic/lib/angular-file-upload-1.6.12/angular-file-upload.js'],
            'sitestatic/js/libs/jquery.url.js': ['sitestatic/js/libs/jquery.url.js'],
            'sitestatic/js/excellent.js': ['sitestatic/js/excellent.js'],
        }
    });

    grunt.loadNpmTasks('grunt-contrib-cssmin');
    grunt.loadNpmTasks('grunt-contrib-uglify');
    grunt.registerTask('default', ['cssmin', 'uglify']);
};