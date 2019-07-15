import asyncio
import json
import os
import re
import threading
import time
from argparse import ArgumentParser
from datetime import datetime
from typing import List, Union, Callable

import aiohttp
import requests
import telebot
from bs4 import BeautifulSoup
from telebot import apihelper
from telebot.types import Message

from config import TOKEN, OWNER_ID
from logger import get_logger
from settings import (
    ENCODING_NAME,
    proxy,
    timeout_upd_first,
    timeout_upd,
    KEY_MEGA_FILM, KEY_MEGA_SERIAL, KEY_NEWSTUDIO,
    sites,
)

try:
    from settings_dev import *
except ModuleNotFoundError:
    pass


class KinoRelease:
    bot = telebot.TeleBot(TOKEN)
    apihelper.proxy = proxy

    def __init__(self, debug, logs_show):
        self.logger = get_logger(is_debug=debug, show_logs=logs_show)

        self.data_dir = 'data'
        self._init_need_dirs(dirs=[self.data_dir])

        self.file_data_url = None
        self.file_data_chats = None
        self._init_need_files()

    @staticmethod
    def _init_need_dirs(dirs: List):
        """Создает необходимые для работы директории"""

        [os.mkdir(dir_) for dir_ in dirs if not os.path.exists(dir_)]

    def _init_need_files(self):
        """Создает файлы c начальными данными"""

        self.file_data_url = os.path.join(self.data_dir, 'data_url.json')
        self.file_data_chats = os.path.join(self.data_dir, 'data_chats.json')

        init_files_data = [
            (self.file_data_url, {}),
            (self.file_data_chats, {}),
        ]
        [self.dump_json(file, data) for file, data in init_files_data if not os.path.exists(file)]

    @staticmethod
    def dump_json(filename, data):
        """Записывает данные в json файл"""

        with open(filename, "w", encoding=ENCODING_NAME) as file:
            file.write(json.dumps(data, indent=4, ensure_ascii=False))

    @staticmethod
    def load_json(filename):
        """Считывает данные из json файла"""

        with open(filename, 'r', encoding=ENCODING_NAME) as file:
            data = json.load(file)
        return data

    @staticmethod
    def get_command_code(command: str):
        """Возвращает код команды"""

        codes = {
            'start': '/start',
            'help': '/help',
            'last': '/last',
            'ip': '/ip',
            'ping_megashara': '/ping_megashara',
            'more_film': '/more',
        }
        return codes.get(command)

    @staticmethod
    def get_site_code(site: str):
        """Возвращает код (аббревиатуру) сайта"""

        codes = {
            'all': 'all',
            'mega_film': 'mf',
            'mega_serial': 'ms',
            'newstudio': 'ns',
        }
        return codes.get(site)

    @staticmethod
    def get_month_str(num: int):
        """Получение сокращенного названия месяца по числу"""

        month_str = {
            0: 'Дек', 1: 'Янв', 2: 'Фев', 3: 'Мар', 4: 'Апр', 5: 'Май', 6: 'Июн',
            7: 'Июл', 8: 'Авг', 9: 'Сен', 10: 'Окт', 11: 'Ноя', 12: 'Дек'
        }
        return month_str.get(num)

    @staticmethod
    def get_telegram_name(message: Message):
        """Возвращает username в телеграме или, если нету, тогда имя"""

        if message.from_user.username:
            return f'@{message.from_user.username}'

        first_name = message.from_user.first_name
        last_name = message.from_user.last_name
        if first_name and last_name:
            return f'{first_name} {last_name}'
        return first_name or last_name

    @staticmethod
    def get_next_element_text(pars_block, title_parent_bl: str) -> str:
        """
        Возвращает текст (value) следующего за исходным элемента. Исходный элемент ищется по названию.
        На странице выглядит как title: value.

        **Args**:

         ``pars_block``: bs4.element блок, в котором производится поиск поля с необходимым атрибутом

         ``title_parent_bl``: название соседнего поля на странице - title: value
        """

        parent_bl = pars_block.find(string=title_parent_bl)
        return parent_bl.next_element.text if parent_bl else '-'

    @staticmethod
    def get_rating_kinopoisk(pars_block) -> dict:
        """
        Возвращает рейтинг кинопоиска из предоставленного блока

        **Args**:

         ``pars_block``: bs4.element-html блок для поиска рейтинга
        """

        try:
            kinopoisk_url = pars_block.find(alt='Кинопоиск').previous_element['href']
            film_id = kinopoisk_url.split('/')[-2]
            rating_url = f'https://rating.kinopoisk.ru/{film_id}.xml'

            response = requests.get(rating_url)
            soup = BeautifulSoup(response.content, 'html.parser')
            rating = soup.kp_rating.text
            kinopoisk_url = f"<a href='{kinopoisk_url}'>перейти</a>"

        except AttributeError:
            rating = '-'
            kinopoisk_url = '-'

        return {'rating': rating, 'kinopoisk_url': kinopoisk_url}

    def command_start(self, message: Message):
        """Приветствие / Добавление нового пользователя"""

        chat_id = message.chat.id
        first_name = message.from_user.first_name
        data_chats = self.load_json(self.file_data_chats)

        if str(chat_id) in data_chats.keys():
            reply = f"Привет, {first_name}"

        else:
            self.bot.send_message(OWNER_ID, f'Мне написал start {self.get_telegram_name(message)}')
            data_chats[chat_id] = message.chat.username
            self.dump_json(self.file_data_chats, data_chats)
            reply = f"Добро пожаловать, {first_name}"

        self.bot.reply_to(message, reply)
        self.command_help(message)

    def command_help(self, message: Message):
        help_text = "Доступны следующие команды: \n"

        indent = " " * 6
        commands = {
            f'{self.get_command_code("start")}': 'начать использовать бота',

            f'{self.get_command_code("help")}': 'показать доступные команды',

            f'{self.get_command_code("last")} X': 'показать последние релизы, где\nX - опционально:\n'
            f'{indent}{self.get_site_code("mega_film")} - последние релизы фильмов Megashara\n'
            f'{indent}{self.get_site_code("mega_serial")} - последние релизы сериалов Megashara\n'
            f'{indent}{self.get_site_code("newstudio")} - последние релизы из подписки сериалов Newstudio\n'
            f'{indent}{self.get_site_code("all")} - все релизы в подписке\n'
            f'(если X не указано, то выведет {self.get_site_code("mega_film")}+{self.get_site_code("mega_serial")})\n',

            f'{self.get_command_code("more_film")}_X_Y': 'показать полную информацию о фильме или сериале, где\n'
            'X - код сайта:\n'
            f'{indent}{self.get_site_code("mega_film")} - megashara фильм,\n'
            f'{indent}{self.get_site_code("mega_serial")} - megashara сериал,\n'
            'Y - id релиза ',

            f'{self.get_command_code("ip")}': 'показать ip и регион бота',

            f'{self.get_command_code("ping_megashara")}': 'получить статус сайта megashara',
        }

        for key in commands:
            help_text += key + " - "
            help_text += commands[key] + "\n"
        self.bot.send_message(message.chat.id, help_text)

    def command_last(self, message: Message):
        """Выводит данные о последних релизах с указанных сайтов"""

        unique_code = message.text.split()[1] if len(message.text.split()) > 1 else None
        exclude = [KEY_MEGA_FILM, KEY_MEGA_SERIAL, KEY_NEWSTUDIO]

        if unique_code == self.get_site_code("all"):
            exclude = []
            reply_wait = 'Придется подождать.. (~1мин.) Подписок много.. Ушёл, за информацией..'

        elif unique_code == self.get_site_code("mega_film"):
            exclude.remove(KEY_MEGA_FILM)
            reply_wait = 'Подождите.. Вспоминаю о последних фильмах Megashara..'

        elif unique_code == self.get_site_code("mega_serial"):
            exclude.remove(KEY_MEGA_SERIAL)
            reply_wait = 'Подождите.. Посмотрю, что там с сериалами на Megashara..'

        elif unique_code == self.get_site_code("newstudio"):
            exclude.remove(KEY_NEWSTUDIO)
            reply_wait = 'Придется подождать.. (~1мин.) Получаю информацию о последних релизах Newstudio..'

        else:
            exclude.remove(KEY_MEGA_FILM)
            exclude.remove(KEY_MEGA_SERIAL)
            reply_wait = 'Подождите.. Получаю информацию о последних релизах Megashara..'

        self.bot.reply_to(message, reply_wait)
        data = self.get_all_and_new_url()[0]

        reply_full = ''
        for key in data:
            if key in exclude:
                continue
            reply = '<b>Фильмы: </b>' if key == KEY_MEGA_FILM else '<b>Сериалы: </b>'

            if key in [KEY_MEGA_FILM, KEY_MEGA_SERIAL]:
                reply += '(Megashara)\n'
            elif key == KEY_NEWSTUDIO:
                reply += '(Newstudio)\n'

            limit = 5
            if isinstance(data[key], list):
                count = limit if limit < len(data[key]) else len(data[key])
                lst_urls = data[key][-count:]
            else:
                lst_urls = []
                for k_serial in data[key].keys():
                    count = limit if limit < len(data[key][k_serial]) else len(data[key][k_serial])
                    lst_urls.extend(data[key][k_serial][-count:])

            lst_info = self.get_info_less(lst_urls)
            if not lst_info:
                lst_info = "Там все очень старое, даже выводить не буду.."
            reply_full += reply + lst_info + '\n'

        self.bot.send_message(message.chat.id, reply_full, parse_mode='HTML')

    def command_ip(self, message: Message):
        """Вовращает данне об ip бота"""

        chat_id = message.chat.id
        if chat_id == OWNER_ID:
            response = requests.get('https://yandex.ru/internet/', proxies=apihelper.proxy)
            soup = BeautifulSoup(response.content, 'html.parser')
            reply = (f"IPv4: {soup.find('span', class_='info__value_type_ipv4').text}\n"
                     f"Регион: {soup.find('span', class_='info__value_type_pinpoint-region').text}\n")
        else:
            reply = 'У Вас нет прав на данную операцию'
        self.bot.send_message(chat_id, reply)

    def command_ping_megashara(self, message: Message):
        """Возвращает статус код сайта megashara"""

        response = requests.get('http://megashara.com.', proxies=apihelper.proxy)
        reply = f"Статус код: {response.status_code}"
        self.bot.send_message(message.chat.id, reply)

    def command_more_film(self, message: Message):
        """Возвращает подробную информацию о фильме или сериале"""

        msg_split = message.text.split('_')
        if len(msg_split) == 3:
            self.bot.reply_to(message, 'Получаю информацию о релизе..')
            data_url = self.get_all_and_new_url()[0]

            if msg_split[1] == self.get_site_code("mega_film"):
                key = KEY_MEGA_FILM
            elif msg_split[1] == self.get_site_code("mega_serial"):
                key = KEY_MEGA_SERIAL
            else:
                key = None

            if key:
                for url in data_url[key]:
                    if msg_split[2] in url:
                        reply = self.get_info_full(url)
                        return self.bot.send_message(message.chat.id, reply, parse_mode='HTML')

                return self.bot.reply_to(message, 'Релиз не найден')

        self.bot.reply_to(message, f'Хм.. может {self.get_command_code("help")}?')

    def get_site_urls_for_parsing(self, site: str, count=9):
        """parsing site, return list pars_urls"""

        response = requests.get(site, proxies=apihelper.proxy)
        soup = BeautifulSoup(response.content, 'html.parser')
        try:
            if 'megashara' in site:
                response = list(map(lambda x: f"{x.a['href']}",
                                    soup.find('div', id='mid-side').findAll('div', class_='name-block')))[:count]

            elif 'newstudio' in site:
                site_url = 'http://newstudio.tv'
                response = list(map(lambda x: f"{site_url}{x.a['href'][1:]}",
                                    soup.findAll('div', class_='topic-list')))[:count]

            pars_urls = list(reversed(response))

        except AttributeError:
            self.logger.error(f'[URL]: {site} [STATUS CODE]: {response.status_code}')
            time.sleep(10 * 60)
            pars_urls = []

        return pars_urls

    @staticmethod
    async def async_parsing_url(parsing_handler: Callable,
                                urls: List[str],
                                is_single_request: bool) -> str:
        """
        Асинхронный парсинг url

        **Args**:

         ``parsing_handler``: функция-обработчик, парсящая url

         ``urls``: url, подлежащие парсингу

          ``is_single_request``: является ли запрос на получение одиночным или входит в состав для парсинга
        """

        if not urls:
            return ''

        tasks = []

        async with aiohttp.ClientSession() as session:
            for i, url in enumerate(urls):
                task = asyncio.ensure_future(parsing_handler(session, url, is_single_request))
                tasks.append(task)
                await asyncio.sleep(0.2 if i % 5 != 0 else 1)
            result = await asyncio.gather(*tasks)

        return ''.join(result)

    def get_info_less(self, urls: Union[str, list]):
        """
        Возвращает короткое описание релиза

        **Args**:

         ``urls``: url для парсинга, может быть как строкой (одиночный url), так и списком url
        """

        # convert in list if input url is string
        if isinstance(urls, str):
            urls = [urls]

        is_single_request = len(urls) == 1
        urls_megashara = [url for url in urls if 'megashara' in url]
        urls_newstudio = [url for url in urls if 'newstudio' in url]

        loop = asyncio.new_event_loop()

        tasks = [
            loop.create_task(self.async_parsing_url(parsing_handler=self.get_info_less_megashara,
                                                    urls=urls_megashara,
                                                    is_single_request=is_single_request)),

            loop.create_task(self.async_parsing_url(parsing_handler=self.get_info_less_newstudio,
                                                    urls=urls_newstudio,
                                                    is_single_request=is_single_request)),
        ]

        done, _ = loop.run_until_complete(asyncio.wait(tasks))
        loop.close()

        reply = ''
        for d in done:
            reply += d.result() if d.result() else ''
        return reply

    async def get_info_less_megashara(self, session, url: str, is_single_request: bool) -> str:
        """
        Парсит url Megashara

        **Args**:

         ``url``: url, который подлежит парсингу

         ``is_single_request``: является ли запрос на получение одиночным или входит в состав для парсинга
        """

        reply = ''
        try:
            self.logger.debug(f'Starting {url}')
            async with session.get(url, proxy=proxy) as response:
                text = await response.text()
                self.logger.debug(f'response.status {response.status} {url}')

                if response.status != 200:
                    return ''

                soup = BeautifulSoup(text, 'html.parser')

                pars_block = soup.select_one('#mid-side')
                title = pars_block.h1.text

                if is_single_request:
                    genre = self.get_next_element_text(pars_block, 'Жанр:')
                    exclude_genre = ['ТВ-Шоу', 'Мультфильм', 'Документальный', 'Anime', 'Спорт', 'КВН']

                    if any((exc_g in genre for exc_g in exclude_genre)):
                        return ''

                    kind = 'Фильм' if url.startswith(sites[KEY_MEGA_FILM]) else 'Сериал'
                    photo = pars_block.select_one('.preview img')['src']
                    reply += f"<b>{kind}</b><a href='{photo}'>.</a>\n"

                d_kinopoisk = self.get_rating_kinopoisk(pars_block)

                url_split = url.split('/')
                kind_code = self.get_site_code("mega_film") if url_split[3] == 'movies' \
                    else self.get_site_code("mega_serial")
                link_more = f'{self.get_command_code("more_film")}_{kind_code}_{url_split[4]}'

                reply += (
                    f"{title}\n"
                    f"Рейтинг: {d_kinopoisk['rating']} ({link_more})\n\n"
                )

        except Exception as error:
            self.logger.exception(f"{error} [URL]: {url}")

        finally:
            return reply

    async def get_info_less_newstudio(self, session, url: str, is_single_request: bool) -> str:
        """
        Парсит url Newstudio

        **Args**:

         ``url``: url, который подлежит парсингу

         ``is_single_request``: является ли запрос на получение одиночным или входит в состав для парсинга
        """

        reply = ''
        try:
            self.logger.debug(f'Starting {url}')
            async with session.get(url, proxy=proxy) as response:
                text = await response.text()
                self.logger.debug(f'response.status {response.status} {url}')

                if response.status != 200:
                    return ''

                soup = BeautifulSoup(text, 'html.parser')
                pars_block = soup.select_one('.accordion-inner')

                title = pars_block.select_one('.post-b').text
                date_release = pars_block.select_one("a[title='Линк на это сообщение']").text
                spl_date_release = date_release.split('-')
                now = datetime.now()

                is_new_release = False  # need for command /last newstudio release
                if len(spl_date_release) == 3:
                    date_release_month = spl_date_release[1]
                    date_release_year = int(spl_date_release[2].split(' ')[0])

                    if now.year == date_release_year or now.month == 1:
                        if self.get_month_str(now.month) == date_release_month or \
                                self.get_month_str(now.month - 1) == date_release_month:
                            is_new_release = True
                else:
                    is_new_release = True

                if is_new_release:
                    if "WEBDLRip" not in title:
                        torrent_tag = soup.select_one('.seedmed') or soup.select_one('.genmed')

                        if not torrent_tag:
                            for _ in range(5):
                                self.logger.error(f"Not found torrent-file url: ", url)
                                time.sleep(1 * 60)
                                response = requests.get(url, proxies=apihelper.proxy)
                                soup = BeautifulSoup(response.content, 'html.parser')
                                torrent_tag = soup.select_one('.seedmed')
                                if torrent_tag:
                                    break

                        if torrent_tag:
                            torrent_dirty = torrent_tag.get('href')
                            torrent = 'http://newstudio.tv/' + torrent_dirty
                        else:
                            torrent = '-'

                        if is_single_request:
                            reply += f"<b> \U0000203C РЕЛИЗ \U0000203C</b>\n"

                        reply += (
                            f"{title} <a href='{torrent}'> Торрент \U0001F4E5</a>\n\n"
                        )

        except Exception as error:
            self.logger.exception(f"{error} [URL]: {url}")

        finally:
            return reply

    def get_info_full_megashara(self, url) -> str:
        """Возвращает подробное описание о релизе Megashara"""

        response = requests.get(url, proxies=apihelper.proxy)
        soup = BeautifulSoup(response.content, 'html.parser')
        pars_block = soup.select_one('#mid-side')
        table_2 = pars_block.select_one('.back-bg3 .info-table').extract()

        title = pars_block.h1.text
        photo = pars_block.select_one('.preview img')['src']

        genre = self.get_next_element_text(pars_block, 'Жанр:')
        country = self.get_next_element_text(pars_block, 'Студия/Страна:')
        translate = self.get_next_element_text(pars_block, 'Перевод:')
        video = self.get_next_element_text(table_2, 'Видео:')
        audio = self.get_next_element_text(table_2, 'Звук:')
        size = self.get_next_element_text(table_2, 'Размер:')

        desc_dirty = pars_block.select_one('.back-bg3').text
        desc_clean = re.sub("\n+", '\n', desc_dirty)
        description = desc_clean.strip()

        d_kinopoisk = self.get_rating_kinopoisk(pars_block)

        if url.startswith(sites[KEY_MEGA_FILM]):
            reply = (
                f"<b>Фильм</b><a href='{photo}'>.</a>\n"
                f"<a href='{url}'>{title}</a>\n"
                f"Жанр: {genre}\n"
                f"Студия/Страна: {country}\n"
                f"Перевод: {translate}\n"
                f"Видео: {video}\n"
                f"Аудио: {audio}\n"
                f"Размер: {size}\n"
                f"Рейтинг: {d_kinopoisk['rating']}\n"
                f"Трейлер: {d_kinopoisk['kinopoisk_url']}\n\n"
                f"{description}\n"
            )
        else:
            reply = (
                f"<b>Сериал</b><a href='{photo}'>.</a>\n"
                f"<a href='{url}'>{title}</a>\n"
                f"Рейтинг: {d_kinopoisk['rating']}\n"
                f"Трейлер: {d_kinopoisk['kinopoisk_url']}\n\n"
                f"{description}\n"
            )

        return reply

    def get_info_full(self, url) -> str:
        """Возвращает подробное описание о релизе"""

        try:
            if 'megashara' in url:
                return self.get_info_full_megashara(url)
            else:
                return 'В разработке'

        except Exception as error:
            self.logger.exception(f"{error} [URL]: {url}")
            return 'Ошибка при получении подробной информации'

    def get_all_and_new_url(self) -> tuple:
        """Определяет есть ли новые url и возвращает данные в виде кортежа по всем url и по новым"""

        data_urls: dict = self.load_json(self.file_data_url)
        _new_urls: List[str] = []

        self.logger.info('Start update')

        for k_site in sites.keys():
            if isinstance(sites[k_site], str):
                if not data_urls.get(k_site):
                    data_urls[k_site] = []

                pars_urls = self.get_site_urls_for_parsing(site=sites[k_site])
                for url in pars_urls:
                    if url not in data_urls[k_site]:
                        _new_urls.append(url)
                        data_urls[k_site].append(url)
            else:
                if not data_urls.get(k_site):
                    data_urls[k_site] = {}

                for url_serial in sites[k_site]:
                    k_serial = re.findall(r'\?f=(\d+)', url_serial)[0]
                    if not data_urls[k_site].get(k_serial):
                        data_urls[k_site][k_serial] = []

                    pars_urls = self.get_site_urls_for_parsing(site=url_serial)
                    for url in pars_urls:
                        if url not in data_urls[k_site][k_serial]:
                            _new_urls.append(url)
                            data_urls[k_site][k_serial].append(url)

        self.logger.info(f'Update done, new_data = {bool(_new_urls)}')

        return data_urls, _new_urls

    def listener(self, messages):
        """When new messages arrive TeleBot will call this function."""
        for m in messages:
            if m.content_type == 'text':
                self.logger.info("{} (@{}) [{}]: {!r}\n".format(
                    m.from_user.first_name,
                    m.from_user.username,
                    m.from_user.id,
                    m.text,
                ))

                if m.text.startswith(self.get_command_code('start')):
                    self.command_start(m)

                elif m.text.startswith(self.get_command_code('ip')):
                    self.command_ip(m)

                elif m.text.startswith(self.get_command_code('help')):
                    self.command_help(m)

                elif m.text.startswith(self.get_command_code('last')):
                    self.command_last(m)

                elif m.text.startswith(self.get_command_code('ping_megashara')):
                    self.command_ping_megashara(m)

                elif m.text.startswith(self.get_command_code('more_film')):
                    self.command_more_film(m)

                else:
                    self.bot.reply_to(m, f'Хм.. может {self.get_command_code("help")}?')

    def update_data(self, skip_first_alert: bool):
        """
        Обновление имеющихся данных url

        **Args**:

        ``skip_first_alert``: необходимо ли пропустить первое оповещение обновленных данных
        """

        while True:
            try:
                upd_data, new_data = self.get_all_and_new_url()

                if new_data:
                    if skip_first_alert is True:
                        time.sleep(timeout_upd_first)
                        skip_first_alert = False
                    else:
                        for url in new_data:
                            if url.startswith(sites[KEY_MEGA_SERIAL]):
                                continue

                            reply = self.get_info_less(url)
                            if reply:
                                chats = self.load_json(self.file_data_chats)
                                for chat in chats.keys():
                                    self.bot.send_message(int(chat), reply, parse_mode='HTML')
                    self.dump_json(self.file_data_url, upd_data)

                time.sleep(timeout_upd)

            except Exception as error:
                self.logger.error(error)
                time.sleep(2 * 60)

    def start(self, skip_first_alert: bool):
        """Запуск бота"""

        self.bot.set_update_listener(self.listener)
        self.bot.send_message(OWNER_ID, 'Я запущен заново')

        threading.Thread(name='Update-pars', target=self.update_data, args=[skip_first_alert, ]).start()

        while True:
            try:
                self.bot.polling(none_stop=True, interval=0, timeout=60)

            except Exception as error:
                self.logger.error(error)
                time.sleep(5 * 60)

            else:
                # сработает, если polling остановить вручную
                break


def parse_cli_args():
    """Разбор аргументов, передаваемых интерфейсом командной строки"""

    parser = ArgumentParser()
    parser.add_argument('-sfa', '--skip_first_alert',
                        help='Sets whether to skip the first update alert',
                        action="store_true")

    parser.add_argument('-d', '--debug',
                        help='Sets debug mode',
                        action="store_true")

    parser.add_argument('--logs-show',
                        help='Output logs to the console. Default is True',
                        metavar=False,
                        default=True,
                        type=lambda x: str(x).capitalize() == 'True')

    return parser.parse_args()


if __name__ == '__main__':
    args = parse_cli_args()

    bot = KinoRelease(debug=args.debug, logs_show=args.logs_show)
    bot.start(args.skip_first_alert)
