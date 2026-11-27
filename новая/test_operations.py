import os
import unittest
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock

import test_interface
import test_render
from storage import now


class OperationsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        test_interface.InterfaceTests.setUp(self)

    def add_payment(self, uid, charge, token):
        p = self.app.rate(1)
        self.db.record_order(token, uid, p, now())
        self.assertEqual(self.db.apply_payment(token, uid, 'XTR', p['stars'], charge, now())[0], 'applied')

    async def test_renewal_once_per_deadline_and_optout(self):
        t = now()
        self.db.grant(2, 1, t-300)
        self.db.grant(3, 1, t-300)
        self.db.run('INSERT INTO renewal_optouts VALUES (?)', 3)
        for _ in range(2):
            await self.app.renewal_tick()
        self.bot.send_message.assert_awaited_once()
        self.assertEqual(self.bot.send_message.call_args.args[0], 2)
        self.assertEqual(self.db.one('SELECT COUNT(*) AS n FROM renewal_notices')['n'], 1)

    async def test_renewal_prompts_new_access_request_without_issuing_invoice(self):
        self.db.set('sales_paused', '0')
        self.add_payment(2, 'pay-2', 'o-2')
        self.db.edit_plan(1, {'stars': 475}, self.app.admin)
        self.q.from_user.id = 2
        self.q.data = 'u:renew'
        await self.app.user_button(self.q)
        self.assertIn('Выберите срок для новой заявки', self.m.edit_text.call_args.args[0])
        self.bot.send_invoice.assert_not_awaited()

    async def test_user_sees_only_own_payment_history(self):
        self.add_payment(2, 'only-user-two', 'o-2')
        self.add_payment(3, 'only-user-three', 'o-3')
        self.q.from_user.id = 2
        self.q.data = 'u:payments'
        await self.app.user_button(self.q)
        panel_text = self.m.edit_text.call_args.args[0]
        self.assertIn('only-user-two', panel_text)
        self.assertNotIn('only-user-three', panel_text)
        self.q.data = 'a:payments'
        await self.app.admin_button(self.q)
        self.q.answer.assert_awaited_with('Нет доступа.', show_alert=True)
        self.q.from_user.id = 1
        await self.app.payment_detail(self.m, 'only-user-three')
        self.assertIn('Пользователь: 3', self.m.edit_text.call_args.args[0])

    async def test_pause_rejects_new_checkout_but_honors_confirmed_payment(self):
        plan = self.app.rate(1)
        self.db.record_order('o1', 2, plan, now())
        self.db.set('sales_paused', '1')
        self.q.data = 'u:buy:1'
        await self.app.user_button(self.q)
        self.bot.send_invoice.assert_not_awaited()
        q = Obj(invoice_payload='o1', from_user=Obj(id=2), currency='XTR', total_amount=plan['stars'], answer=AsyncMock())
        await self.app.checkout(q)
        self.assertFalse(q.answer.call_args.kwargs['ok'])
        self.assertEqual(self.db.apply_payment('o1', 2, 'XTR', plan['stars'], 'already-confirmed', now())[0], 'applied')

    async def test_owner_audit_records_targets_once_and_plan_delta(self):
        t = now()
        self.db.grant(123, 5, t, actor=1)
        self.db.grant(456, 1, t-172800, actor=1)
        self.db.edit_plan(1, {'stars': 275}, 1)
        self.db.set('extend_confirmation', '901:3')
        self.assertEqual(self.db.extend_all(1, '901:3', 3, t), 1)
        self.assertIsNone(self.db.extend_all(1, '901:3', 3, t))
        self.assertEqual([r['uid'] for r in self.db.all('SELECT uid FROM owner_audit_users')], [123])
        self.assertEqual(self.db.one('SELECT until FROM memberships WHERE uid=123')['until'], t+8*86400)
        self.assertEqual([r['action'] for r in self.db.all('SELECT action FROM owner_audit ORDER BY id')], ['grant','grant','plan_edit','extend_all'])
        edit = self.db.one("SELECT id FROM owner_audit WHERE action='plan_edit'")['id']
        await self.app.audit_panel(self.m, 'audit_one', edit)
        self.assertIn('250 → 275', self.m.edit_text.call_args.args[0])


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'TEST_DATABASE_URL not provided')
class OperationsPostgresTests(OperationsTests):
    def setUp(self):
        super().setUp()
        self.app.db = self.db = test_render.make_pg_store(self)
