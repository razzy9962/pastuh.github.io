"""Persistent Store for Render, with the same SQL contract as the local SQLite Store."""
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from storage import SCHEMA, Store

PG_SCHEMA = SCHEMA.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'BIGSERIAL PRIMARY KEY').replace('INTEGER', 'BIGINT')


class PostgresConnection:
    def __init__(self, db):
        self.db = db

    def execute(self, sql, args=()):
        # Only internal SQL templates use this adapter; values are always parameterized.
        return self.db.execute(sql.replace('?', '%s'), args)


class PostgresStore(Store):
    def __init__(self, url):
        self.pool = ConnectionPool(
            conninfo=url, min_size=1, max_size=3, timeout=5, open=False,
            kwargs={'row_factory': dict_row, 'connect_timeout': 8, 'prepare_threshold': None},
        )
        self.pool.open(wait=True, timeout=15)
        try:
            with self.connection() as db:
                for statement in PG_SCHEMA.split(';'):
                    if statement.strip():
                        db.execute(statement)
                self._seed(db)
        except BaseException:
            self.close()
            raise

    @contextmanager
    def connection(self):
        with self.pool.connection() as db:
            yield PostgresConnection(db)

    @staticmethod
    def _begin_payment(db):
        # Implicit PostgreSQL transaction. Unique payment charge and atomic UPSERT
        # handle duplicate events and concurrent renewals safely.
        pass

    def close(self):
        self.pool.close()
