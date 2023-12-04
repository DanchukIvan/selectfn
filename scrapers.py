from abc import ABC, abstractmethod
from contextlib import suppress
from datetime import datetime
from urllib.parse import urlparse

from attrs import define, field, validators
from httpx import AsyncClient

import base
from constants import NOTHING
from helpers import mark_as_trigger
from repo import LocalRepo, NetworkRepo, Repo, SqlRepo
from resources import Resource

scrapers_registry = {}


@define(slots=False)
class Scraper(ABC, base.YassActor):
    storage: Repo = field(default=NOTHING)
    resource: Resource = field(default=NOTHING)
    extra_headers: dict = field(default={})
    meta: str = field(default="scrapers")

    def __attrs_pre_init__(self, **kwargs):
        super().__init__(kwargs)

    @abstractmethod
    def scrape(self):
        """Основной метод скрапинга, частный метод реализации которого зависит от типа паука"""

    @abstractmethod
    def pending(self):
        ...

    def make_path(self, storage):
        if (strg_cls := storage.__class__) in (NetworkRepo, LocalRepo):
            domain = urlparse(self.resource.url).hostname
            # TODO: нужно сделать геттеры в ресурсе и кверях - очень неудобно это все расписывать
            query_name, schema_name = (
                self.resource.query_name,
                self.resource.schema_name,
            )
            date = datetime.now().date()
            # TODO: формат вывода должен согласовываться с объектов лоадера - объект, который
            path = f"{domain}/{query_name}/{date}_{schema_name}.{storage.output_format}"
        elif strg_cls == SqlRepo:
            # TODO: для sql хранилищ нужно больше изучить сигнатуру функции to_sql - возможно там можно указать схему
            # в которой нужно создать таблицу и тогда это нужно передавать в сторадж, а путь парсить как 'схема(кверя)/таблица(имя схемы)'
            path = f"{self.resource.current_query.query_name}"

        return path

    def __init_subclass__(cls, crawl_type) -> None:
        if crawl_type is None:
            raise ValueError("Обязательно должен быть указан тип скрапера!")
        scrapers_registry[crawl_type] = cls


@define(slots=False)
class ApiScraper(Scraper, crawl_type="api"):
    client: AsyncClient = field(factory=AsyncClient)

    async def pending(self):
        await self.trigger.pending()

    @mark_as_trigger
    async def scrape(self):
        async with self.storage as repo:
            async for url in self.resource.get_url_for():
                print(url)
                raw_data = await self.client.get(
                    url, headers=self.extra_headers
                )
                # TODO: нужно сделать метод, позволяющий не делать цепочку вызовов к методу очистки данных
                # и вообще переименовать его во что-то более/менее внятное
                if raw_data.status_code == 200:
                    json = raw_data.json()
                    # TODO: здесь должна быть конкретная ошибка, по названию которой можно понять что произошло
                    # Оставим либо так, либо организуем какой-то перехватчик на уровне цикла
                    with suppress(ValueError):
                        data = self.resource.cleare_data(json)
                        path = self.make_path(repo)
                        await repo.write(data, path)
                else:
                    raise RuntimeError(
                        f"Получен ненадлежащий код ответа {raw_data.status_code}. Проверьте дополнительные параметры запроса"
                    )

    def __hash__(self) -> int:
        return hash(id(self))
