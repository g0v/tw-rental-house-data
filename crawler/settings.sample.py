# when in development, sqlite will be used
# change to non-development to apply DB_* setting
ENVIRONMENT = 'development'

# support only postgres for now
DB = {
    'NAME': 'my.db',
    'ARGS': {
        'user': 'username',
        'password': 'password',
        'host': 'host.name.of.db',
        'port': 5432
    }
}
