import re
import time
import hashlib

from requests.adapters import HTTPAdapter

from streamlink.plugin import Plugin
from streamlink.plugin.api import http, validate, useragents
from streamlink.stream import HTTPStream, HLSStream, RTMPStream

API_URL = "https://capi.douyucdn.cn/api/v1/{0}&auth={1}"
OAPI_URL = "http://open.douyucdn.cn/api/RoomApi/room/{}"
VAPI_URL = "https://vmobile.douyu.com/video/getInfo?vid={0}"
API_SECRET = "Y237pxTx2In5ayGz"
SHOW_STATUS_ONLINE = 1
SHOW_STATUS_OFFLINE = 2
STREAM_WEIGHTS = {
        "low": 540,
        "medium": 720,
        "source": 1080
        }

_url_re = re.compile(r"""
    RECORD:http(s)?://
    (?:
        (?P<subdomain>.+)
        \.
    )?
    douyu.com/
    (?:
        show/(?P<vid>[^/&?]+)|
        (?P<channel>[^/&?]+)
    )
""", re.VERBOSE)

_room_id_re = re.compile(r'"room_id\\*"\s*:\s*(\d+),')
_room_id_alt_re = re.compile(r'data-onlineid=(\d+)')

_room_id_schema = validate.Schema(
        {
            "data": validate.any(None, {
                "room_id": validate.all(
                    validate.text,
                    validate.transform(int)
                    ),
                "room_status": validate.all(
                    validate.text,
                    validate.transform(int)
                    )
                })
            }
)

_room_schema = validate.Schema(
    {
        "data": validate.any(None, {
            "show_status": validate.all(
                validate.text,
                validate.transform(int)
            ),
            "rtmp_url": validate.text,
            "rtmp_live": validate.text,
            "hls_url": validate.text,
            "rtmp_multi_bitrate": validate.all(
                validate.any([], {
                    validate.text: validate.text
                }),
                validate.transform(dict)
            )
        })
    },
    validate.get("data")
)

_vapi_schema = validate.Schema(
    {
        "data": validate.any(None, {
            "video_url": validate.text
        })
    },
    validate.get("data")
)


class Douyutv_record(Plugin):
    @classmethod
    def can_handle_url(cls, url):
        return _url_re.match(url)

    @classmethod
    def stream_weight(cls, stream):
        if stream in STREAM_WEIGHTS:
            return STREAM_WEIGHTS[stream], "douyutv_record"
        return Plugin.stream_weight(stream)

    def _get_streams(self):
        match = _url_re.match(self.url)
        subdomain = match.group("subdomain")

        http.verify = False
        http.mount('https://', HTTPAdapter(max_retries=99))

        if subdomain == 'v':
            vid = match.group("vid")
            headers = {
                "User-Agent": useragents.ANDROID,
                "X-Requested-With": "XMLHttpRequest"
            }
            res = http.get(VAPI_URL.format(vid), headers=headers)
            room = http.json(res, schema=_vapi_schema)
            yield "source", HLSStream(self.session, room["video_url"])
            return

        channel = match.group("channel")
        channel = channel.split('/', -1)[-1]
        http.headers.update({'User-Agent': useragents.ANDROID})
        while(True):
            res = http.get(OAPI_URL.format(channel))
            room_id = http.json(res, schema=_room_id_schema)
            channel = room_id["data"]["room_id"]
            if not room_id:
                self.logger.info("Not a valid room url.")
                return
            if room_id["data"]["room_status"] != SHOW_STATUS_ONLINE:
                self.logger.info("[%s]Stream currently unavailable." % time.ctime())
                time.sleep(60)
            else:
                break

        cdns = ["ws", "tct", "ws2", "dl"]
        ts = int(time.time())
        suffix = "room/{0}?aid=androidhd1&cdn={1}&client_sys=android&time={2}".format(channel, cdns[0], ts)
        sign = hashlib.md5((suffix + API_SECRET).encode()).hexdigest()

        res = http.get(API_URL.format(suffix, sign))
        room = http.json(res, schema=_room_schema)


        url = room["hls_url"]
        yield "source", HLSStream(self.session, url)

        url = "{room[rtmp_url]}/{room[rtmp_live]}".format(room=room)
        if 'rtmp:' in url:
            stream = RTMPStream(self.session, {
                    "rtmp": url,
                    "live": True
                    })
            yield "source", stream
        else:
            yield "source", HTTPStream(self.session, url)

        multi_streams = {
                "middle": "low",
                "middle2": "medium"
                }
        for name, url in room["rtmp_multi_bitrate"].items():
            url = "{room[rtmp_url]}/{url}".format(room=room, url=url)
            name = multi_streams[name]
            if 'rtmp:' in url:
                stream = RTMPStream(self.session, {
                        "rtmp": url,
                        "live": True
                        })
                yield name, stream
            else:
                yield name, HTTPStream(self.session, url)


__plugin__ = Douyutv_record
