'''Django management command 外殼的無 Django 版（介面刻意對齊，搬指令時只改 import）。'''
import argparse
import sys


class CommandError(Exception):
    '''同 Django：handle() 丟它＝印訊息到 stderr、exit 1（returncode 可覆寫）。'''

    def __init__(self, *args, returncode=1):
        self.returncode = returncode
        super().__init__(*args)


class _Out:
    def __init__(self, stream):
        self._stream = stream

    def write(self, msg='', ending='\n'):
        if ending and not msg.endswith(ending):
            msg += ending
        self._stream.write(msg)
        self._stream.flush()


class BaseCommand:
    help = ''

    def __init__(self):
        self.stdout = _Out(sys.stdout)
        self.stderr = _Out(sys.stderr)

    def add_arguments(self, parser):
        pass

    def handle(self, *args, **options):
        raise NotImplementedError

    def create_parser(self, prog):
        parser = argparse.ArgumentParser(prog=prog, description=self.help)
        self.add_arguments(parser)
        return parser

    def run_from_argv(self, prog, argv):
        '''回傳 exit code。SystemExit（argparse --help／指令自己 raise SystemExit(n)）也收成
        回傳值，讓 __main__ 的「沒有載入 django」斷言一定跑得到。'''
        try:
            options = vars(self.create_parser(prog).parse_args(argv))
            output = self.handle(**options)
        except CommandError as err:
            sys.stderr.write('CommandError: {}\n'.format(err))
            return err.returncode
        except SystemExit as exc:
            code = exc.code
            if code is None:
                return 0
            if isinstance(code, int):
                return code
            sys.stderr.write('{}\n'.format(code))
            return 1
        if output:
            self.stdout.write(output)
        return 0
