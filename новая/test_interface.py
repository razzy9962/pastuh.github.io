import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher
from aiogram.types import Update

import test_render
from interface import InterfaceApp
from storage import Store, now


class InterfaceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = Store(Path(folder.name) / 'test.db')
        self.bot = AsyncMock()
        self.bot.get_me.return_value = Obj(username='test_project_bot')
        self.app = InterfaceApp(self.bot, self.db, 1, -100123)
        self.m = Obj(edit_text=AsyncMock(), answer=AsyncMock(), answer_document=AsyncMock())
        self.q = Obj(data='', from_user=Obj(id=1), message=self.m, answer=AsyncMock())

    async def click(self, data):
        self.q.data = data
        await self.app.admin_button(self.q)

    async def owner_reply(self, text, to, next_id):
        m = Obj(text=text, from_user=Obj(id=1), reply_to_message=Obj(message_id=to),
                answer=AsyncMock(return_value=Obj(message_id=next_id)))
        await self.app.admin_reply(m)
        return m

    async def test_create_draft_edit_and_publish(self):
        self.m.answer.return_value = Obj(message_id=10)
        await self.click('a:new_rate')
        await self.owner_reply('VIP 2 недели', 10, 11)
        await self.owner_reply('14', 11, 12)
        await self.owner_reply('Разборы раз в неделю', 12, 14)
        p = self.db.one('SELECT id FROM plans WHERE id<>1')
        ident = p['id']
        self.assertIsNone(self.app.rate(ident, active=True))
        self.assertEqual(self.app.rate(ident)['description'], 'Разборы раз в неделю')
        await self.click(f'a:toggle:{ident},1')
        self.assertEqual(self.app.rate(ident, active=True)['days'], 14)
        self.assertIn(f'https://t.me/test_project_bot?start=plan_{ident}', self.m.edit_text.call_args.args[0])
        self.m.answer.return_value = Obj(message_id=20)
        await self.click(f'a:field:{ident},days')
        await self.owner_reply('100', 20, 21)
        self.assertEqual(self.app.rate(ident, active=True)['days'], 100)

    async def test_trial_only_once_and_only_if_enabled(self):
        t = now()
        self.assertIsNone(self.db.claim_trial(2, t))
        self.db.set('trial_enabled', '1')
        self.assertEqual(self.db.claim_trial(2, t), t + 86400)
        self.assertIsNone(self.db.claim_trial(2, t + 100000))
        self.db.grant(3, 5, t)
        self.assertIsNone(self.db.claim_trial(3, t))

    async def test_csv_admin_only_and_no_old_values(self):
        self.db.grant(123456789, 7, now())
        self.q.from_user.id = 2
        await self.click('a:export')
        self.m.answer_document.assert_not_awaited()
        self.q.from_user.id = 1
        await self.click('a:export')
        doc = self.m.answer_document.call_args.args[0]
        self.assertTrue(doc.filename.endswith('.csv'))
        self.assertIn('123456789;', doc.data.decode('utf-8-sig'))

    async def test_design_changes_button_and_optional_page(self):
        default = self.app.home_keyboard()
        self.assertEqual(len(default.inline_keyboard), 2)
        self.m.answer.return_value = Obj(message_id=30)
        await self.click('a:text:menu_plans')
        await self.owner_reply('Подписаться', 30, 31)
        self.assertEqual(self.app.home_keyboard().inline_keyboard[0][0].text, 'Подписаться')
        self.m.answer.return_value = Obj(message_id=32)
        await self.click('a:text:faq')
        await self.owner_reply('В этом проекте публикуются статьи.', 32, 33)
        self.assertEqual(self.app.home_keyboard().inline_keyboard[-1][0].callback_data, 'u:faq')

    async def test_giveaway_with_one_eligible_and_single_confirmation(self):
        t = now()
        self.db.run('INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)', 'o', 2, 'paid', 30, 50, t)
        self.db.apply_payment('o', 2, 'XTR', 50, 'c', t)
        self.db.grant(4, 30, t)
        await self.click('a:giveaway_prepare')
        token = self.db.get('giveaway_confirmation').split(':')[0]
        await self.click('a:giveaway_draw:' + token)
        self.assertIn('ID 2', self.db.get('last_giveaway'))
        await self.click('a:giveaway_draw:' + token)
        self.assertIn('больше не действует', self.m.edit_text.call_args.args[0])

    async def test_real_start_routing_accepts_plan_parameter(self):
        self.app.show_home = AsyncMock()
        self.app.user_plan = AsyncMock()
        dispatcher = Dispatcher()
        dispatcher.include_router(self.app.router)
        async with Bot('123456:fake-token') as api:
            event = Update.model_validate({'update_id': 1, 'message': {'message_id': 2, 'date': now(),
                'chat': {'id': 1, 'type': 'private'}, 'from': {'id': 1, 'is_bot': False, 'first_name': 'Owner'},
                'text': '/start plan_1', 'entities': [{'type': 'bot_command', 'offset': 0, 'length': 6}]}}, context={'bot': api})
            await dispatcher.feed_update(api, event)
        self.app.show_home.assert_awaited_once()
        self.assertEqual(self.app.user_plan.call_args.args[1], 1)


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'TEST_DATABASE_URL not provided')
class InterfacePostgresTests(InterfaceTests):
    def setUp(self):
        super().setUp()
        self.app.db = self.db = test_render.make_pg_store(self)
