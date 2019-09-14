from config import newstudio_subscr

ENCODING_NAME = 'utf-8'
proxy = None
timeout_upd_first = 3 * 60
timeout_upd = 5 * 60

# number of urls for parsing on the site
num_pars_url_megashara = 9
num_pars_url_lordsfilm = 18
num_pars_url_newstudio = 9

# number of releases per site for response command /last
num_last_release_per_site = 5


KEY_MEGA_FILM = 'mega_f'
KEY_MEGA_SERIAL = 'mega_s'
KEY_LORD_FILM = 'lord_f'
KEY_NEWSTUDIO = 'ns'

sites = {  # sites for parsing
    KEY_MEGA_FILM: 'http://megashara.com/movies',
    KEY_MEGA_SERIAL: 'http://megashara.com/tv',
    KEY_LORD_FILM: 'http://lordsfilms.tv/films',
    KEY_NEWSTUDIO: [
        'http://newstudio.tv/viewforum.php?f=444&sort=2',  # Миллиарды
        'http://newstudio.tv/viewforum.php?f=206&sort=2',  # Форс-мажоры
        *newstudio_subscr,
    ]
}
