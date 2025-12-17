import logging
import re
from scrapy_twrh.items import RawHouseItem, GenericHouseItem
from scrapy_twrh.spiders import enums
from scrapy_twrh.spiders.util import clean_number
from .util import ListRequestMeta, DetailRequestMeta, css, parse_price
from .request_generator import RequestGenerator

class ListMixin(RequestGenerator):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.target_cities = []
        # Set to track houses we've already requested
        self.requested_houses = set()

    def default_start_list(self):
        for city in self.target_cities:
            yield self.gen_list_request(ListRequestMeta(
                city['id'],
                city['city'],
                0
            ))

    def default_parse_list(self, response):
        meta = response.meta['rental']

        page_items = css(response, '.paging li a::attr("href")')
        page_string = page_items[-1]
        page_match = re.search(r'page=(\d+)', page_string)
        if page_match:
            total_page = int(page_match.group(1))
        else:
            total_page = 1  # Default if no page number found

        logging.info('[list] crawl city:%s of %d/%d pages', meta.name, meta.page, total_page)

        if meta.page == 0:
            # generate all list request as now we know number of result
            cur_page = 1
            while cur_page < total_page:
                yield self.gen_list_request(ListRequestMeta(
                    meta.id,
                    meta.name,
                    cur_page
                ))
                cur_page += 1

        promotion_houses = self.gen_promotion_house(response)
        regular_houses = self.gen_regular_house(response)

        for house in promotion_houses + regular_houses:
            house_id = house['house_id']
            
            # Yield RawHouseItem with both raw HTML and parsed dict
            yield RawHouseItem(
                house_id=house_id,
                vendor=house['vendor'],
                is_list=True,
                raw=house['raw'],
                dict=house.get('dict', {})
            )
            
            # Transform and yield GenericHouseItem
            if 'dict' in house and house['dict']:
                generic_item = self._transform_list_to_generic(house_id, house['dict'], meta.name)
                yield GenericHouseItem(**generic_item)
            
            # Only generate detail request if we haven't seen this house before
            if house_id not in self.requested_houses:
                self.requested_houses.add(house_id)
                yield self.gen_detail_request(DetailRequestMeta(house_id))

    def gen_promotion_house(self, response):
        """
        Parse .recommend-ware divs (promoted houses)
        Returns list of dicts with house_id, vendor, raw HTML, and parsed dict
        """
        houses = []
        houses_resp = response.css('.recommend-ware')
        for house in houses_resp:
            url = house.css('a.title::attr("href")').get()
            if not url:
                continue
            # url can be 'https://rent.591.com.tw/20267611' or 'https://rent.591.com.tw/20267611?is_ai_video=1&ai_title_id=5673585'
            house_id = url.split('/')[-1].split('?')[0]
            
            # Extract raw data
            raw_dict = self._parse_promotion_raw(house)
            
            houses.append({
                'vendor': self.vendor,
                'house_id': house_id,
                'raw': house.get(),
                'dict': raw_dict
            })

        return houses

    def _extract_title(self, house, title_selector):
        """Extract title from house element"""
        title = css(house, title_selector)
        return title[0] if title else None

    def _extract_images(self, house):
        """Extract images from .image-slider"""
        images = house.css('.image-slider img::attr(data-src)').getall()
        return images if images else None

    def _extract_landmark_info(self, landmark_text, distance_text):
        """Extract landmark and distance if present"""
        result = {}
        if landmark_text and distance_text and '距' in landmark_text[0]:
            result['nearby_landmark'] = landmark_text[0]
            result['distance_to_landmark'] = distance_text[0]
        return result

    def _parse_promotion_raw(self, house):
        """Extract raw fields from .recommend-ware div"""
        raw_dict = {}
        
        # Title
        title = self._extract_title(house, 'a.title::text')
        if title:
            raw_dict['title'] = title
        
        # Location info
        location_parts = css(house, '.address-info span::text')
        if location_parts:
            # First span is community (optional)
            if len(location_parts) >= 1 and '-' not in location_parts[0]:
                raw_dict['community'] = location_parts[0]
                if len(location_parts) >= 2:
                    raw_dict['location'] = location_parts[1]
            else:
                raw_dict['location'] = location_parts[0]
        
        # Area (坪)
        area = css(house, '.address-info .area::text')
        if area:
            raw_dict['area'] = area[0]
        
        # Distance to landmark
        landmark = css(house, '.distance-info .desc::text')
        distance = css(house, '.distance-info .distance::text')
        landmark_info = self._extract_landmark_info(landmark, distance)
        raw_dict.update(landmark_info)
        
        # Price
        price = css(house, '.price-info .price::text')
        if price:
            raw_dict['price'] = price[0]
        
        # Images
        images = self._extract_images(house)
        if images:
            raw_dict['images'] = images
        
        return raw_dict

    def gen_regular_house(self, response):
        """
        Parse .item divs (regular houses)
        Returns list of dicts with house_id, vendor, raw HTML, and parsed dict
        """
        houses = []
        houses_resp = response.css('.item')
        for house in houses_resp:
            url = house.css('.item-info-title a::attr("href")').get()
            if not url:
                continue
            # url can be 'https://rent.591.com.tw/20267611' or 'https://rent.591.com.tw/20267611?is_ai_video=1&ai_title_id=5673585'
            house_id = url.split('/')[-1].split('?')[0]
            
            # Extract raw data
            raw_dict = self._parse_regular_raw(house)
            
            houses.append({
                'vendor': self.vendor,
                'house_id': house_id,
                'raw': house.get(),
                'dict': raw_dict
            })

        return houses

    def _parse_regular_raw(self, house):
        """Extract raw fields from .item div"""
        raw_dict = {}
        
        # Title
        title = self._extract_title(house, '.item-info-title a::text')
        if title:
            raw_dict['title'] = title
        
        # Tags
        tags = css(house, '.item-info-tag .tag::text')
        if tags:
            raw_dict['tags'] = tags
        
        # Property info from .item-info-txt spans
        # First row: property_type, rooms, area, floor
        info_texts = house.css('.item-info-txt')
        
        if len(info_texts) >= 1:
            # Parse property type and room info
            first_row = info_texts[0]
            spans = css(first_row, 'span::text')
            
            if len(spans) >= 1:
                raw_dict['property_type'] = spans[0]
            
            # Room/hall info (only for 整層住家)
            if len(spans) >= 2 and '房' in spans[1]:
                raw_dict['room_hall_info'] = spans[1]
            
            # Area - using self_text to handle .inline-flex-row obfuscation
            area = css(first_row, 'span .inline-flex-row', self_text=True)
            if area and '坪' in ''.join(area):
                for a in area:
                    if '坪' in a:
                        raw_dict['area'] = a
                        break
            
            # Floor - using self_text to handle .inline-flex-row obfuscation
            floor = css(first_row, 'span .inline-flex-row', self_text=True)
            if floor and 'F' in ''.join(floor):
                for f in floor:
                    if 'F' in f:
                        raw_dict['floor'] = f
                        break
        
        # Second row: community and location
        if len(info_texts) >= 2:
            second_row = info_texts[1]
            spans = css(second_row, 'span::text')
            
            if len(spans) >= 1:
                raw_dict['community'] = spans[0]
            
            # Location - using self_text for .inline-flex-row
            location = css(second_row, 'span .inline-flex-row', self_text=True)
            if location:
                raw_dict['location'] = location[0]
        
        # Third row: nearby landmark and distance (optional)
        # Or contact info if no landmark
        if len(info_texts) >= 3:
            third_row = info_texts[2]
            landmark = css(third_row, 'span::text')
            distance = css(third_row, 'strong::text')
            
            # Check if this row has landmark info (has "距" prefix)
            landmark_info = self._extract_landmark_info(landmark, distance)
            if landmark_info:
                raw_dict.update(landmark_info)
            else:
                # No landmark, this is contact info row
                spans = css(third_row, 'span::text')
                if len(spans) >= 1:
                    raw_dict['contact_info'] = spans[0]
                if len(spans) >= 2:
                    raw_dict['update_time'] = spans[1]
                if len(spans) >= 3:
                    raw_dict['view_count'] = spans[2]
        
        # Fourth row: contact info, update time, view count (only if landmark exists)
        if len(info_texts) >= 4 and 'contact_info' not in raw_dict:
            fourth_row = info_texts[3]
            spans = css(fourth_row, 'span::text')
            
            if len(spans) >= 1:
                raw_dict['contact_info'] = spans[0]
            
            if len(spans) >= 2:
                raw_dict['update_time'] = spans[1]
            
            if len(spans) >= 3:
                raw_dict['view_count'] = spans[2]
        
        # Price - using self_text for .inline-flex-row
        price = css(house, '.item-info-price strong .inline-flex-row', self_text=True)
        if price:
            raw_dict['price'] = price[0]
        
        # Images
        images = self._extract_images(house)
        if images:
            raw_dict['images'] = images
        
        # Check if featured/preferred
        if house.css('.tag.recom').get():
            raw_dict['is_featured'] = True
        
        if house.css('.tag.preferred').get():
            raw_dict['is_preferred'] = True
        
        return raw_dict

    def _transform_list_to_generic(self, house_id, raw_dict, top_region_name):
        """
        Transform raw dict to GenericHouseItem
        Similar to detail_mixin's gen_detail_shared_attrs but for list page data
        """
        ret = {
            'vendor': self.vendor,
            'vendor_house_id': house_id,
            'deal_status': enums.DealStatusType.OPENED,
        }
        
        # Parse top_region from city name
        ret['top_region'] = self.get_enum(
            enums.TopRegionType,
            house_id,
            top_region_name
        )
        
        # Parse sub_region from location string
        if 'location' in raw_dict:
            location = raw_dict['location']
            # Format: "花蓮市-中正路" -> sub_region is "花蓮市"
            if '-' in location:
                sub_region_name = location.split('-')[0]
                ret['sub_region'] = self.get_enum(
                    enums.SubRegionType,
                    house_id,
                    f'{top_region_name}{sub_region_name}'
                )
            ret['rough_address'] = location
        
        # Parse price
        if 'price' in raw_dict:
            price_str = raw_dict['price'].replace(',', '')
            price_range = parse_price(price_str)
            ret['monthly_price'] = price_range['monthly_price']
            if 'min_monthly_price' in price_range:
                ret['min_monthly_price'] = price_range['min_monthly_price']
        
        # Parse property type
        if 'property_type' in raw_dict:
            property_type = raw_dict['property_type']
            try:
                ret['property_type'] = self.get_enum(
                    enums.PropertyType,
                    house_id,
                    property_type
                )
            except (ValueError, KeyError):
                # Ignore unknown property types
                pass
        
        # Skip parking lots (車位)
        if ret.get('property_type') == enums.PropertyType.車位:
            return ret
        
        # Parse area (floor_ping)
        if 'area' in raw_dict:
            area_str = raw_dict['area'].replace('坪', '')
            area = clean_number(area_str)
            if area:
                ret['floor_ping'] = area
        
        # Parse floor info
        if 'floor' in raw_dict:
            floor_str = raw_dict['floor']
            # Format: "1F/2F", "頂樓加蓋/2F", "B1/2F", 整棟/2F or 平面式, 1F~3F/3F
            floor_parts = floor_str.split('/')
            
            if len(floor_parts) >= 2:
                floor = clean_number(floor_parts[0].split('~')[0])  # for 1F~3F
                total_floor = clean_number(floor_parts[1])
                
                if total_floor:
                    ret['total_floor'] = total_floor
                ret['is_rooftop'] = False

                # mark 整棟 as floor 0
                ret['floor'] = 0
                
                if floor_parts[0] == '頂樓加蓋' and total_floor:
                    ret['is_rooftop'] = True
                    ret['floor'] = total_floor + 1
                elif 'B' in floor_parts[0] and floor:
                    # basement
                    ret['floor'] = floor * -1
                elif floor:
                    ret['floor'] = floor
                
                if 'floor' in ret and 'total_floor' in ret:
                    ret['dist_to_highest_floor'] = ret['total_floor'] - ret['floor']
        
        # Parse room/hall/bath info (only for 整層住家)
        if 'room_hall_info' in raw_dict:
            room_info = raw_dict['room_hall_info']
            # Format: "2房1廳" or "3房2廳1衛"
            apt_parts = re.findall(r'(\d)([^\d]+)', room_info)
            
            if len(apt_parts) >= 1:
                ret['n_bed_room'] = clean_number(apt_parts[0])
            
            if len(apt_parts) >= 2:
                ret['n_living_room'] = clean_number(apt_parts[1])
            
            if len(apt_parts) >= 3:
                ret['n_bath_room'] = clean_number(apt_parts[2])
            
            # Calculate apt_feature_code if we have room info
            if 'n_bed_room' in ret:
                n_balcony = 0  # list page doesn't show balcony info
                ret['apt_feature_code'] = '{:02d}{:02d}{:02d}{:02d}'.format(
                    n_balcony,
                    ret.get('n_bath_room', 0),
                    ret.get('n_bed_room', 0),
                    ret.get('n_living_room', 0)
                )
        
        # Parse contact info
        if 'contact_info' in raw_dict:
            contact_str = raw_dict['contact_info']
            # Format: "仲介 name" or "屋主 name"
            if '仲介' in contact_str:
                ret['contact'] = enums.ContactType.房仲
            elif '屋主' in contact_str:
                ret['contact'] = enums.ContactType.屋主
            elif '代理人' in contact_str:
                ret['contact'] = enums.ContactType.代理人
        
        # Parse tags for boolean flags
        if 'tags' in raw_dict:
            tags = raw_dict['tags']
            
            # Check for cooking
            if '可開伙' in tags:
                ret['can_cook'] = True
            
            # Check for pet
            if '可養寵物' in tags:
                ret['allow_pet'] = True
            
            # Store facilities from tags
            facilities = {}
            facility_mapping = {
                '有電梯': '電梯',
                '有陽台': '陽台',
                '有車位': '車位',
                '有冷氣': '冷氣',
                '近捷運': '近捷運',
                '近商圈': '近商圈',
            }
            
            for tag in tags:
                if tag in facility_mapping:
                    facilities[facility_mapping[tag]] = True
                elif tag not in ['新上架', '拎包入住', '可開伙', '可養寵物', '精選', '優選好屋']:
                    # Store other tags as-is
                    facilities[tag] = True
            
            if facilities:
                ret['facilities'] = facilities
        
        # Parse images
        if 'images' in raw_dict:
            ret['imgs'] = raw_dict['images']
        
        # Calculate per_ping_price if we have both price and area
        if 'monthly_price' in ret and 'floor_ping' in ret:
            monthly_price = ret['monthly_price']
            floor_ping = ret['floor_ping']
            if monthly_price and floor_ping and floor_ping > 0:
                ret['per_ping_price'] = monthly_price / floor_ping
        
        return ret
