import re
import string
import scrapy

from rottentomatoes import items

class ReviewsSpider(scrapy.Spider):
    name = 'reviews'
    allowed_domains = ["www.rottentomatoes.com"]

    def start_requests(self):
        urls = [
            'https://www.rottentomatoes.com/critics/authors?letter=%s' % c
            for c in string.lowercase
        ] + [
            'https://www.rottentomatoes.com/critics/legacy_authors?letter=%s' % c
            for c in string.lowercase
        ]

        for url in urls:
            yield scrapy.Request(url=url, callback=self.parse)

    def parse(self, response):
        critic_hrefs = response.selector.css(
            '.critic-names a[href*="/critic/"]::attr(href)'
        ).extract()
        for href in critic_hrefs:
            link = re.match(r'^/critic/([^/]+)', href).groups()[0]

            yield scrapy.Request(
                url='https://www.rottentomatoes.com/critic/%s/movies' % link,
                                 callback=self.parse_critic)

    def parse_critic(self, response):
        css = response.selector.css
        critic_link = response.url.split('/')[-1]
        name = css('#criticPanel h2.title::text')[0].extract().strip()
        image = css('.critic_thumb.fullWidth::attr(src)')[0].extract()

        yield items.Critic(link=critic_link, name=name, image=image)

        for i in self.parse_reviews(response):
            yield i

    def parse_reviews(self, response):
        critic_link = re.search(r'/critic/([^/]+)/', response.url).groups()[0]
        page = int(response.url.split('?page=')[-1]) if '?page=' in response.url else 1

        css = response.selector.css
        rows = css('.table-striped tr')

        print critic_link, page, len(rows)

        for row in rows[1:]:
            rating = row.css('td span::attr(title)')
            if len(rating):
                rating = rating[0].extract()
            else:
                rating = None
            movie_link = row.css('.movie-link::attr(href)')[0].extract().split('/')[-1]
            first_classes = row.css('td span::attr(class)')[0].extract().strip()
            fresh = 'fresh' in first_classes

            yield items.Review(critic_link=critic_link,
                               movie_link=movie_link,
                               rating=rating,
                               fresh=fresh)

        pages = response.selector.css('.pagination a::text')[2].extract()
        page_end, total = re.match('Showing [0-9]+ - ([0-9]+) of ([0-9]+)', pages).groups()

        if int(page_end) < int(total):
            yield scrapy.Request(
                url='https://www.rottentomatoes.com/critic/%s/movies?page=%d' % (
                    critic_link, page + 1),
                callback=self.parse_reviews)
