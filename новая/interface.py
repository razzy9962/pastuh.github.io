"""Button-driven customer and owner flows; all settings live in the existing database."""
import asyncio
import csv
import io
import json
import logging
import re
import secrets
from datetime import datetime, timezone
from html import escape
from types import SimpleNamespace

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram import F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions

from bot import App, DAY, NOTICE, keyboard, profile, utc
from storage import now

OWNER_MENU = keyboard(
    [('📊 Статистика', 'a:stats'), ('📋 Варианты доступа', 'a:tariffs:0')],
    [('💳 Реквизиты оплаты', 'a:requisites'), ('📥 Заявки / Скрины', 'a:requests:0')],
    [('👥 Подписчики', 'a:people'), ('🎨 Дизайн бота', 'a:design')],
    [('📣 Рассылка', 'a:broadcast_ui'), ('🧾 Архив обращений', 'a:reviews:0')],
    [('📋 Журнал', 'a:audit:0'), ('🏆 Розыгрыш', 'a:giveaway')],
    [('👁 Предпросмотр', 'a:preview'), ('🗃 Архив оплат', 'a:payments')],
)
OWNER_BACK = [('‹ Управление', 'a:home')]
MENU_HOME = [('⌂ Главное меню', 'u:home')]
DESIGN = {
    'welcome': ('Приветствие', 'Добро пожаловать в закрытый клуб!\n\n📈 Здесь публикуются идеи и разборы рынка. Выберите вариант, чтобы оплатить по реквизитам и получить доступ.', 1500),
    'resource_label': ('Название закрытого ресурса', 'Приватный чат проекта', 80),
    'tariffs': ('Текст над вариантами доступа', 'Выберите тариф. После перевода по реквизитам отправьте скриншот чека на проверку.', 900),
    'requisites': ('Реквизиты для оплаты', 'Банк: Т-Банк / Сбербанк\nНомер карты: 2200 7000 1234 5678\nСБП (по номеру): +7 (999) 123-45-67\nПолучатель: Владелец проекта', 1000),
    'payment_note': ('Инструкция к оплате', 'Переведите точную сумму тарифа по реквизитам выше, затем отправьте скриншот чека (фото или документ) прямо в этот чат для проверки.', 800),
    'support': ('Текст поддержки', 'Напишите сюда свой вопрос. По оплате укажите, что случилось, без реквизитов и кодов.', 900),
    'paid': ('Ответ после оплаты', 'Оплата получена.', 450),
    'faq': ('Текст своей страницы', '', 2500),
    'faq_label': ('Название своей кнопки', 'ℹ️ О проекте', 25),
    'menu_plans': ('Кнопка «Тарифы»', '📋 Варианты доступа', 25),
    'menu_access': ('Кнопка «Мой доступ»', '🔐 Мой доступ', 25),
    'menu_support': ('Кнопка «Поддержка»', '💬 Поддержка', 25),
    'menu_news': ('Кнопка объявлений', '🔔 Объявления', 25),
}
PAGE = 6
LOG = logging.getLogger('invest_bot.renewal')
AUDIT_FIELDS = {'title': 'Название', 'days': 'Срок в днях', 'stars': 'Цена (Stars)',
                'enabled': 'Публикация', 'description': 'Описание'}


def decimal(raw, size=16):
    return int(raw) if raw and re.fullmatch(rf'[0-9]{{1,{size}}}', raw) else None


class InterfaceApp(App):
    def __init__(self, bot, db, admin, channel):
        super().__init__(bot, db, admin, channel)
        self.router.message.register(self.cancel_command, Command('cancel'), F.from_user.id == admin)
        self.router.message.register(self.owner_text, F.from_user.id == admin, F.text)
        # Parent router registers owner replies before its non-owner fallback.

    def setting_text(self, key):
        default = DESIGN[key][1]
        if key == 'welcome':
            return self.db.get('welcome', default)
        return self.text(key, default)

    def home_keyboard(self):
        rows = [[(self.setting_text('menu_plans'), 'u:plans'), (self.setting_text('menu_access'), 'u:access')],
                [(self.setting_text('menu_support'), 'u:support'), (self.setting_text('menu_news'), 'u:news')]]
        if self.setting_text('faq'):
            rows.append([(self.setting_text('faq_label'), 'u:faq')])
        return keyboard(*rows)

    async def panel(self, m, text, rows=None, *, edit=True, markup=None, html=False):
        kb = markup if markup is not None else keyboard(*rows) if rows else None
        if edit:
            try:
                return await m.edit_text(text, reply_markup=kb, parse_mode='HTML' if html else None,
                                         link_preview_options=LinkPreviewOptions(is_disabled=True))
            except TelegramBadRequest as exc:
                if 'message is not modified' in str(exc).lower():
                    return m
        return await m.answer(text, reply_markup=kb, parse_mode='HTML' if html else None,
                              link_preview_options=LinkPreviewOptions(is_disabled=True))

    def rate(self, ident, active=False):
        return self.db.one('''SELECT p.*, COALESCE(d.description, '') AS description
            FROM plans p LEFT JOIN plan_details d ON d.plan_id=p.id WHERE p.id=? AND (?=0 OR p.enabled=1)''',
            ident, int(active))

    async def start(self, m, command=None):
        uid = m.from_user.id
        self.db.start(uid, now())
        if uid != self.admin:
            count = self.db.one('SELECT starts FROM users WHERE id=?', uid)['starts']
            note = await self.notify(f'👋 Запуск бота №{count}\n\n{profile(m.from_user)}',
                                     reply_markup=keyboard([('👤 Открыть карточку', f'a:person:{uid}')]))
            if note:
                self.remember(note.message_id, uid)
        await self.show_home(m, edit=False)
        payload = (getattr(command, 'args', None) or '')
        if payload.startswith('plan_'):
            ident = decimal(payload[5:], 10)
            if ident:
                await self.user_plan(m, ident, edit=False)

    async def show_home(self, m, *, edit=True, preview=False):
        headline, sep, intro = self.setting_text('welcome').partition('\n')
        text = f'<b>{escape(headline)}</b>' + ('\n\n' + escape(intro.strip()) if sep and intro.strip() else '')
        text += ('\n\n<i>Данные профиля и сообщения этого личного чата видит владелец. '
                 'При первом запуске включаются сервисные объявления; отключить их можно в меню.</i>')
        if preview:
            text = '👁 Предпросмотр главного меню\n\n' + text
            rows = self.home_keyboard().inline_keyboard + [[InlineKeyboardButton(text='‹ Управление', callback_data='a:home')]]
            markup = InlineKeyboardMarkup(inline_keyboard=rows)
        else:
            markup = self.home_keyboard()
        return await self.panel(m, text, edit=edit, markup=markup, html=True)

    async def user_plan(self, m, ident, *, edit=True):
        p = self.rate(ident, active=True)
        if not p:
            return await self.panel(m, 'Этот тариф сейчас недоступен.', [[('‹ Тарифы', 'u:plans')], MENU_HOME], edit=edit)
        description = f'\n\n{escape(p["description"])}' if p['description'] else ''
        price_line = f'<b>Стоимость:</b> {p["stars"]} ₽\n' if p['stars'] else ''
        card = (f'<b>Вариант доступа: {escape(p["title"])}</b>\n'
                f'<b>Срок:</b> {p["days"]} дн.\n'
                f'{price_line}\n'
                f'<b>Вы получите доступ к:</b>\n• {escape(self.setting_text("resource_label"))}'
                f'{description}\n\n<b>Оплата по реквизитам</b>\n'
                'Переведите сумму по реквизитам и отправьте скриншот чека на проверку владельцу.')
        return await self.panel(m, card, [[('💳 Оплатить по реквизитам', f'u:request:{ident}')], [('‹ Назад', 'u:plans')]], edit=edit, html=True)

    async def relay(self, m):
        uid = m.from_user.id
        has_media = bool(getattr(m, 'photo', None) or getattr(m, 'document', None))
        if has_media:
            draft = self.db.get_payment_draft(uid)
            open_req = self.db.one("SELECT * FROM access_requests WHERE uid=? AND status='pending'", uid)
            if draft or open_req:
                return await self.handle_payment_screenshot(m)
        return await super().relay(m)

    async def handle_payment_screenshot(self, m):
        uid = m.from_user.id
        file_id = ''
        media_type = 'photo'
        if getattr(m, 'photo', None):
            last_photo = m.photo[-1]
            file_id = getattr(last_photo, 'file_id', 'photo_attachment')
            media_type = 'photo'
        elif getattr(m, 'document', None):
            file_id = getattr(m.document, 'file_id', 'doc_attachment')
            media_type = 'document'
        caption = getattr(m, 'caption', None) or getattr(m, 'text', None) or ''
        sent_mid = 0
        try:
            sent = await self.bot.forward_message(self.admin, m.chat.id, m.message_id)
            sent_mid = getattr(sent, 'message_id', 0) or 0
        except TelegramAPIError:
            try:
                sent = await self.bot.copy_message(self.admin, m.chat.id, m.message_id)
                sent_mid = getattr(sent, 'message_id', 0) or 0
            except TelegramAPIError as exc:
                LOG.warning('Не удалось переслать скриншот %s: %s', m.message_id, type(exc).__name__)
        if sent_mid:
            self.remember(sent_mid, uid)
        state, item = await asyncio.to_thread(
            self.db.attach_payment_screenshot, uid, file_id, media_type, sent_mid, caption, now()
        )
        if not item:
            return await m.answer(
                'Не удалось создать заявку на проверку. Если предыдущая заявка была отклонена, повторить можно через сутки.',
                reply_markup=keyboard([('📋 Варианты доступа', 'u:plans')], MENU_HOME),
            )
        ident = item['id']
        shot = self.db.get_request_screenshot(ident)
        price = shot['price'] if shot else 0
        price_str = f' · {price} ₽' if price else ''
        comment_str = f'\nКомментарий: {caption[:200]}' if caption else ''
        notice = await self.notify(
            f'🧾 Скриншот на проверку · Заявка #{ident}\n\n'
            f'{item["title"]} · {item["days"]} дн.{price_str}{comment_str}\n\n{profile(m.from_user)}',
            reply_markup=keyboard(
                [('✅ Подтвердить оплату', f'a:request_approve:{ident}'),
                 ('✖️ Отклонить', f'a:request_deny:{ident}')],
                [('📥 Очередь заявок', 'a:requests:0'), ('🧾 Скриншоты', 'a:reviews:0')],
            ),
        )
        if notice:
            self.remember(notice.message_id, uid)
        return await m.answer(
            f'🧾 Скриншот получен и прикреплён к заявке #{ident}!\n\n'
            f'Тариф: {item["title"]} · {item["days"]} дн.{price_str}\n'
            f'Статус: На проверке у владельца.\n\n'
            'Как только оплата будет проверена, бот пришлёт уведомление и откроет доступ к закрытому чату.',
            reply_markup=keyboard([('📨 Статус заявки', 'u:request_status')], MENU_HOME),
        )

    async def user_button(self, q):
        act, _, arg = q.data[2:].partition(':')
        if act == 'announcement_off':
            self.db.run('UPDATE users SET news=0 WHERE id=?', q.from_user.id)
            await q.answer('Объявления отключены.')
            try:
                await q.message.edit_reply_markup(reply_markup=None)
            except TelegramAPIError:
                pass
            return
        if act not in {'home', 'plans', 'open', 'faq', 'news', 'news_on', 'news_off', 'trial', 'trial_yes', 'support',
                       'access', 'enter', 'renew', 'payments', 'payment_help', 'reminders', 'remind_on', 'remind_off', 'data',
                       'request', 'request_yes', 'request_status', 'cancel_draft'}:
            return await super().user_button(q)
        await q.answer()
        m, uid = q.message, q.from_user.id
        if act == 'home':
            return await self.show_home(m)
        if act == 'cancel_draft':
            self.db.clear_payment_draft(uid)
            return await self.panel(m, 'Оформление оплаты отменено.', [[('📋 Варианты доступа', 'u:plans')], MENU_HOME])
        if act in {'request', 'request_yes', 'request_status'}:
            return await self.request_panel(q, act, decimal(arg, 10))
        if act == 'access':
            row = self.db.one('SELECT until FROM memberships WHERE uid=?', uid)
            active = bool(row and row['until'] > now())
            if row:
                status = f'{"✅ Действует до" if active else "🕓 Истекла"} {utc(row["until"])}'
            else:
                status = 'У вас пока нет подписки.'
            rows = [[('🔐 Войти в закрытый чат', 'u:enter')]] if active else []
            rows += [[('🔄 Запросить продление' if row else '📋 Варианты доступа', 'u:plans')],
                     [('📨 Моя заявка', 'u:request_status'), ('🔔 Напоминания', 'u:reminders')]]
            if self.db.one('SELECT 1 FROM payments p JOIN orders o ON o.token=p.token WHERE o.uid=? LIMIT 1', uid):
                rows.append([('🗃 Старые оплаты', 'u:payments')])
            rows.append(MENU_HOME)
            return await self.panel(m, f'🔐 МОЙ ДОСТУП\n\n{status}\n\nАвтосписаний нет.', rows)
        if act == 'enter':
            return await self.access(uid)
        if act == 'renew':
            return await self.user_renew(m, uid)
        if act == 'payments':
            rows = self.db.all('''SELECT p.paid,p.charge,o.title,o.stars
                FROM payments p JOIN orders o ON o.token=p.token WHERE o.uid=?
                ORDER BY p.paid DESC,p.charge LIMIT 5''', uid)
            text = '\n\n'.join(f'{utc(r["paid"])} · {r["stars"]} ⭐\n{r["title"]}\nID: {r["charge"]}' for r in rows)
            return await self.panel(m, '💰 ПОСЛЕДНИЕ ОПЛАТЫ\n\n' + (text or 'Подтверждённых оплат пока нет.'),
                                    [[('Проблема с оплатой', 'u:payment_help')], [('‹ Мой доступ', 'u:access')]])
        if act == 'payment_help':
            return await self.panel(m, 'Опишите проблему следующим сообщением. Укажите ID из истории оплат, если он есть. '
                                    'Владелец получит ваше сообщение. Не отправляйте пароли, карты или коды.',
                                    [[('‹ Мои оплаты', 'u:payments')], MENU_HOME])
        if act in {'reminders', 'remind_on', 'remind_off'}:
            if act == 'remind_on':
                self.db.run('DELETE FROM renewal_optouts WHERE uid=?', uid)
                self.expiry_changed.set()
            if act == 'remind_off':
                self.db.run('INSERT INTO renewal_optouts VALUES (?) ON CONFLICT(uid) DO NOTHING', uid)
                self.expiry_changed.set()
            on = not self.db.one('SELECT 1 FROM renewal_optouts WHERE uid=?', uid)
            return await self.panel(m, f'🔔 НАПОМИНАНИЯ: {"ВКЛЮЧЕНЫ" if on else "ВЫКЛЮЧЕНЫ"}\n\n'
                                    'Одно сообщение за сутки до окончания доступа. Это не рассылка и не автопродление.',
                                    [[('Выключить' if on else 'Включить', 'u:remind_off' if on else 'u:remind_on')], [('‹ Мой доступ', 'u:access')]])
        if act == 'data':
            return await self.panel(m, 'ℹ️ КАК ОБРАБАТЫВАЮТСЯ ДАННЫЕ\n\n' + NOTICE
                                    + '\n\nЕсли нужен доступ к своим данным или их удаление, напишите владельцу здесь.',
                                    [[('🔔 Объявления', 'u:news')], MENU_HOME])
        if act == 'support':
            return await self.panel(m, self.setting_text('support') + '\n\nВаше сообщение получит владелец.',
                                    [[('ℹ️ Как обрабатываются данные', 'u:data')], MENU_HOME])
        if act == 'faq':
            return await self.panel(m, self.setting_text('faq') or 'Информация пока не добавлена.', [MENU_HOME])
        if act == 'plans':
            items = self.db.all('SELECT id,title,days,stars FROM plans WHERE enabled=1 ORDER BY days,id LIMIT 30')
            rows = [[(f'{p["title"]} · {p["days"]} дн.' + (f' · {p["stars"]} ₽' if p['stars'] else ''), f'u:open:{p["id"]}')] for p in items]
            if self.db.get('trial_enabled') == '1' and uid != self.admin and not self.db.one('SELECT 1 FROM memberships WHERE uid=?', uid):
                rows.insert(0, [('🎁 Попробовать 1 день бесплатно', 'u:trial')])
            caption = self.setting_text('tariffs') if rows else 'Сейчас нет доступных тарифов. Напишите в поддержку.'
            return await self.panel(m, f'📋 ВАРИАНТЫ ДОСТУПА\n\n{caption}', rows + [MENU_HOME])
        if act == 'open':
            ident = decimal(arg, 10)
            if ident:
                return await self.user_plan(m, ident)
        if act in {'news', 'news_on', 'news_off'}:
            if act != 'news':
                self.db.run('INSERT INTO users(id,first_seen,last_start,starts) VALUES (?, ?, ?, 0) ON CONFLICT(id) DO NOTHING', uid, now(), now())
                self.db.run('UPDATE users SET news=? WHERE id=?', int(act == 'news_on'), uid)
            saved = self.db.one('SELECT news FROM users WHERE id=?', uid)
            on = bool(saved and saved['news'])
            return await self.panel(m, f'🔔 СЕРВИСНЫЕ ОБЪЯВЛЕНИЯ: {"ВКЛЮЧЕНЫ" if on else "ВЫКЛЮЧЕНЫ"}\n\n'
                                    'Это сообщения об изменениях в работе проекта. Отключение не влияет на доступ к группе.',
                                    [[('Выключить' if on else 'Включить', 'u:news_off' if on else 'u:news_on')], MENU_HOME])
        if act == 'trial':
            return await self.panel(m, '🎁 Пробный доступ на 1 день\n\nБесплатно, один раз для нового подписчика. Автосписаний нет.',
                                    [[('Активировать', 'u:trial_yes')], [('‹ Тарифы', 'u:plans')]])
        if act == 'trial_yes':
            async with self.access_lock:
                end = None if uid == self.admin else self.db.claim_trial(uid, now())
                if end is not None:
                    self.expiry_changed.set()
            if end is None:
                return await self.panel(m, 'Пробный доступ недоступен или уже был использован.', [[('‹ Тарифы', 'u:plans')], MENU_HOME])
            await self.panel(m, f'🎁 Пробный доступ активирован до {utc(end)}.', [[('🔐 Открыть мой доступ', 'u:access')], MENU_HOME])
            return await self.access(uid)

    async def user_renew(self, m, uid):
        return await self.panel(m, 'Выберите срок для новой заявки. Уже выданный доступ не изменится, а после одобрения новый срок прибавится к действующему.',
                                [[('📋 Варианты доступа', 'u:plans')], [('‹ Мой доступ', 'u:access')]])

    async def renewal_tick(self):
        rows = await asyncio.to_thread(self.db.due_renewals, self.admin, now(), DAY)
        for row in rows:
            uid, end = row['uid'], row['until']
            async with self.access_lock:
                allowed = await asyncio.to_thread(self.db.reserve_reminder, uid, end, now())
            if not allowed:
                continue
            try:
                await self.bot.send_message(uid, f'⏳ Доступ действует до {utc(end)}. Хотите остаться? Отправьте заявку на продление.',
                                            reply_markup=keyboard([('🔄 Запросить продление', 'u:renew')], [('🔔 Настроить напоминания', 'u:reminders')]))
            except TelegramAPIError:
                LOG.info('Уведомление о продлении не доставлено')
            await asyncio.sleep(0.08)
        upcoming = await asyncio.to_thread(self.db.next_renewal, self.admin, now())
        if upcoming is None:
            return None
        return max(now()+60, upcoming - DAY)

    async def admin_home(self, m):
        return await self.panel(m, '⚙️ УПРАВЛЕНИЕ ПРОЕКТОМ\n\nТарифы, реквизиты, проверка скриншотов и управление доступом.',
                                edit=False, markup=OWNER_MENU)

    async def tariffs(self, m, page=0, *, edit=True):
        total = self.db.one('SELECT COUNT(*) AS n FROM plans')['n']
        last = max(0, (total-1)//PAGE)
        page = min(page, last)
        plans = self.db.all('SELECT * FROM plans ORDER BY id DESC LIMIT ? OFFSET ?', PAGE, page * PAGE)
        rows = [[(f'{"●" if p["enabled"] else "○"} {p["title"]} · {p["days"]} дн.' + (f' · {p["stars"]} ₽' if p['stars'] else ''), f'a:rate:{p["id"]}')] for p in plans]
        nav = []
        if page:
            nav.append(('‹', f'a:tariffs:{page-1}'))
        if page < last:
            nav.append(('›', f'a:tariffs:{page+1}'))
        if nav:
            rows.append(nav)
        state = 'вкл.' if self.db.get('trial_enabled') == '1' else 'выкл.'
        rows += [[('＋ Новый вариант', 'a:new_rate'), (f'🎁 Пробный: {state}', 'a:trial_setup')], OWNER_BACK]
        return await self.panel(m, f'📋 ВАРИАНТЫ ДОСТУПА · {page+1}/{last+1}\n\n● Видно подписчикам   ○ Скрыто', rows, edit=edit)

    async def admin_rate(self, m, ident, *, edit=True):
        p = self.rate(ident)
        if not p:
            return await self.panel(m, 'Тариф не найден.', [[('‹ Тарифы', 'a:tariffs:0')]], edit=edit)
        username = (await self.bot.get_me()).username
        state = 'виден подписчикам' if p['enabled'] else 'скрыт (черновик)'
        link = f'https://t.me/{username}?start=plan_{ident}' if username else '—'
        return await self.panel(m, f'💳 {p["title"]}\nТариф #{ident} · {state}\n\n'
                                f'Описание: {p["description"] or "—"}\nСрок: {p["days"]} дн.\nСтоимость: {p["stars"]} ₽\n\n'
                                f'Прямая ссылка для опубликованного тарифа:\n{link}', [
                                    [('✏️ Название', f'a:field:{ident},title'), ('📝 Описание', f'a:field:{ident},description')],
                                    [('⏳ Срок', f'a:field:{ident},days'), ('💰 Цена (₽)', f'a:field:{ident},stars')],
                                    [('🙈 Скрыть' if p['enabled'] else '✅ Опубликовать', f'a:toggle:{ident},{0 if p["enabled"] else 1}')],
                                    [('‹ Тарифы', 'a:tariffs:0')],
                                ], edit=edit)

    async def requisites_panel(self, m, *, edit=True):
        req = self.setting_text('requisites')
        note = self.setting_text('payment_note')
        text = (f'💳 РЕКВИЗИТЫ ДЛЯ ОПЛАТЫ\n\n{req}\n\n'
                f'📸 Инструкция для подписчика:\n{note}')
        return await self.panel(m, text, [
            [('✏️ Изменить реквизиты', 'a:text:requisites')],
            [('📝 Изменить инструкцию', 'a:text:payment_note')],
            OWNER_BACK,
        ], edit=edit)

    async def design(self, m, *, edit=True):
        return await self.panel(m, '🎨 ДИЗАЙН БОТА\n\nНастройте тексты ответов, реквизиты и кнопки. Уведомление о передаче сообщений остаётся видимым.', [
            [('✉️ Тексты ответов', 'a:texts'), ('🔳 Главное меню', 'a:menu_design')],
            [('💳 Реквизиты оплаты', 'a:requisites'), ('👁 Предпросмотр', 'a:preview')],
            OWNER_BACK], edit=edit)

    async def person(self, m, uid, *, edit=True):
        u = self.db.one('SELECT * FROM users WHERE id=?', uid)
        r = self.db.one('SELECT until FROM memberships WHERE uid=?', uid)
        paid = self.db.one('SELECT COUNT(*) AS n FROM payments p JOIN orders o ON o.token=p.token WHERE o.uid=?', uid)['n']
        if not u and not r:
            return await self.panel(m, 'Нет записи с таким ID. Попросите пользователя запустить бота.', [[('‹ Подписчики', 'a:people')]], edit=edit)
        status = 'Подписки ещё не было.' if not r else f'{"Активна до" if r["until"] > now() else "Истекла"} {utc(r["until"])}'
        return await self.panel(m, f'👤 ПОДПИСЧИК · {uid}\n\n{status}\nОплат: {paid}\nЗапусков: {u["starts"] if u else 0}', [
            [('📝 Выдать или продлить доступ', f'a:grant_for:{uid}')], [('‹ Подписчики', 'a:people')]], edit=edit)

    async def prompt(self, m, act, text, **payload):
        # A single owner draft, tied to a reply to this exact message, survives redeploys.
        item = await m.answer(text + '\n\nОтветьте на это сообщение. Отмена: /cancel',
                              reply_markup=ForceReply(input_field_placeholder='Введите значение'))
        self.db.set('owner_prompt', json.dumps(dict(act=act, mid=item.message_id, expires=now()+1800, **payload)))

    async def owner_text(self, m):
        raw = self.db.get('owner_prompt')
        if raw and json.loads(raw)['expires'] > now():
            return await m.answer('Нажмите «Ответить» на сообщение, в котором бот просит ввод, и отправьте значение. Отмена: /cancel')

    async def cancel_command(self, m):
        if m.from_user.id == self.admin:
            self.db.run('DELETE FROM settings WHERE key=?', 'owner_prompt')
            return await self.panel(m, 'Ввод отменён. Уже сохранённые изменения остались.', [OWNER_BACK], edit=False)

    async def admin_reply(self, m):
        if m.text == '/cancel':
            return await self.cancel_command(m)
        raw = self.db.get('owner_prompt')
        data = json.loads(raw) if raw else None
        if not data or data['mid'] != m.reply_to_message.message_id:
            return await super().admin_reply(m)
        if data['expires'] <= now():
            self.db.run('DELETE FROM settings WHERE key=?', 'owner_prompt')
            return await m.answer('Время ввода истекло. Откройте нужный раздел ещё раз.')
        act = data['act']
        text = (m.text or '').strip()
        if act == 'broadcast':
            if not (m.text or m.photo or m.video or m.document or m.animation or m.audio or m.voice or m.sticker):
                return await m.answer('Для рассылки ответьте на приглашение текстом, фото, видео, голосовым или файлом.')
            self.db.run('DELETE FROM settings WHERE key=?', 'owner_prompt')
            return await self.admin_command(SimpleNamespace(reply_to_message=m, answer=m.answer),
                                            SimpleNamespace(command='broadcast', args=None))
        if not text:
            return await m.answer('Для этого действия нужен текст. Ответьте на исходное приглашение ещё раз.')
        reply = None
        if act == 'new_title':
            if len(text) > 32 or '\n' in text:
                return await m.answer('Название — одна строка, до 32 символов. Ответьте на приглашение ещё раз.')
            return await self.prompt(m, 'new_days', 'Шаг 2/3. На сколько дней выдавать доступ? Введите число от 1 до 365.', title=text)
        elif act == 'new_days':
            days = decimal(text, 3)
            if not days or days > 365:
                return await m.answer('Нужно число от 1 до 365. Ответьте на приглашение ещё раз.')
            return await self.prompt(m, 'new_description', 'Шаг 3/3. Опишите доступ (до 800 символов). Чтобы пропустить, отправьте дефис: -',
                                     title=data['title'], days=days)
        elif act == 'new_description':
            if len(text) > 800:
                return await m.answer('В описании может быть до 800 символов.')
            ident = self.db.create_plan(data['title'], data['days'], 0, '' if text == '-' else text, actor=self.admin)
            await m.answer('Черновик создан. Проверьте детали, укажите цену и нажмите «Опубликовать», когда будете готовы.')
            reply = self.admin_rate(m, ident, edit=False)
        elif act == 'field':
            ident, name = data['ident'], data['name']
            if not self.rate(ident):
                return await m.answer('Тариф больше не найден.')
            if name == 'description':
                if len(text) > 800:
                    return await m.answer('Описание: не больше 800 символов.')
                self.db.edit_plan(ident, {'description': '' if text == '-' else text}, self.admin)
            elif name == 'title':
                if len(text) > 32 or '\n' in text:
                    return await m.answer('Название: одна строка, до 32 символов.')
                self.db.edit_plan(ident, {'title': text}, self.admin)
            elif name == 'days':
                value = decimal(text, 5)
                if not value or value > 365:
                    return await m.answer('Введите число из диапазона в приглашении.')
                self.db.edit_plan(ident, {name: value}, self.admin)
            elif name == 'stars':
                value = decimal(text, 7)
                if value is None or value > 1000000:
                    return await m.answer('Введите стоимость в рублях от 0 до 1000000.')
                self.db.edit_plan(ident, {'stars': value}, self.admin)
            reply = self.admin_rate(m, ident, edit=False)
        elif act == 'design':
            key = data['key']
            cap = DESIGN[key][2]
            if len(text) > cap or (cap == 25 and '\n' in text):
                return await m.answer(f'Введите не более {cap} символов. Для названия кнопки нужна одна строка.')
            dbkey = 'welcome' if key == 'welcome' else 'text:' + key
            if text == '-':
                self.db.run('DELETE FROM settings WHERE key=?', dbkey)
            else:
                self.db.set(dbkey, text)
            await m.answer('Настройка сохранена.')
            reply = self.requisites_panel(m, edit=False) if key in {'requisites', 'payment_note'} else self.design(m, edit=False)
        elif act == 'payment_find':
            if len(text) > 256 or '\n' in text:
                return await m.answer('Введите ID одной строкой (до 256 символов).')
            reply = self.payment_detail(m, text, edit=False)
        elif act == 'find':
            ident = decimal(text)
            if not ident:
                return await m.answer('Нужен личный числовой Telegram ID без минуса.')
            reply = self.person(m, ident, edit=False)
        elif act in {'grant', 'grant_for', 'extend'}:
            if act == 'grant':
                if not re.fullmatch(r'[0-9]{1,16}\s+[0-9]{1,3}', text):
                    return await m.answer('Введите ID и срок через пробел. Пример: 123456789 30')
                values = text.split()
            elif act == 'grant_for':
                values = [str(data['uid']), text]
            else:
                values = [text]
            if not decimal(values[-1], 3) or int(values[-1]) > 365:
                return await m.answer('Введите срок от 1 до 365 дней.')
            reply = self.admin_command(m, SimpleNamespace(command='extend' if act == 'extend' else 'grant', args=' '.join(values)))
        self.db.run('DELETE FROM settings WHERE key=?', 'owner_prompt')
        if reply:
            await reply

    async def admin_button(self, q):
        if q.from_user.id != self.admin:
            return await q.answer('Нет доступа.', show_alert=True)
        act, _, arg = q.data[2:].partition(':')
        extra = {
            'home', 'stats', 'tariffs', 'settings', 'rate', 'toggle', 'new_rate', 'field', 'trial_setup', 'trial_set',
            'people', 'person', 'find', 'active', 'soon', 'expired', 'grant', 'grant_for', 'extend',
            'design', 'texts', 'menu_design', 'text', 'preview', 'broadcast_ui', 'broadcast', 'reviews', 'review', 'close',
            'export', 'giveaway', 'giveaway_prepare', 'giveaway_draw', 'payments', 'payment_find', 'sales_pause',
            'audit', 'audit_one', 'audit_csv', 'requests', 'request_detail', 'request_approve', 'request_deny', 'requisites',
        }
        if act not in extra:
            return await super().admin_button(q)
        await q.answer()
        m = q.message
        if act == 'home':
            return await self.panel(m, '⚙️ УПРАВЛЕНИЕ ПРОЕКТОМ\n\nТарифы, реквизиты, проверка скриншотов и управление доступом.', markup=OWNER_MENU)
        if act == 'requisites':
            return await self.requisites_panel(m)
        if act == 'stats':
            t = now()
            s = self.db.one('''SELECT COUNT(*) AS users, COALESCE(SUM(starts),0) AS starts,
                (SELECT COUNT(*) FROM memberships WHERE until>?) AS active,
                (SELECT COUNT(*) FROM payments) AS paid,
                (SELECT COALESCE(SUM(o.stars),0) FROM payments p JOIN orders o ON p.token=o.token) AS stars,
                (SELECT COUNT(*) FROM trial_claims) AS trials,
                (SELECT COUNT(*) FROM access_requests WHERE status='pending') AS pending
                FROM users WHERE users.id<>?''', t, self.admin)
            return await self.panel(m, f'📊 СТАТИСТИКА\n\nПользователей: {s["users"]}\nЗапусков: {s["starts"]}\n'
                                    f'Активный доступ: {s["active"]}\nПробных доступов выдано: {s["trials"]}\n\n'
                                    f'Заявок / скриншотов на проверке: {s["pending"]}\nПодтверждённых оплат: {s["paid"]}',
                                    [[('📥 Заявки / Скрины', 'a:requests:0'), ('🧾 Архив обращений', 'a:reviews:0')],
                                     [('👥 Подписчики', 'a:people')], OWNER_BACK])
        if act in {'requests', 'request_detail', 'request_approve', 'request_deny'}:
            return await self.owner_request_panel(m, act, decimal(arg, 12) or 0)
        if act in {'tariffs', 'settings'}:
            return await self.tariffs(m, decimal(arg, 6) or 0)
        if act == 'rate':
            ident = decimal(arg, 10)
            if ident:
                return await self.admin_rate(m, ident)
        if act == 'new_rate':
            return await self.prompt(m, 'new_title', 'Шаг 1/3. Как называется вариант доступа? Введите одну строку до 32 символов.')
        if act in {'field', 'toggle'}:
            raw, _, val = arg.partition(',')
            ident = decimal(raw, 10)
            p = self.rate(ident) if ident else None
            if not p:
                return await self.tariffs(m)
            if act == 'toggle' and val in {'0', '1'}:
                if val == '1' and not p['enabled'] and self.db.one('SELECT COUNT(*) AS n FROM plans WHERE enabled=1')['n'] >= 30:
                    return await m.answer('Можно показать не больше 30 тарифов. Сначала скройте один из действующих.')
                self.db.edit_plan(ident, {'enabled': int(val)}, self.admin)
                return await self.admin_rate(m, ident)
            rules = {'title': 'Введите новое название — одна строка до 32 символов.',
                     'description': 'Введите описание до 800 символов. Один дефис (-) убирает описание.',
                     'days': 'Введите срок в днях, от 1 до 365. Действующие подписки не изменятся.',
                     'stars': 'Введите стоимость тарифа в рублях (от 0 до 1000000).',
                     }
            if act == 'field' and val in rules:
                return await self.prompt(m, 'field', f'Тариф #{ident} · {p["title"]}\n\n{rules[val]}', ident=ident, name=val)
        if act in {'trial_setup', 'trial_set'}:
            if act == 'trial_set' and arg in {'0', '1'}:
                self.db.set('trial_enabled', arg)
            enabled = self.db.get('trial_enabled') == '1'
            return await self.panel(m, f'🎁 ПРОБНЫЙ ДОСТУП: {"ВКЛЮЧЁН" if enabled else "ВЫКЛЮЧЕН"}\n\n'
                                    '24 часа бесплатно. Доступен один раз на аккаунт, если подписки ещё не было. '
                                    'Выключение скрывает предложение, но не отзывает уже выданные дни.',
                                    [[('Выключить' if enabled else 'Включить', f'a:trial_set:{0 if enabled else 1}')], [('‹ Тарифы', 'a:tariffs:0')]])
        if act == 'people':
            return await self.panel(m, '👥 ПОДПИСЧИКИ\n\nЧтобы найти конкретного человека, используйте Telegram ID из уведомления о /start.', [
                [('🔎 Найти по ID', 'a:find'), ('📝 Выдать доступ', 'a:grant')],
                [('🟢 Активные', 'a:active:0'), ('⏳ Истекают за 7 дней', 'a:soon:0')],
                [('🕓 Последние истечения', 'a:expired'), ('＋ Продлить всем', 'a:extend')],
                [('📥 Скачать список CSV', 'a:export')], OWNER_BACK])
        if act == 'person':
            uid = decimal(arg)
            if uid:
                return await self.person(m, uid)
        if act == 'find':
            return await self.prompt(m, 'find', 'Введите Telegram ID пользователя — только цифры.')
        if act in {'grant', 'grant_for', 'extend'}:
            if act == 'grant':
                return await self.prompt(m, 'grant', 'Введите Telegram ID и число дней через пробел. Пример: 123456789 30.')
            if act == 'extend':
                return await self.prompt(m, 'extend', 'На сколько дней продлить все действующие подписки? Введите число от 1 до 365. Перед изменением будет подтверждение.')
            uid = decimal(arg)
            if uid:
                return await self.prompt(m, 'grant_for', f'На сколько дней выдать или продлить доступ для ID {uid}? Введите число от 1 до 365.', uid=uid)
        if act in {'active', 'soon', 'expired'}:
            page = decimal(arg, 6) or 0
            t = now()
            if act == 'soon':
                found = self.db.all('SELECT uid,until FROM memberships WHERE until>? AND until<=? ORDER BY until,uid LIMIT ? OFFSET ?', t, t+7*DAY, PAGE+1, page*PAGE)
                title = 'ИСТЕКАЮТ В БЛИЖАЙШИЕ 7 ДНЕЙ'
            elif act == 'active':
                found = self.db.all('SELECT uid,until FROM memberships WHERE until>? ORDER BY until,uid LIMIT ? OFFSET ?', t, PAGE+1, page*PAGE)
                title = 'АКТИВНЫЕ ПОДПИСКИ'
            else:
                page = 0
                found = self.db.all('SELECT uid,until FROM memberships WHERE until<=? ORDER BY until DESC,uid LIMIT 5', t)
                title = 'ПОСЛЕДНИЕ ИСТЕЧЕНИЯ'
            rows = [[(f'{r["uid"]} · {utc(r["until"])}', f'a:person:{r["uid"]}')] for r in found[:PAGE]]
            nav = []
            if page:
                nav.append(('‹', f'a:{act}:{page-1}'))
            if len(found) > PAGE:
                nav.append(('›', f'a:{act}:{page+1}'))
            if nav:
                rows.append(nav)
            return await self.panel(m, f'👥 {title}\n\n' + ('Нажмите на Telegram ID, чтобы открыть карточку.' if found else 'Нет записей на этой странице.'),
                                    rows + [[('‹ Подписчики', 'a:people')]])
        if act == 'design':
            return await self.design(m)
        if act in {'texts', 'menu_design'}:
            keys = ('welcome', 'tariffs', 'requisites', 'payment_note', 'resource_label', 'support', 'paid') if act == 'texts' else ('menu_plans', 'menu_access', 'menu_support', 'menu_news', 'faq_label', 'faq')
            rows = [[(DESIGN[key][0], f'a:text:{key}')] for key in keys]
            title = 'ТЕКСТЫ ОТВЕТОВ' if act == 'texts' else 'ГЛАВНОЕ МЕНЮ'
            subtitle = 'Выберите ответ для редактирования.' if act == 'texts' else 'Переименуйте кнопки. Чтобы добавить свою кнопку, сначала напишите текст её страницы.'
            return await self.panel(m, f'🎨 {title}\n\n{subtitle}', rows + [[('‹ Дизайн', 'a:design')]])
        if act == 'text' and arg in DESIGN:
            label, _, cap = DESIGN[arg]
            current = self.setting_text(arg)
            if len(current) > 450:
                current = current[:450] + '…'
            return await self.prompt(m, 'design', f'{label}\n\nСейчас: {current or "не задано"}\n\n'
                                     f'Введите новый текст (до {cap} символов). Один дефис (-) вернёт стандартный вариант.', key=arg)
        if act == 'preview':
            return await self.show_home(m, preview=True)
        if act in {'broadcast', 'broadcast_ui'}:
            count = self.db.one('SELECT COUNT(*) AS n FROM users WHERE id<>? AND news=1 AND starts>0', self.admin)['n']
            if act == 'broadcast':
                return await self.prompt(m, 'broadcast', f'Получателей: {count}. Ответьте текстом или одним медиафайлом. '
                                         'Сообщение не уйдёт без вашего подтверждения.')
            return await self.panel(m, f'📣 СЕРВИСНЫЕ ОБЪЯВЛЕНИЯ\n\nДоступно получателей: {count}. Новые пользователи подключаются автоматически после /start. '
                                      'Отключившим объявления сообщения не отправляются. Используйте для важных изменений в работе проекта.', [
                [('✏️ Подготовить сообщение', 'a:broadcast')], OWNER_BACK])
        if act in {'payments', 'sales_pause'}:
            last = self.db.all('''SELECT p.paid,p.charge,o.uid,o.stars FROM payments p JOIN orders o ON o.token=p.token
                ORDER BY p.paid DESC,p.charge LIMIT 5''')
            text = '\n\n'.join(f'{utc(r["paid"])} · {r["stars"]} ⭐ · пользователь {r["uid"]}\nID: {r["charge"]}' for r in last)
            return await self.panel(m, '🗃 АРХИВ ОПЛАТ\n\nЗдесь отображаются подтверждённые оплаты.\n\n' + (text or 'Подтверждённых оплат нет.'),
                                    [[('🔎 Поиск по ID платежа', 'a:payment_find')], OWNER_BACK])
        if act == 'payment_find':
            return await self.prompt(m, 'payment_find', 'Вставьте полный ID платежа из уведомления или из истории оплат подписчика.')
        if act in {'audit', 'audit_one', 'audit_csv'}:
            return await self.audit_panel(m, act, decimal(arg, 12) or 0)
        if act == 'export':
            rows = self.db.all('SELECT uid,until FROM memberships ORDER BY uid')
            output = io.StringIO(newline='')
            writer = csv.writer(output, delimiter=';')
            writer.writerow(['Telegram ID', 'Действует до (UTC)', 'Статус'])
            t = now()
            for r in rows:
                dt = datetime.fromtimestamp(r['until'], timezone.utc).isoformat()
                writer.writerow([r['uid'], dt, 'Активна' if r['until'] > t else 'Истекла'])
            path = f'podpiski-{datetime.now(timezone.utc):%Y-%m-%d}.csv'
            doc = BufferedInputFile(output.getvalue().encode('utf-8-sig'), filename=path)
            return await m.answer_document(doc, caption=f'Записей: {len(rows)}. Это список подписок, а не резервная копия Neon.')
        if act in {'giveaway', 'giveaway_prepare', 'giveaway_draw'}:
            eligibility = '''FROM memberships m WHERE m.uid<>? AND m.until>?
                AND EXISTS (SELECT 1 FROM orders o JOIN payments p ON p.token=o.token WHERE o.uid=m.uid)'''
            if act == 'giveaway_prepare':
                ticket = secrets.token_urlsafe(10)
                self.db.set('giveaway_confirmation', f'{ticket}:{now()+600}')
                return await self.panel(m, 'Выбрать одного случайного победителя? Результат увидите только вы. '
                                        'Бот ничего не отправляет подписчикам и не списывает Stars.',
                                        [[('🎲 Выбрать', f'a:giveaway_draw:{ticket}')], [('Отмена', 'a:giveaway')]])
            if act == 'giveaway_draw':
                raw = self.db.get('giveaway_confirmation', '')
                expected, _, expiry = raw.partition(':')
                if not expected or arg != expected or not expiry.isdecimal() or int(expiry) <= now():
                    return await self.panel(m, 'Это подтверждение больше не действует.', [[('‹ Розыгрыш', 'a:giveaway')]])
                roster = self.db.all('SELECT m.uid ' + eligibility + ' ORDER BY m.uid', self.admin, now())
                with self.db.connection() as db:
                    result = db.execute('''DELETE FROM settings WHERE key='giveaway_confirmation' AND value=?''', (raw,))
                    if result.rowcount and roster:
                        uid = secrets.choice(roster)['uid']
                        label = f'ID {uid} · {utc(now())} · участников: {len(roster)}'
                        db.execute('''INSERT INTO settings VALUES ('last_giveaway', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value''', (label,))
                if not roster:
                    return await self.panel(m, 'Нет подходящих участников.', [[('‹ Розыгрыш', 'a:giveaway')]])
                return await self.panel(m, f'🏆 Последний результат\n\n{self.db.get("last_giveaway", "—")}', [[('‹ Розыгрыш', 'a:giveaway')]])
            self.db.run('DELETE FROM settings WHERE key=?', 'giveaway_confirmation')
            n = self.db.one('SELECT COUNT(*) AS n ' + eligibility, self.admin, now())['n']
            previous = self.db.get('last_giveaway', 'ещё не проводился')
            return await self.panel(m, f'🏆 РОЗЫГРЫШ\n\nУчастников сейчас: {n}. Учитываются пользователи с активным доступом '
                                    f'и хотя бы одной оплатой в боте.\n\nПоследний результат: {previous}',
                                    [[('Подготовить розыгрыш', 'a:giveaway_prepare')], OWNER_BACK] if n else [OWNER_BACK])
        if act == 'reviews':
            page = decimal(arg, 6) or 0
            rows = self.db.all('SELECT id,uid FROM reviews WHERE closed=0 ORDER BY id LIMIT ? OFFSET ?', PAGE+1, page*PAGE)
            buttons = [[(f'#{r["id"]} · ID {r["uid"]}', f'a:review:{r["id"]}')] for r in rows[:PAGE]]
            nav = []
            if page:
                nav.append(('‹', f'a:reviews:{page-1}'))
            if len(rows) > PAGE:
                nav.append(('›', f'a:reviews:{page+1}'))
            if nav:
                buttons.append(nav)
            return await self.panel(m, '🧾 СКРИНШОТЫ НА ПРОВЕРКЕ\n\n' + ('Выберите обращение.' if rows else 'Открытых обращений на этой странице нет.'), buttons + [OWNER_BACK])
        if act in {'review', 'close'}:
            ident = decimal(arg, 12)
            r = self.db.one('SELECT * FROM reviews WHERE id=?', ident) if ident else None
            if not r:
                return await self.panel(m, 'Обращение не найдено.', [[('‹ Обращения', 'a:reviews:0')]])
            if act == 'close':
                count, _ = self.db.run('UPDATE reviews SET closed=1 WHERE id=? AND closed=0', ident)
                return await self.panel(m, ('Отмечено проверенным.' if count else 'Уже проверено.') +
                                        '\nЧтобы сообщить результат, ответьте реплаем на карточку обращения.', [[('‹ Обращения', 'a:reviews:0')]])
            paid = self.db.one('SELECT 1 FROM payments WHERE token=?', r['token'])
            try:
                attachment = await self.bot.copy_message(self.admin, self.admin, r['admin_mid'])
                self.remember(attachment.message_id, r['uid'])
            except TelegramAPIError:
                pass
            req_buttons = [('✅ Проверено', f'a:close:{ident}')]
            if r['token'].startswith('req_'):
                req_id = decimal(r['token'][4:], 12)
                if req_id:
                    req_buttons.insert(0, ('📨 Открыть заявку', f'a:request_detail:{req_id}'))
            card = await m.answer(f'🧾 ОБРАЩЕНИЕ #{ident}\n\nОт ID {r["uid"]} · {utc(r["created"])}\n'
                                  f'Оплата в боте: {"подтверждена" if paid else "на проверке"}.\n'
                                  'Ответьте на карточку, чтобы написать подписчику.',
                                  reply_markup=keyboard(req_buttons, [('‹ Обращения', 'a:reviews:0')]))
            self.remember(card.message_id, r['uid'])
            return card

    async def payment_detail(self, m, charge, *, edit=True):
        r = self.db.one('''SELECT p.paid,p.charge,o.uid,o.title,o.days,o.stars FROM payments p
            JOIN orders o ON o.token=p.token WHERE p.charge=?''', charge)
        if not r:
            return await self.panel(m, 'Подтверждённая оплата с таким ID не найдена.', [[('‹ Оплаты', 'a:payments')]], edit=edit)
        return await self.panel(m, f'✅ ОПЛАТА ПОДТВЕРЖДЕНА\n\nДата: {utc(r["paid"])}\nПользователь: {r["uid"]}\n'
                                f'Тариф: {r["title"]}\nСрок: {r["days"]} дн.\nСумма: {r["stars"]} ⭐\nID: {r["charge"]}',
                                [[('👤 Подписчик', f'a:person:{r["uid"]}')], [('‹ Оплаты', 'a:payments')]], edit=edit)

    @staticmethod
    def audit_title(r):
        subject = r['subject']
        return {'grant': f'Ручная выдача · ID {subject}', 'extend_all': 'Массовое продление',
                'plan_create': f'Создан тариф #{subject}', 'plan_edit': f'Изменён тариф #{subject}',
                'access_approved': f'Одобрена заявка · ID {subject}', 'access_denied': f'Отклонена заявка · ID {subject}'}.get(r['action'], r['action'])

    async def audit_panel(self, m, act, ident):
        back = [('‹ Журнал', 'a:audit:0')]
        if act == 'audit':
            page = min(ident, 100000)
            rows = self.db.all('SELECT * FROM owner_audit ORDER BY id DESC LIMIT ? OFFSET ?', PAGE+1, page*PAGE)
            buttons = [[(self.audit_title(r), f'a:audit_one:{r["id"]}')] for r in rows[:PAGE]]
            nav = []
            if page:
                nav.append(('‹', f'a:audit:{page-1}'))
            if len(rows) > PAGE:
                nav.append(('›', f'a:audit:{page+1}'))
            if nav:
                buttons.append(nav)
            return await self.panel(m, '📋 ЖУРНАЛ ДЕЙСТВИЙ\n\nЗдесь записываются изменения после установки обновления. '
                                    + ('Выберите запись.' if rows else 'На этой странице записей нет.'), buttons + [OWNER_BACK])
        r = self.db.one('SELECT * FROM owner_audit WHERE id=?', ident)
        if not r:
            return await self.panel(m, 'Запись не найдена.', [back])
        details = json.loads(r['details'])
        buttons = [back]
        if r['action'] == 'grant':
            content = f'Добавлено дней: {details["days"]}\nДоступ до: {utc(details["until"])}'
            buttons.insert(0, [('👤 Подписчик', f'a:person:{r["subject"]}')])
        elif r['action'] in {'access_approved', 'access_denied'}:
            content = f'Заявка #{details["request"]}, срок: {details["days"]} дн.'
            if details['until']:
                content += f'\nДоступ до: {utc(details["until"])}'
            buttons.insert(0, [('📨 Карточка заявки', f'a:request_detail:{details["request"]}')])
        elif r['action'] == 'extend_all':
            if act == 'audit_csv':
                rows = self.db.all('SELECT uid FROM owner_audit_users WHERE audit_id=? ORDER BY uid', ident)
                csv_bytes = ('Telegram ID\r\n' + ''.join(f'{row["uid"]}\r\n' for row in rows)).encode('utf-8-sig')
                return await m.answer_document(BufferedInputFile(csv_bytes, filename=f'extend-{ident}.csv'),
                                               caption=f'Пользователей в этом продлении: {len(rows)}')
            count = self.db.one('SELECT COUNT(*) AS n FROM owner_audit_users WHERE audit_id=?', ident)['n']
            content = f'Добавлено дней каждому: {details["days"]}\nИзменено подписок: {count}'
            buttons.insert(0, [('📥 Скачать ID пользователей', f'a:audit_csv:{ident}')])
        elif r['action'] == 'plan_edit':
            content = '\n\n'.join(f'{AUDIT_FIELDS.get(key,key)}: {str(delta["before"])[:340] or "—"} → '
                                  f'{str(delta["after"])[:340] or "—"}' for key, delta in details.items())
        else:
            content = '\n'.join(f'{AUDIT_FIELDS.get(key,key)}: {val}' for key, val in details.items())
        return await self.panel(m, f'📋 {self.audit_title(r)}\n{utc(r["happened"])} · владелец {r["actor"]}\n\n{content}', buttons)

    async def request_panel(self, q, act, plan_id):
        m, uid = q.message, q.from_user.id
        menu = [[('‹ Мой доступ', 'u:access')], MENU_HOME]
        if act == 'request_status':
            row = self.db.one('SELECT * FROM access_requests WHERE uid=? ORDER BY id DESC LIMIT 1', uid)
            if not row:
                draft = self.db.get_payment_draft(uid)
                if draft:
                    return await self.panel(
                        m,
                        f'💳 Ожидается скриншот оплаты\n\nТариф: {draft["title"]} · {draft["days"]} дн. ({draft["price"]} ₽)\n\n'
                        f'Реквизиты:\n{self.setting_text("requisites")}\n\n'
                        'Отправьте скриншот чека (фото или документ) в этот чат.',
                        [[('📤 Отправить заявку', f'u:request_yes:{draft["plan_id"]}')], *menu],
                    )
                return await self.panel(m, 'У вас пока нет заявок.', [[('📋 Варианты доступа', 'u:plans')], *menu])
            state = {'pending': 'На рассмотрении', 'approved': 'Одобрена', 'denied': 'Отклонена'}[row['status']]
            shot = self.db.get_request_screenshot(row['id'])
            shot_line = '\nСкриншот чека: прикреплён ✅' if (shot and shot['file_id']) else '\nСкриншот чека: можно отправить фото в этот чат 📸'
            rows = [[('🔐 Мой доступ', 'u:access')], MENU_HOME] if row['status'] == 'approved' else menu
            return await self.panel(m, f'📨 Заявка #{row["id"]}\n\n{row["title"]} · {row["days"]} дн.\nСтатус: {state}.{shot_line}', rows)
        plan = self.rate(plan_id, active=True) if plan_id else None
        if not plan:
            return await self.panel(m, 'Вариант недоступен. Выберите другой.', [[('‹ Варианты доступа', 'u:plans')], MENU_HOME])
        if act == 'request':
            await asyncio.to_thread(self.db.save_payment_draft, uid, plan_id, now())
            price_line = f'Сумма к оплате: {plan["stars"]} ₽\n\n' if plan['stars'] else ''
            return await self.panel(
                m,
                f'💳 Оплата по реквизитам: {plan["title"]} · {plan["days"]} дн.\n'
                f'{price_line}'
                f'📋 Реквизиты для перевода:\n{self.setting_text("requisites")}\n\n'
                f'📸 {self.setting_text("payment_note")}',
                [[('📤 Я оплатил — отправить на проверку', f'u:request_yes:{plan_id}')],
                 [('‹ Назад', f'u:open:{plan_id}')]],
            )
        result, item = await asyncio.to_thread(self.db.submit_access_request, uid, plan_id, now())
        if not item:
            return await self.panel(m, 'Не удалось подать заявку. Если предыдущую заявку отклонили, повторить можно через сутки. '
                                    'В остальных случаях откройте меню заново через /start.', menu)
        ident = item['id']
        if result == 'created':
            price_text = f' · {plan["stars"]} ₽' if plan['stars'] else ''
            notice = await self.notify(f'📨 Новая заявка #{ident}\n\n{item["title"]} · {item["days"]} дн.{price_text}\n\n{profile(q.from_user)}',
                                       reply_markup=keyboard([('✅ Одобрить', f'a:request_approve:{ident}'),
                                                              ('✖️ Отклонить', f'a:request_deny:{ident}')],
                                                             [('📥 Очередь', 'a:requests:0')]))
            if notice:
                self.remember(notice.message_id, uid)
        return await self.panel(
            m,
            f'📨 Заявка #{ident} на рассмотрении.\n\n'
            '📸 Пришлите скриншот чека об оплате (фотографией или документом) прямо в этот чат — бот прикрепит его к вашей заявке и отправит владельцу на проверку.',
            [[('Проверить статус', 'u:request_status')], MENU_HOME],
        )

    async def owner_request_panel(self, m, act, ident):
        nav = [('‹ Заявки на доступ', 'a:requests:0')]
        if act == 'requests':
            page = min(ident, 100000)
            rows = self.db.all("SELECT * FROM access_requests WHERE status='pending' ORDER BY id LIMIT ? OFFSET ?", PAGE+1, page*PAGE)
            buttons = []
            for r in rows[:PAGE]:
                shot = self.db.get_request_screenshot(r['id'])
                icon = '🧾 ' if (shot and shot['file_id']) else ''
                buttons.append([(f'{icon}#{r["id"]} · {r["uid"]} · {r["days"]} дн.', f'a:request_detail:{r["id"]}')])
            pagination = []
            if page:
                pagination.append(('‹', f'a:requests:{page-1}'))
            if len(rows) > PAGE:
                pagination.append(('›', f'a:requests:{page+1}'))
            if pagination:
                buttons.append(pagination)
            return await self.panel(m, '📥 ЗАЯВКИ И СКРИНШОТЫ НА ПРОВЕРКЕ\n\n' + ('Выберите заявку для проверки.' if rows else 'Нет ожидающих заявок на этой странице.'),
                                    buttons + [OWNER_BACK])
        r = self.db.one('SELECT * FROM access_requests WHERE id=?', ident)
        if not r:
            return await self.panel(m, 'Заявка не найдена.', [nav])
        if act in {'request_approve', 'request_deny'} and r['status'] == 'pending':
            approve = act == 'request_approve'
            async with self.access_lock:
                changed, end = await asyncio.to_thread(self.db.decide_access_request, ident, self.admin, approve, now())
                if changed and approve:
                    self.expiry_changed.set()
            if changed:
                user_text = (f'✅ Оплата подтверждена! Заявка #{ident} одобрена. Доступ действует до {utc(end)}.' if approve else
                             f'Заявка #{ident} отклонена (оплата не подтверждена). Если у вас уже есть подписка, её срок не изменился.')
                try:
                    await self.bot.send_message(r['uid'], user_text, reply_markup=keyboard([('🔐 Мой доступ', 'u:access')]))
                except TelegramAPIError:
                    await m.answer('Решение сохранено, но личное уведомление не доставлено.')
            r = self.db.one('SELECT * FROM access_requests WHERE id=?', ident)
        shot = self.db.get_request_screenshot(ident)
        if act == 'request_detail' and shot and shot['admin_mid']:
            try:
                copied = await self.bot.copy_message(self.admin, self.admin, shot['admin_mid'])
                if copied:
                    self.remember(copied.message_id, r['uid'])
            except TelegramAPIError:
                pass
        state = {'pending': 'На рассмотрении', 'approved': 'Одобрена', 'denied': 'Отклонена'}[r['status']]
        shot_info = f'\nСкриншот чека: {"прикреплён (" + str(shot["price"]) + " ₽)" if shot and shot["file_id"] else "ожидается"}'
        rows = []
        if r['status'] == 'pending':
            rows.append([('✅ Одобрить', f'a:request_approve:{ident}'), ('✖️ Отклонить', f'a:request_deny:{ident}')])
        return await self.panel(m, f'📨 ЗАЯВКА #{ident}\n\nTelegram ID: {r["uid"]}\n{r["title"]} · {r["days"]} дн.{shot_info}\n'
                                f'Получена: {utc(r["created_at"])}\nСтатус: {state}.',
                                rows + [[('👤 Подписчик', f'a:person:{r["uid"]}')], nav])
