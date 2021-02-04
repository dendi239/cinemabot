import asyncio
import dataclasses
import logging
import os
import typing as tp

from aiogram import Bot, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher import Dispatcher
from justwatch import JustWatch


API_TOKEN = os.environ['API_TOKEN']

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

jw = JustWatch(country='RU')
providers = {provider['id']: provider for provider in jw.get_providers()}


@dp.message_handler(commands=['start', 'help'])
async def show_help(message: types.Message) -> None:
    help_message = "Это Cinemabot. " \
                   "Бот который умеет искать фильмы и/или сериалы для просмотра.\n" \
                   "Для простого поиска просто введите запрос. " \
                   "Далее можете либо посмотреть первый найденный фильм, либо выбрать из результатов поиска.\n\n" \
                   "/start, /help покажут это сообщение снова\n" \
                   "/todo покажет сообщение с текущим тудулистом"

    await bot.send_message(message.chat.id, help_message, parse_mode=types.ParseMode.MARKDOWN)


@dp.message_handler(commands=['todo'])
async def show_todo(message: types.Message) -> None:
    todo_message = """TODO list:
- [ ] webhooks
- [ ] Movie inherits from BaseMovie
- [ ] Data validation for BaseMovie.object_type
- [ ] Unified format for callback data storage
- [ ] Add rating
    """
    await bot.send_message(message.chat.id, todo_message, parse_mode=types.ParseMode.MARKDOWN)


@dp.message_handler()
async def search_for_film(message: types.Message) -> None:
    async for film in search_for_item(message.text):
        keyboard = WrappedInlineKeyboardMarkup()
        keyboard.add(
            *(types.InlineKeyboardButton(offer.cinema, url=offer.url) for offer in film.offers),
            types.InlineKeyboardButton('more', callback_data=f'list:{message.text}'),
        )

        await bot.send_photo(message.chat.id, film.get_poster_url(), format_description(film),
                             parse_mode=types.ParseMode.HTML, reply_markup=keyboard)
        break
    else:
        await message.reply(f'Ничего не найдено по запросу "{message.text}"',
                            reply_markup=types.ReplyKeyboardRemove())


@dataclasses.dataclass
class CinemaLink:
    cinema: str
    url: str


@dataclasses.dataclass
class Movie:
    title: str
    original_release_year: tp.Optional[int]
    short_description: str
    object_type: str
    poster: str
    offers: tp.List[CinemaLink]

    def get_poster_url(self) -> str:
        return 'https://images.justwatch.com' + self.poster.format(profile='s592')


def parse_cinema_link(cinema_link_json: tp.Dict[str, tp.Any]) -> tp.Optional[CinemaLink]:
    if 'provider_id' not in cinema_link_json or \
            'urls' not in cinema_link_json or \
            'standard_web' not in cinema_link_json['urls']:
        return None

    return CinemaLink(
        providers[cinema_link_json['provider_id']]['clear_name'],
        cinema_link_json['urls']['standard_web'],
    )


def parse_movie(film_json: tp.Dict[str, tp.Any]) -> tp.Optional[Movie]:
    if 'title' not in film_json or \
            'short_description' not in film_json or \
            'poster' not in film_json or \
            'object_type' not in film_json:
        return None

    offers: tp.Dict[str, CinemaLink] = {}
    if 'offers' in film_json and film_json['offers']:
        for offer_json in film_json['offers']:
            cinema_link = parse_cinema_link(offer_json)
            if cinema_link is not None:
                offers[cinema_link.cinema] = cinema_link

    return Movie(
        title=film_json['title'],
        short_description=film_json['short_description'],
        object_type=film_json['object_type'],
        original_release_year=film_json.get('original_release_year', None),
        poster=film_json['poster'],
        offers=list(offers.values()),
    )


def format_description(movie: Movie) -> str:
    name_line = movie.title
    if movie.original_release_year is not None:
        name_line += f' ({movie.original_release_year})'

    return f"<b>{name_line}</b>\n" \
           f"\n" \
           f"{movie.short_description}"


@dataclasses.dataclass
class BaseMovie:
    id: int
    title: str
    object_type: str
    original_release_year: tp.Optional[int]


def parse_base_movie(film_json: tp.Dict[str, tp.Any]) -> tp.Optional[BaseMovie]:
    if 'id' not in film_json or 'title' not in film_json or 'object_type' not in film_json:
        return None

    return BaseMovie(
        id=film_json['id'],
        title=film_json['title'],
        object_type=film_json['object_type'],
        original_release_year=film_json.get('original_release_year', None),
    )


async def base_search_for_item(query: str) -> tp.AsyncIterable[BaseMovie]:
    results = await asyncio.get_event_loop() \
        .run_in_executor(None, lambda: jw.search_for_item(query=query))

    if ('items' not in results) or (not results['items']):
        return

    results = results['items']
    for result_json in results:
        result = parse_base_movie(result_json)
        if result is not None:
            yield result


async def search_for_item(query: str) -> tp.AsyncIterable[Movie]:
    async for base_result in base_search_for_item(query):
        film_json = await asyncio.get_event_loop() \
            .run_in_executor(None, lambda: jw.get_title(base_result.id, content_type=base_result.object_type))

        film = parse_movie(film_json)
        if film is not None:
            yield film


class WrappedInlineKeyboardMarkup(types.InlineKeyboardMarkup):
    def __init__(self, symbols_limit: int = 20, count_limit: int = 3) -> None:
        self.symbols_limit = symbols_limit
        super().__init__(row_width=count_limit)

    def add(self, *args: types.InlineKeyboardButton) -> None:
        row: tp.List[types.InlineKeyboardButton] = []
        row_len = 0

        for button in args:
            if row_len + len(button.text) <= self.symbols_limit and len(row) + 1 <= self.row_width:
                row.append(button)
                row_len += len(button.text)
            else:
                self.inline_keyboard.append(row)
                row = [button]
                row_len = len(button.text)

        self.inline_keyboard.append(row)


@dp.callback_query_handler(lambda c: c.data.startswith('movie:') or c.data.startswith('show:'))
async def movie_by_id(callback_data: types.CallbackQuery) -> None:
    movie_type, movie_id = callback_data.data.split(':', maxsplit=2)
    movie_id = int(movie_id)

    film_json = await asyncio.get_event_loop() \
        .run_in_executor(None, lambda: jw.get_title(movie_id, movie_type))

    film = parse_movie(film_json)
    if film is None:
        return

    keyboard = WrappedInlineKeyboardMarkup()
    keyboard.add(
        *(types.InlineKeyboardButton(offer.cinema, url=offer.url) for offer in film.offers),
    )

    await bot.send_photo(callback_data.from_user.id, film.get_poster_url(), format_description(film),
                         parse_mode=types.ParseMode.HTML, reply_markup=keyboard)


def format_base_movie(base_movie: BaseMovie) -> str:
    if base_movie.original_release_year is not None:
        return f'<b>{base_movie.title}</b> ({base_movie.original_release_year})'
    else:
        return f'<b>{base_movie.title}</b>'


@dp.callback_query_handler(lambda c: c.data.startswith('list:'))
async def search_for_item_list(callback_data: types.CallbackQuery) -> None:
    query = callback_data.data[len('list:'):]
    base_movies = [base_movie async for base_movie in base_search_for_item(query)][:10]

    if not base_movies:
        await bot.send_message(callback_data.from_user.id, f'Ничего не найдено по запросу "{query}"')
        return

    message = f'Результаты поиска по запросу "{query}"' + '\n'.join(
        f'{index}. {format_base_movie(base_movie)}'
        for index, base_movie in enumerate(base_movies, start=1)
    )

    keyboard = WrappedInlineKeyboardMarkup(symbols_limit=10, count_limit=5)
    keyboard.add(
        *(types.InlineKeyboardButton(str(index + 1), callback_data=f'{movie.object_type}:{movie.id}')
          for index, movie in enumerate(base_movies))
    )

    await bot.send_message(callback_data.from_user.id, message,
                           parse_mode=types.ParseMode.HTML, reply_markup=keyboard)


async def main():
    await dp.start_polling()


if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(main())
