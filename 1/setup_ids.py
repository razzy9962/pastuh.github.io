"""Run before launching bot.py. Do not run alongside another polling process."""
import asyncio
import os
from pathlib import Path

from aiogram import Bot
from dotenv import load_dotenv


async def main():
    load_dotenv(Path(__file__).with_name('.env'))
    token = os.getenv('BOT_TOKEN', '').strip()
    if not token:
        raise SystemExit('Заполните BOT_TOKEN в .env.')
    print('Напишите боту /id и опубликуйте ID-SETUP в закрытом канале. Можно сделать это сейчас.')
    ids = {}
    offset = None
    async with Bot(token) as bot:
        if (await bot.get_webhook_info()).url:
            raise SystemExit('У бота активен webhook. Для этого проекта используйте отдельного бота либо отключите webhook.')
        for _ in range(6):
            updates = await bot.get_updates(offset=offset, timeout=10, allowed_updates=['message', 'channel_post'])
            for update in updates:
                offset = update.update_id + 1
                if update.message and update.message.chat.type == 'private' and update.message.text == '/id':
                    ids['ADMIN_ID'] = update.message.chat.id
                if update.channel_post and update.channel_post.text == 'ID-SETUP':
                    ids['CHANNEL_ID'] = update.channel_post.chat.id
            if len(ids) == 2:
                break
        if offset is not None:
            await bot.get_updates(offset=offset, timeout=0, allowed_updates=['message', 'channel_post'])
    for k, v in ids.items():
        print(f'{k}={v}')
    if len(ids) < 2:
        print('Получены не все ID. Повторите команды и запустите скрипт снова.')


if __name__ == '__main__':
    asyncio.run(main())
