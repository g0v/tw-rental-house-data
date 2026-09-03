"""Remove duplicated request"""
from django.core.management.base import BaseCommand
from django.db import connection

# status < 10：只在未終結列（pending/in_flight/failed）之間去重——
# 1-1 後 DONE/DEAD 列留存當對帳憑證，不能被當成重複列掃掉
SQL = """
delete from request_ts where id in (
  select id from (
    select
      min(id) as id,
      count(*) as n
      from request_ts
      where status < 10
      group by year, month, day, coalesce(seed->>'id', seed->>0)
  )
  as t where n > 1
);
"""

class Command(BaseCommand):
    help = 'Remove duplicated request'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
          cursor.execute(SQL)
