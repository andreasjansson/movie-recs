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
            yield scrapy.Request(url='https://www.rottentomatoes.com' + href,
                                 callback=self.parse_reviewer)

    def parse_reviewer(self, response):
        css = response.selector.css
        reviewer_id = response.url.split('/')[-1]
        name = css('#criticPanel h2.title::text')[0].extract().strip()
        image = css('.critic_thumb.fullWidth::attr(src)')[0].extract()

        yield items.Reviewer(id=reviewer_id, name=name, image=image)

        for i in self.parse_reviews(response):
            yield i

    def parse_reviews(self, response):
        reviewer_id = response.url.split('/')[-1].split('?')[0]
        page = int(response.url.split('?page=')[-1]) if '?page=' in response.url else 1

        css = response.selector.css
        rows = css('.table-striped tr')

        print reviewer_id, page, len(rows)

        for row in rows[1:]:
            rating = row.css('td span::attr(title)')
            if len(rating):
                rating = rating[0].extract()
            else:
                rating = None
            movie_id = row.css('.movie-link::attr(href)')[0].extract().split('/')[-1]
            first_classes = row.css('td span::attr(class)')[0].extract().strip()
            fresh = 'fresh' in first_classes

            yield items.Review(reviewer_id=reviewer_id,
                               movie_id=movie_id,
                               rating=rating,
                               fresh=fresh)

        pages = response.selector.css('.pagination a::text')[2].extract()
        page_end, total = re.match('Showing [0-9]+ - ([0-9]+) of ([0-9]+)', pages).groups()

        if int(page_end) < int(total):
            yield scrapy.Request(
                url='https://www.rottentomatoes.com/critic/%s?page=%d' % (
                    reviewer_id, page + 1),
                callback=self.parse_reviews)
