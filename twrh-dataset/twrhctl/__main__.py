'''python -m twrhctl <command> [args...]'''
import importlib
import os
import pkgutil
import sys

import twrhctl  # noqa: F401 — sys.path／.env／sentry
from twrhctl import commands as _commands_pkg


def available():
    return sorted(m.name for m in pkgutil.iter_modules(_commands_pkg.__path__)
                  if not m.name.startswith('_'))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    names = available()
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print('usage: python -m twrhctl <command> [args...]\n\ncommands:\n  ' + '\n  '.join(names))
        return 0
    name, rest = argv[0], argv[1:]
    if name not in names:
        print('unknown command {!r}; available: {}'.format(name, ', '.join(names)), file=sys.stderr)
        return 2
    module = importlib.import_module('twrhctl.commands.' + name)
    code = module.Command().run_from_argv('twrhctl ' + name, rest)
    # 本入口的存在理由：整條路徑不靠 Django。有人不小心 import 了就當場紅
    leaked = sorted(m for m in sys.modules if m == 'django' or m.startswith('django.'))
    if leaked and not os.environ.get('TWRHCTL_ALLOW_DJANGO'):
        print('!!! twrhctl {}: django got imported ({} modules, e.g. {})'.format(
            name, len(leaked), leaked[0]), file=sys.stderr)
        return code or 3
    return code


if __name__ == '__main__':
    sys.exit(main())
