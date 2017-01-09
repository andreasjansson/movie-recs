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
NUM_SIMILAR_CRITICS = 25
NUM_RECOMMENDED_MOVIES = 24

last_update_time = 0


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        t = time.time()
        g._database = db = MySQLdb.connect('localhost', db='movie_recs_2', charset='utf8')
        db.autocommit(True)
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


all_genres = [
    'Drama',
    'Comedy',
    'Art House & International',
    'Action & Adventure',
    'Mystery & Suspense',
    'Documentary',
    'Special Interest',
    'Horror',
    'Romance',
    'Science Fiction & Fantasy',
    'Classics',
    'Musical & Performing Arts',
    'Kids & Family',
    'Animation',
    'Television',
    'Western',
    'Sports & Fitness',
    'Faith & Spirituality',
    'Gay & Lesbian',
    'Cult Movies',
    'Anime & Manga',
    'Adult',
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
    def load_latest_update_time(self):
        cursor = get_db().cursor()
        cursor.execute('''
            SELECT date_inserted
            FROM user_similar_critic
            WHERE user_id = %s
            ORDER BY date_inserted DESC
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
    def load_similar_critics(self):
        cursor = get_db().cursor()
        cursor.execute('''
            SELECT critic_id, score, rating_similarity,
                acceptability, num_shared_reviews, samesidedness
            FROM user_similar_critic
            WHERE user_id = %s
            ORDER BY score DESC
        ''', (self.id, ))
        return [Critic(critic_id, score, rating_similarity,
                       acceptability, num_shared_reviews, samesidedness)
                for (critic_id, score, rating_similarity,
                     acceptability, num_shared_reviews, samesidedness) in cursor]

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

    def load_critic_by_id(self, critic_id):
        cursor = get_db().cursor()

        cursor.execute('''
            SELECT
                rating_similarity
                    * POWER(acceptability, 2)
                    * POWER(num_shared_reviews, 1/2.)
                    * POWER(samesidedness, 2) AS score,
                rating_similarity,
                acceptability,
                num_shared_reviews,
                samesidedness
            FROM (
                SELECT
                    AVG(5 - ABS(r.rating - ur.rating)) AS rating_similarity,
                    AVG(ABS(r.rating - ur.rating) < 2) AS acceptability,
                    COUNT(*) AS num_shared_reviews,
                    AVG(SIGN(r.rating - meanrating) =
                        SIGN(ur.rating - meanrating)) AS samesidedness
                FROM review r
                JOIN user_rating ur
                ON r.movie_id = ur.movie_id
                JOIN meanratings mr
                ON r.movie_id = mr.movie_id
                WHERE user_id = %s
                AND critic_id = %s
                GROUP BY critic_id
            ) t
        ''', (self.id, critic_id))

        # cursor.execute('''
        #     SELECT score, rating_similarity, acceptability, num_shared_reviews, samesidedness
        #     FROM user_similar_critic
        #     WHERE user_id = %s
        #     AND critic_id = %s
        # ''', (self.id, critic_id))
        row = cursor.fetchone()

        if row:
            score, rating_similarity, acceptability, num_shared_reviews, samesidedness = row
            return Critic(critic_id, score, rating_similarity,
                          acceptability, num_shared_reviews, samesidedness)
        else:
            return Critic(critic_id, None)

    def update_similar_critics(self, count=NUM_SIMILAR_CRITICS):
        cursor = get_db().cursor()

        sql = '''
            SELECT
                critic_id,
                rating_similarity
                    * POWER(acceptability, 2)
                    * POWER(num_shared_reviews, 1/2.)
                    * POWER(samesidedness, 2) AS score,
                rating_similarity,
                acceptability,
                num_shared_reviews,
                samesidedness
            FROM (
                SELECT critic_id,
                    AVG(5 - ABS(r.rating - ur.rating)) AS rating_similarity,
                    AVG(ABS(r.rating - ur.rating) < 2) AS acceptability,
                    COUNT(*) AS num_shared_reviews,
                    AVG(SIGN(r.rating - meanrating) =
                        SIGN(ur.rating - meanrating)) AS samesidedness
                FROM review r
                JOIN user_rating ur
                ON r.movie_id = ur.movie_id
                JOIN meanratings mr
                ON r.movie_id = mr.movie_id
                WHERE user_id = %s
                GROUP BY critic_id
            ) t
            ORDER BY score DESC
            LIMIT %s;
        '''

        t = time.time()
        cursor.execute(sql, (self.id, count))
        rows = cursor.fetchall()

        print 'updated critic %d (%s) in %.2f seconds' % (self.id, self.username, time.time() - t)

        cursor.execute('''
            DELETE FROM user_similar_critic
            WHERE user_id = %s
        ''', (self.id, ))

        for (critic_id, score, rating_similarity, acceptability,
             num_shared_reviews, samesidedness) in rows:
            cursor.execute('''
                INSERT INTO user_similar_critic
                    (user_id, critic_id, score, rating_similarity, acceptability, num_shared_reviews, samesidedness)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (self.id, critic_id, score, rating_similarity,
                  acceptability, num_shared_reviews, samesidedness))

        cursor.execute('''
            DELETE FROM user_similar_critic_review
            WHERE user_id = %s
        ''', (self.id, ))

        cursor.execute('''
            INSERT INTO user_similar_critic_review
            SELECT %s, critic_id, movie_id, rating
            FROM review
            WHERE critic_id IN (
                SELECT critic_id
                FROM user_similar_critic
                WHERE user_id = %s
            )
        ''', (self.id, self.id))


class Movie(namedtuple('Movie', [
        'id',
        'title',
        'year',
        'image',
        'link',
        'duration',
        'plot',
        'director',
        'genres',
        'user_rating',
        'critic_rating',
        'mean_rating',
        'num_ratings',
        'saved',
        'skipped',
        'reviews',
        'critics',
])):

    def __new__(self, id,
                user_rating=None, critic_rating=None, mean_rating=None,
                num_ratings=None, saved=False, skipped=False,
                reviews=None, critics=None,
                title=None, year=None, image=None, link=None,
                duration=None, plot=None, director=None, genres=None,
    ):

        if not title:
            cached = movie_cache[id]
            title = cached.title
            year = cached.year
            image = cached.image
            link = cached.link
            duration = cached.duration
            plot = cached.plot
            director = cached.director
            genres = cached.genres

        if reviews:
            num_ratings = len(reviews)
            mean_rating = sum(reviews.values()) / float(len(reviews.values()))
            critics = reviews.keys()

        return super(Movie, self).__new__(
            self, id, title, year, image, link, duration, plot, director,
            genres, user_rating, critic_rating, mean_rating, num_ratings,
            saved, skipped, reviews, critics)

    def rotten_tomatoes_link(self):
        return 'https://www.rottentomatoes.com/m/%s' % self.link

    def html_title(self):
        return '%s (%d)\nDirector: %s\nRunning time: %s\n\n%s' % (
            self.title, self.year, self.director, self.duration, self.plot)

    def director_id(self):
        return director_index.inv[self.director]


class Critic(namedtuple('Critic', [
        'id',
        'name',
        'image',
        'link',
        'score',
        'rating_similarity',
        'acceptability',
        'num_shared_reviews',
        'samesidedness',
])):
    def __new__(self, id, score=None, rating_similarity=None,
                acceptability=None, num_shared_reviews=None, samesidedness=None):
        link, name, image = critic_cache[id]
        return super(Critic, self).__new__(
            self, id, name, image, link,
            score, rating_similarity, acceptability, num_shared_reviews, samesidedness)

    def image_url(self):
        if self.image:
            return self.image

        return '/images/avatars/%s' % avatars[self.id % len(avatars)]

    def rotten_tomatoes_link(self):
        return 'https://www.rottentomatoes.com/critic/%s' % self.link

    def html_title(self):
        s = self.name
        if self.rating_similarity:
            s += '''

Rating similarity: %d%%
Acceptability: %d%%
Samesidedness: %d%%
Shared reviews: %d''' % (round(20 * self.rating_similarity),
                         round(100 * self.acceptability),
                         round(100 * self.samesidedness),
                         self.num_shared_reviews)

        return s


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

    def sql_where_clauses(self):
        clauses = []

        if frozenset(self.genres) != frozenset(all_genres):
            clauses.append(
                'genre IN (%s)' % (', '.join(['%s'] * len(self.genres))))

        if frozenset(self.decades) != frozenset(all_decades):
            clauses.append(
                'FLOOR(year / 10) * 10 IN (%s)' %
                (', '.join(['%s'] * len(self.decades))))

        excluded_genres = set(['Kids & Family', 'Animation']) - set(self.genres)
        if excluded_genres:
            clauses.append('''
                m.id NOT IN (
                    SELECT movie_id
                    FROM movie2genre
                    WHERE genre IN (%s))
            ''' % ', '.join(['%s'] * len(excluded_genres)))

        if clauses:
            return '(%s)' % ' AND '.join(clauses)
        return 'TRUE'

    def sql_where_arguments(self):
        args = []

        if frozenset(self.genres) != frozenset(all_genres):
            args += self.genres

        if frozenset(self.decades) != frozenset(all_decades):
            args += self.decades

        excluded_genres = set(['Kids & Family', 'Animation']) - set(self.genres)
        args += list(excluded_genres)

        return args

    def sql_having_clauses(self):
        return '''
            (FLOOR(AVG(r.rating) + .5) IN (%s) OR AVG(r.rating) IS NULL)
        ''' % (', '.join(['%s'] * len(self.stars)))

    def sql_having_arguments(self):
        return self.stars


def timestamp_to_int(d):
    return time.mktime(d.timetuple())


def movie_filter_from_session():
    if 'movie_filter' in session:
        values = session['movie_filter']
        if len(values) != 3:
            return MovieFilter()
        genres, decades, stars = values
        return MovieFilter(genres, decades, stars)
    return MovieFilter()
#Shadows in Paradise

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
        SELECT id
        FROM movie
        WHERE (title = %s OR translation = %s) AND year = %s
    ''', (title, title, year))

    row = cursor.fetchone()
    if not row:
        return None
    movie_id = row[0]

    return Movie(movie_id)


def load_movie_for_user(movie_id, user):
    cursor = get_db().cursor()

    similar_critics_by_id = {r.id: r for r in user.load_similar_critics()}

    saves = user.load_saves()
    skips = user.load_skips()

    sql = '''
        SELECT m.id, ur.rating, r.critic_id, r.rating
        FROM movie m
        LEFT JOIN user_rating ur
        ON m.id = ur.movie_id
        AND ur.user_id = %s
        LEFT JOIN review r
        ON r.movie_id = m.id
        AND critic_id IN ({critics_placeholders})
        WHERE m.id = %s
    '''.format(
        critics_placeholders=', '.join(
            ['NULL'] + (['%s'] * (len(similar_critics_by_id)))),
    )

    args = [user.id] + similar_critics_by_id.keys() + [movie_id]

    cursor.execute(sql, args)
    rows = cursor.fetchall()

    if not rows:
        return None

    first = rows[0]
    movie_id, user_rating, _, _ = first

    reviews = OrderedDict(sorted([
        (similar_critics_by_id[critic_id], rating)
        for _, _, critic_id, rating in rows
        if critic_id is not None
    ], key=lambda x: x[0].score, reverse=True))

    saved = movie_id in saves
    skipped = movie_id in skips

    return Movie(id=movie_id,
                 user_rating=user_rating, saved=saved, skipped=skipped,
                 reviews=reviews)


def load_movie_for_critic(movie_id, critic_id, user):
    cursor = get_db().cursor()

    saves = user.load_saves()
    skips = user.load_skips()

    sql = '''
        SELECT m.id, ur.rating, r.rating
        FROM movie m
        JOIN review r
        ON r.movie_id = m.id
        AND critic_id = %s
        LEFT JOIN user_rating ur
        ON m.id = ur.movie_id
        AND ur.user_id = %s
        WHERE m.id = %s
    '''

    args = [critic_id, user.id, movie_id]

    cursor.execute(sql, args)
    row = cursor.fetchone()

    if not row:
        return None

    movie_id, user_rating, critic_rating = row

    return Movie(id=movie_id,
                 user_rating=user_rating, critic_rating=critic_rating,
                 saved=movie_id in saves and not user_rating,
                 skipped=movie_id in skips and not user_rating)


def load_movies_for_user(user, movie_filter, movie_ids):
    if not movie_ids:
        return []

    cursor = get_db().cursor()

    sql = '''
        SELECT id, ur.rating, AVG(r.rating), COUNT(DISTINCT critic_id), GROUP_CONCAT(critic_id SEPARATOR ',')
        FROM movie m
        LEFT JOIN user_similar_critic_review r
        ON r.movie_id = m.id
        AND r.user_id = %s
        LEFT JOIN user_rating ur
        ON m.id = ur.movie_id
        AND ur.user_id = %s
        JOIN movie2genre g
        ON g.movie_id = m.id
        WHERE m.id in ({movies_placeholders})
        AND {filter_clauses}
        GROUP BY m.id
    '''.format(
        filter_clauses=movie_filter.sql_where_clauses(),
        movies_placeholders=', '.join(['%s'] * len(movie_ids)),
    )

    args = ([user.id] + [user.id] +
            movie_ids + movie_filter.sql_where_arguments())

    cursor.execute(sql, args)

    movies = [
        Movie(
            id=movie_id,
            user_rating=user_rating, mean_rating=mean_rating,
            num_ratings=num_ratings,
            critics=[Critic(int(r))
                       for r in set(critics.split(','))
                       if r] if critics else []
        )
        for (movie_id, user_rating, mean_rating, num_ratings, critics)
        in cursor
    ]

    skipped_movie_ids = frozenset(user.load_skips())
    saved_movie_ids = frozenset(user.load_saves())

    movies_with_flags = []
    for movie in movies:
        if movie.id in skipped_movie_ids:
            movie = movie._replace(skipped=True)
        elif movie.id in saved_movie_ids:
            movie = movie._replace(saved=True)
        movies_with_flags.append(movie)

    return movies_with_flags


def load_movies_for_critic(critic, user, movie_filter):
    cursor = get_db().cursor()

    saves = user.load_saves()
    skips = user.load_skips()

    sql = '''
        SELECT m.id, ur.rating, r.rating
        FROM movie m
        JOIN review r
        ON r.movie_id = m.id
        AND critic_id = %s
        LEFT JOIN user_rating ur
        ON m.id = ur.movie_id
        AND ur.user_id = %s
        JOIN movie2genre g
        ON g.movie_id = m.id
        WHERE {filter_clauses}
        GROUP BY m.id
        ORDER BY r.rating DESC, title
        LIMIT 500
    '''.format(
        filter_clauses=movie_filter.sql_where_clauses(),
    )

    args = ([critic.id] + [user.id] +
            movie_filter.sql_where_arguments())

    cursor.execute(sql, args)

    movies = [
        Movie(id=movie_id,
              user_rating=user_rating, critic_rating=critic_rating,
              saved=movie_id in saves and not user_rating,
              skipped=movie_id in skips and not user_rating
        )
        for movie_id, user_rating, critic_rating
        in cursor
    ]

    return movies


def load_recommended_movies(user, movie_filter, limit=NUM_RECOMMENDED_MOVIES):
    cursor = get_db().cursor()

    excluded_movie_ids = (
        user.load_ratings().keys() +
        user.load_skips() +
        user.load_saves()
    )

    sql = '''
        SELECT id, ur.rating, AVG(r.rating), COUNT(DISTINCT critic_id), GROUP_CONCAT(critic_id SEPARATOR ',')
        FROM movie m
        JOIN user_similar_critic_review r
        ON r.movie_id = m.id
        AND r.user_id = %s
        LEFT JOIN user_rating ur
        ON m.id = ur.movie_id
        AND ur.user_id = %s
        JOIN movie2genre g
        ON g.movie_id = m.id
        WHERE m.id NOT IN ({movies_placeholders})
        AND {filter_where_clauses}
        GROUP BY m.id
        HAVING {filter_having_clauses}
        ORDER BY COUNT(DISTINCT critic_id) DESC
        LIMIT %s
    '''.format(
        movies_placeholders=', '.join(['%s'] * len(excluded_movie_ids)),
        filter_where_clauses=movie_filter.sql_where_clauses(),
        filter_having_clauses=movie_filter.sql_having_clauses(),
    )

    args = (
        [user.id] +
        [user.id] +
        excluded_movie_ids +
        movie_filter.sql_where_arguments() +
        movie_filter.sql_having_arguments() +
        [limit * 2]
    )

    cursor.execute(sql, args)

    movies = [
        Movie(id=movie_id,
              user_rating=user_rating, mean_rating=mean_rating,
              num_ratings=num_ratings,
              critics=[Critic(int(r))
                       for r in set(critics.split(',')) if r])
        for (movie_id, user_rating, mean_rating, num_ratings, critics)
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
        user, MovieFilter(),
        rated_movie_ids + skipped_movie_ids,
    )

    movies_by_id = {m.id: m for m in movies}

    rated_movies = [movies_by_id[movie_id] for movie_id in rated_movie_ids
                    if movie_id in movies_by_id]
    skipped_movies = [movies_by_id[movie_id]
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

    saved_movies = sorted(movies, key=lambda m: m.mean_rating, reverse=True)

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
    movie = load_movie_by_title_year(title, year)
    if not movie:
        session['error'] = '"%s (%s)" is not in the database' % (title, year)
        return redirect(url_for('curate'))

    user.rate_movie_id(movie.id, 5)

    return redirect(url_for('curate'))


@app.route('/autocomplete/titles')
def autocomplete_titles():
    query = request.args['query'].lower()
    matching_titles = sorted(
        ['%s (%s)' % (m.title, m.year) for m in movie_cache.itervalues()
         if query in m.title.lower()][:100],
        key=lambda s: (len(s), s))
    return jsonify({
        'suggestions': [{'value': title} for title in matching_titles]
    })


@app.route('/autocomplete/directors')
def autocomplete_directors():
    query = request.args['query'].lower()
    matching_directors = sorted(
        set([m.director for m in movie_cache.itervalues()
             if m.director and query in m.director.lower()]),
            key=lambda s: (len(s), s))[:100]
    return jsonify({
        'suggestions': [{'value': title} for title in matching_directors]
    })


@app.route('/autocomplete/critics')
def autocomplete_critics():
    query = request.args['query'].lower()
    matching_critics = sorted(
        set([name for (_, name, _) in critic_cache.itervalues()
             if query in name.lower()]),
            key=lambda s: (len(s), s))[:100]
    return jsonify({
        'suggestions': [{'value': title} for title in matching_critics]
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


@app.route('/movie/<int:movie_id>/ajax/critic/<int:critic_id>')
@require_user
def movie_ajax_critic(user, movie_id, critic_id):
    movie = load_movie_for_critic(movie_id, critic_id, user)
    return render_template('movie.html', movie=movie, user=user)


@app.route('/movie/<int:movie_id>/ajax/user')
@require_user
def movie_ajax_user(user, movie_id):
    movie = load_movie_for_user(movie_id, user)
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
    critics = user.load_similar_critics()
    return render_template('your25.html', user=user, critics=critics)


@app.route('/search')
@require_user
def search(user):
    return render_template('search.html', user=user,
                           error=session.pop('error', None))


@app.route('/search-title', methods=['POST'])
@require_user
def search_by_title(user):
    title_year = request.form['title-year'].lower()
    match = re.match(r'^(.+) \(([0-9]{4})\)$', title_year)
    if not match:
        session['error'] = 'Title must be in the format "title (year)"'
        return redirect(url_for('search'))

    title, year = match.groups()
    movie = load_movie_by_title_year(title, year)
    if not movie:
        session['error'] = '"%s (%s)" is not in the database' % (title, year)
        return redirect(url_for('search'))

    return redirect(url_for('movie_view', movie_id=movie.id))


@app.route('/search-director', methods=['POST'])
@require_user
def search_by_director(user):
    name = request.form['name']
    if name not in director_index.inv:
        session['error'] = '"%s" is not in the database' % name
        return redirect(url_for('search'))

    director_id = director_index.inv[name]

    return redirect(url_for('director_view', director_id=director_id))


@app.route('/search-critic', methods=['POST'])
@require_user
def search_by_critic(user):
    name = request.form['name']
    critic_ids = [
        critic_id for critic_id, (_, critic_name, _)
        in critic_cache.iteritems() if critic_name == name]

    if not critic_ids:
        session['error'] = '"%s" is not in the database' % name
        return redirect(url_for('search'))

    return redirect(url_for('critic_view', critic_id=critic_ids[0]))


@app.route('/director/<int:director_id>')
@require_user
def director_view(user, director_id):
    movie_filter = MovieFilter()
    director_name = director_index[director_id]
    movie_ids = [m.id for m in movie_cache.itervalues()
                 if m.director == director_name]

    movies = load_movies_for_user(user, movie_filter, movie_ids)
    movies = sorted(movies, key=lambda m: m.mean_rating, reverse=True)
    return render_template('director.html', user=user,
                           director_name=director_name,
                           movies=movies)


@app.route('/critic/<int:critic_id>')
@require_user
def critic_view(user, critic_id):
    movie_filter = movie_filter_from_session()
    critic = user.load_critic_by_id(critic_id)
    movies = load_movies_for_critic(critic, user, movie_filter)

    return render_template('critic_view.html', user=user, critic=critic,
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


@app.route('/update-similar-critics')
def update_similar_critics():
    if time.time() - last_update_time < 60:
        return 'wait'

    t = time.time()
    for user in iter_users():
        latest_rating_time = user.load_latest_rating_time()
        latest_update_time = user.load_latest_update_time()
        if latest_rating_time > latest_update_time:
            user.update_similar_critics()

    return 'done in %.2f seconds\n' % (time.time() - t)


def read_critic_cache():
    with open('critics.cpkl') as f:
        return cPickle.load(f)


def read_movie_cache():
    movie_index = {}
    directors = set()
    with open('movies.cpkl') as f:
        cached_tuples = cPickle.load(f)
    for movie_id, (title, year, image, link, duration, plot,
                   director, genres) in cached_tuples.iteritems():
        movie_index[movie_id] = Movie(
            id=movie_id, title=title, year=year, image=image, link=link,
            duration=duration, plot=plot, director=director, genres=genres)
        if director and director not in directors:
            directors.add(director)

    director_index = bidict({i: d for i, d in enumerate(sorted(directors))})
    return movie_index, director_index


critic_cache = read_critic_cache()
movie_cache, director_index = read_movie_cache()
avatars = [os.path.basename(a) for a in glob('static/images/avatars/*.png')]


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, threaded=True)
