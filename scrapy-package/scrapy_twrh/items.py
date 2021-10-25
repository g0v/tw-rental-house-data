# -*- coding: utf-8 -*-

# Define here the models for your scraped items
#
# See documentation in:
# https://doc.scrapy.org/en/latest/topics/items.html

from scrapy import Field, Item


class GenericHouseItem(Item):
    top_region = Field()
    sub_region = Field()
    deal_time = Field()
    deal_status = Field()
    n_day_deal = Field()
    vendor = Field()
    vendor_house_id = Field()
    vendor_house_url = Field()
    # price related
    monthly_price = Field()
    min_monthly_price = Field()
    deposit_type = Field()
    n_month_deposit = Field()
    deposit = Field()
    is_require_management_fee = Field()
    monthly_management_fee = Field()
    has_parking = Field()
    is_require_parking_fee = Field()
    monthly_parking_fee = Field()
    per_ping_price = Field()
    # other basic info
    building_type = Field()
    property_type = Field()
    is_rooftop = Field()
    floor = Field()
    total_floor = Field()
    dist_to_highest_floor = Field()
    floor_ping = Field()
    n_living_room = Field()
    n_bed_room = Field()
    n_bath_room = Field()
    n_balcony = Field()
    apt_feature_code = Field()
    rough_address = Field()
    # (latitude, longtitude) tuple of WGS84 coordinate
    rough_coordinate = Field()
    # boolean map
    # eletricity: true, water: true, gas: true, internet: true, cable_tv: true
    additional_fee = Field()
    # school, park, dept_store, conv_store, traditional_mkt, night_mkt,
    # hospital, police_office
    living_functions = Field()
    # subway, bus, public_bike, train, hsr
    transportation = Field()
    has_tenant_restriction = Field()
    has_gender_restriction = Field()
    gender_restriction = Field()
    can_cook = Field()
    allow_pet = Field()
    has_perperty_registration = Field()
    # undermined for now
    facilities = Field()
    contact = Field()
    # an unique identifier, could be phone number, image url, etc..
    author = Field()
    agent_org = Field()
    imgs = Field()


class RawHouseItem(Item):
    house_id = Field()
    vendor = Field()
    is_list = Field()
    raw = Field()
    dict = Field()
