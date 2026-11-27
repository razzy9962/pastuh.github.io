"""Render web service entry point. No polling and no local persistent state."""
import asyncio
import hashlib
import hmac
import logging
import os
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import Update
from pydantic import ValidationError

from bot import env_config, init_bot, stop_tasks
from interface import InterfaceApp
from postgres_store import PostgresStore
from storage import now

LOG = logging.getLogger('render_bot')
ROUTE = '/telegram/webhook'
HANDLER = web.AppKey('handler', Callable[[web.Request], Awaitable[web.Response]])


def telegram_handler(bot, dispatcher, store, secret):
    lock = asyncio.Lock()

    async def webhook(request):
        supplied = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
        if not hmac.compare_digest(supplied.encode(), secret.encode()):
            raise web.HTTPForbidden()
        try:
            raw = await request.json()
            update = Update.model_validate(raw, context={'bot': bot})
        except (ValidationError, ValueError, UnicodeError):
            raise web.HTTPBadRequest() from None
        async with lock:
            try:
                seen = await asyncio.to_thread(store.one, 'SELECT 1 FROM webhook_updates WHERE update_id=?', update.update_id)
                if not seen:
                    await dispatcher.feed_update(bot, update)
                    await asyncio.to_thread(store.run,
                        'INSERT INTO webhook_updates VALUES (?, ?) ON CONFLICT(update_id) DO NOTHING', update.update_id, now())
            except Exception:
                LOG.exception('Ошибка обработки Telegram update %s', update.update_id)
                raise web.HTTPServiceUnavailable() from None
        return web.Response(text='ok\n')

    return webhook


def make_app():
    token, admin, channel = env_config()
    url = os.getenv('PUBLIC_BASE_URL', '').strip() or os.getenv('RENDER_EXTERNAL_URL', '').strip()
    dsn = os.getenv('DATABASE_URL', '').strip()
    seed = os.getenv('WEBHOOK_SECRET', '').strip()
    parts = urlsplit(url)
    if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or
            parts.path.rstrip('/') or parts.query or parts.fragment):
        raise SystemExit('Нужен публичный HTTPS-адрес сервиса в RENDER_EXTERNAL_URL или PUBLIC_BASE_URL.')
    if not dsn.startswith(('postgresql://', 'postgres://')):
        raise SystemExit('Добавьте строку PostgreSQL в DATABASE_URL. SQLite на Render не используется.')
    if len(seed) < 32:
        raise SystemExit('WEBHOOK_SECRET: нужен случайный секрет из 32 или более символов.')
    # Render can generate base64 secrets with characters Telegram does not accept.
    secret = hashlib.sha256(seed.encode()).hexdigest()

    async def lifecycle(app):
        store = None
        bot = Bot(token, session=AiohttpSession(timeout=8))
        try:
            try:
                store = await asyncio.to_thread(PostgresStore, dsn)
            except Exception as exc:
                raise RuntimeError(f'Не удалось открыть PostgreSQL ({type(exc).__name__}). Проверьте DATABASE_URL в Render.') from None
            await init_bot(bot, admin, channel)
            controller = InterfaceApp(bot, store, admin, channel)
            dispatcher = Dispatcher()
            dispatcher.include_router(controller.router)
            app[HANDLER] = telegram_handler(bot, dispatcher, store, secret)
            await bot.set_webhook(
                url=url.rstrip('/') + ROUTE, secret_token=secret,
                allowed_updates=dispatcher.resolve_used_update_types(), drop_pending_updates=False,
                max_connections=1,
            )
            LOG.info('Вебхук зарегистрирован. Подписки хранятся в PostgreSQL.')
            worker = asyncio.create_task(controller.expire())
            try:
                yield
            finally:
                await stop_tasks(controller, worker)
        finally:
            await bot.session.close()
            if store:
                await asyncio.to_thread(store.close)

    async def health(_request):
        return web.Response(text='ok\n')

    async def webhook(request):
        return await request.app[HANDLER](request)

    app = web.Application(client_max_size=1024 * 1024)
    app.cleanup_ctx.append(lifecycle)
    app.router.add_get('/', health)
    app.router.add_get('/healthz', health)
    app.router.add_post(ROUTE, webhook)
    return app


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    web.run_app(make_app(), host='0.0.0.0', port=int(os.environ.get('PORT', '10000')), access_log=None)
