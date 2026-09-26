'''notify（twrhctl 版的 publish.sh 通知）：把 NOTIFY_TEXT（或 --text）以單一 mrkdwn section 發到
SLACK_WEBHOOK_URL。取代 publish.sh 原本的 `manage.py shell -c '...'`——那段只為了借 Django
settings 讀 webhook；無 Django 之後直接讀環境變數。webhook 缺就印一行略過（exit 0，同原行為）。
'''
import os

import requests

from twrhctl.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Post a mrkdwn message to SLACK_WEBHOOK_URL (publish.sh notifications)'

    def add_arguments(self, parser):
        parser.add_argument('--text', help='訊息；不給就讀環境變數 NOTIFY_TEXT')

    def handle(self, *_args, **options):
        text = options['text'] or os.environ.get('NOTIFY_TEXT')
        if not text:
            raise CommandError('需要 --text 或 NOTIFY_TEXT')
        hook = os.environ.get('SLACK_WEBHOOK_URL', '')
        if not hook:
            print('(no SLACK_WEBHOOK_URL, notify skipped)')
            return
        requests.post(hook, json={'blocks': [{'type': 'section', 'text': {
            'type': 'mrkdwn', 'text': text}}]}, timeout=10).raise_for_status()
