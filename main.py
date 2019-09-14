import asyncio
import json
import logging
import os
import re
import threading
import time
from argparse import ArgumentParser
from datetime import datetime
from typing import List, Union
from kinopoisk.movie import Movie

import aiohttp
import requests
import telebot
from bs4 import BeautifulSoup
from requests import ReadTimeout
from telebot import apihelper
from telebot.types import Message

from config import TOKEN, OWNER_ID
from logger import get_logger
from settings import (
    ENCODING_NAME,
    proxy,
    timeout_upd_first,
    timeout_upd,
    KEY_MEGA_FILM, KEY_MEGA_SERIAL, KEY_NEWSTUDIO, KEY_LORD_FILM,
    sites,
    num_last_release_per_site,
    num_pars_url_lordsfilm, num_pars_url_megashara, num_pars_url_newstudio
)

try:
    from settings_dev import *
except ModuleNotFoundError:
    pass


class Release:
    exclude_genre = ['ТВ-Шоу', 'Мультфильм', 'Документальный', 'Anime', 'Спорт', 'КВН']
    access_country = ['США', 'Россия', 'Германия', 'Великобритания', 'Испания', 'Франция']

    def __init__(self, url, is_single_request=True, is_less_info=True):
        self.logger = logging.getLogger('main')
        self.is_single_request = is_single_request
        self.is_less_info = is_less_info

        self.url = url

        self.title = None
        self.kind = None
        self.photo = None

        self.genre = None
        self.country = None
        self.video = None
        self.audio = None
        self.description = None
        self.translate = None

        self.size = None
        self.torrent = None
        self.rating = None
        self.trailer_url = None
        self.link_more = None

    @staticmethod
    def get_month_str(num: int):
        """Получение сокращенного названия месяца по числу"""

        month_str = {
            0: 'Дек', 1: 'Янв', 2: 'Фев', 3: 'Мар', 4: 'Апр', 5: 'Май', 6: 'Июн',
            7: 'Июл', 8: 'Авг', 9: 'Сен', 10: 'Окт', 11: 'Ноя', 12: 'Дек'
        }
        return month_str.get(num)

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

        except AttributeError:
            rating = '-'
            kinopoisk_url = None

        return {'rating': rating, 'kinopoisk_url': kinopoisk_url}

    def get_trailer_url_kinopoisk(self, title: str, directors: list):
        """Получает ссылку на релиз на кинопоиске, если на кинопоиске есть трейлер"""

        movie_list = Movie.objects.search(title)
        if not movie_list:
            return None

        movie = movie_list[0]
        # if directors:
        #     movie.get_content('main_page')
        #     if not any([d.name in directors for d in movie.directors]):
        #         return None

        movie.get_content('trailers')
        return f"https://www.kinopoisk.ru/film/{movie.id}" if bool(movie.trailers) else None

    async def async_get_info(self, session) -> str:
        """Асинхронное получение информации о релизе"""

        self.logger.debug(f'Starting {self.url}')

        async with session.get(self.url, proxy=proxy) as response:
            self.logger.debug(f'response.status {response.status} {self.url}')
            text = await response.text()

            if response.status != 200:
                return ''

            return self.parsing_and_prepare(self.url, text)

    def get_info(self) -> str:
        """Получение информации о релизе"""

        self.logger.debug(f'Starting {self.url}')
        response = requests.get(self.url, proxies=apihelper.proxy)

        if response.status_code != 200:
            return ''

        return self.parsing_and_prepare(self.url, response.content)

    def parsing_and_prepare(self, url, html: str):

        reply = ''
        try:
            if 'megashara' in url:
                parsing_completed = self.parsing_release_megashara(url, html)
                if parsing_completed:
                    reply = self.prepare_response_film()

            elif 'lordsfilm' in url:
                parsing_completed = self.parsing_release_lordsfilm(url, html)
                if parsing_completed:
                    reply = self.prepare_response_film()

            elif 'newstudio' in url:
                parsing_completed = self.parsing_release_newstudio(url, html)
                if parsing_completed:
                    reply = self.prepare_response_newstudio()

        except Exception as error:
            self.logger.exception(f"{error} [URL]: {url}")
            reply = ''

        return reply

    def parsing_release_megashara(self, url, html: str) -> bool:
        """
        Парсит url Megashara

        **Args**:

         ``url``: url, который подлежит парсингу

         ``html``: страница с контентом
        """

        soup = BeautifulSoup(html, 'html.parser')
        pars_block = soup.select_one('#mid-side')

        if pars_block.select_one('.big-error') or not pars_block:
            return False

        table_2 = pars_block.select_one('.back-bg3 .info-table').extract()
        self.title = pars_block.h1.text
        self.photo = pars_block.select_one('.preview img')['src']

        self.genre = self.get_next_element_text(pars_block, 'Жанр:')
        self.country = self.get_next_element_text(pars_block, 'Студия/Страна:')

        d_kinopoisk = self.get_rating_kinopoisk(pars_block)
        self.rating = d_kinopoisk['rating']
        self.trailer_url = d_kinopoisk['kinopoisk_url']

        if not self.is_less_info:
            self.translate = self.get_next_element_text(pars_block, 'Перевод:')
            self.video = self.get_next_element_text(table_2, 'Видео:')
            self.audio = self.get_next_element_text(table_2, 'Звук:')
            self.size = self.get_next_element_text(table_2, 'Размер:')

            desc_dirty = pars_block.select_one('.back-bg3').text
            desc_clean = re.sub("\n+", '\n', desc_dirty)
            self.description = desc_clean.strip()

        url_split = url.split('/')
        kind_code = KinoReleaseBot.get_site_code("mega_film") if url_split[3] == 'movies' \
            else KinoReleaseBot.get_site_code("mega_serial")
        self.link_more = f'{KinoReleaseBot.get_command_code("more_film")}_{kind_code}_{url_split[4]}'

        return True

    def parsing_release_lordsfilm(self, url, html: str) -> bool:
        """
        Парсит url Lordsfilm

        **Args**:

         ``url``: url, который подлежит парсингу

         ``html``: страница с контентом
        """
        soup = BeautifulSoup(html, 'html.parser')

        if not soup.select_one('.fmain'):
            return False

        url_split = url.rsplit('/', 1)
        pars_block = soup.select_one('.fcols')
        self.title = pars_block.div.h1.text.strip('смотреть онлайн')
        self.photo = f"{url_split[0]}{pars_block.select_one('.fposter img')['src']}"

        genre_bl = pars_block.find(string='Жанр:')
        country_bl = pars_block.find(string='Страна:')

        self.kind, self.genre = genre_bl.next_element.next_element.text.split(',', 1) if genre_bl else ('Фильм', '-')
        self.kind = self.kind.rstrip('ы')
        self.country = country_bl.next_element if country_bl else '-'

        b_kinopoisk = pars_block.select_one('.db-rates .r-kp')
        b_imdb = pars_block.select_one('.db-rates .r-imdb')
        rating_kp = b_kinopoisk.text if b_kinopoisk else '-'
        rating_imdb = b_imdb.text if b_imdb else '-'
        self.rating = f"KP {rating_kp}, IMDB {rating_imdb}"

        if not self.is_less_info:
            title_en_bl = pars_block.find(string='Название:')
            director_bl = pars_block.find(string='Режиссер:')
            translate_bl = pars_block.find(string='Перевод:')
            video_bl = pars_block.find(string='Качество:')

            title_en = title_en_bl.next_element.next_element.text if title_en_bl else None
            directors = director_bl.next_element.next_element.text.split(',') if director_bl else None
            self.video = video_bl.next_element.next_element.text if video_bl else '-'
            self.translate = translate_bl.next_element if translate_bl else '-'

            desc_dirty = pars_block.select_one('.fdesc').text
            desc_clean = re.sub("\n+", '\n', desc_dirty)
            self.description = desc_clean.strip()

            title_for_search = title_en if title_en else self.title
            self.trailer_url = self.get_trailer_url_kinopoisk(title_for_search, directors)

        kind_code = KinoReleaseBot.get_site_code("lord_film")
        self.link_more = f'{KinoReleaseBot.get_command_code("more_film")}_{kind_code}_{url_split[1].split("-")[0]}'

        return True

    def parsing_release_newstudio(self, url, html: str) -> bool:
        """
        Парсит url Newstudio

        **Args**:

         ``url``: url, который подлежит парсингу

         ``html``: страница с контентом
        """
        soup = BeautifulSoup(html, 'html.parser')
        pars_block = soup.select_one('.accordion-inner')

        self.title = pars_block.select_one('.post-b').text
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
                self.torrent = 'http://newstudio.tv/' + torrent_dirty
            else:
                self.torrent = '-'

            return True

        else:
            return False

    def prepare_response_film(self) -> str:
        """Подготавливает ответ с информацией о фильме"""

        if self.is_less_info:
            reply = self.prepare_response_film_less()
        else:
            reply = self.prepare_response_film_full()

        return reply

    def prepare_response_film_less(self) -> str:
        """Подготавливает сокращенное инфо для фильмов"""

        if self.is_single_request and (any(exc_g in self.genre for exc_g in self.exclude_genre)
                                       or not any(acc_c in self.country for acc_c in self.access_country)):
            return ''

        kind = f"<b>{self.kind}</b><a href='{self.photo}'>.</a>\n" if self.is_single_request else ""
        title = f"<a href='{self.url}'>{self.title}</a>" if self.is_single_request else f"{self.title}"

        reply = (
            f"{kind}"
            f"{title}\n"
            f"Рейтинг: {self.rating} ({self.link_more})\n\n"
        )
        return reply

    def prepare_response_film_full(self) -> str:
        """Подготавливает развернутое инфо для фильмов"""

        audio = f"Аудио: {self.audio}\n" if self.audio else ''
        size = f"Размер: {self.size}\n" if self.size else ''
        trailer = f"<a href='{self.trailer_url}'>перейти</a>" if self.trailer_url else '-'

        reply = (
            f"<b>{self.kind}</b><a href='{self.photo}'>.</a>\n"
            f"<a href='{self.url}'>{self.title}</a>\n"
            f"Жанр: {self.genre}\n"
            f"Страна: {self.country}\n"
            f"Перевод: {self.translate}\n"
            f"Видео: {self.video}\n"
            f"{audio}"
            f"{size}"
            f"Рейтинг: {self.rating}\n"
            f"Трейлер: {trailer}\n\n"
            f"{self.description}\n"
        )
        return reply

    def prepare_response_newstudio(self) -> str:
        """Подготавливает ответ для релиза с newstudio"""

        reply = ''

        if "WEBDLRip" in self.title:
            return reply

        if self.is_single_request:
            reply = f"<b> \U0000203C РЕЛИЗ \U0000203C</b>\n"

        reply += (
            f"{self.title} <a href='{self.torrent}'> Торрент \U0001F4E5</a>\n\n"
        )
        return reply


class KinoReleaseBot:
    bot = telebot.TeleBot(TOKEN)
    apihelper.proxy = proxy

    def __init__(self, debug, logs_show):
        self.logger = get_logger(is_debug=debug, show_logs=logs_show)

        self.data_dir = 'data'
        self._init_need_dirs(dirs=[self.data_dir])

        self.file_data_url = None
        self.file_data_chats = None
        self._init_need_files()

        self.data_urls = self.load_json(self.file_data_url)
        self.data_chats = self.load_json(self.file_data_chats)

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
            'ping_site': '/ping',
            'more_film': '/more',
        }
        return codes.get(command)

    @staticmethod
    def get_site_code(site: str):
        """Возвращает код (аббревиатуру) сайта"""

        codes = {
            'all': 'all',
            'lord_film': 'lf',
            'mega_film': 'mf',
            'mega_serial': 'ms',
            'newstudio': 'ns',
        }
        return codes.get(site)

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

    def command_start(self, message: Message):
        """Приветствие / Добавление нового пользователя"""

        chat_id = message.chat.id
        first_name = message.from_user.first_name

        if str(chat_id) in self.data_chats.keys():
            reply = f"Привет, {first_name}"

        else:
            self.bot.send_message(OWNER_ID, f'Мне написал start {self.get_telegram_name(message)}')
            self.data_chats[chat_id] = message.chat.username
            self.dump_json(self.file_data_chats, self.data_chats)
            reply = f"Добро пожаловать, {first_name}"

        self.bot.reply_to(message, reply)
        self.command_help(message)

    def command_help(self, message: Message):
        help_text = "<b>Доступны следующие команды: </b>\n"

        commands = {
            f'{self.get_command_code("start")}': 'начать использовать бота',

            f'{self.get_command_code("help")}': 'показать доступные команды',

            f'{self.get_command_code("ip")}': 'показать ip и регион бота',

            f'{self.get_command_code("ping_site")} X': 'получить статус сайта, где X - код сайта '
            f'(если X не указано, то выведет для {self.get_site_code("lord_film")})',

            f'{self.get_command_code("last")} X': 'показать последние релизы, где\nX - код сайта '
            f'(если X не указано, то выведет для {self.get_site_code("lord_film")})',

            f'{self.get_command_code("more_film")}_X_Y': 'показать полную информацию о фильме или сериале, где\n'
                                                         'X - код сайта, Y - id релиза ',
        }

        for key in commands:
            help_text += key + " - "
            help_text += commands[key] + "\n\n"

        help_text += (
            f'<b>Коды сайтов:</b>\n'
            f'{self.get_site_code("lord_film")} - релизы фильмов Lordsfilms\n'
            f'{self.get_site_code("mega_film")} - релизы фильмов Megashara\n'
            f'{self.get_site_code("mega_serial")} - релизы сериалов Megashara\n'
            f'{self.get_site_code("newstudio")} - релизы из подписки сериалов Newstudio\n'
            f'{self.get_site_code("all")} - релизы со всех сайтов в подписке '
            f'(для команды {self.get_command_code("last")})\n'
        )

        self.bot.send_message(message.chat.id, help_text, parse_mode='HTML')

    def command_last(self, message: Message):
        """Выводит данные о последних релизах с указанных сайтов"""

        unique_code = message.text.split()[1] if len(message.text.split()) > 1 else None
        exclude = [KEY_MEGA_FILM, KEY_MEGA_SERIAL, KEY_NEWSTUDIO, KEY_LORD_FILM]

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

        elif unique_code == self.get_site_code("lord_film"):
            exclude.remove(KEY_LORD_FILM)
            reply_wait = 'Придется подождать.. Получаю информацию о последних релизах Lordsfilm..'

        else:
            exclude.remove(KEY_LORD_FILM)
            reply_wait = 'Подождите.. Получаю информацию о последних релизах Lordsfilm..'

        self.bot.reply_to(message, reply_wait)
        data = self.data_urls

        reply_full = ''
        for key in data:
            if key in exclude:
                continue
            reply = '<b>Фильмы: </b>' if key in [KEY_MEGA_FILM, KEY_LORD_FILM] else '<b>Сериалы: </b>'

            if key in [KEY_MEGA_FILM, KEY_MEGA_SERIAL]:
                reply += '(Megashara)\n'
            elif key == KEY_NEWSTUDIO:
                reply += '(Newstudio)\n'
            elif key == KEY_LORD_FILM:
                reply += '(Lordsfilms)\n'

            limit = num_last_release_per_site
            if isinstance(data[key], list):
                amount = limit if limit < len(data[key]) else len(data[key])
                lst_urls = data[key][-amount:]
            else:
                lst_urls = []
                for k_serial in data[key].keys():
                    amount = limit if limit < len(data[key][k_serial]) else len(data[key][k_serial])
                    lst_urls.extend(data[key][k_serial][-amount:])

            lst_info = self.get_info_less(lst_urls)
            if not lst_info:
                lst_info = "Там все очень старое, даже выводить не буду..\n"
            reply_full += reply + lst_info + '\n'

        if not reply_full:
            reply_full = 'Релизов не найдено'

        self.bot.send_message(message.chat.id, reply_full, parse_mode='HTML')

    def command_ip(self, message: Message):
        """Вовращает данне об ip бота"""

        chat_id = message.chat.id
        if chat_id == OWNER_ID:
            j_response = requests.get('http://ip-api.com/json', proxies=apihelper.proxy).json()
            reply = (f"IP: {j_response.get('query')}\n"
                     f"Страна: {j_response.get('country')}\n"
                     f"Город: {j_response.get('city')}\n")
        else:
            reply = 'У Вас нет прав на данную операцию'
        self.bot.send_message(chat_id, reply)

    def command_ping_site(self, message: Message):
        """Возвращает статус код сайта"""

        unique_code = message.text.split()[1] if len(message.text.split()) > 1 else None

        if unique_code == self.get_site_code("mega_film") or unique_code == self.get_site_code("mega_serial"):
            url = 'http://megashara.com'

        elif unique_code == self.get_site_code("lord_film"):
            url = 'http://lordsfilms.tv'

        elif unique_code == self.get_site_code("newstudio"):
            url = 'http://newstudio.tv'

        elif unique_code is None:
            url = 'http://lordsfilms.tv'

        else:
            url = None

        if url:
            response = requests.get(url, proxies=apihelper.proxy)
            reply = f"Статус код: {response.status_code} {url}"
            self.bot.send_message(message.chat.id, reply)

        else:
            self.bot.reply_to(message, f'Хм.. может {self.get_command_code("help")}?')

    def command_more_film(self, message: Message):
        """Возвращает подробную информацию о фильме или сериале"""

        msg_split = message.text.split('_')
        if len(msg_split) == 3:
            self.bot.reply_to(message, 'Получаю информацию о релизе..')

            if msg_split[1] == self.get_site_code("mega_film"):
                url = f'{sites[KEY_MEGA_FILM]}/{msg_split[2]}/'

            elif msg_split[1] == self.get_site_code("mega_serial"):
                url = f'{sites[KEY_MEGA_SERIAL]}/{msg_split[2]}/'

            elif msg_split[1] == self.get_site_code("lord_film"):
                lord_urls_data = self.data_urls.get(KEY_LORD_FILM)
                for u in lord_urls_data:
                    if f'/{msg_split[2]}-' in u:
                        url = u
                        break
                else:
                    url = None

            else:
                url = None

            if url:
                reply = self.get_info_full(url)
                if reply:
                    return self.bot.send_message(message.chat.id, reply, parse_mode='HTML')

                return self.bot.reply_to(message, 'Релиз не найден')

        self.bot.reply_to(message, f'Хм.. может {self.get_command_code("help")}?')

    def get_site_urls_for_parsing(self, site: str):
        """parsing site, return list pars_urls"""

        pars_urls = []
        try:
            response = requests.get(site, timeout=300, proxies=apihelper.proxy)
            soup = BeautifulSoup(response.content, 'html.parser')

            if response.status_code != 200:
                self.logger.info(f'[STATUS CODE]: {response.status_code} [URL]: {site}')

            if 'megashara' in site:
                pars_bl = soup.find('div', id='mid-side')
                if not pars_bl:
                    return pars_urls

                response = list(map(lambda x: f"{x.a['href']}",
                                    pars_bl.findAll('div', class_='name-block')))[:num_pars_url_megashara]

            elif 'newstudio' in site:
                site_url = 'http://newstudio.tv'
                response = list(map(lambda x: f"{site_url}{x.a['href'][1:]}",
                                    soup.findAll('div', class_='topic-list')))[:num_pars_url_lordsfilm]

            elif 'lordsfilm' in site:
                response = list(map(lambda x: f"{x.a['href']}",
                                    soup.find('div', id='dle-content')
                                    .findAll('div', class_='short')))[:num_pars_url_newstudio]

            pars_urls = list(reversed(response))

        except ReadTimeout as error:
            self.logger.error(f'{error}')

        except AttributeError:
            self.logger.error(f'[URL]: {site}')
            time.sleep(10 * 60)

        return pars_urls

    @staticmethod
    async def async_parsing_url(urls: List[str],
                                is_single_request: bool) -> str:
        """
        Асинхронный парсинг url

        **Args**:

         ``urls``: url, подлежащие парсингу

          ``is_single_request``: является ли запрос на получение одиночным или входит в состав для парсинга
        """

        if not urls:
            return ''

        tasks = []

        async with aiohttp.ClientSession() as session:
            for i, url in enumerate(urls):
                task = asyncio.ensure_future(Release(url, is_single_request).async_get_info(session))
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
        urls_lordsfilm = [url for url in urls if 'lordsfilm' in url]
        urls_newstudio = [url for url in urls if 'newstudio' in url]

        loop = asyncio.new_event_loop()

        tasks = [
            loop.create_task(self.async_parsing_url(urls=urls_megashara,
                                                    is_single_request=is_single_request)),

            loop.create_task(self.async_parsing_url(urls=urls_lordsfilm,
                                                    is_single_request=is_single_request)),

            loop.create_task(self.async_parsing_url(urls=urls_newstudio,
                                                    is_single_request=is_single_request)),
        ]

        done, _ = loop.run_until_complete(asyncio.wait(tasks))
        loop.close()

        reply = ''
        for d in done:
            reply += d.result() if d.result() else ''
        return reply

    def get_info_full(self, url) -> str:
        """Возвращает подробное описание о релизе"""

        try:
            return str(Release(url, is_single_request=True, is_less_info=False).get_info())

        except Exception as error:
            self.logger.exception(f"{error} [URL]: {url}")
            return 'Ошибка при получении подробной информации'

    def get_new_urls(self) -> list:
        """Определяет есть ли новые url и возвращает данные"""

        if self.data_urls is None:
            data_urls: dict = self.load_json(self.file_data_url)
        else:
            data_urls = self.data_urls

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

        return _new_urls

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

                elif m.text.startswith(self.get_command_code('ping_site')):
                    self.command_ping_site(m)

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
                new_data = self.get_new_urls()

                if new_data:
                    if skip_first_alert is True:
                        time.sleep(timeout_upd_first)
                        skip_first_alert = False
                    else:
                        for url in new_data:
                            if url.startswith(sites.get(KEY_MEGA_SERIAL, 'None')):
                                continue

                            reply = self.get_info_less(url)
                            if reply:
                                for chat in self.data_chats.keys():
                                    try:
                                        self.bot.send_message(int(chat), reply, parse_mode='HTML')
                                    except Exception as error:
                                        self.logger.info(f'Не могу отправить {int(chat)} {error}')
                    self.dump_json(self.file_data_url, self.data_urls)

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

    bot = KinoReleaseBot(debug=args.debug, logs_show=args.logs_show)
    bot.start(args.skip_first_alert)
