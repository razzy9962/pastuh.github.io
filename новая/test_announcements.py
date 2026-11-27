import os
import unittest
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock

from aiogram.enums import ChatMemberStatus, ChatType

import test_interface
import test_render
from bot import init_bot
from storage import now


class AnnouncementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        test_interface.InterfaceTests.setUp(self)

    async def test_broadcast_has_optout_and_respects_existing_preferences(self):
        t = now()
        self.db.run('INSERT INTO users(id,first_seen,last_start,news) VALUES (?, ?, ?, 0)', 2, t, t)
        self.db.start(2, t)  # Keep the previous setting on a repeated /start.
        self.db.start(3, t)
        self.db.start(4, t)
        self.db.start(self.app.admin, t)
        self.db.run('INSERT INTO users(id,first_seen,last_start,starts,news) VALUES (?, ?, ?, 0, 1)', 5, t, t)
        self.q.from_user.id = 4
        self.q.data = 'u:announcement_off'
        self.m.edit_reply_markup = AsyncMock()
        await self.app.user_button(self.q)
        self.m.edit_reply_markup.assert_awaited_once()
        self.db.start(4, t)
        await self.app.broadcast(678)
        self.bot.copy_message.assert_awaited_once()
        self.assertEqual(self.bot.copy_message.call_args.args, (3, 1, 678))
        kb = self.bot.copy_message.call_args.kwargs['reply_markup']
        self.assertEqual(kb.inline_keyboard[0][0].callback_data, 'u:announcement_off')

    async def test_public_menu_no_privacy_command(self):
        self.bot.get_chat.return_value = Obj(type=ChatType.SUPERGROUP, username=None)
        self.bot.get_chat_member.return_value = Obj(status=ChatMemberStatus.ADMINISTRATOR,
                                                     can_invite_users=True, can_restrict_members=True)
        self.bot.get_me.return_value = Obj(id=100)
        await init_bot(self.bot, self.app.admin, self.app.channel)
        public = self.bot.set_my_commands.call_args_list[0].args[0]
        self.assertNotIn('privacy', [v.command for v in public])
        self.q.from_user.id = 2
        self.q.data = 'u:data'
        await self.app.user_button(self.q)
        self.assertIn('передаются владельцу', self.m.edit_text.call_args.args[0])

    async def test_plan_card_formats_and_escapes_owner_text(self):
        self.db.edit_plan(1, {'title': '<Новое>', 'description': 'Обзор A & B'}, 1)
        self.db.set('text:resource_label', 'Чат <VIP>')
        await self.app.user_plan(self.m, 1)
        markup = self.m.edit_text.call_args.kwargs['reply_markup']
        self.assertFalse(any(row[0].callback_data.startswith('u:buy:') for row in markup.inline_keyboard))
        self.db.set('sales_paused', '0')
        await self.app.user_plan(self.m, 1)
        text = self.m.edit_text.call_args.args[0]
        self.assertNotIn('Стоимость', text)
        self.assertIn('Оплаты в боте отключены', text)
        self.assertIn('Чат &lt;VIP&gt;', text)
        self.assertIn('A &amp; B', text)
        self.assertIn('Вариант доступа: &lt;Новое&gt;', text)


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'TEST_DATABASE_URL not provided')
class AnnouncementPostgresTests(AnnouncementTests):
    def setUp(self):
        super().setUp()
        self.app.db = self.db = test_render.make_pg_store(self)
