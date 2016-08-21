from concurrent.futures import ThreadPoolExecutor
from logging.handlers import RotatingFileHandler
import json
import logging
import queue
import signal
import socket
import threading

from tweepy.streaming import StreamListener
from tweepy import OAuthHandler
from tweepy import Stream
import requests
import tornado.httpserver
import tornado.ioloop
import tornado.web
import tornado.websocket

import settings

# Log init
logger = logging.getLogger()
logger.setLevel(settings.LOG_LEVEL)

formatter = logging.Formatter('%(asctime)s :: %(levelname)s :: %(message)s')

stream_handler = logging.StreamHandler()
stream_handler.setLevel(settings.LOG_LEVEL)
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

# Queue for sending back videos data
ws_sender_queue = queue.Queue()

def ws_sender_manager():
    while True:
        msg = ws_sender_queue.get()
        for client in application.clients:
            client.write_message(msg)
        ws_sender_queue.task_done()

t = threading.Thread(target=ws_sender_manager)
t.daemon = True
t.start()
del t

# Find the best quality video amongs all available
def find_media_url(entities):
    max_bitrate = 0
    url = None
    
    if "video_info" in entities:
        for variant in entities['video_info']['variants']:
            if variant['content_type'] == 'video/mp4':
                if max_bitrate <= variant['bitrate']:
                    max_bitrate = variant['bitrate']
                    url = variant['url']
    return url

def process_status(status):
    if "extended_entities" in status:
        for media in status["extended_entities"]['media']:
            media_url = find_media_url(media)
            if media_url:
                media_md5 = get_media_md5(media_url)
                ws_sender_queue.put(json.dumps({'text': status['text'],'user':status['user']['screen_name'],'url':media_url,'md5':media_md5}))

# Get the MD5 either cached or by HTTP HEAD the video
def get_media_md5(media_url):
    try:
        if media_url in application.medias:
            return application.medias[media_url]
        req = requests.head(media_url)
        return req.headers.get('content-md5',media_url)
    except Exception as e:
        logger.error(e)
    finally:
        return media_url

# Listener class for twitter stream
class MediaExtractor(StreamListener):
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=10)
    def on_data(self, data):
        try:
            json_data = json.loads(data)
            self.executor.submit(process_status,json_data)       
        except Exception as e:
            logger.error(e)

# Handler to serve base HTML
class MainHandler(tornado.web.RequestHandler):
    def get(self):
        self.render("templates/index.html",hostname=settings.SERVICE_HOSTNAME, track= ','.join(self.application.twitter_track) )

# Handler for Websocket connection
class WSHandler(tornado.websocket.WebSocketHandler):
    def check_origin(self, origin):
        return True
    def open(self):
        logger.info('new connection')
        self.application.clients[self] = True    
    def on_message(self, message):
        logger.info('message received %s' , message )
    def on_close(self):
        logger.info('connection closed' )
        del self.application.clients[self]

# Tornado application init
application = tornado.web.Application([
                                        (r'/ws', WSHandler),
                                        (r'/', MainHandler),
                                      ], 
                                      debug=settings.APP_DEBUG)
application.clients = {}
application.media_md5 = set()
application.media_url = set()
application.medias ={}

if __name__ == '__main__':

    l = MediaExtractor()

    auth = OAuthHandler(settings.TWITTER_CONSUMER_KEY, settings.TWITTER_CONSUMER_SECRET)
    auth.set_access_token(settings.TWITTER_ACCESS_TOKEN,settings.TWITTER_ACCESS_TOKEN_SECRET)

    if not settings.TWITTER_TRACK:
        exit(1)

    application.twitter_track = settings.TWITTER_TRACK
    stream = Stream(auth, l)
    stream.filter(track=settings.TWITTER_TRACK,async=True)

    http_server = tornado.httpserver.HTTPServer(application)
    http_server.listen(settings.WS_PORT)
    tornado.ioloop.IOLoop.instance().start()
