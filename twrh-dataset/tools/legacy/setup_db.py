import sys
import os

sys.path.append('{}/../..'.format(
    os.path.dirname(os.path.realpath(__file__))))

from backend.db.seed import create_seed

create_seed()
