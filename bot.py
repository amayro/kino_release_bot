import json
import os
import re
import time
from threading import Thread

import requests
import telebot
from bs4 import BeautifulSoup
from telebot import apihelper
from telebot.types import Message

from config import TOKEN

file_json = 'data_url.json'
chats_json = 'data_chats.json'

KEY_MEGA_FILM = 'mega_f'
KEY_MEGA_SERIAL = 'mega_s'

sites = {   # sites for parsing
    KEY_MEGA_FILM: 'http://megashara.com/movies',
    KEY_MEGA_SERIAL: 'http://megashara.com/tv'
}

apihelper.proxy = {
    'http': 'socks5://45.63.66.99:1080',
    'https': 'socks5://45.63.66.99:1080',
}

commands = {  # command description used in the "help" command
    'start': 'начать использовать бота',
    'help': 'показать доступные команды',
    'last': 'показать последние релизы',
    'more_(1)_(2)': 'показать полную информацию о фильме или сериале, где\n'
                    '(1) -код сайта:\n'
                    f'{" ":6}(mf - megashara фильм),\n'
                    f'{" ":6}(ms - megashara сериал),\n'
                    '(2) - id релиза ',
    'ip': 'показать ip и регион бота',
    'ping_megashara': 'получить статус сайта megashara',
}

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
    for key in commands:  # generate help text out of the commands dictionary defined at the top
        help_text += "/" + key + " - "
        help_text += commands[key] + "\n"
    bot.send_message(message.chat.id, help_text)


@bot.message_handler(commands=['last'])
def command_last(message: Message):
    data = load_check_urls_json()[0]

    reply_full = ''
    bot.reply_to(message, 'Получаю информацию о последних релизах..')
    for key in data:
        reply = '<b>Фильмы: </b>' if key == KEY_MEGA_FILM else '<b>Сериалы: </b>'
        if key in [KEY_MEGA_FILM, KEY_MEGA_SERIAL]:
            reply += '(Megashara)\n'
        limit = 5
        count = limit if limit < len(data[key]) else len(data[key])
        lst_urls = list(reversed(data[key]))[:count]
        reply += get_info_less(lst_urls)
        reply_full += reply + '\n'
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
    print(message.chat.id)

    if message.text.startswith('/more_'):
        msg_split = message.text.split('_')
        if len(msg_split) == 3:
            bot.reply_to(message, 'Получаю информацию о релизе..')
            data_url = load_check_urls_json()[0]

            if msg_split[1] == 'mf':
                key = KEY_MEGA_FILM
            elif msg_split[1] == 'ms':
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


def parsing_site(site, count=3):
    """parsing site, return list pars_urls"""
    response = requests.get(site, proxies=apihelper.proxy)
    soup = BeautifulSoup(response.content, 'html.parser')

    if 'megashara' in site:
        response = list(map(lambda x: f"{x.a['href']}",
                            soup.find('div', id='mid-side').findAll('div', class_='name-block')))[:count]
    return response


def get_info_less(urls):
    """get short movie description"""

    if type(urls) == str:
        urls = [urls]

    reply = ''
    for url in urls:
        # parsing for megashara
        if 'megashara' in url:
            response = requests.get(url, proxies=apihelper.proxy)
            soup = BeautifulSoup(response.content, 'html.parser')
            pars_block = soup.select_one('#mid-side')

            title = pars_block.h1.text

            if len(urls) == 1:
                if url.startswith(sites[KEY_MEGA_FILM]):
                    kind = 'Фильм'
                elif url.startswith(sites[KEY_MEGA_SERIAL]):
                    kind = 'Сериал'

                photo = pars_block.select_one('.preview img')['src']
                reply += f"<b>{kind}</b><a href='{photo}'>.</a>\n"

            url_split = url.split('/')
            kind_code = 'mf' if url_split[3] == 'movies' else 'ms'
            link_more = f'/more_{kind_code}_' + url_split[4]

            reply += (
                f"{title} ({link_more})\n\n"
            )

    print(reply)
    return reply


def get_info_full(url):
    """get full movie description"""

    # parsing for megashara
    if 'megashara' in url:
        response = requests.get(url, proxies=apihelper.proxy)
        soup = BeautifulSoup(response.content, 'html.parser')
        pars_block = soup.select_one('#mid-side')
        table_2 = pars_block.select_one('.back-bg3 .info-table').extract()
        # print(soup.prettify())

        title = pars_block.h1.text
        photo = pars_block.select_one('.preview img')['src']
        genre = pars_block.find(string='Жанр:').next_element.text
        translate = pars_block.find(string='Перевод:').next_element.text
        video = table_2.find(string='Видео:').next_element.text
        audio = table_2.find(string='Звук:').next_element.text
        size = table_2.find(string='Размер:').next_element.text

        desc_dirty = pars_block.select_one('.back-bg3').text
        desc_clean = re.sub("\n+", '\n', desc_dirty)
        description = desc_clean.strip()

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

        reply = (
            f"<b>Фильм</b><a href='{photo}'>.</a>\n"
            f"<a href='{url}'>{title}</a>\n"
            f"Жанр: {genre}\n"
            f"Перевод: {translate}\n"
            f"Видео: {video}\n"
            f"Аудио: {audio}\n"
            f"Размер: {size}\n"
            f"Рейтинг: {rating}\n"
            f"Трейлер: {kinopoisk_url}\n\n"
            f"{description}\n"
        )

        print(reply)
        return reply


url = 'http://megashara.com/movies/889329/pomeshannyi_na_vremeni_time_freak.html'
url = 'http://megashara.com/tv/889969/chuzhestranka_sezon_4_epizod_10_outlander.html'
url2 = 'http://megashara.com/movies/889853/discovery_mastera_oruzhiya_01_04_iz_06_mad_dog_made.html'
# get_info_full(url)
# get_info_less(url)
# get_info_less([url, url2])


def load_check_urls_json():
    """check new and load data_urls"""

    with open(file_json, 'r', encoding='utf-8') as file:
        data_urls = json.load(file)

        _new_urls = []
        for k_site in sites.keys():
            if not data_urls.get(k_site):
                data_urls[k_site] = []

            for url in parsing_site(site=sites[k_site]):
                if url not in data_urls[k_site]:
                    _new_urls.append(url)
                    data_urls[k_site].append(url)

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
            time_val = time.strftime("[%Y-%m-%d %H:%M:%S]", time.localtime())
            print(f"{time_val} {str(m.chat.first_name)} (@{str(m.chat.username)}) [{str(m.chat.id)}]: {m.text}")


bot.set_update_listener(listener)


def update_data():
    while True:
        try:
            time_val = time.strftime("[%Y-%m-%d %H:%M:%S]", time.localtime())
            print(f"{time_val} 'UPDATE'")

            upd_data, new_data = load_check_urls_json()

            if new_data:
                dump_data_json(upd_data)
                for url in new_data:
                    if url.startswith(sites[KEY_MEGA_SERIAL]):
                        continue

                    reply = get_info_less(url)
                    chats = load_chat_json()
                    for chat in chats.keys():
                        bot.send_message(int(chat), reply, parse_mode='HTML')

            time.sleep(5)
        except Exception as e:
            print(e)
            time.sleep(10)


class UpdatePars(Thread):
    """thread for infinite update_parsing"""

    def run(self):
        update_data()


#Start and check file exists
if not os.path.exists(file_json):
    dump_data_json({})

if not os.path.exists(chats_json):
    dump_chat_json({})

UpdatePars().start()

while True:
    try:
        bot.polling(none_stop=True, interval=0, timeout=60)
    except Exception as e:
        print(e)
        time.sleep(15)
