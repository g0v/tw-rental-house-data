'''最小 Slack 通知 helper（1-1 queuefinalize 用）。

statscheck 自帶一套 rich blocks 版本；告警通道的完整收斂是 1-2
（manifest 統一）的事，這裡先不動它，只提供 queuefinalize 需要的
單一函數。設定走 settings.SLACK_WEBHOOK_URL（.env），未設即靜默略過。
'''
import json

import requests
from django.conf import settings


def send_slack(message, is_error=False, title=None):
    webhook_url = getattr(settings, 'SLACK_WEBHOOK_URL', '')
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
