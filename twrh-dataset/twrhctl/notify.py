'''Slack 通知（crawlerrequest/notify.py 的無 Django 版：webhook 讀環境變數）。'''
import json
import os

import requests


def send_slack(message, is_error=False, title=None):
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL', '')
    if not webhook_url:
        return False

    blocks = []
    if title:
        blocks.append({
            'type': 'header',
            'text': {'type': 'plain_text', 'text': title, 'emoji': True},
        })
    blocks.append({
        'type': 'section',
        'text': {'type': 'mrkdwn', 'text': message},
    })
    payload = {'blocks': blocks}
    if is_error:
        payload['attachments'] = [{
            'color': '#ff0000',
            'blocks': [{
                'type': 'section',
                'text': {'type': 'mrkdwn', 'text': '⚠️ *錯誤警告*'},
            }],
        }]

    try:
        response = requests.post(
            webhook_url,
            data=json.dumps(payload),
            headers={'Content-Type': 'application/json'},
            timeout=10,
        )
        response.raise_for_status()
        return True
    except requests.RequestException as err:
        print('Failed to send Slack notification: {}'.format(err))
        return False
