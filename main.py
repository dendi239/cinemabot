import asyncio
import logging
import os

from aiogram import Bot, types
from aiogram.dispatcher import Dispatcher
from aiogram.utils.executor import start_webhook

API_TOKEN = os.environ['API_TOKEN']

# webhook settings
WEBHOOK_HOST = os.environ['WEBHOOK_URL']
WEBHOOK_PATH = '/webhook'
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

# webserver settings
WEBAPP_HOST = 'localhost'  # or ip
WEBAPP_PORT = 3001

logging.basicConfig(level=logging.INFO)

loop = asyncio.get_event_loop()
bot = Bot(token=API_TOKEN, loop=loop)
dp = Dispatcher(bot)


@dp.message_handler()
async def echo(message: types.Message):
    await bot.send_message(message.chat.id, message.text)


@dp.message_handler(['start', 'help'])
async def print_help(message: types.Message):
    await bot.send_message(message.chat.id, "Hello, I'm under development!")


async def on_startup(dp):
    await bot.set_webhook(WEBHOOK_URL)


async def on_shutdown(dp):
    await bot.delete_webhook()


if __name__ == '__main__':
    start_webhook(dispatcher=dp, webhook_path=WEBHOOK_PATH, on_startup=on_startup, on_shutdown=on_shutdown,
                  skip_updates=True, host=WEBAPP_HOST, port=WEBAPP_PORT)
