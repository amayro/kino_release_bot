import json
import logging
import os
import re
import time
from datetime import datetime
from threading import Thread

import requests
import telebot
from bs4 import BeautifulSoup
from telebot import apihelper
from telebot import logger
from telebot.types import Message

from config import TOKEN

file_json = 'data_url.json'
chats_json = 'data_chats.json'

try:
    # settings for develop
    from config_dev import *

    apihelper.proxy = proxy
except:
    # settings for production
    apihelper.proxy = None
    timeout_upd_first = 3 * 60
    timeout_upd = 2 * 60

KEY_MEGA_FILM = 'mega_f'
KEY_MEGA_SERIAL = 'mega_s'
KEY_NEWSTUDIO = 'ns'

try:
    # import need NS sites for parsing
    from config import sites
except:
    # some sites for example
    sites = {   # sites for parsing
        KEY_MEGA_FILM: 'http://megashara.com/movies',
        KEY_MEGA_SERIAL: 'http://megashara.com/tv',
        KEY_NEWSTUDIO: [
            'http://newstudio.tv/viewforum.php?f=444&sort=2',    # Миллиарды
            'http://newstudio.tv/viewforum.php?f=206&sort=2',    # Форс-мажоры
        ]
    }

# codes for command (CC) last and more
CC_MEGA_FILM = 'mf'
CC_MEGA_SERIAL = 'ms'
CC_NEWSTUDIO = 'ns'
CC_ALL = 'all'

commands = {  # command description used in the "help" command
    'start': 'начать использовать бота',
    'help': 'показать доступные команды',
    'last X': 'показать последние релизы, где\n'
              'X - опционально:\n'
              f'{" ":6}{CC_MEGA_FILM} - последние релизы фильмов Megashara\n'
              f'{" ":6}{CC_MEGA_SERIAL} - последние релизы сериалов Megashara\n'
              f'{" ":6}{CC_NEWSTUDIO} - последние релизы из подписки сериалов Newstudio\n'
              f'{" ":6}{CC_ALL} - все релизы в подписке\n'
              f'(если X не указано, то выведет {CC_MEGA_FILM}+{CC_MEGA_SERIAL})\n',
    'more_X_Y': 'показать полную информацию о фильме или сериале, где\n'
                'X - код сайта:\n'
                f'{" ":6}{CC_MEGA_FILM} - megashara фильм,\n'
                f'{" ":6}{CC_MEGA_SERIAL} - megashara сериал,\n'
                'Y - id релиза ',
    'ip': 'показать ip и регион бота',
    'ping_megashara': 'получить статус сайта megashara',
}


month_str = {
    0: 'Дек', 1: 'Янв', 2: 'Фев', 3: 'Мар', 4: 'Апр',  5: 'Май', 6: 'Июн',
    7: 'Июл', 8: 'Авг', 9: 'Сен', 10: 'Окт', 11: 'Ноя', 12: 'Дек'
}

telebot.logger.setLevel(logging.INFO)
bot = telebot.TeleBot(TOKEN)


@bot.message_handler(commands=['start'])
def command_start(message: Message):
    chat_id = message.chat.id
    first_name = str(message.chat.first_name)
    data_chats = load_chat_json()

    if str(chat_id) in data_chats.keys():
        bot.reply_to(message, f"Привет, {first_name}")
    else:
        data_chats[chat_id] = message.chat.username
        dump_chat_json(data_chats)
        bot.reply_to(message, f"Добро пожаловать, {first_name}")

    command_help(message)


@bot.message_handler(commands=['help'])
def command_help(message: Message):
    help_text = "Доступны следующие команды: \n"
    for key in commands:
        help_text += "/" + key + " - "
        help_text += commands[key] + "\n"
    bot.send_message(message.chat.id, help_text)


@bot.message_handler(commands=['last'])
def command_last(message: Message):
    unique_code = message.text.split()[1] if len(message.text.split()) > 1 else None
    exclude = [KEY_MEGA_FILM, KEY_MEGA_SERIAL, KEY_NEWSTUDIO]
    if unique_code == CC_ALL:
        exclude = []
        reply_wait = 'Придется подождать.. (~1мин.) Подписок много.. Ушёл, за информацией..'
    elif unique_code == CC_MEGA_FILM:
        exclude.remove(KEY_MEGA_FILM)
        reply_wait = 'Подождите.. Вспоминаю о последних фильмах Megashara..'
    elif unique_code == CC_MEGA_SERIAL:
        exclude.remove(KEY_MEGA_SERIAL)
        reply_wait = 'Подождите.. Посмотрю, что там с сериалами на Megashara..'
    elif unique_code == CC_NEWSTUDIO:
        exclude.remove(KEY_NEWSTUDIO)
        reply_wait = 'Придется подождать.. (~1мин.) Получаю информацию о последних релизах Newstudio..'
    else:
        exclude.remove(KEY_MEGA_FILM)
        exclude.remove(KEY_MEGA_SERIAL)
        reply_wait = 'Подождите.. Получаю информацию о последних релизах Megashara..'

    bot.reply_to(message, reply_wait)
    data = load_check_urls_json()[0]

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
        if type(data[key]) == list:
            count = limit if limit < len(data[key]) else len(data[key])
            lst_urls = data[key][-count:]
        else:
            lst_urls = []
            for k_serial in data[key].keys():
                count = limit if limit < len(data[key][k_serial]) else len(data[key][k_serial])
                lst_urls.extend(data[key][k_serial][-count:])

        lst_info = get_info_less(lst_urls)
        if not lst_info:
            lst_info = "Там все очень старое, даже выводить не буду.."
        reply_full += reply + lst_info + '\n'

    bot.send_message(message.chat.id, reply_full, parse_mode='HTML')


@bot.message_handler(commands=['ip'])
def command_ip(message: Message):
    response = requests.get('https://yandex.ru/internet/', proxies=apihelper.proxy)
    soup = BeautifulSoup(response.content, 'html.parser')
    reply = (f"IPv4: {soup.find('span', class_='info__value_type_ipv4').text}\n"
             f"Регион: {soup.find('span', class_='info__value_type_pinpoint-region').text}\n")
    bot.send_message(message.chat.id, reply)


@bot.message_handler(commands=['ping_megashara'])
def command_ping_megashara(message: Message):
    response = requests.get('http://megashara.com.', proxies=apihelper.proxy)
    reply = f"Статус код: {response.status_code}"
    bot.send_message(message.chat.id, reply)


@bot.message_handler(content_types=['text'])
def get_more_film(message: Message):
    """command get more info about film or serial"""

    if message.text.startswith('/more_'):
        msg_split = message.text.split('_')
        if len(msg_split) == 3:
            bot.reply_to(message, 'Получаю информацию о релизе..')
            data_url = load_check_urls_json()[0]

            if msg_split[1] == CC_MEGA_FILM:
                key = KEY_MEGA_FILM
            elif msg_split[1] == CC_MEGA_SERIAL:
                key = KEY_MEGA_SERIAL
            else:
                key = None

            if key:
                for url in data_url[key]:
                    if msg_split[2] in url:
                        reply = get_info_full(url)
                        bot.send_message(message.chat.id, reply, parse_mode='HTML')
                        return
                return bot.reply_to(message, 'Релиз не найден')

    reply = 'Хм.. может /help?'
    bot.reply_to(message, reply)


def parsing_site(site, count=9):
    """parsing site, return list pars_urls"""
    response = requests.get(site, proxies=apihelper.proxy)
    soup = BeautifulSoup(response.content, 'html.parser')

    if 'megashara' in site:
        response = list(map(lambda x: f"{x.a['href']}",
                            soup.find('div', id='mid-side').findAll('div', class_='name-block')))[:count]

    elif 'newstudio' in site:
        site_url = 'http://newstudio.tv'
        response = list(map(lambda x: f"{site_url}{x.a['href'][1:]}",
                            soup.findAll('div', class_='topic-list')))[:count]
    return list(reversed(response))


def get_rating_kinopoisk(pars_block):
    """
    Find kinopoisk rating on the page and get it
    :param pars_block: bs4.element-html for search
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


def get_info_less(urls):
    """get short movie description"""

    # convert in list if input url is string
    if type(urls) == str:
        urls = [urls]

    reply = ''
    for url in urls:
        try:
            # parsing for megashara
            if 'megashara' in url:
                response = requests.get(url, proxies=apihelper.proxy)
                soup = BeautifulSoup(response.content, 'html.parser')
                pars_block = soup.select_one('#mid-side')

                title = pars_block.h1.text

                if len(urls) == 1:
                    if url.startswith(sites[KEY_MEGA_FILM]):
                        kind = 'Фильм'
                    else:
                        kind = 'Сериал'

                    photo = pars_block.select_one('.preview img')['src']
                    reply += f"<b>{kind}</b><a href='{photo}'>.</a>\n"

                d_kinopoisk = get_rating_kinopoisk(pars_block)

                url_split = url.split('/')
                kind_code = CC_MEGA_FILM if url_split[3] == 'movies' else CC_MEGA_SERIAL
                link_more = f'/more_{kind_code}_' + url_split[4]

                reply += (
                    f"{title}\n"
                    f"Рейтинг: {d_kinopoisk['rating']} ({link_more})\n\n"
                )

            # parsing for newstudio
            elif 'newstudio' in url:
                response = requests.get(url, proxies=apihelper.proxy)
                soup = BeautifulSoup(response.content, 'html.parser')
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
                        if month_str[now.month] == date_release_month or \
                                month_str[(now.month - 1)] == date_release_month:
                            is_new_release = True
                else:
                    is_new_release = True

                if is_new_release:
                    if "WEBDLRip" not in title:
                        torrent_dirty = pars_block.select_one('.seedmed')['href']
                        torrent = 'http://newstudio.tv/' + torrent_dirty

                        if len(urls) == 1:
                            reply += f"<b> \U0000203C РЕЛИЗ \U0000203C</b>\n"

                        reply += (
                            f"{title} <a href='{torrent}'> Торрент \U0001F4E5</a>\n\n"
                        )

        except Exception as error:
            logger.info(url)
            logger.exception(error)

    return reply


def get_info_full(url):
    """get full movie description"""

    try:
        # parsing for megashara
        if 'megashara' in url:
            response = requests.get(url, proxies=apihelper.proxy)
            soup = BeautifulSoup(response.content, 'html.parser')
            pars_block = soup.select_one('#mid-side')
            table_2 = pars_block.select_one('.back-bg3 .info-table').extract()

            title = pars_block.h1.text
            photo = pars_block.select_one('.preview img')['src']

            # find parent block for specific value
            bl_genre = pars_block.find(string='Жанр:')
            bl_country = pars_block.find(string='Студия/Страна:')
            bl_translate = pars_block.find(string='Перевод:')
            bl_video = table_2.find(string='Видео:')
            bl_audio = table_2.find(string='Звук:')
            bl_size = table_2.find(string='Размер:')

            # get value from block.next_element
            genre = bl_genre.next_element.text if bl_genre else '-'
            country = bl_country.next_element.text if bl_country else '-'
            translate = bl_translate.next_element.text if bl_translate else '-'
            video = bl_video.next_element.text if bl_video else '-'
            audio = bl_audio.next_element.text if bl_audio else '-'
            size = bl_size.next_element.text if bl_size else '-'

            desc_dirty = pars_block.select_one('.back-bg3').text
            desc_clean = re.sub("\n+", '\n', desc_dirty)
            description = desc_clean.strip()

            d_kinopoisk = get_rating_kinopoisk(pars_block)

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

        else:
            return 'В разработке'

    except Exception as error:
        logger.info(url)
        logger.exception(error)
        return 'Ошибка при получении подробной информации'


def load_check_urls_json():
    """check new and load data_urls"""

    with open(file_json, 'r', encoding='utf-8') as file:
        data_urls = json.load(file)

        _new_urls = []
        for k_site in sites.keys():

            if type(sites[k_site]) == str:
                if not data_urls.get(k_site):
                    data_urls[k_site] = []
                pars_urls = parsing_site(site=sites[k_site])
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
                    pars_urls = parsing_site(site=url_serial)
                    for url in pars_urls:
                        if url not in data_urls[k_site][k_serial]:
                            _new_urls.append(url)
                            data_urls[k_site][k_serial].append(url)

        return data_urls, _new_urls


def dump_data_json(data_urls):
    with open(file_json, "w", encoding='utf-8') as file:
        file.write(json.dumps(data_urls, indent=4, ensure_ascii=False))


def load_chat_json():
    with open(chats_json, "r", encoding='utf-8') as file:
        _data = json.load(file)
    return _data


def dump_chat_json(data_chat):
    with open(chats_json, "w", encoding='utf-8') as file:
        file.write(json.dumps(data_chat, indent=4, ensure_ascii=False))


def listener(messages):
    """When new messages arrive TeleBot will call this function."""
    for m in messages:
        if m.content_type == 'text':
            logger.info(f"{str(m.chat.first_name)} (@{str(m.chat.username)}) [{str(m.chat.id)}]: {m.text}")


def update_data():
    first_update = True
    while True:
        try:
            upd_data, new_data = load_check_urls_json()

            if new_data:
                dump_data_json(upd_data)
                if first_update is True:
                    time.sleep(timeout_upd_first)
                    first_update = False
                else:
                    for url in new_data:
                        if url.startswith(sites[KEY_MEGA_SERIAL]):
                            continue

                        reply = get_info_less(url)
                        if reply:
                            chats = load_chat_json()
                            for chat in chats.keys():
                                bot.send_message(int(chat), reply, parse_mode='HTML')
                    time.sleep(timeout_upd)
        except Exception as error:
            logger.exception(error)
            time.sleep(10 * 60)


class UpdatePars(Thread):
    """thread for infinite update_parsing"""

    def __init__(self):
        Thread.__init__(self)
        self.name = "UpdatePars"

    def run(self):
        update_data()


def main():
    bot.set_update_listener(listener)
    bot.send_message(351443384, 'Я запущен заново')

    if not os.path.exists(file_json):
        dump_data_json({})
    if not os.path.exists(chats_json):
        dump_chat_json({})

    UpdatePars().start()

    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=60)
        except Exception as error:
            logger.exception(error)
            time.sleep(15)


if __name__ == '__main__':
    main()
