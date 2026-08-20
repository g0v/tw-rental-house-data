'''
Pick the detail parser which matches the HTML at hand.

591 redesigned the detail page in 2026 and moved every container the old
parser reads, so one parser cannot cover both templates. Each template has its
own module, named after the date its HTML was gathered:

    detail_raw_parser_20251209  the template 591 served up to the redesign
    detail_raw_parser_20260820  the template 591 serves today

Crawling only ever meets today's template. The old one still matters because
`HouseEtc.detail_raw` holds years of pages in it, and
`twrh-dataset/tools/rerun_detail_raw.py` re-parses those without re-crawling,
so it has to keep working, unchanged, forever.

Adding the next template means adding the next dated module and its marker
here - never editing an older one, or every archived page silently re-parses
into something else.
'''
import logging

from . import detail_raw_parser_20251209 as legacy_parser
from . import detail_raw_parser_20260820 as current_parser

logger = logging.getLogger(__name__)

# Containers only the old template has. They are what
# detail_raw_parser_20251209 reads for 租金含 / 產權登記, 提供設備, 房屋守則
# and the obfuscated price / floor / area.
LEGACY_MARKERS = ', '.join([
    '.house-detail .content.left',
    '.house-detail .content.right',
    '.service .service-cate',
    '.service .service-facility',
    'wc-obfuscate-c-price',
    'wc-obfuscate-c-floor',
    'wc-obfuscate-c-area',
])

def pick_parser(response):
    '''
    Return the parser module for this page.

    Today's template is the default: a page carrying neither template's
    markers is far more likely to be a new one 591 changed again than an
    archived page, and the current parser is the one worth fixing then. Only a
    page which actually shows the old containers goes to the old parser.
    '''
    if response.css(LEGACY_MARKERS):
        logger.debug('Parsing %s as pre-2026 HTML', response.url)
        return legacy_parser

    return current_parser

def get_detail_raw_attrs(response):
    '''
    parse detail page HTML and find all fields in best effort
    keep original text, without any processing, so that we can re-parse it later
    '''
    return pick_parser(response).get_detail_raw_attrs(response)
