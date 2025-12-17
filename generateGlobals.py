from plexapi.server import PlexServer
from plexapi.video import Episode, Season, Show
import requests, os, sys
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
from itertools import zip_longest

load_dotenv()


PLEX_URL = os.environ.get('PLEX_URL', 'https://192.168.0.27:32400/')  # Plex server URL. can also use for local server: http://localhost:32400
PLEX_TOKEN = os.environ.get('PLEX_TOKEN', 'WPz3dw8jK36NNbAKvcoY')  # Plex Authentication Token WPz3dw8jK36NNbAKvcoY  ### fxFNLRwxuHdMdusJ6rof
PLEX_BIF_FRAME_INTERVAL = int(os.environ.get('PLEX_BIF_FRAME_INTERVAL', 5))  # Interval between preview images
THUMBNAIL_QUALITY = int(os.environ.get('THUMBNAIL_QUALITY', 2))  # Preview image quality (2-6)
PLEX_LOCAL_MEDIA_PATH = os.environ.get('PLEX_LOCAL_MEDIA_PATH', '\\\\192.168.10.3\\internal\\Android\\data\\com.plexapp.mediaserver.smb\\Plex Media Server\\Media\\localhost\\')  # Local Plex media path
TMP_FOLDER = os.environ.get('TMP_FOLDER', 'G:/Temp/vpt')  # Temporary folder for preview generation
PLEX_TIMEOUT = int(os.environ.get('PLEX_TIMEOUT', 60))  # Timeout for Plex API requests (seconds)

# Path mappings for remote preview generation. # So you can have another computer generate previews for your Plex server
# If you are running on your plex server, you can set both variables to ''
PLEX_LOCAL_VIDEOS_PATH_MAPPING = os.environ.get('PLEX_LOCAL_VIDEOS_PATH_MAPPING', '\\\\172.17.1.77\\Union')  # Local video path (Usually ending in "/Union/" for the script ###Change this to where the videos are relative to the encoder, or if merged use the local path to make it faaast  U:/
PLEX_LOCAL_VIDEOS_PATH_ARRAY = os.environ.get('PLEX_LOCAL_VIDEOS_PATH_ARRAY', ['G:/LinuxShare/Union','\\\\172.17.1.77\\Union']) ### Sean Added for using backends instead of Union ###
PLEX_VIDEOS_PATH_MAPPING = os.environ.get('PLEX_VIDEOS_PATH_MAPPING', '/media/sean/1tb1/Union/')  # Plex server video path    the normal path for above  ^'//192.168.0.27/Union/' ^
PLEX_VIDEOS_PATH_ARRAY = os.environ.get('PLEX_VIDEOS_PATH_ARRAY', ['/zfs/zpool1/media_root/Union','/zfs/zpool2/media_root/Union', 
                                        '/zfs/zpool3/media_root/Union','/zfs/zpool4/media_root/Union', '/zfs/zpool5/media_root/Union',
                                        '/zfs/zpool6/media_root/Union','/rclone/Crypts/Crypt-Mum/Union', '/rclone/Crypts/Crypt-Dad/Union',
                                        '/rclone/Crypts/Crypt-OD/Union','/rclone/Crypts/Crypt-OD2/Union', '/rclone/Crypts/Crypt-S59S1/Union',
                                        '/rclone/Crypts/Crypt-SS59/Union']) ### Sean Added for using backends instead of Union ###
GPU_THREADS = int(os.environ.get('GPU_THREADS', 2))  # Number of GPU threads for preview generation
CPU_THREADS = int(os.environ.get('CPU_THREADS', 0))  # Number of CPU threads for preview generation


SHIELD_URL = 'https://192.168.10.3:32400/'
PLEX_TOKEN = 'WPz3dw8jK36NNbAKvcoY'
requests.packages.urllib3.disable_warnings()
sess = requests.Session()
sess.verify = False
WMPlex = PlexServer(PLEX_URL, PLEX_TOKEN, session=sess)
shieldPlex = PlexServer(SHIELD_URL, PLEX_TOKEN, session=sess)
manualList = []
guidVars = {"episode" : "plex://episode/5d9c133202391c001f5ff718", 
            "season" : "plex://season/602e690cea35e0002c23e7f6",
            "episode1" : "plex://episode/5d9c13327b5c2e001e6cfaeb", 
            "season1" : "plex://season/602e6909ea35e0002c23e5b1", 
            "show" : "plex://show/5d9c0871e264b7001fc4435c" }


###-- SET RUN TYPE HERE --###
runType = "Other"
# runType = "Full"

def fetch_manual_list():
    """Fetch unwatched items from WMPlex based on shieldPlex shows"""
    mediaItems = shieldPlex.library.search(libtype='show')
    n=0
    for item in mediaItems:
        print(f"[{n}]: {item.title}")
        n += 1
    picked = input("Pick a number from the list above: ")
    if picked != "":
        if picked.upper() == "EXIT" or picked.upper() == "QUIT" or picked.upper() == "Q" or picked.upper() == "X":
            exit()  # Keep full list
    try :
        picked = int(picked)
        mediaItems = [mediaItems[picked]]
    except :
        print("Invalid input, proceeding with full list")   
    
    guids_to_fetch = []
    for ep in mediaItems:
        items = ep if isinstance(ep, list) else [ep]
        for item in items:
            if isinstance(item, Show):
                guids_to_fetch.append(item.guid)
            elif isinstance(item, Season):
                guids_to_fetch.append(item.parentGuid)
            elif isinstance(item, Episode):
                guids_to_fetch.append(item.grandparentGuid)
    
    def fetchWMEps(guid):
        try:
            results = WMPlex.library.search(guid=guid)
            if not results:
                return None
            # return results[0].unwatched()
            return results[0]
        except Exception as e:
            print(f"Error fetching {guid}: {e}")
            return None
    
    RCLONE, WM, ZPOOL1, ZPOOL2, ZPOOL3, ZPOOL4, ZPOOL5, ZPOOL6 = [], [], [], [], [], [], [], []
    
    result_list = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        for result in executor.map(fetchWMEps, guids_to_fetch):
            if result:
                for ep in result.episodes():
                    file = ep.media[0].parts[0].file
                    if file.startswith('/rclone'):
                        RCLONE.append(ep)
                    elif file.startswith('/zfs/zpool1'):
                        ZPOOL1.append(ep)
                    elif file.startswith('/zfs/zpool2'):
                        ZPOOL2.append(ep)
                    elif file.startswith('/zfs/zpool3'):
                        ZPOOL3.append(ep)
                    elif file.startswith('/zfs/zpool4'):
                        ZPOOL4.append(ep)
                    elif file.startswith('/zfs/zpool5'):
                        ZPOOL5.append(ep)
                    elif file.startswith('/zfs/zpool6'):
                        ZPOOL6.append(ep)
                    else:
                        WM.append(ep)
    
    for r, w, z1, z2, z3, z4, z5, z6 in zip_longest(RCLONE, WM, ZPOOL1, ZPOOL2, ZPOOL3, ZPOOL4, ZPOOL5, ZPOOL6, fillvalue=None):
        sublist = []
        if r is not None:
            sublist.append(r)
        if w is not None:
            sublist.append(w)
        if z1 is not None:
            sublist.append(z1)
        if z2 is not None:
            sublist.append(z2)
        if z3 is not None:
            sublist.append(z3)
        if z4 is not None:
            sublist.append(z4)
        if z5 is not None:
            sublist.append(z5)
        if z6 is not None:
            sublist.append(z6)
        result_list.append(sublist)
            
    for item in result_list:
        print(f"Added to manual list: {item}")
    # exit()
    return result_list