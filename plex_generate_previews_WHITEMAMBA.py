#!/usr/bin/env python3
import sys
import re
import subprocess
import shutil
import glob
import os
import struct
import urllib3
import array
import time
from concurrent.futures import ProcessPoolExecutor, as_completed  # Add as_completed to import
from pathlib import Path
from plexapi.video import Episode, Season, Show
from plexapi.exceptions import NotFound  # Add this import
from generateGlobals import *

# Set the timeout envvar for https://github.com/pkkid/python-plexapi
os.environ["PLEXAPI_PLEXAPI_TIMEOUT"] = str(PLEX_TIMEOUT)

if not shutil.which("mediainfo"):
    print('MediaInfo not found.  MediaInfo must be installed and available in PATH.')
    sys.exit(1)
try:
    from pymediainfo import MediaInfo
except ImportError:
    print('Dependencies Missing!  Please run "pip3 install pymediainfo".')
    sys.exit(1)
try:
    import gpustat
except ImportError:
    print('Dependencies Missing!  Please run "pip3 install gpustat".')
    sys.exit(1)

try:
    import requests
except ImportError:
    print('Dependencies Missing!  Please run "pip3 install requests".')
    sys.exit(1)

try:
    from plexapi.server import PlexServer
except ImportError:
    print('Dependencies Missing!  Please run "pip3 install plexapi".')
    sys.exit(1)

try:
    from loguru import logger
except ImportError:
    print('Dependencies Missing!  Please run "pip3 install loguru".')
    sys.exit(1)

try:
    from rich.console import Console
except ImportError:
    print('Dependencies Missing!  Please run "pip3 install rich".')
    sys.exit(1)

try:
    from rich.progress import Progress, SpinnerColumn, MofNCompleteColumn
except ImportError:
    print('Dependencies Missing!  Please run "pip3 install rich".')
    sys.exit(1)

FFMPEG_PATH = shutil.which("ffmpeg")
if not FFMPEG_PATH:
    print('FFmpeg not found.  FFmpeg must be installed and available in PATH.')
    sys.exit(1)

# Logging setup
console = Console()
logger.remove()
logger.add(
    lambda _: console.print(_, end=''),
    level='INFO',
    format='<green> {time:YYYY/MM/DD HH:mm:ss}</green> | {level.icon}'
    + '  - <level>{message}</level>',
    enqueue=True
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def generate_images(video_file_param, output_folder):
    video_file = video_file_param.replace(PLEX_VIDEOS_PATH_MAPPING, PLEX_LOCAL_VIDEOS_PATH_MAPPING)
    ogFile = Path(video_file_param.replace(PLEX_VIDEOS_PATH_MAPPING, ""))
    
    logfile=Path("G:/VPT-Processing/"+ogFile.stem+".txt")
    logfile.parent.mkdir(exist_ok=True, parents=True)
    with open(logfile, 'w') as file:
        file.write("Processing")
    media_info = MediaInfo.parse(video_file)
    vf_parameters = "fps=fps={}:round=up,scale=w=320:h=240:force_original_aspect_ratio=decrease".format(
        round(1 / PLEX_BIF_FRAME_INTERVAL, 6))

    # Check if we have a HDR Format. Note: Sometimes it can be returned as "None" (string) hence the check for None type or "None" (String)
    if media_info.video_tracks:
        is_hdr = media_info.video_tracks[0].hdr_format != "None" and media_info.video_tracks[0].hdr_format is not None
        
        if is_hdr:
            vf_parameters = "fps=fps={}:round=up,zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,scale=w=320:h=240:force_original_aspect_ratio=decrease".format(round(1 / PLEX_BIF_FRAME_INTERVAL, 6))
        else:
            vf_parameters = "fps=fps={}:round=up,scale=w=320:h=240:force_original_aspect_ratio=decrease".format(round(1 / PLEX_BIF_FRAME_INTERVAL, 6))

    args = [
        FFMPEG_PATH, "-loglevel", "info", "-skip_frame:v", "nokey", "-threads:0", "1", "-i",
        video_file, "-an", "-sn", "-dn", "-q:v", str(THUMBNAIL_QUALITY), '{}/img-%06d.jpg'.format(output_folder)
    ]

    start = time.time()
    hw = False

    gpu_stats_query = gpustat.core.new_query()
    gpu = gpu_stats_query[0] if gpu_stats_query else None
    if gpu:
        gpu_ffmpeg = [c for c in gpu.processes if c["command"].lower().startswith("ffmpeg")]
        if len(gpu_ffmpeg) < GPU_THREADS or CPU_THREADS == 0:
            hw = True
            args.insert(5, "-hwaccel")
            args.insert(6, "cuda")
            args.insert(5, "-hwaccel_output_format")
            args.insert(6, "cuda")
            if is_hdr:
                # HDR with hardware - use p010le for HEVC/H.264
                vf_parameters = f"hwdownload,format=p010le,{vf_parameters}"
            else:
                # Non-HDR with hardware - use nv12
                vf_parameters = f"hwdownload,format=nv12,{vf_parameters}"
            
    args.insert(-1, "-vf")
    args.insert(-1, vf_parameters)
            

    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Allow time for it to start
    time.sleep(1)

    out, err = proc.communicate()
    if proc.returncode != 0:
        err_lines = err.decode('utf-8', 'ignore').split('\n')[-5:]
        logger.error(err_lines)
        logger.error('Problem trying to ffmpeg images for {}'.format(video_file))

    # Speed
    end = time.time()
    seconds = round(end - start, 1)
    speed = re.findall('speed= ?([0-9]+\\.?[0-9]*|\\.[0-9]+)x', err.decode('utf-8', 'ignore'))
    if speed:
        speed = speed[-1]

    # Optimize and Rename Images
    for image in glob.glob('{}/img*.jpg'.format(output_folder)):
        frame_no = int(os.path.basename(image).strip('-img').strip('.jpg')) - 1
        frame_second = frame_no * PLEX_BIF_FRAME_INTERVAL
        os.rename(image, os.path.join(output_folder, '{:010d}.jpg'.format(frame_second)))

    # Return the data instead of logging
    logfile.unlink()
    return {'video_file': video_file, 'hw': hw, 'seconds': seconds, 'speed': speed}

def generate_bif(bif_filename, images_path):
    """
    Build a .bif file
    @param bif_filename name of .bif file to create
    @param images_path Directory of image files 00000001.jpg
    """
    magic = [0x89, 0x42, 0x49, 0x46, 0x0d, 0x0a, 0x1a, 0x0a]
    version = 0

    images = [img for img in os.listdir(images_path) if os.path.splitext(img)[1] == '.jpg']
    images.sort()

    f = open(bif_filename, "wb")
    array.array('B', magic).tofile(f)
    f.write(struct.pack("<I", version))
    f.write(struct.pack("<I", len(images)))
    f.write(struct.pack("<I", 1000 * PLEX_BIF_FRAME_INTERVAL))
    array.array('B', [0x00 for x in range(20, 64)]).tofile(f)

    bif_table_size = 8 + (8 * len(images))
    image_index = 64 + bif_table_size
    timestamp = 0

    # Get the length of each image
    for image in images:
        statinfo = os.stat(os.path.join(images_path, image))
        f.write(struct.pack("<I", timestamp))
        f.write(struct.pack("<I", image_index))
        timestamp += 1
        image_index += statinfo.st_size

    f.write(struct.pack("<I", 0xffffffff))
    f.write(struct.pack("<I", image_index))

    # Now copy the images
    for image in images:
        data = open(os.path.join(images_path, image), "rb").read()
        f.write(data)

    f.close()


def process_item(item_key):
    sess = requests.Session()
    sess.verify = False
    plex = PlexServer(PLEX_URL, PLEX_TOKEN, timeout=PLEX_TIMEOUT, session=sess)
    try:
        data = plex.query('{}/tree'.format(item_key))
    except NotFound:
        logger.warning('Item {} no longer exists in Plex library/Merge, skipping...'.format(item_key))
        return
    except Exception as e:
        logger.error('Error processing item {}. `{}:{}` error when querying Plex API'.format(item_key, type(e).__name__, str(e)))
        return

    for media_part in data.findall('.//MediaPart'):
        if 'hash' in media_part.attrib:
            # Filter Processing by HDD Path
            if len(sys.argv) > 1:
                if sys.argv[1] not in media_part.attrib['file']:
                    return
            bundle_hash = media_part.attrib['hash']
            media_file = media_part.attrib['file']
            if 'PLEX_LOCAL_VIDEOS_PATH_ARRAY' in globals():
                if len(PLEX_LOCAL_VIDEOS_PATH_ARRAY) > 0:
                    found=False
                    for local_path in PLEX_LOCAL_VIDEOS_PATH_ARRAY:
                        for other_path in PLEX_VIDEOS_PATH_ARRAY:
                            # logger.info('Checking if {} exists'.format(media_file.replace(other_path, local_path)))                           
                            if os.path.isfile(media_file.replace(other_path, local_path)):
                                # logger.info('Found matching path {} for {}'.format(local_path, media_file))
                                global PLEX_LOCAL_VIDEOS_PATH_MAPPING
                                global PLEX_VIDEOS_PATH_MAPPING
                                PLEX_LOCAL_VIDEOS_PATH_MAPPING = local_path
                                PLEX_VIDEOS_PATH_MAPPING = other_path
                                # logger.info('PLEX_LOCAL_VIDEOS_PATH_MAPPING = '+PLEX_LOCAL_VIDEOS_PATH_MAPPING)
                                found=True
                                break
                        if found:
                            break
                            
            media_file = media_file.replace(PLEX_VIDEOS_PATH_MAPPING, PLEX_LOCAL_VIDEOS_PATH_MAPPING) ### This line was added by sean.
            # logger.info('media file = '+media_file)
            if not os.path.isfile(media_file):
                logger.error('Skipping as file not found {}'.format(media_file))
                continue

            try:
                bundle_file = '{}/{}{}'.format(bundle_hash[0], bundle_hash[1::1], '.bundle')
            except Exception as e:
                logger.error('Error generating bundle_file for {} due to {}:{}'.format(media_file, type(e).__name__, str(e)))
                continue

            bundle_path = os.path.join(PLEX_LOCAL_MEDIA_PATH, bundle_file)
            indexes_path = os.path.join(bundle_path, 'Contents', 'Indexes')
            index_bif = os.path.join(indexes_path, 'index-sd.bif')
            tmp_path = os.path.join(TMP_FOLDER, bundle_hash)
            if (not os.path.isfile(index_bif)) and (not os.path.isdir(tmp_path)):
                if not os.path.isdir(indexes_path):
                    try:
                        os.makedirs(indexes_path)
                    except OSError as e:
                        logger.error('Error generating images for {}. `{}:{}` error when creating index path {}'.format(media_file, type(e).__name__, str(e), indexes_path))
                        continue

                try:
                    os.makedirs(tmp_path)
                except OSError as e:
                    logger.error('Error generating images for {}. `{}:{}` error when creating tmp path {}'.format(media_file, type(e).__name__, str(e), tmp_path))
                    continue

                try:
                    result = generate_images(media_part.attrib['file'], tmp_path)
                except Exception as e:
                    logger.error('Error generating images for {}. `{}: {}` error when generating images'.format(media_file, type(e).__name__, str(e)))
                    if os.path.exists(tmp_path):
                        shutil.rmtree(tmp_path)
                    continue

                try:
                    generate_bif(index_bif, tmp_path)
                except Exception as e:
                    # Remove bif, as it prob failed to generate
                    if os.path.exists(index_bif):
                        os.remove(index_bif)
                    logger.error('Error generating images for {}. `{}:{}` error when generating bif'.format(media_file, type(e).__name__, str(e)))
                    continue
                finally:
                    if os.path.exists(tmp_path):
                        shutil.rmtree(tmp_path)
                        
                return result  # Return the result for logging
            else:
                # logger.info('Skipping as bif already exists or tmp path exists {}'.format(media_file))
                continue

def run():
    ###-- V2.0 with Parallel Sublist Processing --###
    # Ignore SSL Errors
    sess = requests.Session()
    sess.verify = False

    # Clean up old processing directory
    shutil.rmtree("G:/VPT-Processing/") if os.path.exists("G:/VPT-Processing/") else None

    plex = PlexServer(PLEX_URL, PLEX_TOKEN, session=sess)

    def process_media(media, sublist_index, sublist_name, workers=CPU_THREADS + GPU_THREADS):
        """Process media for a specific sublist"""
        if not media:
            return
            
        logger.info(f'Processing {len(media)} media files from {sublist_name} (Sublist {sublist_index})')
            
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(process_item, key) for key in media]
            for future in as_completed(futures):
                result = future.result()
                if result:
                    logger.info('Generated Video Preview for {} on {} HW={} TIME={}seconds SPEED={}x'.format(
                        result['video_file'], sublist_name, result['hw'], result['seconds'], result['speed']))
                progress.advance(task)
                progress.refresh()


    if runType != "Currently Playing" and runType != "Full":
        from generateGlobals import fetch_result_list
        result_list = fetch_result_list()
        lenResultList = sum(1 for sublist in result_list if sublist)
        lenSubLists = sum(len(sublist) for sublist in result_list if sublist)
        
        # Process all sublists in parallel
        sublist_names = ['RCLONE', 'WM', 'ZPOOL1', 'ZPOOL2', 'ZPOOL3', 'ZPOOL4', 'ZPOOL5', 'ZPOOL6']
        
        from concurrent.futures import ThreadPoolExecutor
        with Progress(SpinnerColumn(), *Progress.get_default_columns(), MofNCompleteColumn(), console=console) as progress:
            task = progress.add_task(f"Working...", total=lenSubLists)
            with ThreadPoolExecutor(max_workers=lenResultList) as executor:
                futures = []
                for idx, sublist in enumerate(result_list):
                    if sublist:  # Only submit non-empty sublists
                        future = executor.submit(
                            process_media,
                            [m.key for m in sublist],
                            idx,
                            sublist_names[idx] if idx < len(sublist_names) else f'Sublist {idx}',
                            workers = 1
                        )
                        futures.append(future)
                
                # Wait for all to complete
                for future in futures:
                    future.result()
                    progress.advance(task)
                    progress.refresh()
                
    elif runType == "Currently Playing":
        for item in plex.library.onDeck():
            if isinstance(item, Episode):
                title = item.grandparentTitle
                process_media([m.key for m in item.season().unwatched()], 0, 'Currently Playing')
    else:
        for section in plex.library.sections():
            if section.METADATA_TYPE == 'episode':
                title = section.title
                media = [m.key for m in section.search(libtype='episode')]
                process_media(media, 0, section.title)
            elif section.METADATA_TYPE == 'changedSoNoMovies':
                title = section.title
                media = [m.key for m in section.search()]
                process_media(media, 0, section.title)
            else:
                logger.info(f'Skipping {section.title}, unsupported type: {section.METADATA_TYPE}')


def main():
    if not os.path.exists(PLEX_LOCAL_MEDIA_PATH):
        logger.error(
            '%s does not exist, please edit PLEX_LOCAL_MEDIA_PATH environment variable' % PLEX_LOCAL_MEDIA_PATH)
        exit(1)

    if PLEX_URL == '':
        logger.error('Please set the PLEX_URL environment variable')
        exit(1)

    if PLEX_TOKEN == '':
        logger.error('Please set the PLEX_TOKEN environment variable')
        exit(1)

    try:
        # Clean TMP Folder
        if os.path.isdir(TMP_FOLDER):
            shutil.rmtree(TMP_FOLDER)
        os.makedirs(TMP_FOLDER)
        while True:
            run()
    except KeyboardInterrupt:
        logger.info('Shutting down...')
    finally:
        if os.path.isdir(TMP_FOLDER):
            shutil.rmtree(TMP_FOLDER)


if __name__ == '__main__':
    main()
    

# def run():
###-- ORIGIN --###
#     # Ignore SSL Errors
#     sess = requests.Session()
#     sess.verify = False
#     if os.path.exists("G:/VPT-Processing/"):
#         shutil.rmtree("G:/VPT-Processing/")
#     plex = PlexServer(PLEX_URL, PLEX_TOKEN, session=sess)

#     if runType == "Currently Playing":
#         for ep in plex.library.onDeck():
#             if isinstance(ep, Episode):
#                 unwatched = ep.season().unwatched()
#                 media = [m.key for m in unwatched]
#                 logger.info('Got {} media files for library {}'.format(len(media), ep.grandparentTitle))
#                 with Progress(SpinnerColumn(), *Progress.get_default_columns(), MofNCompleteColumn(), console=console) as progress:
#                     with ProcessPoolExecutor(max_workers=CPU_THREADS + GPU_THREADS) as process_pool:
#                         futures = [process_pool.submit(process_item, key) for key in media]
#                         for future in progress.track(futures):
#                             future.result()
        
#     else:
#         for section in plex.library.sections():
#             logger.info('Getting the media files from library \'{}\''.format(section.title))
            
#             if section.METADATA_TYPE == 'episode':
#                 media = [m.key for m in section.search(libtype='episode')]
#             elif section.METADATA_TYPE == 'changedSoNoMovies':
#                 media = [m.key for m in section.search()]
#             else:
#                 logger.info('Skipping library {} as \'{}\' is unsupported'.format(section.title, section.METADATA_TYPE))
#                 continue
#             logger.info('Got {} media files for Series :  {}'.format(len(media), section.title))
#             with Progress(SpinnerColumn(), *Progress.get_default_columns(), MofNCompleteColumn(), console=console) as progress:
#                 with ProcessPoolExecutor(max_workers=CPU_THREADS + GPU_THREADS) as process_pool:
#                     futures = [process_pool.submit(process_item, key) for key in media]
#                     for future in progress.track(futures):
#                         future.result()