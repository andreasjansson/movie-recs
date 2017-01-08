import scrapy

from rottentomatoes import items

class MoviesSpider(scrapy.Spider):
    name = 'movies'
    allowed_domains = ["www.rottentomatoes.com", "www.flixster.com"]

    def start_requests(self):
        i = 0
        with open('movie_links.txt') as f:
            for line in f:
                i += 1
                print i, line

                movie_link = line.strip()
                url = 'https://www.rottentomatoes.com/m/%s' % movie_link
                yield scrapy.Request(url=url, callback=self.parse,
                                     meta={'movie_link': movie_link})

    def parse(self, response):
        movie_id = response.selector.css('meta[name=movieID]::attr(content)')[0].extract()

        yield scrapy.Request(url='https://www.flixster.com/movie/' + movie_id,
                             callback=self.parse_flixter,
                             meta={'movie_link': response.meta['movie_link'],
                                   'movie_id': movie_id})

    def parse_flixter(self, response):
        css = response.selector.css

        image = css('img.poster::attr(src)')[0].extract()
        title = css('.title-and-year .title::text')[0].extract()
        year = css('.title-and-year .year::text')[0].extract()
        director_el = css('span[itemprop=director] span[itemprop=name]::text')
        if director_el:
            director = director_el[0].extract()
        else:
            director = None
        duration_el = css('time[itemprop=duration]::text')
        if duration_el:
            duration = duration_el[0].extract()
        else:
            duration = None
        genres = css('div.genre span[itemprop=genre]::text').extract()
        plot_el = css('span.hidden[itemprop=description]::text')
        if plot_el:
            plot = plot_el[0].extract()
        else:
            plot = ''
            print 'missing plot:', response.meta['movie_link']

        movie_id=response.meta['movie_id']
        movie_link=response.meta['movie_link']

        yield items.Movie(
            id=movie_id,
            link=movie_link,
            image=image,
            title=title,
            year=year,
            director=director,
            duration=duration,
            genres=genres,
            plot=plot,
        )
