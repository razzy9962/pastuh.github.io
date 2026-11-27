import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock

from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import ForwardMessage

from bot import App, DAY
from storage import Store, now


class Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = Store(Path(temp.name) / 'test.sqlite3')
        self.bot = AsyncMock()
        self.bot.send_message.return_value = Obj(message_id=10)
        self.bot.forward_message.return_value = Obj(message_id=11)
        self.bot.copy_message.return_value = Obj(message_id=12)
        self.app = App(self.bot, self.db, 1, -100123)
        self.user = Obj(id=2, full_name='Пётр Тестов', username='test', language_code='ru', is_premium=None)
        self.message = Obj(from_user=self.user, chat=Obj(id=2), message_id=14, answer=AsyncMock(), photo=None, document=None)

    def order(self, token='order', created=None):
        self.db.run('INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)', token, 2, 'Тест', 30, 50, now() if created is None else created)

    async def test_start_twice(self):
        await self.app.start(self.message)
        await self.app.start(self.message)
        self.assertEqual(self.db.one('SELECT starts FROM users WHERE id=2')['starts'], 2)
        self.assertEqual(self.bot.send_message.await_count, 2)
        self.assertIn('@test', self.bot.send_message.call_args.args[1])
        self.assertIn('передаются владельцу', self.message.answer.call_args.args[0])

    async def test_ordinary_message_silent_and_copy_fallback(self):
        self.bot.forward_message.side_effect = TelegramBadRequest(ForwardMessage(chat_id=1, from_chat_id=2, message_id=14), 'no')
        await self.app.relay(self.message)
        self.bot.copy_message.assert_awaited_once_with(1, 2, 14)
        self.message.answer.assert_not_awaited()
        self.assertEqual(self.db.one('SELECT uid FROM relays WHERE admin_mid=12')['uid'], 2)

    async def test_screenshots_are_ordinary_support_messages(self):
        self.message.photo = [object()]
        self.order()
        await self.app.relay(self.message)
        self.message.answer.assert_not_awaited()
        self.assertEqual(len(self.db.all('SELECT * FROM reviews')), 0)
        self.assertIsNone(self.db.one('SELECT * FROM memberships'))
        self.bot.forward_message.assert_awaited_once()

    async def test_checkout_refuses_even_old_valid_invoice(self):
        self.db.set('sales_paused', '0')
        self.order()
        q = Obj(invoice_payload='order', from_user=self.user, currency='XTR', total_amount=50, answer=AsyncMock())
        await self.app.checkout(q)
        self.assertFalse(q.answer.call_args.kwargs['ok'])

    async def test_member_payment_idempotent_and_extends_time(self):
        self.order()
        at = now()
        self.assertEqual(self.db.grant(2, 7, at), at + 7 * DAY)
        self.assertEqual(self.db.apply_payment('order', 2, 'XTR', 49, 'charge', at)[0], 'invalid')
        self.assertEqual(self.db.apply_payment('order', 2, 'XTR', 50, 'charge', at), ('applied', at + 37 * DAY))
        self.assertEqual(self.db.apply_payment('order', 2, 'XTR', 50, 'charge', at)[0], 'duplicate')
        self.assertEqual(self.db.one('SELECT until FROM memberships WHERE uid=2')['until'], at + 37 * DAY)

    async def test_paid_message_delivers_private_access(self):
        self.order()
        self.bot.get_chat_member.return_value = Obj(status=ChatMemberStatus.LEFT)
        self.bot.create_chat_invite_link.return_value = Obj(invite_link='https://t.me/+example')
        self.message.successful_payment = Obj(invoice_payload='order', currency='XTR', total_amount=50, telegram_payment_charge_id='charge')
        await self.app.paid(self.message)
        await self.app.paid(self.message)
        self.bot.create_chat_invite_link.assert_awaited_once()
        self.assertEqual(self.bot.send_message.await_count, 2)
        self.assertIn('Оплата получена.', self.bot.send_message.call_args.args[1])

    async def test_join_checks_id(self):
        self.db.set('invite:-100123', 'https://t.me/+example')
        join = Obj(from_user=self.user, invite_link=Obj(invite_link='https://t.me/+example'), approve=AsyncMock(), decline=AsyncMock())
        await self.app.join(join)
        join.decline.assert_awaited_once()
        self.db.grant(2, 30, now())
        await self.app.join(join)
        join.approve.assert_awaited_once()

    async def test_admin_only(self):
        q = Obj(from_user=self.user, data='a:stats', answer=AsyncMock(), message=self.message)
        await self.app.admin_button(q)
        q.answer.assert_awaited_once_with('Нет доступа.', show_alert=True)
        self.message.answer.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
