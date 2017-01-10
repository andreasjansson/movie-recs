$(function() {
    route();

    $('body').on('mouseover', '.star.open', openStarMouseover);
    $('body').on('mouseout', '.star.open', openStarMouseout);
});

function route() {
    var routes = {
        '/curate': curate,
        '/discover': discover,
        '/filter': filter,
        '/critic/[^/]+': critic,
        '/movie/[^/]+': movie,
        '/search': search,
        '/director/[^/]+': director,
        '/actor/[^/]+': actor
    }

    for (key in routes) {
        var pattern = new RegExp('^' + key + '$');
        if (pattern.test(location.pathname)) {
            routes[key]();
            break;
        }
    }
}

function discover() {
    $('a.ajax-movie-control').on('click', discoverAjaxMovieControlClick);
}

function critic() {
    $('a.ajax-movie-control').on('click', criticAjaxMovieControlClick);
}

function director() {
    $('a.ajax-movie-control').on('click', directorAjaxMovieControlClick);
}

function actor() {
    $('a.ajax-movie-control').on('click', directorAjaxMovieControlClick);
}

function curate() {
    $('#title-year').autocomplete({
        serviceUrl: '/autocomplete/titles',
        deferRequestsBy: 100,
        onSelect: function (suggestion) {
            $('#add-movie-form').submit()
        }
    });
}

function filter() {
    setupEnableAll($('#genres'));
    setupEnableAll($('#decades'));
    setupEnableAll($('#ratings'));
    $('#submit').hide();
    $('input[type=checkbox]').click(submitFilterForm);
}

function movie() {
    $('a.ajax-movie-control').on('click', ajaxMovieControlClickRefresh);
    $('#show-full-plot').on('click', function() {
        $('#movie-plot').hide();
        $('#movie-plot-long').show();
        return false;
    });
}

function search() {
    $('#title-year').autocomplete({
        serviceUrl: '/autocomplete/titles',
        deferRequestsBy: 100,
        onSelect: function (suggestion) {
            $('#title-form').submit()
        }
    });
    $('#director-input').autocomplete({
        serviceUrl: '/autocomplete/directors',
        deferRequestsBy: 100,
        onSelect: function (suggestion) {
            $('#director-form').submit()
        }
    });
    $('#actor-input').autocomplete({
        serviceUrl: '/autocomplete/actors',
        deferRequestsBy: 100,
        onSelect: function (suggestion) {
            $('#actor-form').submit()
        }
    });
    $('#critic-input').autocomplete({
        serviceUrl: '/autocomplete/critics',
        deferRequestsBy: 100,
        onSelect: function (suggestion) {
            $('#critic-form').submit()
        }
    });
}

function openStarMouseover(e) {
    var $star = $(e.target);
    var rating = $star.data('rating')
    var $wrapper = $star.closest('.stars');
    var $stars = $wrapper.find('.star');
    $stars.each(function(i, el) {
        var $s = $(el);
        if ($s.data('rating') <= rating) {
            $s.attr('src', '/images/star.png');
        }
    });
}

function openStarMouseout(e) {
    var $star = $(e.target);
    var rating = $star.data('rating')
    var $wrapper = $star.closest('.stars');
    var $stars = $wrapper.find('.star');
    $stars.attr('src', '/images/star-open.png');
}

function discoverAjaxMovieControlClick(e) {
    e.preventDefault();

    var $a = $(e.target).closest('a');
    var href = $a.attr('href');
    $.get(href);

    var $movie = $a.closest('.movie');

    $a.addClass('selected');
    setTimeout(function() {
        $movie.parent().remove();

        console.log($('#discover-movies .movie').length);

        if ($('#discover-movies .movie').length == 0) {
            location.reload();
        };
    }, 200);

    return false;
}

function criticAjaxMovieControlClick(e) {
    e.preventDefault();

    var $a = $(e.target).closest('a');
    var href = $a.attr('href');

    var $movie = $a.closest('.movie');
    var movieId = $movie.data('movie-id');
    var criticId = $('#wrapper').data('critic-id');
    var url = '/movie/' + movieId + '/ajax/critic/' + criticId;

    $a.addClass('selected');

    $.get(href, function() {
        $.get(url, function(html) {
            console.log(html);
            $movie.replaceWith(html);
        });
    });

    return false;
}

function directorAjaxMovieControlClick(e) {
    e.preventDefault();

    var $a = $(e.target).closest('a');
    var href = $a.attr('href');

    var $movie = $a.closest('.movie');
    var movieId = $movie.data('movie-id');
    var url = '/movie/' + movieId + '/ajax/user';

    $a.addClass('selected');

    $.get(href, function() {
        $.get(url, function(html) {
            console.log(html);
            $movie.replaceWith(html);
        });
    });

    return false;
}

function ajaxMovieControlClickRefresh(e) {
    var $a = $(e.target).closest('a');
    var href = $a.attr('href');

    $a.addClass('selected');

    $.get(href, function() {
        location.reload();
    });

    return false;
}

function setupEnableAll($div) {
    var $inputs = $('input', $div);

    var $a = $('.enable-disable-all', $div);

    var anyChecked = function() {
        return $('input:checked', $div).length > 0;
    }

    var checkButtonsState = function() {
        if (anyChecked()) {
            $a.text('Disable all');
        } else {
            $a.text('Enable all');
        }
        return true;
    };

    $a.click(function() {
        if (anyChecked()) {
            $inputs.removeAttr('checked');
        } else {
            $inputs.prop('checked', true);
        }
        checkButtonsState();

        submitFilterForm();

        return false;
    });

    $inputs.on('click', checkButtonsState);

    checkButtonsState();
}

function submitFilterForm() {
    var $form = $('#form');
    $.post('/filter', $form.serialize());
}
