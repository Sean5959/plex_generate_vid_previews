import os

# if os.path.isfile("\\\\172.17.1.77\\Union/Series/Fallout/Season 1/Fallout - S01E01 - The End WEBDL-2160p.mkv"):
#     print("File exists")
    
args = [
    'FFMPEG_PATH', "-loglevel", "info", "-skip_frame:v", "nokey", "-threads:0", "1", "-i",
    'video_file', "-an", "-sn", "-dn", "-q:v", str('THUMBNAIL_QUALITY'),
    "-vf",
    'vf_parameters', '{}/img-%06d.jpg'.format('output_folder')
]

args.insert(5, 'Hello')
args.insert(6, 'World')

print(args)

