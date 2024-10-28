import re
from collections import namedtuple
from scrapy.http import Response
from scrapy_twrh.spiders.util import clean_number

SITE_URL = 'https://rent.591.com.tw'
API_URL = 'https://bff-house.591.com.tw'
LIST_ENDPOINT = f'{API_URL}/v1/web/rent/list?'
DETAIL_ENDPOINT = f'{SITE_URL}/'
SESSION_ENDPOINT = '{}/?kind=0&region=6'.format(SITE_URL)

ListRequestMeta = namedtuple('ListRequestMeta', ['id', 'name', 'page'])

DetailRequestMeta = namedtuple('DetailRequestMeta', ['id'])

zh_number_dict = {
    '零': 0,
    '一': 1,
    '二': 2,
    '三': 3,
    '四': 4,
    '五': 5,
    '六': 6,
    '七': 7,
    '八': 8,
    '九': 9,
    '十': 10
}

def parse_price(number_string: str):
    '''
    #87, 社會住宅's monthly_price is a range
    '''
    tokens = number_string.split('~')
    price = clean_number(tokens[0])
    ret = { 'monthly_price':  price }
    if len(tokens) >= 2:
        ret['min_monthly_price'] = clean_number(tokens[1])

    return ret

def reorder_inline_flex_dom(base: Response, selector):
    '''
    Issue #181, we may get innerHTML like <span> <i style="order:2;font-style:normal;">5</i></span>
    '''
    items = base.css(selector)
    ret = []
    for item in items:
        # child span may contain style="display:inline-flex;flex-direction:row-reverse;"
        i_list = item.css('span[style*=display\\:inline-flex] > i')
        plain_value = item.xpath('text()').get()
        if plain_value is not None:
            ret.append(plain_value)
        elif i_list:
            # check if it's reversed, find all values of flex-direction
            container_style = item.css('span[style*=display\\:inline-flex]::attr(style)').get()

            # we may have multiple flex-direction, get last one
            flex_directions = re.findall(r'flex-direction: ?([\w-]+)', container_style)
            order_base = 1
            if flex_directions:
                last_flex_direction = flex_directions[-1]
                if last_flex_direction == 'row-reverse':
                    order_base = -1
            # store i_list order (in style:order) and its ::text content)
            shuffled_list = []
            for i in i_list:
                order = i.css('::attr(style)').re_first(r'order:(\d+)')
                order = int(order) * order_base
                text = i.css('::text').get()
                shuffled_list.append((order, text))
            # sort by order
            shuffled_list.sort(key=lambda x: x[0])
            ret.append(''.join(map(lambda x: x[1], shuffled_list)))
    return ret

def css(base: Response, selector, default=None, deep_text=False, self_text=False):
    '''retrieve text in clean way'''
    if self_text:
        ret = reorder_inline_flex_dom(base, selector)
    elif deep_text:
        # Issue #30, we may get innerHTML like "some of <kkkk></kkkk>target <qqq></qqq>string"
        # deep_text=True retrieve text in the way different from ::text,
        # which will also get all child text.
        ret = map(lambda dom: ''.join(dom.css('*::text').getall()), base.css(selector))
    else:
        ret = base.css(selector).getall()
    if not ret:
        ret = [] if default is None else default

    ret = clean_string(ret)
    return list(ret)

def clean_string(strings):
    '''
    remove empty and strip
    '''
    strings = filter(lambda str: str.replace('\xa0', '').strip(), strings)
    strings = map(lambda str: str.replace('\xa0', '').strip(), strings)
    return strings

def from_zh_number(zh_number):
    '''
    一二三 -> 123
    '''
    if zh_number in zh_number_dict:
        return zh_number_dict[zh_number]
    else:
        raise Exception('ZH number {} not defined.'.format(zh_number))


class SimpleNuxtInitParser:
    '''
    A simple parser to read nuxt init script, without using AST
    '''
    def __init__(self, script):
        self.script = script
        self.arguments = self.list_arguments()
        self.values = self.list_values()
        self.dict = self.compose_arg_dict()

    def list_arguments(self):
        '''
        get arguments of the function call using regex, and store them in a list
        match: function(a, b, c, d, ...)
        '''
        matches = re.search(r'function ?\(([^)]+)\)', self.script)
        if not matches:
            return []

        return map(
            lambda x: x.strip(),
            matches.group(1).split(',')
        )

    def list_values(self):
        '''
        get values of the function call using regex, and store them in a list
        match: }(a, b, c, ...)
        '''
        matches = re.search(r'}\((.+)\)\)', self.script)
        if not matches:
            return []

        value_str = matches.group(1)
        # dirty hack 0, remove font-family as there is a comma in the string
        value_str = re.sub(r'font-family:[^;]+;', '', value_str)

        # dirty hack 1, remove comma from "12,345" XD
        value_str = re.sub(r'"(\d+),(\d+)"', r'\1\2', value_str)
        ret = []
        for raw_value in value_str.split(','):
            # remove leading and trailing double quotes
            value = raw_value.strip(' "')
            ret.append(value)

        return ret

    def compose_arg_dict(self):
        '''
        compose a dictionary of arguments and their values
        '''
        arg_dict = {}
        for i, arg in enumerate(self.arguments):
            if i >= len(self.values):
                break
            arg_dict[arg] = self.values[i]

        return arg_dict

    def get_component_arg_list(self, arg_list):
        '''
        retrieve multiple arguments and their values, in the same depth of object
        nested object, say, favData.area, is not supported

        unhandled case:
        favData: { otherNestedVar: { haha: a }, title: 'title' }

        arg_list is order sensitive
        '''
        arg_vars = []
        if not arg_list:
            raise ValueError('arg_list is empty')

        reg_pattern = f'{arg_list[0]}: ?([^,{{}} ]+)'
        for arg in arg_list[1:]:
            reg_pattern += f', ?{arg}: ?([^,{{}} ]+)'

        matches = re.findall(reg_pattern, self.script)
        if not matches:
            return None

        # group matches into a list of dictionaries
        for match in matches:
            single_match = {}
            for i, arg_name in enumerate(arg_list):
                if i >= len(match):
                    break
                var_name = match[i]
                if var_name in self.dict:
                    single_match[arg_name] = self.dict[var_name]
                else:
                    single_match[arg_name] = None

            arg_vars.append(single_match)

        return arg_vars

    def get_component_arg_var(self, arg_name):
        '''
        use regex to find target string: [arg_name]: [var_name]
        arg_name can contain dot, say, favData.area

        regex pattern: [arg_name]: ([^,]+)
        match: [arg_name]: var_name
        group 1: var_name
        '''
        arg_name_list = arg_name.split('.')
        reg_pattern = ''
        if len(arg_name_list) > 1:
            # handle favData.title, which will looks like
            # favData: { otherVar: sth, title: 'title' }
            # unhandled case:
            # favData: { otherNestedVar: { haha: a }, title: 'title' }
            reg_pattern = f'{arg_name_list[0]}: ?{{[^}}]*'
            for i in range(1, len(arg_name_list) - 1):
                reg_pattern += f'{arg_name_list[i]}: ?{{[^}}]'

        reg_pattern += f'{arg_name_list[-1]}: ?([^, ]+)'

        # find all matches
        matches = re.findall(reg_pattern, self.script)
        if not matches:
            return None

        # if there are more than one match and var_name is not unique, raise error
        if len(matches) > 1:
            unique_vars = list(set(matches))
            if len(unique_vars) > 1:
                raise ValueError(f'Variable name {arg_name} is not unique')
            return unique_vars[0]

        return matches[0]

    def get_component_arg_value(self, arg_name):
        '''
        get value of the argument
        '''
        arg_var = self.get_component_arg_var(arg_name)
        if not arg_var:
            return None

        if arg_var not in self.dict:
            return None

        return self.dict[arg_var]
