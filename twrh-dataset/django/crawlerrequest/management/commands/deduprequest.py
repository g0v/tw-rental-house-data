"""Remove duplicated request"""
from django.core.management.base import BaseCommand
from django.db import connection

SQL = """
delete from request_ts where id in (
  select id from (
    select
      min(id) as id, 
      count(*) as n
      from request_ts
      group by year, month, day, (seed->>0)
  )
  as t where n > 1
);
"""

class Command(BaseCommand):
    help = 'Remove duplicated request'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
          cursor.execute(SQL)
