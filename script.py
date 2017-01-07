# -*- coding: utf-8 -*-

import MySQLdb
import cPickle
import re
from collections import defaultdict
import os
import csv

DATA_DIR = 'ml-20m'
TITLE_YEAR_REGEX = re.compile(r'^(.+)[^a-z0-9]?\(([0-9]{4})\) ?$')
CLEANUP_REGEX = re.compile(
    r'^(?P<title>.+?)(?:, (?P<prefix>[a-z]+))?(?: \((?P<translation>.+)\))?$')

conn = MySQLdb.connect('localhost', db='movie_recs')
conn.autocommit(False)
cursor = conn.cursor()


def create_user_tables():
    cursor.execute('SET FOREIGN_KEY_CHECKS=0')
    cursor.execute('DROP TABLE IF EXISTS user')
    cursor.execute('''
        CREATE TABLE user (
            id              INT PRIMARY KEY AUTO_INCREMENT,
            username        TEXT,
            password        BINARY(60)
        ) ENGINE=InnoDB'''
    )
    cursor.execute('DROP TABLE IF EXISTS user_rating')
    cursor.execute('''
        CREATE TABLE user_rating (
            user_id         INT,
            movie_id        INT,
            rating          FLOAT,
            date_added      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, movie_id),
            FOREIGN KEY (user_id) REFERENCES user (id),
            FOREIGN KEY (movie_id) REFERENCES movie (id)
        ) ENGINE=InnoDB'''
    )
    cursor.execute('DROP TABLE IF EXISTS user_save')
    cursor.execute('''
        CREATE TABLE user_save (
            user_id         INT,
            movie_id        INT,
            date_saved      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, movie_id),
            FOREIGN KEY (user_id) REFERENCES user (id),
            FOREIGN KEY (movie_id) REFERENCES movie (id)
        ) ENGINE=InnoDB'''
    )
    cursor.execute('DROP TABLE IF EXISTS user_skip')
    cursor.execute('''
        CREATE TABLE user_skip (
            user_id         INT,
            movie_id        INT,
            date_skipped    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, movie_id),
            FOREIGN KEY (user_id) REFERENCES user (id),
            FOREIGN KEY (movie_id) REFERENCES movie (id)
        ) ENGINE=InnoDB'''
    )
    cursor.execute('DROP TABLE IF EXISTS user_similar_reviewer')
    cursor.execute('''
        CREATE TABLE user_similar_reviewer (
            user_id         INT,
            reviewer_id     INT,
            similarity      FLOAT,
            PRIMARY KEY (user_id, reviewer_id),
            FOREIGN KEY (user_id) REFERENCES user (id)
        ) ENGINE=InnoDB'''
    )
    cursor.execute('DROP TABLE IF EXISTS user_similar_reviewer_review')
    cursor.execute('''
        CREATE TABLE user_similar_reviewer_review (
            user_id         INT,
            reviewer_id     INT,
            movie_id        INT,
            rating          FLOAT,
            PRIMARY KEY (user_id, reviewer_id, movie_id),
            FOREIGN KEY (user_id) REFERENCES user (id)
        ) ENGINE=InnoDB'''
    )
    create_indexes([
        ('user_similar_reviewer_review', 'user_id'),
        ('user_similar_reviewer_review', 'reviewer_id'),
        ('user_similar_reviewer_review', 'movie_id')
    ])


def write_title_cache():
    titles = set()
    for title, translation, year in cursor.execute(
            'SELECT title, translation, year FROM movie'):
        titles.add('%s (%s)' % (title, year))
        if translation:
            titles.add('%s (%s)' % (translation, year))

    with open('titles.cpkl', 'w') as f:
        cPickle.dump(titles, f, protocol=cPickle.HIGHEST_PROTOCOL)


def insert_movies():
    cursor.execute('SET FOREIGN_KEY_CHECKS=0')

    cursor.execute('DROP TABLE IF EXISTS movie')
    cursor.execute('''CREATE TABLE movie (
        id              INT PRIMARY KEY,
        year            INT,
        title           VARCHAR(128),
        translation     VARCHAR(128),
        imdb_id         CHAR(7)
    ) ENGINE=InnoDB''')

    cursor.execute('DROP TABLE IF EXISTS movie2genre')
    cursor.execute('''CREATE TABLE movie2genre (
        movie_id        INT,
        genre           VARCHAR(32),
        PRIMARY KEY (genre, movie_id),
        FOREIGN KEY (movie_id) REFERENCES movie(id)
    ) ENGINE=InnoDB''')

    i = 0
    with open(os.path.join(DATA_DIR, 'movies.csv'), 'rU') as f:
        for movie_id, title_year, genres in unicode_csv_reader(f):

            if movie_id == 'movieId':
                continue

            title_year = title_year.lower()

            if not TITLE_YEAR_REGEX.match(title_year):
                continue

            title, year = TITLE_YEAR_REGEX.match(title_year).groups()
            title = title.strip()
            year = int(year)

            clean_match = CLEANUP_REGEX.match(title)
            clean_title, prefix, translation = clean_match.groups()
            if prefix:
                clean_title = '%s %s' % (prefix, clean_title)

            movie_id = int(movie_id)
            genres = [g.lower() for g in genres.split('|')]

            if True:
#            try:
                cursor.execute('INSERT INTO movie (id, year, title, translation) VALUES (%s, %s, %s, %s)',
                               (movie_id, year, clean_title, translation))

                for genre in genres:
                    cursor.execute('INSERT INTO movie2genre VALUES (%s, %s)',
                                   (movie_id, genre))

                if i % 1000 == 0:
                    conn.commit()
                    print i

                i += 1

#            except Exception as e:
#                print e, movie_id

    i = 0
    with open(os.path.join(DATA_DIR, 'links.csv')) as f:
        for movie_id, imdb_id, tmdb_id in csv.reader(f):

            cursor.execute('UPDATE movie SET imdb_id = %s WHERE id = %s',
                           (imdb_id, movie_id))

            if i % 1000 == 0:
                conn.commit()
                print i

            i += 1

    create_indexes([
        ('movie', 'year'),
        ('movie', 'title'),
        ('movie', 'translation'),
        ('movie2genre', 'movie_id'),
        ('movie2genre', 'genre'),
    ])


def create_indexes(indexes):
    for table, column in indexes:
        cursor.execute('CREATE INDEX {table}_{column} ON {table} ({column})'
                       .format(table=table, column=column))

    conn.commit()


def insert_reviews():
    cursor.execute('SET FOREIGN_KEY_CHECKS=0')
    cursor.execute('DROP TABLE IF EXISTS review')
    cursor.execute('''CREATE TABLE review (
        movie_id        INT,
        reviewer_id     INT,
        rating          FLOAT,
        PRIMARY KEY (movie_id, reviewer_id),
        FOREIGN KEY (movie_id) REFERENCES movie(id)
    ) ENGINE=InnoDB''')

    i = 0
    with open(os.path.join(DATA_DIR, 'ratings.csv')) as f:
        for reviewer_id, movie_id, rating, timestamp in unicode_csv_reader(f):
            if movie_id == 'movieId':
                continue

            movie_id = int(movie_id)
            rating = float(rating)
            cursor.execute('INSERT INTO review VALUES (%s, %s, %s)',
                           (movie_id, reviewer_id, rating))

            if i % 100000 == 0:
                conn.commit()
                print i

            i += 1


    indexes = [
        ('review', 'movie_id'),
        ('review', 'reviewer_id'),
    ]
    for table, column in indexes:
        cursor.execute('CREATE INDEX {table}_{column} ON {table} ({column})'
                       .format(table=table, column=column))

    conn.commit()


def unicode_csv_reader(unicode_csv_data, dialect=csv.excel, **kwargs):
    # csv.py doesn't do Unicode; encode temporarily as UTF-8:
    csv_reader = csv.reader(utf_8_encoder(unicode_csv_data),
                            dialect=dialect, **kwargs)
    for row in csv_reader:
        # decode UTF-8 back to Unicode, cell by cell:
        yield [unicode(cell, 'utf-8') for cell in row]

def utf_8_encoder(unicode_csv_data):
    for line in unicode_csv_data:
        yield line


def main():
    pass


if __name__ == '__main__':
    main()
