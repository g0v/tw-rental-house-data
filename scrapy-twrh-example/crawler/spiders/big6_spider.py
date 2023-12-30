from scrapy_twrh.spiders.rental591 import Rental591Spider

class Big6Spider(Rental591Spider):
    name = 'big6'

    def __init__(self):
        super().__init__(target_cities=['台北市', '新北市', '桃園市', '台中市', '台南市', '高雄市'])
