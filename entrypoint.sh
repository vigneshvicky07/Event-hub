#!/bin/sh
set -e

echo "=== Waiting for Database Connection ==="
python -c "
import os, time, sys

host = os.environ.get('DB_HOST', '')
port = os.environ.get('DB_PORT', '5432')
user = os.environ.get('DB_USER', '')
password = os.environ.get('DB_PASSWORD', '')
dbname = os.environ.get('DB_NAME', '')

if host and os.environ.get('USE_SQLITE', 'false').lower() not in ('true', '1', 'yes'):
    import psycopg2
    for i in range(30):
        try:
            conn = psycopg2.connect(
                dbname=dbname,
                user=user,
                password=password,
                host=host,
                port=port,
                connect_timeout=3
            )
            conn.close()
            print('PostgreSQL is ready!')
            sys.exit(0)
        except Exception as e:
            print(f'Waiting for PostgreSQL... ({e})')
            time.sleep(1)
    print('Timed out waiting for PostgreSQL!')
    sys.exit(1)
"

echo "=== Waiting for Redis Connection ==="
python -c "
import os, time, sys

redis_host = os.environ.get('REDIS_HOST', '')
redis_port = int(os.environ.get('REDIS_PORT', '6379'))
use_redis = os.environ.get('USE_REDIS', 'false').lower() in ('true', '1', 'yes')

if redis_host and use_redis:
    import redis
    for i in range(30):
        try:
            r = redis.Redis(host=redis_host, port=redis_port, socket_connect_timeout=2)
            if r.ping():
                print('Redis is ready!')
                sys.exit(0)
        except Exception as e:
            print(f'Waiting for Redis... ({e})')
            time.sleep(1)
    print('Timed out waiting for Redis!')
    sys.exit(1)
"

echo "=== Running Django Database Migrations ==="
python manage.py makemigrations --noinput
python manage.py migrate --noinput
echo "=== Migrations Complete ==="

echo "=== Starting EventHub Server on 0.0.0.0:8000 ==="
exec python manage.py runserver 0.0.0.0:8000
