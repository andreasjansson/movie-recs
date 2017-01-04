$(function() {
    route();
    replaceImdbImages();
});

function route() {
    var routes = {
        '/': index,
        '/tune': tune,
        '/reviewer/[0-9]+': reviewer
    }

    for (key in routes) {
        var pattern = new RegExp('^' + key + '$');
        if (pattern.test(location.pathname)) {
            routes[key]();
            break;
        }
    }
}

function index() {
    $('#title-year').autocomplete({
        serviceUrl: '/autocomplete/titles',
        onSelect: function (suggestion) {
            $('#add-movie-form').submit()
        }
    });
}

function tune() {
    setupRatingSlider();
    setupNumReviewsSlider();
    setupYearSlider();
    setupGenres();
}

function reviewer() {
    setupRatingSlider();
    setupYearSlider();
    setupGenres();

    var $minReviews = $('#min-reviews');
    var $maxReviews = $('#max-reviews');
    $minReviews.attr('readonly', 'readonly');
    $maxReviews.attr('readonly', 'readonly');
}

function replaceImdbImages() {
    $('.imdb-image').each(replaceImdbImage);
}

function replaceImdbImage(i, el) {
    var $el = $(el);
    var imdbId = $el.data('imdb-id');
    $.getJSON('http://www.omdbapi.com',
              {i: 'tt' + imdbId,
               plot: 'short',
               r: 'json'},
              function(ret) {
                  var imageUrl = ret['Poster'];
                  $el.attr('src', imageUrl);
              });
}

function setupRatingSlider() {
    var $minRating = $('#min-rating');
    var $maxRating = $('#max-rating');
    var $slider = $("#rating-slider");
    $slider.slider({
        range: true,
        min: 5,
        max: 50,
        values: [$minRating.val() * 10, $maxRating.val() * 10],
        slide: function(event, ui) {
            $minRating.val(ui.values[0] / 10);
            $maxRating.val(ui.values[1] / 10);
        }
    });

    $minRating.attr('readonly', 'readonly');
    $maxRating.attr('readonly', 'readonly');
}

function setupNumReviewsSlider() {

    var $minReviews = $('#min-reviews');
    var $maxReviews = $('#max-reviews');
    var $slider = $("#reviews-slider");
    $slider.slider({
        range: true,
        min: 1,
        max: 20,
        values: [$minReviews.val(), $maxReviews.val()],
        slide: function(event, ui) {
            $minReviews.val(ui.values[0]);
            $maxReviews.val(ui.values[1]);
        }
    });

    $minReviews.attr('readonly', 'readonly');
    $maxReviews.attr('readonly', 'readonly');
}

function setupYearSlider() {
    var $minYear = $('#min-year');
    var $maxYear = $('#max-year');
    var $slider = $("#year-slider");
    $slider.slider({
        range: true,
        min: 1891,
        max: 2015,
        values: [$minYear.val(), $maxYear.val()],
        slide: function(event, ui) {
            $minYear.val(ui.values[0]);
            $maxYear.val(ui.values[1]);
        }
    });

    $minYear.attr('readonly', 'readonly');
    $maxYear.attr('readonly', 'readonly');
}

function setupGenres() {
    var $genreInputs = $('#genres input');

    var anyGenresChecked = function() {
        return $('#genres input:checked').length > 0;
    }

    var checkGenreButtonsState = function() {
        if (anyGenresChecked()) {
            $a.text('Disable all genres');
        } else {
            $a.text('Enable all genres');
        }
        return true;
    };

    var $a = $('#check-all-genres');

    $a.click(function() {
        if (anyGenresChecked()) {
            $genreInputs.removeAttr('checked');
        } else {
            $genreInputs.prop('checked', true);
        }
        checkGenreButtonsState();
    });

    $genreInputs.on('click', checkGenreButtonsState);
}
