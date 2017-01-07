$(function() {
    route();
    replaceImdbImages();

    $('body').on('mouseover', '.star.open', openStarMouseover);
    $('body').on('mouseout', '.star.open', openStarMouseout);
});

function route() {
    var routes = {
        '/curate': curate,
        '/discover': discover,
        '/filter': filter,
        '/reviewer/[^/]+$': reviewer,
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

function reviewer() {
    $('a.ajax-movie-control').on('click', reviewerAjaxMovieControlClick);
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

    $('img').on('omdb-response', populateMovieInfo);
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

function populateMovieInfo(e, r) {
    $('#movie-country').text('Country: ' + r.Country);
    $('#movie-duration').text('Runtime: ' + r.Runtime);
    $('#movie-plot').text(r.Plot);
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

function reviewerAjaxMovieControlClick(e) {
    e.preventDefault();

    var $a = $(e.target).closest('a');
    var href = $a.attr('href');

    var $movie = $a.closest('.movie');
    var movieId = $movie.data('movie-id');
    var reviewerId = $('#wrapper').data('reviewer-id');
    var url = '/movie/' + movieId + '/ajax/reviewer/' + reviewerId;

    $a.addClass('selected');

    $.get(href, function() {
        $.get(url, function(html) {
            console.log(html);
            $movie.replaceWith(html);
            replaceImdbImages();
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

function replaceImdbImages() {
    $('.imdb-image').on('omdb-response', handleOmdbResponse);
    $('.imdb-image').each(replaceImdbImage);
}

function handleOmdbResponse(e, r) {
    var $el = $(e.target);
    var imageUrl = r['Poster'];
    $el.attr('src', imageUrl);

    var title = $el.attr('title');

    title += '\n' + r.Country + ', ' + r.Year + '\n' +
        r.Runtime + '\n\n' + r.Plot;

    $el.attr('title', title);
}

function replaceImdbImage(i, el) {
    var $el = $(el);
    var imdbId = $el.data('imdb-id');
    $.getJSON('http://www.omdbapi.com',
              {i: 'tt' + imdbId,
               plot: 'short',
               r: 'json'}, function(r) {
                   $el.trigger('omdb-response', [r])
               });

    $el.removeClass('imdb-image');
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
