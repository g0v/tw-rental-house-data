'''filequeuecheck：4e 雙軌對帳——檔案 queue（seeds／terminals）vs DB request_ts。

    manage.py filequeuecheck [--date] [--strict]

每 vendor × request type：檔案版 reconcile（seeds／done／dead／residue）與 DB
同型計數逐項比；全部相等＝AGREE。預設 advisory（exit 0），--strict 有差即 exit 1
——切換認領路徑到檔案前要連續多日 AGREE。
'''
import json
import os
import sys
from datetime import date as date_cls, datetime

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from crawlerrequest.enums import RequestStatus, RequestType
from crawlerrequest.models import RequestTS
from rental import filequeue
from rental.models import Vendor
from rental.raws import vendor_dirname


class Command(BaseCommand):
    help = 'Compare file-based queue bookkeeping against request_ts'

    def add_arguments(self, parser):
        parser.add_argument('--date')
        parser.add_argument('--strict', action='store_true')

    def handle(self, *_args, **options):
        if options['date']:
            try:
                day = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                raise CommandError('--date 需為 YYYY-MM-DD')
        else:
            env = os.environ.get('TWRH_TARGET_DATE')
            day = datetime.strptime(env, '%Y-%m-%d').date() if env else date_cls.today()
        max_attempts = int(os.environ.get('TWRH_QUEUE_MAX_ATTEMPTS', 3))
        ts = {'year': day.year, 'month': day.month, 'day': day.day, 'hour': 0}

        all_agree = True
        checked = 0
        for vendor in Vendor.objects.all():
            short = vendor_dirname(vendor.name)
            for type_name in filequeue.type_names(short, day.isoformat()):
                request_type = RequestType[type_name.upper()]
                file_side = filequeue.reconcile(short, day.isoformat(), type_name, max_attempts)
                by_status = dict(RequestTS.objects.filter(
                    **ts, vendor=vendor, request_type=request_type)
                    .values_list('status').annotate(n=Count('id')))
                db_seeds = sum(by_status.values())
                db_done = by_status.get(int(RequestStatus.DONE), 0)
                db_dead = by_status.get(int(RequestStatus.DEAD), 0)
                db_side = {'seeds': db_seeds, 'done': db_done, 'dead': db_dead,
                           'residue': db_seeds - db_done - db_dead}
                agree = all(file_side[k] == db_side[k] for k in db_side) \
                    and not file_side['orphan_terminals']
                all_agree &= agree
                checked += 1
                print('filequeue {} {}: file seeds {seeds} = done {done} + dead {dead} + residue {residue}'
                      ' | db seeds {ds} = done {dd} + dead {dx} + residue {dr} → {verdict}'.format(
                          short, type_name, verdict='AGREE' if agree else 'DIFF',
                          ds=db_side['seeds'], dd=db_side['done'], dx=db_side['dead'],
                          dr=db_side['residue'], **file_side))
                if file_side['orphan_terminals'] or file_side['duplicate_seed_lines']:
                    print('    anomalies: {}'.format(json.dumps({
                        'orphan_terminals': file_side['orphan_terminals'],
                        'duplicate_seed_lines': file_side['duplicate_seed_lines']})))
                if file_side['errors']:
                    print('    file error breakdown: {}'.format(
                        json.dumps(file_side['errors'], ensure_ascii=False)))
        if not checked:
            print('filequeue {}: no seed files — skip'.format(day))
            return
        print('filequeuecheck: {}'.format('AGREE' if all_agree else 'DIFF'))
        if not all_agree and options['strict']:
            sys.exit(1)
