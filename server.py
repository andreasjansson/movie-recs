from glob import glob
import MySQLdb
import time
from bidict import bidict
import urllib
import random
import base64
from scipy.stats import trim_mean
import numpy as np
import re
from collections import namedtuple, defaultdict
import cPickle
from flask import (
    Flask, redirect, url_for, request, render_template, g, jsonify
)

app = Flask(__name__, static_url_path='')
app.secret_key = 'super super secret key'

NUM_SIMILAR_USERS = 20


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        t = time.time()
        g._database = db = MySQLdb.connect('localhost', db='movie_recs', charset='utf8')
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

    num_names = len(names)
    user_names = bidict()
    for i in range(138493):
        name = names[i % num_names].capitalize()
        j = 0
        while True:
            if name not in user_names.inv:
                user_names[i] = name
                break
            j += (i % 26)
            name += ' %s' % chr(65 + ((i + j) % 26))
        else:
            print i

    return user_names


cached_titles = read_title_cache()
user_names = read_names()
avatars = glob('static/images/avatars/*.png')


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

#@app.route('/<path:path>')
#def static_proxy(path):
#    return app.send_static_file(path)


def decode_session(s):
    if s:
        try:
            return cPickle.loads(base64.b64decode(s))
        except Exception as e:
            print 'decode error', e
            return {}
    return {}


def encode_session(s):
    return base64.b64encode(cPickle.dumps(s, protocol=cPickle.HIGHEST_PROTOCOL))


def get_session():
    return decode_session(encoded_session())


def session_contains(key):
    session = get_session()
    return key in session


def session_get(key, default=None):
    session = get_session()
    return session.get(key, default)


def session_put(key, value):
    session = get_session()
    session[key] = value
    request.updated_session = encode_session(session)


def session_pop(key, default=None):
    session = get_session()
    ret = session.get(key, default)
    if key in session:
        del session[key]
        request.updated_session = encode_session(session)
    return ret


def session_delete(key):
    session = get_session()
    if key in session:
        del session[key]
        request.updated_session = encode_session(session)


def encoded_session():
    if hasattr(request, 'updated_session'):
        return request.updated_session
    return request.args.get('s', '')


def url_for_with_session(name, **kwargs):
    return url_for(name, s=encoded_session(), **kwargs)


def session_params():
    return {
        'session_param': urllib.urlencode({'s': encoded_session()})
    }


class Movie(namedtuple('Movie', [
        'id', 'year', 'title', 'translation', 'imdb_id', 'ratings'
])):

    def imdb_link(self):
        return 'http://www.imdb.com/title/tt%s/' % self.imdb_id


class User(namedtuple('User', ['id'])):

    def name(self):
        return user_names[self.id]

    def avatar(self):
        return avatars[self.id % len(avatars)]

    def hue(self):
        return self.id % 360


def get_user_id(name):
    return user_names.inv[name]


def load_movie_by_id(movie_id, similar_users=None):
    movie_id = int(movie_id)
    cursor = get_db().cursor()
    if similar_users:
        sql = '''
            SELECT year, title, translation, imdb_id, user_id, rating
            FROM movie m
            LEFT OUTER JOIN review r
            ON m.id = r.movie_id
            AND user_id IN (%s)
            WHERE id = %%s
        ''' % ', '.join(['%s'] * len(similar_users))
        cursor.execute(sql, similar_users + [movie_id])
        rows = cursor.fetchall()
        year, title, translation, imdb_id, _, _ = rows[0]
        ratings = {User(user_id): rating
                   for _, _, _, _, user_id, rating in rows
                   if user_id}

        return Movie(movie_id, year, title, translation, imdb_id, ratings)
    else:
        cursor.execute('SELECT year, title, translation, imdb_id FROM movie WHERE id = ?', (movie_id, ))
        year, title, translation, imdb_id = cursor.fetchone()
        return Movie(movie_id, year, title, translation, imdb_id, {})


def load_movie_by_title_year(title, year):
    cursor = get_db().cursor()
    cursor.execute('SELECT id, year, title, translation, imdb_id FROM movie WHERE title = ? AND year = ?', (title, year))
    row = cursor.fetchone()
    if not row:
        cursor.execute('SELECT id, year, title, translation, imdb_id FROM movie WHERE translation = ? AND year = ?', (title, year))
        row = cursor.fetchone()
        if not row:
            return None
    movie_id, year, title, translation, imdb_id = row
    return Movie(movie_id, year, title, translation, imdb_id)


def score_diffs(diffs):
    mean_diff = np.mean(np.abs(diffs))
    count = len(diffs)
    score = (5 - mean_diff) ** 2 * np.sqrt(count)

    return score


def get_similar_users(ratings, count=NUM_SIMILAR_USERS):
    cursor = get_db().cursor()

    sql = '''SELECT movie_id, user_id, rating
             FROM review
             WHERE movie_id IN (%s)''' % ', '.join(['%s'] * len(ratings))

    user_diffs = defaultdict(list)
    cursor.execute(sql, ratings.keys())
    for movie_id, user_id, rating in cursor.fetchall():
        diff = rating - ratings[movie_id]
        user_diffs[user_id].append(diff)

    sorted_users = [user_id for user_id, _ in
                    sorted(user_diffs.items(),
                           key=lambda x: score_diffs(x[1]), reverse=True)]

    #for user_id in sorted_users[:100]:
    #    print '*** ', user_id, len(user_diffs[user_id]), user_diffs[user_id], score_diffs(user_diffs[user_id])

    return sorted_users[:count]


def get_recs(ratings, similar_users,
             skips, saves,
             min_rating, max_rating,
             min_reviews, max_reviews,
             min_year, max_year,
             genres,
             count=10,
             sort=None):
    cursor = get_db().cursor()

    print 'similar users', similar_users

    sql = '''SELECT m.id
             FROM review r
             JOIN movie m
             ON r.movie_id = m.id
             JOIN movie2genre g
             ON g.movie_id = m.id
             WHERE m.id NOT IN (%s)
             AND m.id NOT IN (%s)
             AND m.id NOT IN (%s)
             AND user_id IN (%s)
             AND year >= %%s
             AND year <= %%s
             AND genre IN (%s)
             GROUP BY m.id
             HAVING AVG(rating) >= %%s
             AND AVG(rating) <= %%s
             AND COUNT(*) >= %%s
             AND COUNT(*) <= %%s
             %s
          ''' % (
              ', '.join(['%s'] * len(ratings)),
              ', '.join(['%s'] * len(skips)),
              ', '.join(['%s'] * len(saves)),
              ', '.join(['%s'] * len(similar_users)),
              ', '.join(['%s'] * len(genres)),
              'ORDER BY AVG(rating) DESC' if sort == 'rating' else '',
          )

    movie_ids = []
    cursor.execute(
        sql, tuple(ratings.keys() + skips + saves + similar_users +
                   [min_year, max_year] + genres +
                   [min_rating, max_rating, min_reviews, max_reviews]))
    for row in cursor.fetchall():
        movie_ids.append(row[0])

    if sort == 'rating':
        return movie_ids[:count]
    else:
        if len(movie_ids) > count:
            return random.sample(movie_ids, count)
        return movie_ids


def get_ratings():
    ratings = session_get('ratings', {})
    liked_movie_ids = session_get('liked_movie_ids', [])
    for movie_id in liked_movie_ids:
        ratings[movie_id] = 5.0

    return ratings


@app.route('/')
def index():
    if session_contains('liked_movie_ids'):
        liked_movie_ids = session_get('liked_movie_ids')
        liked_movies = [load_movie_by_id(movie_id)
                        for movie_id in liked_movie_ids]
    else:
        liked_movies = []

    error = session_pop('error', None)
    previous_title = session_pop('previous_title', '')

    session_delete('recs')

    return render_template('index.html', liked_movies=liked_movies,
                           error=error, previous_title=previous_title,
                           **session_params())


@app.route('/add-movie', methods=['POST'])
def add_movie():
    title_year = request.form['title-year'].lower()
    match = re.match(r'^(.+) \(([0-9]{4})\)$', title_year)
    if not match:
        session_put('previous_title', title_year)
        session_put('error', 'Title must be in the format "title (year)"')
        return redirect(url_for_with_session('index'))

    title, year = match.groups()
    movie = load_movie_by_title_year(title, year)
    if not movie:
        session_put('previous_title', title_year)
        session_put('error', '"%s (%s)" is not in the database' % (title, year))
        return redirect(url_for_with_session('index'))

    liked_movie_ids = session_get('liked_movie_ids', [])
    liked_movie_ids.append(movie.id)
    session_put('liked_movie_ids', liked_movie_ids)

    return redirect(url_for_with_session('index'))


@app.route('/remove-movie')
def remove_movie():
    movie_id = int(request.args.get('id'))
    liked_movie_ids = session_get('liked_movie_ids', [])
    liked_movie_ids.remove(movie_id)
    session_put('liked_movie_ids', liked_movie_ids)

    return redirect(url_for_with_session('index'))


@app.route('/autocomplete/titles')
def autocomplete_titles():
    query = request.args['query'].lower()
    matching_titles = sorted([t for t in cached_titles if query in t][:100],
                             key=lambda s: (len(s), s))
    return jsonify({
        'suggestions': [{'value': title} for title in matching_titles]
    })


@app.route('/tune')
def tune():
    if not session_contains('liked_movie_ids'):
        print get_session()
        return redirect(url_for('index'))

    min_rating = session_get('min_rating', 4.5)
    max_rating = session_get('max_rating', 5.0)
    min_reviews = session_get('min_reviews', 1)
    max_reviews = session_get('max_reviews', NUM_SIMILAR_USERS)
    min_year = session_get('min_year', 1891)
    max_year = session_get('max_year', 2015)
    genres = session_get('genres', all_genres)

    skips = session_get('skips', [])
    saves = session_get('saves', [])
    recs = session_get('recs', None)
    ratings = get_ratings()

    if recs and len(recs) > 0:
        recs = [r for r in recs if r not in skips + saves + ratings.keys()]
        if not recs:
            recs = None

    similar_users = get_similar_users(ratings)

    if recs is None:
        recs = get_recs(
            ratings=ratings,
            similar_users=similar_users,
            skips=skips, saves=saves,
            min_rating=min_rating, max_rating=max_rating,
            min_reviews=min_reviews,
            max_reviews=max_reviews,
            min_year=min_year, max_year=max_year,
            genres=genres,
        )

        print '----------> finished making recs'

        session_put('recs', recs)
        return redirect(url_for_with_session('tune'))

    movies = [load_movie_by_id(movie_id, similar_users=similar_users)
              for movie_id in recs]
    return render_template(
        'tune.html', movies=movies,
        min_rating=min_rating, max_rating=max_rating,
        min_reviews=min_reviews,
        max_reviews=max_reviews,
        min_year=min_year, max_year=max_year,
        genres=genres,
        all_genres=all_genres,
        **session_params()
    )


@app.route('/skip')
def skip():
    movie_id = int(request.args['id'])
    skips = session_get('skips', [])
    if movie_id not in skips:
        skips.append(movie_id)
    session_put('skips', skips)

    return redirect(url_for_with_session('tune'))


@app.route('/save')
def save():
    movie_id = int(request.args['id'])
    saves = session_get('saves', [])
    if movie_id not in saves:
        saves.append(movie_id)
    session_put('saves', saves)

    return redirect(url_for_with_session('tune'))


@app.route('/rate')
def rate():
    movie_id = int(request.args['id'])
    rating = float(request.args['rating'])
    ratings = session_get('ratings', {})
    ratings[movie_id] = rating

    session_put('ratings', ratings)
    return redirect(url_for_with_session('tune'))


def handle_options():
    min_rating = float(request.form['min-rating'])
    max_rating = float(request.form['max-rating'])
    min_reviews = int(request.form.get('min-reviews', session_get('min_reviews', 1)))
    max_reviews = int(request.form.get('max-reviews', session_get('max_reviews', NUM_SIMILAR_USERS)))
    min_year = int(request.form['min-year'])
    max_year = int(request.form['max-year'])
    genres = request.form.getlist('genres')

    session_put('min_rating', min_rating)
    session_put('max_rating', max_rating)
    session_put('min_reviews', min_reviews)
    session_put('max_reviews', max_reviews)
    session_put('min_year', min_year)
    session_put('max_year', max_year)
    session_put('genres', genres)
    session_delete('recs')


@app.route('/update-options', methods=['POST'])
def update_options():
    handle_options()
    return redirect(url_for_with_session('tune'))


@app.route('/update-reviewer-options/<user_id>', methods=['POST'])
def update_reviewer_options(user_id):
    handle_options()
    return redirect(url_for_with_session('reviewer', user_id=user_id))


@app.route('/reviewer/<user_id>')
def reviewer(user_id):
    user_id = int(user_id)
    min_rating = session_get('min_rating', 4.5)
    max_rating = session_get('max_rating', 5.0)
    min_year = session_get('min_year', 1891)
    max_year = session_get('max_year', 2015)
    genres = session_get('genres', all_genres)

    recs = get_recs(
        ratings={},
        similar_users=[user_id],
        skips=[], saves=[],
        min_rating=min_rating, max_rating=max_rating,
        min_reviews=1,
        max_reviews=1,
        min_year=min_year, max_year=max_year,
        genres=genres,
        count=100,
        sort='rating',
    )

    print '----------> finished making recs'

    movies = [load_movie_by_id(movie_id, similar_users=[user_id])
              for movie_id in recs]

    return render_template(
        'reviewer.html', movies=movies,
        min_rating=min_rating, max_rating=max_rating,
        min_reviews=1, max_reviews=1,
        min_year=min_year, max_year=max_year,
        genres=genres,
        all_genres=all_genres,
        user=User(user_id),
        **session_params()
    )


@app.route('/saves')
def list_saves():
    ratings = get_ratings()
    similar_users = get_similar_users(ratings)
    movies = [load_movie_by_id(movie_id, similar_users)
              for movie_id in session_get('saves', [])]
    return render_template('saves.html', movies=movies, **session_params())


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, threaded=True)
