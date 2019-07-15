from config import newstudio_subscr

ENCODING_NAME = 'utf-8'
proxy = None
timeout_upd_first = 3 * 60
timeout_upd = 5 * 60


KEY_MEGA_FILM = 'mega_f'
KEY_MEGA_SERIAL = 'mega_s'
KEY_NEWSTUDIO = 'ns'

sites = {  # sites for parsing
    KEY_MEGA_FILM: 'http://megashara.com/movies',
    KEY_MEGA_SERIAL: 'http://megashara.com/tv',
    KEY_NEWSTUDIO: [
        'http://newstudio.tv/viewforum.php?f=444&sort=2',  # Миллиарды
        'http://newstudio.tv/viewforum.php?f=206&sort=2',  # Форс-мажоры
        *newstudio_subscr,
    ]
}