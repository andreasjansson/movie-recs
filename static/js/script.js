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
        '/critic/[^/]+$': critic,
        '/movie/[^/]+$': movie
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

function curate() {
    $('#title-year').autocomplete({
        serviceUrl: '/autocomplete/titles',
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
    $('input').click(submitFilterForm);
}

function movie() {
    $('a.ajax-movie-control').on('click', ajaxMovieControlClickRefresh);
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
    setTimeout(function() { $movie.parent().remove(); }, 200);

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
    });

    $inputs.on('click', checkButtonsState);

    checkButtonsState();
}

function submitFilterForm() {
    var $form = $('#form');
    $.post('/filter', $form.serialize());
}
