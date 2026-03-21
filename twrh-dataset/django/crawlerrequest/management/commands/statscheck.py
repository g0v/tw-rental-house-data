import os
from datetime import datetime, timedelta
from django.utils import timezone
from django.core.management.base import BaseCommand
from django.db.models import Count, IntegerField
from django.conf import settings
import sentry_sdk
import requests
import json
from crawlerrequest.models import RequestTS, Stats
from crawlerrequest.enums import RequestType
from rental import models
from rental.models import House, HouseTS, Vendor
from rental.enums import DealStatusType

class Command(BaseCommand):
    help = 'Generate daily crawler statistics and error, if any'
    requires_migrations_checks = True

    def send_slack_notification(self, message, is_error=False):
        """Send notification to Slack with rich formatting"""
        webhook_url = getattr(settings, 'SLACK_WEBHOOK_URL', '')
        
        if not webhook_url:
            return
        
        try:
            # Create rich Slack message with blocks
            timestamp = f"{self.this_ts['year']}/{self.this_ts['month']}/{self.this_ts['day']}"
            
            payload = {
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"📊 租屋爬蟲統計 - {timestamp}",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": message
                        }
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"時間: {timestamp} | 時段: {self.this_ts['hour']}:00"
                            }
                        ]
                    }
                ]
            }
            
            # Add color bar for errors
            if is_error:
                payload["attachments"] = [{
                    "color": "#ff0000",
                    "blocks": [{
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "⚠️ *錯誤警告*"
                        }
                    }]
                }]
            
            response = requests.post(
                webhook_url,
                data=json.dumps(payload),
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            response.raise_for_status()
            
        except (requests.RequestException, json.JSONDecodeError) as e:
            error_msg = f"Failed to send Slack notification: {str(e)}"
            print(error_msg)
            # Report Slack notification failures to Sentry if configured
            if getattr(settings, 'SENTRY_DSN', ''):
                sentry_sdk.capture_exception(e)

    def get_vendor_stats(self, vendor_id):
        if vendor_id not in self.stats:
            vendor_stats, _ = Stats.objects.get_or_create(
                **self.this_ts,
                vendor=self.vendors[vendor_id]
            )

            # reset everything, so we get latest status
            for field in Stats._meta.get_fields():  # pylint: disable=protected-access
                if field.__class__ is IntegerField and field.name.startswith('n_'):
                    setattr(vendor_stats, field.name, 0)

            self.stats[vendor_id] = vendor_stats

        return self.stats[vendor_id]

    def handle(self, *_args, **_options):
        self.this_ts = {
            'year': models.current_year(),
            'month': models.current_month(),
            'day': models.current_day(),
            'hour': models.current_stepped_hour()
        }

        self.vendors = {}
        for vendor in Vendor.objects.all():
            self.vendors[vendor.id] = vendor

        self.stats = {}

        # get every remaining request, include pending request
        failed_query = RequestTS.objects.filter(
            **self.this_ts
        ).values(
            'request_type',
            'vendor'
        ).annotate(
            count=Count('id')
        )

        for row in failed_query:
            vendor_stats = self.get_vendor_stats(row['vendor'])

            if row['request_type'] == RequestType.LIST:
                vendor_stats.n_list_fail = row['count']
            else:
                vendor_stats.n_fail = row['count']
        
        # get today's successed query
        successed_query = HouseTS.objects.filter(
            **self.this_ts
        ).values(
            'vendor',
            'deal_status'
        ).annotate(
            count=Count('id')
        )

        for row in successed_query:
            vendor_stats = self.get_vendor_stats(row['vendor'])

            if row['deal_status'] == DealStatusType.OPENED:
                # n_crawled = opened + not found + dealt
                vendor_stats.n_crawled = row['count']
            elif row['deal_status'] == DealStatusType.NOT_FOUND:
                vendor_stats.n_closed = row['count']
            elif row['deal_status'] == DealStatusType.DEAL:
                vendor_stats.n_dealt = row['count']

        # get today's new item
        override = os.environ.get('TWRH_TARGET_DATE')
        if override:
            today_start = timezone.make_aware(datetime.strptime(override, '%Y-%m-%d'))
        else:
            today_start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        new_item_query = House.objects.filter(
            created__gte=today_start,
            created__lt=today_end
        ).values(
            'vendor'
        ).annotate(
            count=Count('id')
        )

        for row in new_item_query:
            vendor_stats = self.get_vendor_stats(row['vendor'])
            vendor_stats.n_new_item = row['count']

        for vendor_id, vendor_stats in self.stats.items():
            vendor_stats.n_crawled += vendor_stats.n_closed + vendor_stats.n_dealt
            vendor_stats.n_expected = vendor_stats.n_crawled + vendor_stats.n_fail
            vendor_stats.save()

            if vendor_stats.n_fail or vendor_stats.n_list_fail:
                error_msg = f'{self.this_ts["year"]}/{self.this_ts["month"]}/{self.this_ts["day"]}: Vendor {vendor_stats.vendor.name} get failed list/detail ({vendor_stats.n_list_fail}/{vendor_stats.n_fail}) requests'
                print(error_msg)
                sentry_sdk.capture_message(error_msg)
                
                # Send Slack notification with rich formatting
                slack_msg = (
                    f"*{vendor_stats.vendor.name}* ⚠️\n"
                    f"• 失敗的列表請求: `{vendor_stats.n_list_fail}`\n"
                    f"• 失敗的詳細請求: `{vendor_stats.n_fail}`\n"
                    f"• 總失敗數: `{vendor_stats.n_list_fail + vendor_stats.n_fail}`"
                )
                self.send_slack_notification(slack_msg, is_error=True)
            else:
                msg = f'{self.this_ts["year"]}/{self.this_ts["month"]}/{self.this_ts["day"]}: Vendor {vendor_stats.vendor.name} get total/closed/dealt ({vendor_stats.n_crawled}/{vendor_stats.n_closed}/{vendor_stats.n_dealt}) requests'
                print(msg)
                
                # Send Slack notification with rich formatting
                slack_msg = (
                    f"*{vendor_stats.vendor.name}* ✅\n"
                    f"• 總爬取數: `{vendor_stats.n_crawled}`\n"
                    f"• 已關閉: `{vendor_stats.n_closed}`\n"
                    f"• 已成交: `{vendor_stats.n_dealt}`\n"
                    f"• 新增物件: `{vendor_stats.n_new_item}`"
                )
                self.send_slack_notification(slack_msg, is_error=False)
