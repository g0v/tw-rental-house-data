import os
import sys
import django
import logging

def load_django():
    # Allow Scrapy to use Django（專案改組後 Django 專案在 django/，
    # 舊路徑 ../../backend 已不存在）
    base = os.path.dirname(os.path.realpath(__file__))
    sys.path.append('{}/../django'.format(base))
    sys.path.append('{}/..'.format(base))
    os.environ['DJANGO_SETTINGS_MODULE'] = 'backend.settings'
    django.setup()

def enable_debug():
    logging.basicConfig(
        format='%(levelname)s: %(message)s',
        level=logging.DEBUG
    )