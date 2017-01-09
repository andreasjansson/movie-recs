# -*- coding: utf-8 -*-

# Define here the models for your scraped items
#
# See documentation in:
# http://doc.scrapy.org/en/latest/topics/items.html

import scrapy


class Critic(scrapy.Item):
    link = scrapy.Field()
    name = scrapy.Field()
    image = scrapy.Field()


class Review(scrapy.Item):
    critic_link = scrapy.Field()
    movie_link = scrapy.Field()
    rating = scrapy.Field()
    fresh = scrapy.Field()


class Movie(scrapy.Item):
    id = scrapy.Field()
    link = scrapy.Field()
    image = scrapy.Field()
    title = scrapy.Field()
    year = scrapy.Field()
    director = scrapy.Field()
    duration = scrapy.Field()
    genres = scrapy.Field()
    plot = scrapy.Field()
