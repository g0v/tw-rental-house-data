from scrapy_twrh.spiders.rental591 import Rental591Spider

class TwoSpider(Rental591Spider):
    name='two'

    def __init__(self):
        super().__init__(target_cities=['基隆市', '宜蘭縣'])

