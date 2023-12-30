import os
import sys
import django
import logging

def load_django():
    # Allow Scrapy to use Django
    sys.path.append('{}/../../backend'.format(os.path.dirname(os.path.realpath(__file__))))
    os.environ['DJANGO_SETTINGS_MODULE'] = 'backend.settings'
    django.setup()

def enable_debug():
    logging.basicConfig(
        format='%(levelname)s: %(message)s',
        level=logging.DEBUG
    )