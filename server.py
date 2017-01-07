import os
import datetime
import bcrypt
from functools import wraps
from glob import glob
import MySQLdb
import time
from bidict import bidict
import random
import re
from collections import namedtuple, defaultdict, OrderedDict
import cPickle
from flask import (
    Flask, session, redirect, url_for, request, render_template, g, jsonify
)

app = Flask(__name__, static_url_path='')
app.secret_key = 'super super secret key'

SALT = 'super super secret salt'
NUM_SIMILAR_REVIEWERS = 25
NUM_RECOMMENDED_MOVIES = 24

last_update_time = 0


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        t = time.time()
        g._database = db = MySQLdb.connect('localhost', db='movie_recs', charset='utf8')
        db.autocommit(True)
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def read_title_cache():
    with open('titles.cpkl') as f:
        return cPickle.load(f)


def read_names():
    names = []
    with open('names.txt') as f:
        for line in f:
            names.append(line.strip())

    return names


cached_titles = read_title_cache()
reviewer_names = read_names()
avatars = [os.path.basename(a) for a in glob('static/images/avatars/*.png')]


all_genres = [
    'drama',
    'comedy',
    'thriller',
    'romance',
    'action',
    'crime',
    'horror',
    'documentary',
    'adventure',
    'sci-fi',
    'mystery',
    'fantasy',
    'war',
    'children',
    'musical',
    'animation',
    'western',
    'film-noir',
]
all_decades = range(1890, 2020, 10)


def object_cache(f):
    @wraps(f)
    def wrapper(self, *args, **kwargs):
        if not hasattr(self, '_object_cache'):
            self._object_cache = {}

        key = (f.__name__, tuple(args), tuple(kwargs.items()))
        if key in self._object_cache:
            return self._object_cache[key]

        ret = f(self, *args, **kwargs)
        self._object_cache[key] = ret

        return ret
    return wrapper


class User(namedtuple('User', 'id username')):

    @object_cache
    def load_latest_rating_time(self):
        cursor = get_db().cursor()
        cursor.execute('''
            SELECT date_added
            FROM user_rating
            WHERE user_id = %s
            ORDER BY date_added DESC
        ''', (self.id, ))
        row = cursor.fetchone()
        if not row:
            return 0
        date_added = timestamp_to_int(row[0])
        return int(date_added)

    @object_cache
    def load_ratings(self):
        cursor = get_db().cursor()
        cursor.execute('''
            SELECT movie_id, rating
            FROM user_rating
            WHERE user_id = %s
            ORDER BY date_added DESC
        ''', (self.id, ))
        ratings = OrderedDict()
        for movie_id, rank in cursor.fetchall():
            ratings[movie_id] = rank
        return ratings

    @object_cache
    def load_similar_reviewers(self):
        cursor = get_db().cursor()
        cursor.execute('''
            SELECT reviewer_id, similarity
            FROM user_similar_reviewer
            WHERE user_id = %s
            ORDER BY similarity DESC
        ''', (self.id, ))
        return [Reviewer(reviewer_id, similarity)
                for reviewer_id, similarity in cursor]

    @object_cache
    def load_skips(self):
        cursor = get_db().cursor()
        cursor.execute('''
            SELECT movie_id
            FROM user_skip
            WHERE user_id = %s
            ORDER BY date_skipped DESC
        ''', (self.id, ))
        return [row[0] for row in cursor]

    @object_cache
    def load_saves(self):
        cursor = get_db().cursor()
        cursor.execute('''
            SELECT movie_id
            FROM user_save
            WHERE user_id = %s
            ORDER BY date_saved DESC
        ''', (self.id, ))
        return [row[0] for row in cursor]

    def rate_movie_id(self, movie_id, rating):
        cursor = get_db().cursor()
        cursor.execute('''
            INSERT INTO user_rating (user_id, movie_id, rating)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE rating = %s
        ''', (self.id, movie_id, rating, rating))

    def save_movie_id(self, movie_id):
        cursor = get_db().cursor()
        cursor.execute('''
            INSERT INTO user_save (user_id, movie_id)
            VALUES (%s, %s)
        ''', (self.id, movie_id))

    def skip_movie_id(self, movie_id):
        cursor = get_db().cursor()
        cursor.execute('''
            INSERT INTO user_skip (user_id, movie_id)
            VALUES (%s, %s)
        ''', (self.id, movie_id))

    def unsave_movie_id(self, movie_id):
        cursor = get_db().cursor()
        cursor.execute('''
            DELETE FROM user_save
            WHERE user_id = %s AND movie_id = %s
        ''', (self.id, movie_id))

    def unskip_movie_id(self, movie_id):
        cursor = get_db().cursor()
        cursor.execute('''
            DELETE FROM user_skip
            WHERE user_id = %s AND movie_id = %s
        ''', (self.id, movie_id))

    def unrate_movie_id(self, movie_id):
        cursor = get_db().cursor()
        cursor.execute('''
            DELETE FROM user_rating
            WHERE user_id = %s AND movie_id = %s
        ''', (self.id, movie_id))

    def load_reviewer_by_id(self, reviewer_id):
        cursor = get_db().cursor()
        cursor.execute('''
            SELECT similarity
            FROM user_similar_reviewer
            WHERE user_id = %s
            AND reviewer_id = %s
        ''', (self.id, reviewer_id))
        row = cursor.fetchone()
        if row:
            return Reviewer(reviewer_id, row[0])
        else:
            return Reviewer(reviewer_id, None)

    def update_similar_reviewers(self, count=NUM_SIMILAR_REVIEWERS):
        cursor = get_db().cursor()

        sql = '''
            SELECT reviewer_id,
                AVG(POWER(5 - ABS(r.rating - ur.rating), 2))
                    * POWER(COUNT(*), 1/10.)
            FROM review r
            JOIN user_rating ur
            ON r.movie_id = ur.movie_id
            WHERE user_id = %s
            GROUP BY reviewer_id
            ORDER by 2 DESC
            LIMIT %s;
        '''

        t = time.time()
        cursor.execute(sql, (self.id, count))
        rows = cursor.fetchall()

        print 'updated reviewer %d (%s) in %.2f seconds' % (self.id, self.username, time.time() - t)

        cursor.execute('''
            DELETE FROM user_similar_reviewer
            WHERE user_id = %s
        ''', (self.id, ))

        for reviewer_id, score in rows:
            cursor.execute('''
                INSERT INTO user_similar_reviewer
                    (user_id, reviewer_id, similarity)
                VALUES (%s, %s, %s)
            ''', (self.id, reviewer_id, score))

        cursor.execute('''
            DELETE FROM user_similar_reviewer_review
            WHERE user_id = %s
        ''', (self.id, ))

        cursor.execute('''
            INSERT INTO user_similar_reviewer_review
            SELECT %s, reviewer_id, movie_id, rating
            FROM review
            WHERE reviewer_id IN (
                SELECT reviewer_id
                FROM user_similar_reviewer
                WHERE user_id = %s
            )
        ''', (self.id, self.id))


class Movie(namedtuple('Movie', [
        'id',
        'year',
        'title',
        'imdb_id',
        'user_rating',
        'reviewer_rating',
        'mean_rating',
        'num_ratings',
        'saved',
        'skipped',
        'reviews',
        'reviewers',
])):

    def __new__(self, id, year, title, imdb_id,
                user_rating=None, reviewer_rating=None, mean_rating=None,
                num_ratings=None, saved=False, skipped=False,
                reviews=None, reviewers=None):

        if reviews:
            num_ratings = len(reviews)
            mean_rating = sum(reviews.values()) / float(len(reviews.values()))
            reviewers = reviews.keys()

        return super(Movie, self).__new__(
            self, id, year, title, imdb_id,
            user_rating, reviewer_rating, mean_rating, num_ratings,
            saved, skipped, reviews, reviewers)

    def imdb_link(self):
        return 'http://www.imdb.com/title/tt%s/' % self.imdb_id


class Reviewer(namedtuple('Reviewer', ['id', 'similarity'])):

    def __new__(self, id, similarity=None):
        return super(Reviewer, self).__new__(self, id, similarity)

    def name(self):
        return reviewer_names[self.id % len(reviewer_names)].capitalize()

    def avatar(self):
        return avatars[self.id % len(avatars)]

    def hue(self):
        return self.id % 360


class MovieFilter(namedtuple('MovieFilter', [
        'genres',
        'decades',
        'stars',
])):

    def __new__(self, genres=None, decades=None, stars=None):
        if genres is None:
            genres = all_genres
        if decades is None:
            decades = all_decades
        if stars is None:
            stars = [4, 5]
        return super(MovieFilter, self).__new__(
            self, genres, decades, stars)

    def get_genre_sql(self):
        return 'genre IN (%s)' % (', '.join(['%s'] * len(self.genres)))

    def get_decade_sql(self):
        return 'FLOOR(year / 10) * 10 IN (%s)' % (
            ', '.join(['%s'] * len(self.decades)))

    def get_avg_rating_sql(self):
        return '(FLOOR(AVG(r.rating) + .5) IN (%s) OR AVG(r.rating) IS NULL)' % (
            ', '.join(['%s'] * len(self.stars)))


def timestamp_to_int(d):
    return time.mktime(d.timetuple())


def movie_filter_from_session():
    if 'movie_filter' in session:
        values = session['movie_filter']
        return MovieFilter(values[0], values[1], values[2])
    return MovieFilter()


def movie_filter_from_form(form):
    genres = form.getlist('genre')
    assert not set(genres) - set(all_genres)

    decades = [int(d) for d in form.getlist('decade')]
    assert not set(decades) - set(all_decades)

    stars = [int(s) for s in form.getlist('star')]
    assert not set(stars) - set(range(1, 6))

    return MovieFilter(genres=genres, decades=decades, stars=stars)


def load_movie_by_title_year(title, year):
    cursor = get_db().cursor()
    cursor.execute('''
        SELECT id, year, title, imdb_id
        FROM movie
        WHERE (title = %s OR translation = %s) AND year = %s
    ''', (title, title, year))

    row = cursor.fetchone()
    if not row:
        return None
    movie_id, title, year, imdb_id = row
    return Movie(id=movie_id, title=title, year=year, imdb_id=imdb_id)


def load_movie_for_user(movie_id, user):
    cursor = get_db().cursor()

    similar_reviewers_by_id = {r.id: r for r in user.load_similar_reviewers()}

    saves = user.load_saves()
    skips = user.load_skips()

    sql = '''
        SELECT m.id, title, year, imdb_id, ur.rating, r.reviewer_id, r.rating
        FROM movie m
        LEFT JOIN user_rating ur
        ON m.id = ur.movie_id
        AND ur.user_id = %s
        LEFT JOIN review r
        ON r.movie_id = m.id
        AND reviewer_id IN ({reviewers_placeholders})
        WHERE m.id = %s
    '''.format(
        reviewers_placeholders=', '.join(
            ['NULL'] + (['%s'] * (len(similar_reviewers_by_id)))),
    )

    args = [user.id] + similar_reviewers_by_id.keys() + [movie_id]

    cursor.execute(sql, args)
    rows = cursor.fetchall()

    if not rows:
        return None

    first = rows[0]
    movie_id, title, year, imdb_id, user_rating, _, _ = first

    reviews = OrderedDict(sorted([
        (similar_reviewers_by_id[reviewer_id], rating)
        for _, _, _, _, _, reviewer_id, rating in rows
        if reviewer_id is not None
    ], key=lambda x: x[0].similarity, reverse=True))

    saved = movie_id in saves
    skipped = movie_id in skips

    return Movie(id=movie_id, title=title, year=year, imdb_id=imdb_id,
                 user_rating=user_rating, saved=saved, skipped=skipped,
                 reviews=reviews)


def load_movie_for_reviewer(movie_id, reviewer_id, user):
    cursor = get_db().cursor()

    saves = user.load_saves()
    skips = user.load_skips()

    sql = '''
        SELECT m.id, title, year, imdb_id, ur.rating, r.rating
        FROM movie m
        JOIN review r
        ON r.movie_id = m.id
        AND reviewer_id = %s
        LEFT JOIN user_rating ur
        ON m.id = ur.movie_id
        AND ur.user_id = %s
        WHERE m.id = %s
    '''

    args = [reviewer_id, user.id, movie_id]

    cursor.execute(sql, args)
    row = cursor.fetchone()

    if not row:
        return None

    movie_id, title, year, imdb_id, user_rating, reviewer_rating = row

    return Movie(id=movie_id, title=title, year=year, imdb_id=imdb_id,
                 user_rating=user_rating, reviewer_rating=reviewer_rating,
                 saved=movie_id in saves and not user_rating,
                 skipped=movie_id in skips and not user_rating)


def load_movies_for_user(user, movie_filter, movie_ids):
    if not movie_ids:
        return []

    cursor = get_db().cursor()

    sql = '''
        SELECT id, title, year, imdb_id, ur.rating, AVG(r.rating), COUNT(DISTINCT reviewer_id), GROUP_CONCAT(reviewer_id, ',')
        FROM movie m
        LEFT JOIN user_similar_reviewer_review r
        ON r.movie_id = m.id
        AND r.user_id = %s
        LEFT JOIN user_rating ur
        ON m.id = ur.movie_id
        AND ur.user_id = %s
        JOIN movie2genre g
        ON g.movie_id = m.id
        WHERE m.id in ({movies_placeholders})
        AND {genre_filter}
        AND {decade_filter}
        GROUP BY m.id
    '''.format(
        genre_filter=movie_filter.get_genre_sql(),
        movies_placeholders=', '.join(['%s'] * len(movie_ids)),
        decade_filter=movie_filter.get_decade_sql(),
    )

    args = ([user.id] + [user.id] +
            movie_ids + movie_filter.genres + movie_filter.decades)

    cursor.execute(sql, args)

    return [
        Movie(
            id=movie_id, title=title, year=year, imdb_id=imdb_id,
            user_rating=user_rating, mean_rating=mean_rating,
            num_ratings=num_ratings,
            reviewers=[Reviewer(int(r))
                       for r in set(reviewers.split(','))
                       if r] if reviewers else []
        )
        for (movie_id, title, year, imdb_id, user_rating,
             mean_rating, num_ratings, reviewers)
        in cursor
    ]


def load_movies_for_reviewer(reviewer, user, movie_filter):
    cursor = get_db().cursor()

    saves = user.load_saves()
    skips = user.load_skips()

    sql = '''
        SELECT m.id, title, year, imdb_id, ur.rating, r.rating
        FROM movie m
        JOIN review r
        ON r.movie_id = m.id
        AND reviewer_id = %s
        LEFT JOIN user_rating ur
        ON m.id = ur.movie_id
        AND ur.user_id = %s
        JOIN movie2genre g
        ON g.movie_id = m.id
        WHERE {genre_filter}
        AND {decade_filter}
        GROUP BY m.id
        ORDER BY r.rating DESC, title
        LIMIT 500
    '''.format(
        genre_filter=movie_filter.get_genre_sql(),
        decade_filter=movie_filter.get_decade_sql(),
    )

    args = ([reviewer.id] + [user.id] +
            movie_filter.genres + movie_filter.decades)

    cursor.execute(sql, args)

    return [
        Movie(id=movie_id, title=title, year=year, imdb_id=imdb_id,
              user_rating=user_rating, reviewer_rating=reviewer_rating,
              saved=movie_id in saves and not user_rating,
              skipped=movie_id in skips and not user_rating
        )
        for movie_id, title, year, imdb_id, user_rating, reviewer_rating
        in cursor
    ]


def load_recommended_movies(user, movie_filter, limit=NUM_RECOMMENDED_MOVIES):
    cursor = get_db().cursor()

    excluded_movie_ids = (
        user.load_ratings().keys() +
        user.load_skips() +
        user.load_saves()
    )

    sql = '''
        SELECT id, title, year, imdb_id, ur.rating, AVG(r.rating), COUNT(DISTINCT reviewer_id), GROUP_CONCAT(reviewer_id, ',')
        FROM movie m
        JOIN user_similar_reviewer_review r
        ON r.movie_id = m.id
        AND r.user_id = %s
        LEFT JOIN user_rating ur
        ON m.id = ur.movie_id
        AND ur.user_id = %s
        JOIN movie2genre g
        ON g.movie_id = m.id
        WHERE m.id NOT IN ({movies_placeholders})
        AND {genre_filter}
        AND {decade_filter}
        GROUP BY m.id
        HAVING {avg_rating_filter}
        ORDER BY COUNT(DISTINCT reviewer_id) DESC
        LIMIT %s
    '''.format(
        movies_placeholders=', '.join(['%s'] * len(excluded_movie_ids)),
        genre_filter=movie_filter.get_genre_sql(),
        decade_filter=movie_filter.get_decade_sql(),
        avg_rating_filter=movie_filter.get_avg_rating_sql(),
    )

    args = (
        [user.id] +
        [user.id] +
        excluded_movie_ids +
        movie_filter.genres +
        movie_filter.decades +
        movie_filter.stars +
        [limit * 2]
    )

    cursor.execute(sql, args)

    movies = [
        Movie(id=movie_id, title=title, year=year, imdb_id=imdb_id,
              user_rating=user_rating, mean_rating=mean_rating,
              num_ratings=num_ratings,
              reviewers=[Reviewer(int(r))
                         for r in set(reviewers.split(',')) if r])
        for (movie_id, title, year, imdb_id, user_rating,
             mean_rating, num_ratings, reviewers)
        in cursor
    ]

    if len(movies) > limit:
        return random.sample(movies, limit)

    return movies


def load_user_by_id(user_id):
    cursor = get_db().cursor()
    cursor.execute('''
        SELECT username
        FROM user
        WHERE id = %s
    ''', (user_id, ))
    row = cursor.fetchone()
    if row:
        return User(user_id, row[0])
    raise NoSuchUser()


class NoSuchUser(Exception):
    pass


class BadPassword(Exception):
    pass


def load_user_by_username_and_password(username, password):
    cursor = get_db().cursor()
    cursor.execute('''
        SELECT id, password
        FROM user
        WHERE username = %s
    ''', (username, ))
    row = cursor.fetchone()
    if not row:
        raise NoSuchUser()
    user_id, hashed = row
    if bcrypt.hashpw(password.encode('utf-8'), hashed) != hashed:
        raise BadPassword()

    return User(user_id, username)


def create_user(username, password):
    cursor = get_db().cursor()
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    cursor.execute('''
        INSERT INTO user (username, password)
        VALUES (%s, %s)
    ''', (username, hashed))


def iter_users():
    cursor = get_db().cursor()
    cursor.execute('''
        SELECT id, username
        FROM user
    ''')
    for user_id, username in cursor:
        yield User(user_id, username)


def check_signed_in(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' in session:
            try:
                load_user_by_id(session['user_id'])
                return redirect(url_for('curate'))
            except NoSuchUser, BadPassword:
                del session['user_id']
        return f(*args, **kwargs)
    return wrapper


def require_user(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('index'))
        try:
            user = load_user_by_id(session['user_id'])
        except NoSuchUser:
            del session['user_id']
            return redirect(url_for('index'))
        return f(user, *args, **kwargs)
    return wrapper


@app.route('/')
@check_signed_in
def index():
    error = session.pop('error', None)
    username = session.pop('username', '')

    return render_template('index.html', error=error, username=username)


@app.route('/sign-in', methods=['POST'])
@check_signed_in
def sign_in():
    if 'username' not in request.form:
        session['error'] = 'Please enter a username'
        return redirect(url_for('index'))

    if 'password' not in request.form:
        session['error'] = 'Please enter a password'
        return redirect(url_for('index'))

    username = request.form['username']
    password = request.form['password']

    if len(username) > 512:
        session['error'] = 'Username must be shorter than 512 characters'
        session['username'] = username[:512]
        return redirect(url_for('index'))

    try:
        user = load_user_by_username_and_password(username, password)
    except BadPassword:
        session['error'] = 'Wrong password'
        session['username'] = username
        return redirect(url_for('index'))
    except NoSuchUser:
        create_user(username, password)
        user = load_user_by_username_and_password(username, password)

    session['user_id'] = user.id

    return redirect(url_for('curate'))


@app.route('/curate')
@require_user
def curate(user):
    movie_filter = movie_filter_from_session()
    rated_movie_ids = user.load_ratings().keys()
    skipped_movie_ids = user.load_skips()

    movies = load_movies_for_user(
        user, movie_filter,
        rated_movie_ids + skipped_movie_ids,
    )

    movies_by_id = {m.id: m for m in movies}

    rated_movies = [movies_by_id[movie_id] for movie_id in rated_movie_ids
                    if movie_id in movies_by_id]
    skipped_movies = [movies_by_id[movie_id]._replace(skipped=True)
                      for movie_id in skipped_movie_ids
                      if movie_id in movies_by_id]

    return render_template(
        'curate.html', user=user, movie_filter=movie_filter,
        rated_movies=rated_movies, skipped_movies=skipped_movies)


@app.route('/saves')
@require_user
def saves_view(user):
    movie_filter = movie_filter_from_session()
    saved_movie_ids = user.load_saves()

    movies = load_movies_for_user(
        user, movie_filter, saved_movie_ids
    )

    saved_movies = [
        m._replace(saved=True)
        for m in sorted(movies, key=lambda m: m.mean_rating, reverse=True)
    ]

    return render_template(
        'saves.html', user=user, movie_filter=movie_filter,
        saved_movies=saved_movies)


@app.route('/add-movie', methods=['POST'])
@require_user
def add_movie(user):
    title_year = request.form['title-year'].lower()
    match = re.match(r'^(.+) \(([0-9]{4})\)$', title_year)
    if not match:
        session['error'] = 'Title must be in the format "title (year)"'
        return redirect(url_for('curate'))

    title, year = match.groups()
    print title, year
    movie = load_movie_by_title_year(title, year)
    if not movie:
        session['error'] = '"%s (%s)" is not in the database' % (title, year)
        return redirect(url_for('curate'))

    user.rate_movie_id(movie.id, 5)

    return redirect(url_for('curate'))


@app.route('/autocomplete/titles')
def autocomplete_titles():
    query = request.args['query'].lower()
    matching_titles = sorted([t for t in cached_titles if query in t][:100],
                             key=lambda s: (len(s), s))
    return jsonify({
        'suggestions': [{'value': title} for title in matching_titles]
    })


@app.route('/discover')
@require_user
def discover(user):
    movie_filter = movie_filter_from_session()
    movies = load_recommended_movies(user, movie_filter)

    return render_template('discover.html', movies=movies, user=user)


@app.route('/movie/<int:movie_id>')
@require_user
def movie_view(user, movie_id):
    movie = load_movie_for_user(movie_id, user)
    return render_template('movie_view.html', movie=movie, user=user)


@app.route('/movie/<int:movie_id>/ajax/reviewer/<int:reviewer_id>')
@require_user
def movie_ajax_reviewer(user, movie_id, reviewer_id):
    movie = load_movie_for_reviewer(movie_id, reviewer_id, user)
    return render_template('movie.html', movie=movie, user=user)


@app.route('/movie/<int:movie_id>/rate')
@require_user
def rate(user, movie_id):
    rating = request.args['rating']
    user.rate_movie_id(movie_id, rating)
    return 'ok'


@app.route('/movie/<int:movie_id>/save')
@require_user
def save(user, movie_id):
    user.save_movie_id(movie_id)
    return 'ok'


@app.route('/movie/<int:movie_id>/skip')
@require_user
def skip(user, movie_id):
    user.skip_movie_id(movie_id)
    return 'ok'


@app.route('/movie/<int:movie_id>/unsave')
@require_user
def unsave(user, movie_id):
    user.unsave_movie_id(movie_id)
    return 'ok'


@app.route('/movie/<int:movie_id>/unskip')
@require_user
def unskip(user, movie_id):
    user.unskip_movie_id(movie_id)
    return 'ok'


@app.route('/movie/<int:movie_id>/unrate')
@require_user
def unrate(user, movie_id):
    user.unrate_movie_id(movie_id)
    return 'ok'


@app.route('/your25')
@require_user
def your25(user):
    reviewers = user.load_similar_reviewers()
    return render_template('your25.html', user=user, reviewers=reviewers)


@app.route('/reviewer/<int:reviewer_id>')
@require_user
def reviewer_view(user, reviewer_id):
    movie_filter = movie_filter_from_session()
    reviewer = user.load_reviewer_by_id(reviewer_id)
    movies = load_movies_for_reviewer(reviewer, user, movie_filter)

    return render_template('reviewer_view.html', user=user, reviewer=reviewer,
                           movies=movies)


@app.route('/filter')
@require_user
def filter_view(user):
    movie_filter = movie_filter_from_session()
    decades = all_decades
    return render_template('filter.html', user=user, filter=movie_filter,
                           genres=all_genres, decades=decades)


@app.route('/filter', methods=['POST'])
@require_user
def update_filter(user):
    movie_filter = movie_filter_from_form(request.form)
    session['movie_filter'] = movie_filter

    return 'ok'


@app.route('/update-similar-reviewers')
def update_similar_reviewers():
    if time.time() - last_update_time < 60:
        return 'wait'

    for user in iter_users():
        latest_rating_time = user.load_latest_rating_time()
        if latest_rating_time > time.time() - 60:
            user.update_similar_reviewers()

    return 'done'


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, threaded=True)
