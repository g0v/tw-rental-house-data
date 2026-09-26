'''filequeuecheck（twrhctl 版）：4e 雙軌對帳在 S4b 之後沒有對照物（request_ts 沒人寫），
Django 版此時只印一行 skip；這裡同一行、同一判定。TWRH_QUEUE_DB=1（DB 記帳回退）需要 DB，拒跑。'''
import argparse  # noqa: F401 — 參數與 Django 版同形

from twrhctl.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'File queue vs request_ts reconciliation (skip since S4b; DB mode refused)'

    def add_arguments(self, parser):
        parser.add_argument('--date')
        parser.add_argument('--strict', action='store_true')

    def handle(self, *_args, **options):
        from rental import filequeue
        if filequeue.db_bookkeeping():
            raise CommandError('TWRH_QUEUE_DB=1（request_ts 對帳）需要 DB，twrhctl 不支援')
        print('filequeuecheck: skip (DB bookkeeping off — file queue is the only ledger since S4b)')
