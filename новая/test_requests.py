import os
import unittest
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock

import test_interface
import test_render
from storage import now


class RequestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        test_interface.InterfaceTests.setUp(self)
        self.bot.send_message.return_value = Obj(message_id=678)
        self.bot.forward_message.return_value = Obj(message_id=777)

    async def test_request_notifies_once_and_only_owner_can_approve(self):
        self.db.start(2, now())
        self.q.from_user = Obj(id=2, full_name='Test Member', username='tester', language_code='ru', is_premium=False)
        self.q.data = 'u:request_yes:1'
        await self.app.user_button(self.q)
        await self.app.user_button(self.q)
        self.bot.send_message.assert_awaited_once()
        call = self.bot.send_message.call_args
        self.assertEqual(call.args[0], 1)
        self.assertIn('Test Member', call.args[1])
        approval = call.kwargs['reply_markup'].inline_keyboard[0][0].callback_data
        self.assertIsNone(self.db.one('SELECT * FROM memberships WHERE uid=2'))
        self.q.data = approval
        await self.app.admin_button(self.q)
        self.q.answer.assert_awaited_with('Нет доступа.', show_alert=True)
        self.q.from_user = Obj(id=1)
        await self.app.admin_button(self.q)
        end = self.db.one('SELECT until FROM memberships WHERE uid=2')['until']
        await self.app.admin_button(self.q)
        self.assertEqual(self.db.one('SELECT until FROM memberships WHERE uid=2')['until'], end)
        self.assertEqual(self.bot.send_message.await_count, 2)
        self.assertIn('одобрена', self.bot.send_message.call_args.args[1])
        self.assertEqual(self.db.one('SELECT action FROM owner_audit')['action'], 'access_approved')

    async def test_requisites_and_screenshot_verification_flow(self):
        t = now()
        self.db.start(2, t)
        self.db.set('text:requisites', 'Сбербанк: 2200 7000 9999 8888\nСБП: +7 900 111-22-33')
        self.q.from_user = Obj(id=2, full_name='Иван Петров', username='ivan_p', language_code='ru', is_premium=False)
        self.q.data = 'u:request:1'
        await self.app.user_button(self.q)
        panel_text = self.m.edit_text.call_args.args[0]
        self.assertIn('2200 7000 9999 8888', panel_text)
        self.assertIsNotNone(self.db.get_payment_draft(2))

        photo_msg = Obj(
            from_user=self.q.from_user,
            chat=Obj(id=2),
            message_id=55,
            photo=[Obj(file_id='receipt_photo_123')],
            document=None,
            caption='Оплатил 250 ₽ с Т-Банка',
            answer=AsyncMock(),
        )
        await self.app.relay(photo_msg)
        self.bot.forward_message.assert_awaited_once_with(1, 2, 55)
        photo_msg.answer.assert_awaited_once()
        self.assertIn('Скриншот получен', photo_msg.answer.call_args.args[0])

        req = self.db.one("SELECT * FROM access_requests WHERE uid=2 AND status='pending'")
        self.assertIsNotNone(req)
        shot = self.db.get_request_screenshot(req['id'])
        self.assertEqual(shot['file_id'], 'receipt_photo_123')
        self.assertEqual(shot['price'], 250)

        self.q.from_user = Obj(id=1)
        self.q.data = f'a:request_approve:{req["id"]}'
        await self.app.admin_button(self.q)
        self.assertIsNotNone(self.db.one('SELECT until FROM memberships WHERE uid=2'))
        self.assertIsNotNone(self.db.one('SELECT * FROM payments WHERE charge=?', f'req-{req["id"]}'))

    async def test_rejection_preserves_existing_membership_and_has_cooldown(self):
        t = now()
        self.db.start(2, t)
        end = self.db.grant(2, 10, t)
        res, r = self.db.submit_access_request(2, 1, t)
        self.assertEqual(res, 'created')
        status, access = self.db.decide_access_request(r['id'], 1, False, t)
        self.assertEqual(status['status'], 'denied')
        self.assertIsNone(access)
        self.assertEqual(self.db.one('SELECT until FROM memberships WHERE uid=2')['until'], end)
        self.assertEqual(self.db.submit_access_request(2, 1, t+30)[0], 'unavailable')
        self.assertEqual(self.db.submit_access_request(2, 1, t+86400)[0], 'created')

    async def test_request_dates_are_snapshots(self):
        t = now()
        self.db.start(2, t)
        _, r = self.db.submit_access_request(2, 1, t)
        self.db.edit_plan(1, {'days': 14, 'enabled': 0}, 1)
        _, until = self.db.decide_access_request(r['id'], 1, True, t)
        self.assertEqual(until, t+30*86400)
        self.assertEqual(self.db.submit_access_request(2, 1, t)[0], 'unavailable')


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'TEST_DATABASE_URL not provided')
class RequestPostgresTests(RequestTests):
    def setUp(self):
        super().setUp()
        self.app.db = self.db = test_render.make_pg_store(self)
