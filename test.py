from plexapi.server import PlexServer
from plexapi.video import Episode
import requests
PLEX_URL = 'https://192.168.10.3:32400/'
PLEX_TOKEN = 'WPz3dw8jK36NNbAKvcoY'
requests.packages.urllib3.disable_warnings()
sess = requests.Session()
sess.verify = False
plex = PlexServer(PLEX_URL, PLEX_TOKEN, session=sess)

epDict = {}

shows = plex.library.search(libtype='show')

for show in shows:
    epDict[show.title] = show.guid



print(epDict)