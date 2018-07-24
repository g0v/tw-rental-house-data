
from django.utils import timezone
def now_tuple():
    now = timezone.localtime(timezone.now())
    # Let's do it once for now
    return [now.year, now.month, now.day, 0]
    # return [now.year, now.month, now.day, now.hour - now.hour % 12]