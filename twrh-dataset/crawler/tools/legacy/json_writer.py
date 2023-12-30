import json

class ListWriter():
    def __init__(self, file_prefix):
        self.__file_prefix = file_prefix
        self.__files = {}

    def write(self, filename, row=None, last_line=False):
        if filename not in self.__files:
            fh = open('{}_{}.json'.format(self.__file_prefix, filename), 'w')
            self.__files[filename] = {
                'fh': fh,
                'last': row
            }
            fh.write('[\n')
        elif self.__files[filename]['last']:
            f = self.__files[filename]
            fh = f['fh']
            join_token = '' if last_line else ','
            fh.write('{}{}\n'.format(json.dumps(f['last'], ensure_ascii=False), join_token))
            f['last'] = row

    def closeAll(self):
        for filename in self.__files:
            self.write(filename, last_line=True)
            fh = self.__files[filename]['fh']
            fh.write(']')
            fh.close()


    