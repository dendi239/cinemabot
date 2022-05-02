import abc
import asyncio
import dataclasses
import logging
import typing as tp

import justwatch


@dataclasses.dataclass
class Rating:
    name: str
    score: float

    @classmethod
    def from_json(cls, json: tp.Dict[str, tp.Any]) -> tp.Optional["Rating"]:
        if "provider_type" not in json or "value" not in json:
            return None

        provider = json["provider_type"]
        if not provider.endswith("score"):
            return None

        return Rating(
            name=provider[: -len(":score")],
            score=json["value"],
        )

    def __str__(self) -> str:
        return f"{self.name.title()}: {self.score}"


@dataclasses.dataclass
class BaseMovie:
    id: int
    title: str
    object_type: str
    original_release_year: tp.Optional[int]
    ratings: tp.List[Rating]

    def __init__(self, film_json: tp.Dict[str, tp.Any]) -> None:
        """
        Parses json with base film data.

        :param film_json: json with 'id', 'title', 'object_type' fields present
        :raise if film_json doesn't have listed fields:
        """
        self.id = film_json["id"]
        self.title = film_json["title"]
        self.object_type = film_json["object_type"]
        self.original_release_year = film_json.get("original_release_year", None)

        self.ratings = []
        if "scoring" in film_json and isinstance(film_json["scoring"], list):
            for rating_json in film_json["scoring"]:
                rating = Rating.from_json(rating_json)
                if rating is not None:
                    self.ratings.append(rating)


@dataclasses.dataclass
class CinemaLink:
    provider_id: int
    url: str

    def __init__(self, cinema_link_json: tp.Dict[str, tp.Any]) -> None:
        self.provider_id = cinema_link_json["provider_id"]
        self.url = cinema_link_json["urls"]["standard_web"]


@dataclasses.dataclass
class Movie(BaseMovie):
    short_description: str
    poster: str
    offers: tp.List[CinemaLink]

    def __init__(self, film_json: tp.Dict[str, tp.Any]) -> None:
        super().__init__(film_json)
        self.short_description = film_json["short_description"]
        self.poster = film_json["poster"]

        offers: tp.Dict[int, CinemaLink] = {}
        if "offers" in film_json:
            for offer_json in film_json["offers"]:
                try:
                    cinema_link = CinemaLink(offer_json)
                    offers[cinema_link.provider_id] = cinema_link
                except KeyError:
                    pass

        self.offers = list(offers.values())

    def get_poster_url(self) -> str:
        return "https://images.justwatch.com" + self.poster.format(profile="s592")


def format_base_movie(base_movie: BaseMovie) -> str:
    if base_movie.original_release_year is not None:
        return f"<b>{base_movie.title}</b> ({base_movie.original_release_year})"
    else:
        return f"<b>{base_movie.title}</b>"


def format_description(movie: Movie) -> str:
    name_line = movie.title
    if movie.original_release_year is not None:
        name_line += f" ({movie.original_release_year})"

    return "\n".join(
        (
            f"<b>{name_line}</b>",
            ", ".join(f"{rating}" for rating in movie.ratings),
            "",
            f"{movie.short_description}",
            f"",
        )
    )


class SearchMovieAPI(abc.ABC):
    @abc.abstractmethod
    def provider_name(self, provider_id: int) -> str:
        pass

    @abc.abstractmethod
    def base_search(self, query: str) -> tp.AsyncIterable[BaseMovie]:
        pass

    @abc.abstractmethod
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
    def __init__(self, country: str = "RU") -> None:
        self.jw = justwatch.JustWatch(country=country)
        self.providers = {provider["id"]: provider for provider in self.jw.get_providers()}

    def provider_name(self, provider_id: int) -> tp.Optional[str]:
        if provider_id not in self.providers:
            logging.error(f"no provider with id: '{provider_id}' was found.")
            logging.error(f"  known providers:")
            for id, provider in self.providers.items():
                logging.error(f"    id: '{id}', clear_name: '{provider['clear_name']}'")
            return None
        if "clear_name" not in self.providers[provider_id]:
            return None
        return self.providers[provider_id]["clear_name"]

    async def base_search(self, query: str) -> tp.AsyncIterable[BaseMovie]:
        results = await asyncio.get_event_loop().run_in_executor(None, lambda: self.jw.search_for_item(query=query))

        if ("items" not in results) or (not results["items"]):
            return

        results = results["items"]
        for result_json in results:
            try:
                yield BaseMovie(result_json)
            except KeyError:
                pass

    async def movie_details(self, movie_id: int, object_type: str) -> Movie:
        film_json = await asyncio.get_event_loop().run_in_executor(
            None, lambda: self.jw.get_title(movie_id, content_type=object_type)
        )

        return Movie(film_json)


api = JustWatchSearchMovieAPI()
