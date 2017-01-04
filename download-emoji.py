# -*- coding: utf-8 -*-

from bs4 import BeautifulSoup
import requests
import urllib

emojis = unicode('😈👿👹👺💩👻💀👽👾🎃😡🐶🐱🐭🐹🐰🐻🐼🐨🐯🐮🐷🐽🐸🐵🙊🙉🙊🐒🐔🐧🐦🐤🐣🐥🐺🐗🐴🐝🐛🐌🐚🐞🐜🐙🐠🐟🐡🐬🐳🐋🐊🐓🕊🐇🐁🐀🐿🐉🐲', 'utf-8')

def get_emoji_url(emoji):
    url = u'http://emojipedia.org/' + emoji
    ret = requests.get(url)

    soup = BeautifulSoup(ret.text)
    img = soup.select('div.vendor-image img')
    return (ret.url, img[0]['src'])

def download_emoji_urls():
    for i in range(0, len(emojis), 2):
        emoji = emojis[i:i + 2]
        url, src = get_emoji_url(emoji)
        name = url.replace('http://emojipedia.org/', '').replace('/', '')
        urllib.urlretrieve(src, 'static/images/avatars/%s.png' % name)
        print name, emoji
