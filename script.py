# -*- coding: utf-8 -*-

import MySQLdb
import cPickle
import re
from collections import defaultdict, Counter
import os
import csv
from bidict import bidict
import json

DATA_DIR = 'ml-20m'
TITLE_YEAR_REGEX = re.compile(r'^(.+)[^a-z0-9]?\(([0-9]{4})\) ?$')
CLEANUP_REGEX = re.compile(
    r'^(?P<title>.+?)(?: \((?P<translation>.+)\))?$')

conn = MySQLdb.connect('localhost', db='movie_recs_2', charset='utf8')
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
    cursor.execute('DROP TABLE IF EXISTS user_similar_critic')
    cursor.execute('''
        CREATE TABLE user_similar_critic (
            user_id            INT,
            critic_id          INT,
            score              FLOAT,
            rating_similarity  FLOAT,
            acceptability      FLOAT,
            num_shared_reviews INT,
            samesidedness      FLOAT,
            date_inserted   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, critic_id),
            FOREIGN KEY (user_id) REFERENCES user (id)
        ) ENGINE=InnoDB'''
    )
    cursor.execute('DROP TABLE IF EXISTS user_similar_critic_review')
    cursor.execute('''
        CREATE TABLE user_similar_critic_review (
            user_id         INT,
            critic_id       INT,
            movie_id        INT,
            rating          FLOAT,
            PRIMARY KEY (user_id, critic_id, movie_id),
            FOREIGN KEY (user_id) REFERENCES user (id)
        ) ENGINE=InnoDB'''
    )
    create_indexes([
        ('user_similar_critic_review', 'user_id'),
        ('user_similar_critic_review', 'critic_id'),
        ('user_similar_critic_review', 'movie_id')
    ])


def insert_movies():
    global movie_id2link

    cursor.execute('SET FOREIGN_KEY_CHECKS=0')

    cursor.execute('DROP TABLE IF EXISTS movie')
    cursor.execute('''CREATE TABLE movie (
        id              INT PRIMARY KEY,
        title           VARCHAR(128),
        translation     VARCHAR(128),
        year            INT,
        image           VARCHAR(128),
        link            VARCHAR(128),
        duration        VARCHAR(15),
        plot            TEXT,
        director        VARCHAR(50)
    ) ENGINE=InnoDB''')

    cursor.execute('DROP TABLE IF EXISTS movie2genre')
    cursor.execute('''CREATE TABLE movie2genre (
        movie_id        INT,
        genre           VARCHAR(32),
        PRIMARY KEY (genre, movie_id),
        FOREIGN KEY (movie_id) REFERENCES movie(id)
    ) ENGINE=InnoDB''')

    conn.commit()

    movie_id2link = bidict()
    i = 0
    with open('movies.json') as f:
        for line in f:
            r = json.loads(line)
            movie_id = r['id']
            movie_id2link[movie_id] = r['link']
            title = r['title']
            match = CLEANUP_REGEX.match(title)
            if match:
                title, translation = match.groups()
            else:
                translation = None
            year = r['year']
            if year and year != '()':
                year = int(year[1:5])
            else:
                year = None

            cursor.execute('''
                INSERT INTO movie (
                    id, title, translation, year, image,
                    link, duration, plot, director)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (movie_id, title, translation, year,
                  r['image'], r['link'], r['duration'],
                  r['plot'], r['director']))

            for genre in r['genres']:
                cursor.execute('''
                    INSERT INTO movie2genre (movie_id, genre)
                    VALUES (%s, %s)
                ''', (movie_id, genre))

            if i % 1000 == 0:
                conn.commit()
                print i
            i += 1

    create_indexes([
        ('movie', 'title'),
        ('movie', 'translation'),
        ('movie', 'year'),
        ('movie2genre', 'genre'),
    ])


def insert_critics():
    global critic_id2link

    cursor.execute('SET FOREIGN_KEY_CHECKS=0')

    cursor.execute('DROP TABLE IF EXISTS critic')
    cursor.execute('''CREATE TABLE critic (
        id              INT PRIMARY KEY,
        link            VARCHAR(50),
        name            VARCHAR(50),
        image           VARCHAR(128)
    ) ENGINE=InnoDB''')

    #cursor.execute('SET FOREIGN_KEY_CHECKS=1')

    conn.commit()

    critic_id2link = bidict()
    i = 0
    with open('reviews.json') as f:
        for line in f:
            r = json.loads(line)
            if 'name' in r:
                critic_id = len(critic_id2link)
                link = r['link']
                critic_id2link[critic_id] = link
                image = r['image']
                if image == 'https://staticv2-4.rottentomatoes.com/static/images/redesign/actor.default.tmb.gif':
                    image = None
                cursor.execute('''
                    INSERT INTO critic (id, name, link, image)
                    VALUES (%s, %s, %s, %s)
                ''', (critic_id, r['name'], link, image))

                if i % 1000 == 0:
                    conn.commit()
                    print i
                i += 1


def insert_reviews():
    global critic_id2link, movie_id2link

    cursor.execute('SET FOREIGN_KEY_CHECKS=0')

    cursor.execute('DROP TABLE IF EXISTS review')
    cursor.execute('''CREATE TABLE review (
        movie_id        INT,
        critic_id       INT,
        rating          FLOAT,
        original_rating VARCHAR(10),
        fresh           BOOLEAN,
        PRIMARY KEY (movie_id, critic_id),
        FOREIGN KEY (movie_id) REFERENCES movie(id),
        FOREIGN KEY (critic_id) REFERENCES critic(id)
    ) ENGINE=InnoDB''')

    cursor.execute('SET FOREIGN_KEY_CHECKS=1')

    conn.commit()

    seen_reviews = set()
    missing_movie_links = 0
    duplicate_reviews = 0
    missing_movies = Counter()
    unparseable_ratings = Counter()

    i = 0
    with open('reviews.json') as f:
        for line in f:
            r = json.loads(line)
            if 'name' not in r:
                critic_link = r['critic_link']
                critic_id = critic_id2link.inv[critic_link]
                movie_link = r['movie_link']

                if not movie_link:
                    missing_movie_links += 1
                    continue

                if movie_link not in movie_id2link.inv:
                    missing_movies.update([movie_link])
                    continue

                movie_id = movie_id2link.inv[movie_link]
                original_rating = r['rating'][:10]
                rating = translate_rating(original_rating)
                if rating is None:
                    unparseable_ratings.update([original_rating])

                if (critic_id, movie_id) in seen_reviews:
                    duplicate_reviews += 1
                    continue

                seen_reviews.add((critic_id, movie_id))

                cursor.execute('''
                    INSERT INTO review (movie_id, critic_id, rating,
                        original_rating, fresh)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (movie_id, critic_id, rating, original_rating,
                      r['fresh']))

                if i % 10000 == 0:
                    conn.commit()
                    print i

                i += 1

    create_indexes([
        ('review', 'rating'),
    ])

    # before i do something about just fresh/rotten
    cursor.execute('DELETE FROM review WHERE rating IS NULL')
    conn.commit()

    cursor.execute('create table meanratings as select movie_id, avg(rating) as meanrating from review group by movie_id')
    conn.commit()

    print 'missing movie links: %d/%d' % (missing_movie_links, i)
    print 'duplicate reviews: %d/%d' % (duplicate_reviews, i)
    print 'missing movies', missing_movies.most_common(20)
    print 'unparseable ratings', unparseable_ratings.most_common(20)


def insert_data():
    insert_movies()
    insert_critics()
    insert_reviews()



alpha_rating_map = {
    'A+' : 5,
    'A'  : 4.5,
    'A-' : 4,
    'B+' : 4,
    'B'  : 3.5,
    'B-' : 3,
    'C+' : 3,
    'C'  : 2.5,
    'C-' : 2,
    'D+' : 2,
    'D'  : 1.5,
    'D-' : 1,
    'F+' : 1,
    'F'  : .5,
    'F-' : .5,
}
num_rating_regex = re.compile(r"^'?([0-9\.]+)/([0-9\.]+)'?$")
def translate_rating(r):
    r = r.replace(' ', '').upper()

    if not r:
        return None

    r = r.strip()
    match = num_rating_regex.match(r)
    if match:
        num, denom = match.groups()
        try:
            rating = 5 * float(num) / float(denom)
            if rating < 0 or rating > 5:
                return None
            if rating < 0.5:
                rating = 0.5
            return rating
        except (ValueError, ZeroDivisionError):
            return None

    if r in alpha_rating_map:
        return alpha_rating_map[r]

    return None


def write_title_cache():
    titles = set()
    cursor.execute('SELECT title, translation, year FROM movie')
    for title, translation, year in cursor:
        titles.add('%s (%s)' % (title, year))
        if translation:
            titles.add('%s (%s)' % (translation, year))

    with open('titles.cpkl', 'w') as f:
        cPickle.dump(titles, f, protocol=cPickle.HIGHEST_PROTOCOL)


def write_critics_cache():
    critics = {}

    cursor.execute('SELECT id, link, name, image FROM critic')
    for critic_id, link, name, image in cursor:
        critics[critic_id] = (link, name, image)

    with open('critics.cpkl', 'w') as f:
        cPickle.dump(critics, f, protocol=cPickle.HIGHEST_PROTOCOL)


def write_movies_cache():
    movies = {}

    cursor.execute('SELECT id, title, year, image, link, duration, plot, director, GROUP_CONCAT(genre SEPARATOR "|") FROM movie m JOIN movie2genre g ON m.id = g.movie_id GROUP BY movie_id')
    for movie_id, title, year, image, link, duration, plot, director, genres in cursor:
        movies[movie_id] = (title, year, image, link, duration, plot, director, genres.split('|'))

    with open('movies.cpkl', 'w') as f:
        cPickle.dump(movies, f, protocol=cPickle.HIGHEST_PROTOCOL)


def create_indexes(indexes):
    for table, column in indexes:
        cursor.execute('CREATE INDEX {table}_{column} ON {table} ({column})'
                       .format(table=table, column=column))

    conn.commit()


def main():
    pass


if __name__ == '__main__':
    main()
