import asyncio
import logging
import os
import typing as tp
import urllib.parse

import aiogram.utils.markdown as md
from aiogram import Bot, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher import Dispatcher
from aiogram.utils.executor import start_webhook

import api
from inline_keyboard import WrappedInlineKeyboardMarkup


API_TOKEN = os.environ['API_TOKEN']

logging.basicConfig(level=logging.DEBUG)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())


@dp.message_handler(commands=['start', 'help'])
async def show_help(message: types.Message) -> None:
    help_message = \
        "Это *Cinemabot*. " \
        "Бот который умеет искать фильмы и/или сериалы для просмотра.\n\n" \
        "Для простого поиска просто введите запрос. " \
        "Далее можете либо посмотреть первый найденный фильм, либо выбрать из результатов поиска.\n\n" \
        "/start, /help покажут это сообщение снова\n" \
        "/todo покажет сообщение с текущим тудулистом\n" \
        "/schedule `N` `query` выполнит поиск через `N` секунд\n"

    await bot.send_message(message.chat.id, help_message, parse_mode=types.ParseMode.MARKDOWN)


@dp.message_handler(commands=['todo'])
async def show_todo(message: types.Message) -> None:
    todo_message = md.text(
        md.bold('TODO list:'),
        md.text('- webhooks'),
        md.text('- Data validation for `BaseMovie.object_type`'),
        md.text('- Add rating'),
        sep='\n'
    )
    await bot.send_message(message.chat.id, todo_message, parse_mode=types.ParseMode.MARKDOWN)


@dp.message_handler(commands=['schedule'])
async def schedule(message: types.Message) -> None:
    command, duration, query = message.text.split(maxsplit=2)
    await asyncio.sleep(int(duration))
    await send_result(query, message)


@dp.message_handler()
async def search_for_film(message: types.Message) -> None:
    await send_result(message.text, message)


def setup_watch_keyboard(keyboard: types.InlineKeyboardMarkup, film: api.Movie,
                         more_button_query: tp.Optional[str]) -> None:
    if more_button_query is not None:
        keyboard.add(
            *(types.InlineKeyboardButton(api.api.provider_name(offer.provider_id), url=offer.url)
              for offer in film.offers),
            types.InlineKeyboardButton('more', callback_data=f'list:{more_button_query}'),
        )
    else:
        keyboard.add(*(types.InlineKeyboardButton(api.api.provider_name(offer.provider_id), url=offer.url)
                       for offer in film.offers))


async def send_result(query: str, message: types.Message, full_results: bool = True) -> None:
    if film := await api.api.search_for_item(query):
        keyboard = WrappedInlineKeyboardMarkup()
        setup_watch_keyboard(keyboard, film, query if full_results else None)
        await bot.send_photo(message.chat.id, film.get_poster_url(), api.format_description(film),
                             parse_mode=types.ParseMode.HTML, reply_markup=keyboard)
    else:
        await message.reply(f'Ничего не найдено по запросу "{message.text}"')


@dp.callback_query_handler(lambda c: c.data.startswith('movie:') or c.data.startswith('show:'))
async def movie_by_id(callback_data: types.CallbackQuery) -> None:
    movie_type, movie_id = callback_data.data.split(':', maxsplit=2)
    movie_id = int(movie_id)

    if (film := await api.api.movie_details(movie_id, movie_type)) is None:
        return

    keyboard = WrappedInlineKeyboardMarkup()
    setup_watch_keyboard(keyboard, film, None)

    await bot.send_photo(callback_data.from_user.id, film.get_poster_url(), api.format_description(film),
                         parse_mode=types.ParseMode.HTML, reply_markup=keyboard)


@dp.callback_query_handler(lambda c: c.data.startswith('list:'))
async def search_for_item_list(callback_data: types.CallbackQuery) -> None:
    query = callback_data.data[len('list:'):]
    base_movies = [base_movie async for base_movie in api.api.base_search(query)][:10]

    if not base_movies:
        await bot.send_message(callback_data.from_user.id, f'Ничего не найдено по запросу "{query}"')
        return

    message = f'Результаты поиска по запросу "{query}":\n' + '\n'.join(
        f'{index}. {api.format_base_movie(base_movie)}'
        for index, base_movie in enumerate(base_movies, start=1)
    )

    keyboard = WrappedInlineKeyboardMarkup(symbols_limit=10, count_limit=5)
    keyboard.add(
        *(types.InlineKeyboardButton(str(index + 1), callback_data=f'{movie.object_type}:{movie.id}')
          for index, movie in enumerate(base_movies))
    )

    await bot.send_message(callback_data.from_user.id, message,
                           parse_mode=types.ParseMode.HTML, reply_markup=keyboard)


def main():
    if 'WEBHOOK_HOST' in os.environ and 'WEBHOOK_PORT' in os.environ:
        webhook_host = os.environ['WEBHOOK_HOST']
        webhook_port = int(os.environ['WEBHOOK_PORT'])
        webhook_url_path = f'/webhook/{API_TOKEN}'
        webhook_url = urllib.parse.urljoin(webhook_host, webhook_url_path)

        async def on_startup(dp: Dispatcher) -> None:
            await bot.set_webhook(webhook_url)
            await bot.get_webhook_info()

        async def on_shutdown(dp: Dispatcher) -> None:
            await bot.delete_webhook()

        start_webhook(
            dispatcher=dp,
            webhook_path=webhook_url_path,
            skip_updates=False,
            on_startup=on_startup,
            on_shutdown=on_shutdown,
            host='127.0.0.1',
            port=webhook_port,
        )

    else:
        logging.warning("Start polling for updates")
        asyncio.get_event_loop().run_until_complete(dp.start_polling())


if __name__ == '__main__':
    main()
