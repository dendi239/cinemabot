import asyncio
import dataclasses
import logging
import os
import typing as tp
from abc import abstractmethod, ABC

import aiogram.utils.markdown as md
from aiogram import Bot, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher import Dispatcher
from justwatch import JustWatch


@dataclasses.dataclass
class BaseMovie:
    id: int
    title: str
    object_type: str
    original_release_year: tp.Optional[int]

    def __init__(self, film_json: tp.Dict[str, tp.Any]) -> None:
        """
        Parses json with base film data.

        :param film_json: json with 'id', 'title', 'object_type' fields present
        :raise if film_json doesn't have listed fields:
        """
        self.id = film_json['id']
        self.title = film_json['title']
        self.object_type = film_json['object_type']
        self.original_release_year = film_json.get('original_release_year', None)


@dataclasses.dataclass
class CinemaLink:
    provider_id: int
    url: str

    def __init__(self, cinema_link_json: tp.Dict[str, tp.Any]) -> None:
        self.provider_id = cinema_link_json['provider_id']
        self.url = cinema_link_json['urls']['standard_web']


@dataclasses.dataclass
class Movie(BaseMovie):
    short_description: str
    poster: str
    offers: tp.List[CinemaLink]

    def __init__(self, film_json: tp.Dict[str, tp.Any]) -> None:
        super().__init__(film_json)
        self.short_description = film_json['short_description']
        self.poster = film_json['poster']

        offers: tp.Dict[int, CinemaLink] = {}
        if 'offers' in film_json:
            for offer_json in film_json['offers']:
                try:
                    cinema_link = CinemaLink(offer_json)
                    offers[cinema_link.provider_id] = cinema_link
                except KeyError:
                    pass

        self.offers = list(offers.values())

    def get_poster_url(self) -> str:
        return 'https://images.justwatch.com' + self.poster.format(profile='s592')


def format_base_movie(base_movie: BaseMovie) -> str:
    if base_movie.original_release_year is not None:
        return f'<b>{base_movie.title}</b> ({base_movie.original_release_year})'
    else:
        return f'<b>{base_movie.title}</b>'


def format_description(movie: Movie) -> str:
    name_line = movie.title
    if movie.original_release_year is not None:
        name_line += f' ({movie.original_release_year})'

    return f"<b>{name_line}</b>\n" \
           f"\n" \
           f"{movie.short_description}\n"


class SearchMovieAPI(ABC):
    @abstractmethod
    def provider_name(self, provider_id: int) -> str:
        pass

    @abstractmethod
    def base_search(self, query: str) -> tp.AsyncIterable[BaseMovie]:
        pass

    @abstractmethod
    async def movie_details(self, movie_id: int, object_type: str) -> Movie:
        pass

    async def search_for_item(self, query: str) -> tp.Optional[Movie]:
        async for base_result in self.base_search(query):
            try:
                return await self.movie_details(base_result.id, base_result.object_type)
            except KeyError:
                pass
        else:
            return None


class JustWatchSearchMovieAPI(SearchMovieAPI):
    def __init__(self, country: str = 'RU') -> None:
        self.jw = JustWatch(country=country)
        self.providers = {provider['id']: provider for provider in self.jw.get_providers()}

    def provider_name(self, provider_id: int) -> str:
        return self.providers[provider_id]['clear_name']

    async def base_search(self, query: str) -> tp.AsyncIterable[BaseMovie]:
        results = await asyncio.get_event_loop() \
            .run_in_executor(None, lambda: self.jw.search_for_item(query=query))

        if ('items' not in results) or (not results['items']):
            return

        results = results['items']
        for result_json in results:
            try:
                yield BaseMovie(result_json)
            except KeyError:
                pass

    async def movie_details(self, movie_id: int, object_type: str) -> Movie:
        film_json = await asyncio.get_event_loop() \
            .run_in_executor(None, lambda: self.jw.get_title(movie_id, content_type=object_type))

        return Movie(film_json)


class WrappedInlineKeyboardMarkup(types.InlineKeyboardMarkup):
    def __init__(self, symbols_limit: int = 23, count_limit: int = 3) -> None:
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


API_TOKEN = os.environ['API_TOKEN']

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())
api = JustWatchSearchMovieAPI()


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


def setup_watch_keyboard(keyboard: types.InlineKeyboardMarkup, film: Movie,
                         more_button_query: tp.Optional[str]) -> None:
    if more_button_query is not None:
        keyboard.add(
            *(types.InlineKeyboardButton(api.provider_name(offer.provider_id), url=offer.url)
              for offer in film.offers),
            types.InlineKeyboardButton('more', callback_data=f'list:{more_button_query}'),
        )
    else:
        keyboard.add(*(types.InlineKeyboardButton(api.provider_name(offer.provider_id), url=offer.url)
                       for offer in film.offers))


async def send_result(query: str, message: types.Message, full_results: bool = True) -> None:
    if film := await api.search_for_item(query):
        keyboard = WrappedInlineKeyboardMarkup()
        setup_watch_keyboard(keyboard, film, query if full_results else None)
        await bot.send_photo(message.chat.id, film.get_poster_url(), format_description(film),
                             parse_mode=types.ParseMode.HTML, reply_markup=keyboard)
    else:
        await message.reply(f'Ничего не найдено по запросу "{message.text}"')


@dp.callback_query_handler(lambda c: c.data.startswith('movie:') or c.data.startswith('show:'))
async def movie_by_id(callback_data: types.CallbackQuery) -> None:
    movie_type, movie_id = callback_data.data.split(':', maxsplit=2)
    movie_id = int(movie_id)

    if (film := await api.movie_details(movie_id, movie_type)) is None:
        return

    keyboard = WrappedInlineKeyboardMarkup()
    setup_watch_keyboard(keyboard, film, None)

    await bot.send_photo(callback_data.from_user.id, film.get_poster_url(), format_description(film),
                         parse_mode=types.ParseMode.HTML, reply_markup=keyboard)


@dp.callback_query_handler(lambda c: c.data.startswith('list:'))
async def search_for_item_list(callback_data: types.CallbackQuery) -> None:
    query = callback_data.data[len('list:'):]
    base_movies = [base_movie async for base_movie in api.base_search(query)][:10]

    if not base_movies:
        await bot.send_message(callback_data.from_user.id, f'Ничего не найдено по запросу "{query}"')
        return

    message = f'Результаты поиска по запросу "{query}":\n' + '\n'.join(
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
