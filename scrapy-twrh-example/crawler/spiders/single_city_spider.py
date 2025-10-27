from scrapy_twrh.spiders.rental591 import Rental591Spider
from scrapy_twrh.spiders.enums import TopRegionType


class SingleCitySpider(Rental591Spider):
    name = 'singleCity'

    def __init__(self, *args, city=None, **kwargs):
        """
        Spider that accepts a single city via command line argument.
        
        Usage:
            scrapy crawl singleCity -a city="台北市"
            scrapy crawl singleCity -a city="新北市"
        
        Args:
            city: The name of the city to crawl. Must be a valid city from TopRegionType enum.
        """
        if not city:
            raise ValueError(
                "City parameter is required. Usage: scrapy crawl singleCity -a city=\"台北市\"\n"
                "Valid cities: " + ", ".join([member.name for member in TopRegionType])
            )
        
        # Validate city name against TopRegionType enum
        valid_cities = [member.name for member in TopRegionType]
        if city not in valid_cities:
            raise ValueError(
                f"Invalid city name: '{city}'. Must be one of: {', '.join(valid_cities)}"
            )
        
        # Initialize spider with the validated city
        super().__init__(target_cities=[city], *args, **kwargs)
        self.logger.info(f'SingleCitySpider initialized for city: {city}')
