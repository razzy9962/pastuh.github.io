import asyncio
import logging
import os
import re
import secrets
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BotCommand, BotCommandScopeChat, CallbackQuery, ChatJoinRequest,
    InlineKeyboardButton, InlineKeyboardMarkup, Message, PreCheckoutQuery,
)
from dotenv import load_dotenv

from storage import Store, now

LOG = logging.getLogger('invest_bot')
DAY = 86400
NOTICE = (
    'Владелец бота получает уведомление при /start и видит данные вашего профиля, '
    'доступные боту. Сообщения и файлы из этого чата передаются владельцу для поддержки; '
    'бот не подтверждает пересылку каждого сообщения. Не отправляйте номера карт, пароли '
    'и документы. На скриншоте закройте лишние персональные данные. '
    'Вы покупаете доступ к материалам, а не инвестируете деньги. Материалы не гарантируют доход.'
)


def keyboard(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=text, callback_data=value) for text, value in row
    ] for row in rows])


HOME = keyboard(
    [('💳 Тарифы', 'u:plans'), ('🔐 Мой доступ', 'u:access')],
    [('💬 Поддержка', 'u:support'), ('🔔 Рассылки', 'u:news')],
)
ADMIN = keyboard(
    [('📊 Статистика', 'a:stats'), ('⚙️ Настройки', 'a:settings')],
    [('📣 Рассылки', 'a:broadcast'), ('📝 Выдать подписку', 'a:grant')],
    [('⏳ Продлить все подписки', 'a:extend')],
    [('🕓 Последние 5 непродливших', 'a:expired')],
    [('🧾 Скриншоты на проверке', 'a:reviews')],
)
BACK = keyboard([('← Админ-панель', 'a:home')])


def utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime('%d.%m.%Y %H:%M UTC')


def profile(user):
    return (
        f'ID: {user.id}\nИмя: {user.full_name}\n'
        f'Username: {"@" + user.username if user.username else "—"}\n'
        f'Язык Telegram: {user.language_code or "—"}\n'
        f'Telegram Premium: {"да" if user.is_premium else "нет / не указано"}'
    )


def is_member(member):
    if member.status == ChatMemberStatus.RESTRICTED:
        return member.is_member
    return member.status in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}


class App:
    def __init__(self, bot, db, admin, channel):
        self.bot, self.db, self.admin, self.channel = bot, db, admin, channel
        self.access_lock = asyncio.Lock()
        self.expiry_changed = asyncio.Event()
        self.broadcasts = set()
        self.router = Router()
        private = F.chat.type == ChatType.PRIVATE
        self.router.message.filter(private)
        self.router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)
        self.router.message.register(self.start, CommandStart())
        self.router.message.register(self.support, Command('paysupport', 'help'))
        self.router.message.register(self.retired_privacy, Command('privacy'))
        self.router.message.register(self.admin_home, Command('admin'), F.from_user.id == admin)
        self.router.message.register(self.admin_command, Command(
            'grant', 'extend', 'plan', 'disable_plan', 'welcome', 'requisites', 'broadcast', 'rotate_link'
        ), F.from_user.id == admin)
        self.router.message.register(self.paid, F.successful_payment)
        self.router.message.register(self.admin_reply, F.from_user.id == admin, F.reply_to_message)
        self.router.message.register(self.relay, F.from_user, F.from_user.id != admin)
        self.router.callback_query.register(self.admin_button, F.data.startswith('a:'))
        self.router.callback_query.register(self.user_button, F.data.startswith('u:'))
        self.router.pre_checkout_query.register(self.checkout)
        self.router.chat_join_request.register(self.join, F.chat.id == channel)

    async def notify(self, text, **kwargs):
        try:
            return await self.bot.send_message(self.admin, text, **kwargs)
        except TelegramAPIError as exc:
            LOG.warning('Не удалось уведомить администратора: %s', type(exc).__name__)
            return None

    def remember(self, mid, uid):
        self.db.run('INSERT INTO relays VALUES (?, ?, ?) ON CONFLICT(admin_mid) DO UPDATE SET uid=excluded.uid, created=excluded.created', mid, uid, now())

    def home_keyboard(self):
        return HOME

    def text(self, key, default):
        return self.db.get('text:' + key, default)

    async def start(self, m: Message):
        uid = m.from_user.id
        self.db.start(uid, now())
        welcome = self.db.get('welcome', '📈 Закрытый доступ к материалам об инвестициях')
        await m.answer(f'{welcome}\n\n{NOTICE}', reply_markup=self.home_keyboard())
        if uid != self.admin:
            saved = self.db.one('SELECT starts FROM users WHERE id=?', uid)
            note = await self.notify(f'👋 Запуск бота №{saved["starts"]}\n\n{profile(m.from_user)}')
            if note:
                self.remember(note.message_id, uid)

    async def support(self, m):
        await m.answer(self.text('support', 'Напишите сюда свой вопрос. По оплате укажите, что случилось, без реквизитов и кодов.')
                       + '\n\nВладелец получает сообщения из этого чата.',
                       reply_markup=keyboard([('Как обрабатываются данные', 'u:data')]))

    async def retired_privacy(self, _message):
        # Consume the old command without relaying it as a user message.
        return None

    async def invite(self, *, rotate=False):
        key = f'invite:{self.channel}'
        current = self.db.get(key)
        if current and not rotate:
            return current
        new = await self.bot.create_chat_invite_link(self.channel, creates_join_request=True, name='Проверка подписки')
        self.db.set(key, new.invite_link)
        if current:
            try:
                await self.bot.revoke_chat_invite_link(self.channel, current)
            except TelegramAPIError:
                LOG.warning('Старая ссылка не отозвана, но бот больше её не принимает')
        return new.invite_link

    async def access(self, uid, prefix=''):
        async with self.access_lock:
            row = self.db.one('SELECT until FROM memberships WHERE uid=? AND until>?', uid, now())
            if not row:
                await self.bot.send_message(uid, prefix + 'Активной подписки нет.', reply_markup=self.home_keyboard())
                return
            until = utc(row['until'])
            try:
                me = await self.bot.get_chat_member(self.channel, uid)
                if is_member(me):
                    await self.bot.send_message(uid, prefix + f'✅ Доступ активен до {until}. Вы уже в закрытом чате.',
                                                reply_markup=self.home_keyboard())
                    return
                if me.status == ChatMemberStatus.KICKED:
                    await self.bot.unban_chat_member(self.channel, uid, only_if_banned=True)
                link = await self.invite()
            except TelegramAPIError as exc:
                LOG.warning('Ошибка выдачи доступа: %s', type(exc).__name__)
                await self.bot.send_message(uid, prefix + f'Подписка активна до {until}, но ссылка сейчас недоступна. '
                                            'Попробуйте позже через «Мой доступ» или напишите /paysupport.', reply_markup=self.home_keyboard())
                return
            await self.bot.send_message(uid, prefix + f'✅ Доступ активен до {until}. Нажмите кнопку и отправьте заявку — бот проверит ваш Telegram ID.',
                                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                                            InlineKeyboardButton(text='🔐 Подать заявку', url=link)
                                        ], [InlineKeyboardButton(text='⌂ Главное меню', callback_data='u:home')]]))

    async def user_button(self, q):
        act, _, arg = q.data[2:].partition(':')
        uid = q.from_user.id
        if act == 'buy':
            return await q.answer('Оплаты в боте отключены. Откройте актуальное меню через /start.', show_alert=True)
        await q.answer()
        if act == 'access':
            return await self.access(uid)
        if act == 'support':
            return await self.support(q.message)

    async def checkout(self, q: PreCheckoutQuery):
        # Reject old unpaid invoices. The successful_payment handler remains only for late receipts.
        await q.answer(ok=False, error_message='Оплаты в боте отключены. Не оплачивайте старый счёт.')

    async def paid(self, m):
        p = m.successful_payment
        async with self.access_lock:
            status, _ = self.db.apply_payment(p.invoice_payload, m.from_user.id, p.currency, p.total_amount,
                                              p.telegram_payment_charge_id, now())
        if status == 'applied':
            await self.notify(f'💰 Оплата: {p.total_amount} ⭐\nID: {m.from_user.id}\nПлатёж: {p.telegram_payment_charge_id}')
            self.expiry_changed.set()
            await self.access(m.from_user.id, self.text('paid', 'Оплата получена.') + '\n\n')
        elif status == 'invalid':
            await self.notify(f'⚠️ Платёж требует ручной сверки. ID {m.from_user.id}; платёж {p.telegram_payment_charge_id}')
            await m.answer('Не удалось связать платёж с заказом. Напишите /paysupport.')

    async def join(self, request: ChatJoinRequest):
        uid = request.from_user.id
        async with self.access_lock:
            link = self.db.get(f'invite:{self.channel}')
            if not link or not request.invite_link or request.invite_link.invite_link != link:
                # Do not touch join requests from other admins' invite links.
                return
            active = self.db.one('SELECT 1 FROM memberships WHERE uid=? AND until>?', uid, now())
            try:
                if active or uid == self.admin:
                    await request.approve()
                else:
                    await request.decline()
            except TelegramAPIError as exc:
                LOG.warning('Ошибка обработки заявки: %s', type(exc).__name__)

    async def renewal_tick(self):
        return None

    async def expire(self):
        next_cleanup = 0
        while True:
            self.expiry_changed.clear()
            pause = 90
            try:
                for r in await asyncio.to_thread(self.db.all,
                        'SELECT uid FROM memberships WHERE until<=? AND removed=0 ORDER BY until LIMIT 50', now()):
                    async with self.access_lock:
                        uid = r['uid']
                        if not self.db.one('SELECT 1 FROM memberships WHERE uid=? AND until<=? AND removed=0', uid, now()):
                            continue
                        if uid != self.admin:
                            try:
                                member = await self.bot.get_chat_member(self.channel, uid)
                                if is_member(member) and member.status not in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
                                    await self.bot.ban_chat_member(self.channel, uid)
                            except TelegramAPIError as exc:
                                LOG.warning('Ошибка снятия доступа: %s', type(exc).__name__)
                                continue
                        self.db.run('UPDATE memberships SET removed=1 WHERE uid=?', uid)
                if now() >= next_cleanup:
                    self.db.run('DELETE FROM relays WHERE created<?', now() - 90 * DAY)
                    self.db.run('DELETE FROM webhook_updates WHERE seen<?', now() - 7 * DAY)
                    self.db.run('DELETE FROM renewal_notices WHERE deadline<?', now() - 90 * DAY)
                    next_cleanup = now() + 3600
                row = await asyncio.to_thread(self.db.one, 'SELECT MIN(until) AS deadline FROM memberships WHERE removed=0')
                deadline = row['deadline']
                pause = min(3600, max(1, deadline - now())) if deadline is not None else 3600
                if deadline is not None and deadline <= now():
                    pause = 90  # retry failed removals or the next batch without a busy loop
                renewal = await self.renewal_tick()
                if renewal is not None:
                    pause = min(pause, max(1, renewal - now()))
            except Exception:
                LOG.exception('Ошибка фоновой проверки подписок')
            try:
                await asyncio.wait_for(self.expiry_changed.wait(), timeout=pause)
            except TimeoutError:
                pass

    async def relay(self, m):
        uid = m.from_user.id
        note = await self.notify(f'📩 Входящее сообщение\n{profile(m.from_user)}\nОтветьте реплаем на это уведомление или на сообщение ниже.')
        if not note:
            return
        self.remember(note.message_id, uid)
        try:
            sent = await self.bot.forward_message(self.admin, m.chat.id, m.message_id)
        except TelegramAPIError:
            try:
                sent = await self.bot.copy_message(self.admin, m.chat.id, m.message_id)
            except TelegramAPIError as exc:
                LOG.warning('Telegram не передал сообщение %s: %s', m.message_id, type(exc).__name__)
                return await self.notify(f'⚠️ Telegram не разрешил передать содержимое сообщения от ID {uid}.')
        self.remember(sent.message_id, uid)
    async def admin_home(self, m):
        await m.answer('АДМИН-ПАНЕЛЬ ПРОЕКТА\n\nУправление подписками, тарифами, рассылками и поддержкой.', reply_markup=ADMIN)

    async def admin_reply(self, m):
        row = self.db.one('SELECT uid FROM relays WHERE admin_mid=?', m.reply_to_message.message_id)
        if not row:
            return
        try:
            await self.bot.copy_message(row['uid'], self.admin, m.message_id)
            await m.answer('Ответ отправлен.')
        except TelegramAPIError:
            await m.answer('Не удалось доставить ответ. Возможно, пользователь заблокировал бота.')

    async def admin_button(self, q):
        if q.from_user.id != self.admin:
            return await q.answer('Нет доступа.', show_alert=True)
        await q.answer()
        act, _, arg = q.data[2:].partition(':')
        m = q.message
        if act == 'home':
            return await self.admin_home(m)
        if act == 'stats':
            r = self.db.one('''SELECT COUNT(*) AS users, COALESCE(SUM(starts),0) AS starts,
                (SELECT COUNT(*) FROM memberships WHERE until>?) AS active,
                (SELECT COUNT(*) FROM payments) AS paid,
                (SELECT COALESCE(SUM(o.stars),0) FROM orders o JOIN payments p ON o.token=p.token) AS stars
                FROM users''', now())
            return await m.answer(f'📊 СТАТИСТИКА\n\nПользователей: {r["users"]}\nЗапусков: {r["starts"]}\n'
                                  f'Активных подписок: {r["active"]}\nОплат: {r["paid"]}\nВаловые поступления: {r["stars"]} ⭐', reply_markup=BACK)
        if act == 'expired':
            rows = self.db.all('SELECT uid, until FROM memberships WHERE until<=? ORDER BY until DESC LIMIT 5', now())
            return await m.answer('🕓 ПОСЛЕДНИЕ НЕПРОДЛИВШИЕ\n\n' + ('\n'.join(f'ID {r["uid"]} — {utc(r["until"])}' for r in rows) or 'Пока нет.'), reply_markup=BACK)
        if act == 'reviews':
            rows = self.db.all('SELECT * FROM reviews WHERE closed=0 ORDER BY id LIMIT 10')
            if not rows:
                return await m.answer('Открытых проверок нет.', reply_markup=BACK)
            for r in rows:
                paid = self.db.one('SELECT 1 FROM payments WHERE token=?', r['token'])
                try:
                    await self.bot.copy_message(self.admin, self.admin, r['admin_mid'])
                except TelegramAPIError:
                    pass
                note = await m.answer(f'🧾 #{r["id"]} · ID {r["uid"]} · {utc(r["created"])}\n'
                                      f'Оплата этого счёта в боте: {"подтверждена" if paid else "не найдена"}',
                                      reply_markup=keyboard([('✅ Проверено', f'a:close:{r["id"]}')]))
                self.remember(note.message_id, r['uid'])
            return
        if act == 'close' and re.fullmatch(r'\d{1,12}', arg):
            count, _ = self.db.run('UPDATE reviews SET closed=1 WHERE id=? AND closed=0', int(arg))
            return await m.answer('Проверка закрыта. Чтобы сообщить результат, ответьте на карточку проверки.' if count else 'Проверка уже закрыта или не найдена.')
        if act == 'settings':
            rows = self.db.all('SELECT * FROM plans ORDER BY id DESC LIMIT 20')
            plans = '\n'.join(f'#{r["id"]} · {r["title"]} · {r["days"]} дн. · {r["stars"]} ⭐ · '
                              + ('вкл.' if r['enabled'] else 'выкл.') for r in rows)
            text = f'⚙️ НАСТРОЙКИ ПРОЕКТА\nЧат: {self.channel}\n\n{plans or "Тарифов нет."}\n\n' \
                   'Откройте «Варианты доступа», чтобы добавить или изменить вариант.\n' \
                   '/disable_plan 1 — выключить тариф #1\n/welcome Новый текст — изменить приветствие\n' \
                   '/rotate_link — заменить ссылку для входа'
            return await m.answer(text, reply_markup=BACK)
        if act == 'confirm_extend' and re.fullmatch(r'\d{1,3}', arg) and 1 <= int(arg) <= 365:
            async with self.access_lock:
                n = await asyncio.to_thread(self.db.extend_all, self.admin, f'{m.message_id}:{arg}', int(arg), now())
            if n is None:
                return await m.answer('Это подтверждение уже использовано или устарело.')
            self.expiry_changed.set()
            return await m.answer(f'Продлено подписок: {n}.', reply_markup=BACK)
        if act == 'confirm_broadcast' and re.fullmatch(r'\d{1,12}', arg):
            key = 'broadcast_confirmation'
            if self.db.get(key) != f'{m.message_id}:{arg}':
                return await m.answer('Рассылка уже запущена или это подтверждение устарело.')
            self.db.run('DELETE FROM settings WHERE key=?', key)
            task = asyncio.create_task(self.broadcast(int(arg)))
            self.broadcasts.add(task)
            task.add_done_callback(self.broadcasts.discard)
            return await m.answer('Рассылка запущена.')
        info = {
            'grant': '/grant 123456789 30 — выдать или продлить доступ на 30 дней. ID берётся из уведомления о /start.',
            'extend': '/extend 7 — продлить действующие подписки на 7 дней. Бот запросит подтверждение.',
            'broadcast': 'Ответьте командой /broadcast на свой текст, фото или другое обычное сообщение в чате с ботом. '
                         'Бот предложит подтверждение и отправит объявление тем, у кого оно не отключено и кому рассылка подключена.',
        }
        if act in info:
            return await m.answer(info[act], reply_markup=BACK)

    async def admin_command(self, m: Message, command: CommandObject):
        name, args = command.command, (command.args or '').strip()
        if name == 'grant':
            match = re.fullmatch(r'(\d{1,16})\s+(\d{1,3})', args)
            if not match or not 1 <= int(match[2]) <= 365:
                return await m.answer('Формат: /grant ID ДНИ (1–365)')
            uid, days = map(int, match.groups())
            if not self.db.one('SELECT 1 FROM users WHERE id=?', uid):
                return await m.answer('Пользователь ещё не запустил бота.')
            async with self.access_lock:
                end = self.db.grant(uid, days, now(), actor=self.admin)
                self.expiry_changed.set()
            try:
                await self.access(uid, 'Владелец выдал вам подписку. ')
            except TelegramAPIError:
                await m.answer('Срок сохранён, но уведомить пользователя не удалось.')
            return await m.answer(f'Подписка ID {uid} активна до {utc(end)}.')
        if name == 'extend':
            if not re.fullmatch(r'\d{1,3}', args) or not 1 <= int(args) <= 365:
                return await m.answer('Формат: /extend ДНИ (1–365)')
            confirm = await m.answer(f'Прибавить {int(args)} дн. ко всем действующим подпискам?',
                                     reply_markup=keyboard([('Подтвердить', f'a:confirm_extend:{int(args)}')]))
            self.db.set('extend_confirmation', f'{confirm.message_id}:{int(args)}')
            return
        if name == 'plan':
            match = re.fullmatch(r'(\d{1,3})\s+(\d{1,7})\s+([^\n]{1,32})', args)
            if not match or not (1 <= int(match[1]) <= 365):
                return await m.answer('Формат: /plan ДНИ ЦЕНА_В_РУБЛЯХ НАЗВАНИЕ (или откройте /admin → Варианты доступа)')
            days, price, title = int(match[1]), int(match[2]), match[3].strip()
            ident = self.db.create_plan(title, days, price, '', actor=self.admin, enabled=1)
            return await m.answer(f'Тариф #{ident} «{title}» ({days} дн. · {price} ₽) создан и опубликован.')
        if name == 'disable_plan':
            if not re.fullmatch(r'\d{1,10}', args):
                return await m.answer('Формат: /disable_plan ID_ТАРИФА')
            count = self.db.edit_plan(int(args), {'enabled': 0}, self.admin)
            return await m.answer('Тариф отключён для новых покупок.' if count else 'Тариф не найден.')
        if name == 'welcome':
            if not 1 <= len(args) <= 1000:
                return await m.answer('Формат: /welcome НОВЫЙ ТЕКСТ (до 1000 символов)')
            self.db.set('welcome', args)
            return await m.answer('Приветствие обновлено.')
        if name == 'requisites':
            if not 1 <= len(args) <= 1000:
                return await m.answer('Формат: /requisites ТЕКСТ РЕКВИЗИТОВ (до 1000 символов, или через /admin → Реквизиты оплаты)')
            self.db.set('text:requisites', args)
            return await m.answer('Реквизиты для оплаты обновлены.')
        if name == 'rotate_link':
            try:
                async with self.access_lock:
                    await self.invite(rotate=True)
                return await m.answer('Ссылка обновлена. Пользователи получат новую через «Мой доступ».')
            except TelegramAPIError:
                return await m.answer('Не удалось обновить ссылку. Проверьте права бота в закрытом чате.')
        if name == 'broadcast':
            if not m.reply_to_message or m.reply_to_message.from_user is None or m.reply_to_message.from_user.id != self.admin:
                return await m.answer('Отправьте /broadcast ответом на своё сообщение с будущей рассылкой.')
            source = m.reply_to_message.message_id
            count = self.db.one('SELECT COUNT(*) AS n FROM users WHERE starts>0 AND news=1 AND id<>?', self.admin)['n']
            msg = await m.answer(f'Отправить сервисное объявление? Получателей: {count}.',
                                 reply_markup=keyboard([('Подтвердить рассылку', f'a:confirm_broadcast:{source}')]))
            self.db.set('broadcast_confirmation', f'{msg.message_id}:{source}')

    async def broadcast(self, source):
        success = fail = 0
        controls = keyboard([('🔕 Отключить объявления', 'u:announcement_off')])
        for row in self.db.all('SELECT id FROM users WHERE starts>0 AND news=1 AND id<>?', self.admin):
            uid = row['id']
            try:
                if not self.db.one('SELECT 1 FROM users WHERE id=? AND news=1 AND starts>0', uid):
                    continue
                try:
                    await self.bot.copy_message(uid, self.admin, source, reply_markup=controls)
                except TelegramRetryAfter as exc:
                    await asyncio.sleep(exc.retry_after + 1)
                    if not self.db.one('SELECT 1 FROM users WHERE id=? AND news=1 AND starts>0', uid):
                        continue
                    await self.bot.copy_message(uid, self.admin, source, reply_markup=controls)
                success += 1
            except TelegramAPIError:
                fail += 1
            await asyncio.sleep(0.08)
        await self.notify(f'📣 Рассылка закончена. Доставлено: {success}. Не доставлено: {fail}.')


def env_config():
    load_dotenv(Path(__file__).with_name('.env'))
    values = {key: os.getenv(key, '').strip() for key in ('BOT_TOKEN', 'ADMIN_ID', 'CHANNEL_ID')}
    formats = {
        'BOT_TOKEN': (r'[0-9]+:[A-Za-z0-9_-]+', 'нужен токен @BotFather: цифры, двоеточие и секретная часть'),
        'ADMIN_ID': (r'[0-9]{1,16}', 'нужен личный числовой Telegram ID без @ и без минуса'),
        'CHANNEL_ID': (r'-100[0-9]{1,13}', 'нужен числовой ID приватной супергруппы или канала, начинающийся с -100'),
    }
    errors = []
    for key, raw in values.items():
        pattern, hint = formats[key]
        if not raw:
            errors.append(f'{key}: отсутствует или пусто в Environment этого сервиса')
        elif raw.startswith(key + '='):
            errors.append(f'{key}: в Value не нужно повторять {key}=')
        elif raw.startswith(('"', "'")) or raw.endswith(('"', "'")):
            errors.append(f'{key}: удалите кавычки вокруг Value')
        elif not re.fullmatch(pattern, raw) or (key == 'ADMIN_ID' and int(raw) == 0):
            errors.append(f'{key}: неверный формат — {hint}')
    if errors:
        raise SystemExit('Проверьте настройки Render → Environment:\n- ' + '\n- '.join(errors))
    return values['BOT_TOKEN'], int(values['ADMIN_ID']), int(values['CHANNEL_ID'])


async def init_bot(bot, admin, channel):
    chat = await bot.get_chat(channel)
    if chat.type == ChatType.GROUP:
        raise SystemExit('Этот чат — обычная группа. Нужна приватная супергруппа. После преобразования укажите её новый ID.')
    if chat.type not in {ChatType.SUPERGROUP, ChatType.CHANNEL}:
        raise SystemExit('CHANNEL_ID должен указывать на приватную супергруппу или канал.')
    if chat.username or getattr(chat, 'active_usernames', None):
        raise SystemExit('Чат должен быть приватным, без активного публичного @username.')
    rights = await bot.get_chat_member(channel, (await bot.get_me()).id)
    if rights.status != ChatMemberStatus.ADMINISTRATOR or not (rights.can_invite_users and rights.can_restrict_members):
        raise SystemExit('Добавьте бота администратором с правами приглашать и блокировать участников.')
    commands = [BotCommand(command='start', description='Меню и подписка'),
                BotCommand(command='paysupport', description='Поддержка по оплате')]
    await bot.set_my_commands(commands)
    try:
        await bot.set_my_commands(commands + [BotCommand(command='admin', description='Панель владельца')],
                                  scope=BotCommandScopeChat(chat_id=admin))
    except TelegramAPIError:
        LOG.warning('Пришлите боту /start с аккаунта администратора, затем /admin.')


async def stop_tasks(app, worker):
    worker.cancel()
    with suppress(asyncio.CancelledError):
        await worker
    tasks = list(app.broadcasts)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def main():
    token, admin, channel = env_config()
    database = Path(os.getenv('DATABASE_PATH', 'bot.sqlite3'))
    if not database.is_absolute():
        database = Path(__file__).parent / database
    async with Bot(token) as bot:
        await init_bot(bot, admin, channel)
        if (await bot.get_webhook_info()).url:
            raise SystemExit('Для этого токена уже включён webhook: не запускайте одновременно локальный и Render-бот.')
        from interface import InterfaceApp
        app = InterfaceApp(bot, Store(database), admin, channel)
        dp = Dispatcher()
        dp.include_router(app.router)
        worker = asyncio.create_task(app.expire())
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), handle_as_tasks=False,
                                   close_bot_session=False)
        finally:
            await stop_tasks(app, worker)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    asyncio.run(main())
