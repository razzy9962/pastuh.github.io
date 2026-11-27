import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import psycopg
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from aiogram import Bot
from psycopg import sql
from psycopg.conninfo import make_conninfo

from postgres_store import PostgresStore
from render_app import ROUTE, telegram_handler
from storage import Store
import test_bot


def make_pg_store(case):
    dsn = os.environ['TEST_DATABASE_URL']
    name = 'invest_test_' + uuid.uuid4().hex
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))

    def cleanup():
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))

    case.addCleanup(cleanup)
    store = PostgresStore(make_conninfo(dsn, options=f'-c search_path={name}'))
    case.addCleanup(store.close)
    return store


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'TEST_DATABASE_URL not provided')
class PostgresTests(test_bot.Tests):
    def setUp(self):
        super().setUp()
        self.app.db = self.db = make_pg_store(self)

    def test_big_ids_and_inserts(self):
        uid = 2**47
        self.db.start(uid, 1)
        self.assertIsNotNone(self.db.one('SELECT id FROM users WHERE id=?', uid))
        count, ident = self.db.run('INSERT INTO plans(title,days,stars) VALUES (?, ?, ?) RETURNING id', 'Demo', 1, 1)
        self.assertEqual(count, 1)
        self.assertGreater(ident, 1)


class WebhookTests(unittest.IsolatedAsyncioTestCase):
    async def test_webhook_auth_validation_and_retries(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'bot.sqlite3')
            secret = 'test-secret'
            headers = {'X-Telegram-Bot-Api-Secret-Token': secret}
            async with Bot('123456:faketoken') as bot:
                dispatcher = AsyncMock()
                app = web.Application()
                app.router.add_post(ROUTE, telegram_handler(bot, dispatcher, store, secret))
                async with TestClient(TestServer(app)) as client:
                    r = await client.post(ROUTE, json={'update_id': 123})
                    self.assertEqual(r.status, 403)
                    r = await client.post(ROUTE, data='bad', headers=headers)
                    self.assertEqual(r.status, 400)
                    dispatcher.feed_update.side_effect = RuntimeError('temporary')
                    with self.assertLogs('render_bot', level='ERROR'):
                        r = await client.post(ROUTE, json={'update_id': 123}, headers=headers)
                    self.assertEqual(r.status, 503)
                    self.assertIsNone(store.one('SELECT 1 FROM webhook_updates'))
                    dispatcher.feed_update.side_effect = None
                    for _ in range(2):
                        r = await client.post(ROUTE, json={'update_id': 123}, headers=headers)
                        self.assertEqual(r.status, 200)
                    self.assertEqual(dispatcher.feed_update.await_count, 2)
