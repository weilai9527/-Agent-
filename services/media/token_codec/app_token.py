import base64
import io
import struct
import time

from .util import sign_utils
from .util import bytes_utils
from .util import compress_utils
import random

from .app_token_options import AppTokenOptions
from .service import Service

VERSION_LENGTH = 3
VERSION_0 = "000"


class AppToken:
    def __init__(self, app_id: str, app_key: str, timestamp: int, issue_timestamp: int = None, salt: int = None,
                 service: Service = None,
                 options: AppTokenOptions = None, signature: bytes = None):
        self.app_id = app_id
        self.app_key = app_key
        self.timestamp = timestamp
        self.issue_timestamp = int(time.time()) if issue_timestamp is None else issue_timestamp
        self.salt = random.randint(1, self.issue_timestamp) if salt is None else salt
        self.service = service
        self.options = options
        self.signature = signature

    def set_service(self, service: Service):
        self.service = service

    def set_options(self, options: AppTokenOptions):
        self.options = options

    def build(self) -> str:
        if self.app_key is None:
            raise ValueError('missing secretKey')
        if self.service is None:
            raise ValueError('missing service')

        signKey = sign_utils.generate_sign(self.app_key, self.issue_timestamp, self.salt)

        bufBody = io.BytesIO()

        app_id_bytes = self.app_id.encode('utf-8')
        bufBody.write(struct.pack('>I', len(app_id_bytes)))
        bufBody.write(app_id_bytes)
        bufBody.write(struct.pack('>I', self.issue_timestamp))
        bufBody.write(struct.pack('>I', self.salt))
        bufBody.write(struct.pack('>I', self.timestamp))

        bufBody.write(self.service.pack())

        if self.options is None:
            self.options = AppTokenOptions()
        bufBody.write(self.options.pack())

        # 按协议补齐参与 HMAC 的消息边界，签名与接收端使用相同的字节序列。
        bufBodyFixedLength = bytes_utils.get_fixed_length_bytes(bufBody.getvalue())
        signature = sign_utils.sign(signKey, bufBodyFixedLength)

        buf = io.BytesIO()
        buf.write(struct.pack('>I', len(signature)))
        buf.write(signature)
        buf.write(bufBodyFixedLength)

        bufFixedLength = bytes_utils.get_fixed_length_bytes(buf.getvalue())

        return "{}{}".format(VERSION_0, base64.b64encode(compress_utils.compress(bufFixedLength)).decode('utf-8'))

    @classmethod
    def parse(cls, token: str):
        if token is None:
            raise ValueError('empty appToken')

        if not token.startswith(VERSION_0):
            raise ValueError('unsupported version')

        data = compress_utils.decompress(base64.b64decode(token[VERSION_LENGTH:]))

        buf = io.BytesIO(data)

        signature_length = struct.unpack('>I', buf.read(4))[0]
        signature = buf.read(signature_length)

        app_id_length = struct.unpack('>I', buf.read(4))[0]
        app_id = buf.read(app_id_length).decode('utf-8')

        issue_timestamp = struct.unpack('>I', buf.read(4))[0]
        salt = struct.unpack('>I', buf.read(4))[0]
        timestamp = struct.unpack('>I', buf.read(4))[0]

        service = Service.unpack(buf)
        options = AppTokenOptions.unpack(buf)

        return AppToken(app_id, None, timestamp, issue_timestamp, salt, service, options, signature)

if __name__ == "__main__":
    # 在 RTC 控制台查看 appId（https://rtc.console.aliyun.com/#/manage/list）。
    app_id = "replace_your_appId"
    # 在 RTC 控制台查看 appKey。
    app_key = "replace_your_appKey"
    # 令牌有效期最长为 24 小时；示例设置为 12 小时，可按需调整。
    expired_ts = int(time.time()) + 12 * 60 * 60 
    channel_id = 'replace_your_channelId'
    user_id = 'replace_your_userId'

    appToken = AppToken(app_id, app_key, expired_ts)

    # 默认允许全部发布权限。示例展示如何分别控制音频、视频和屏幕共享。
    # 权限说明见 https://help.aliyun.com/document_detail/2689025.html 。

    # 示例 0：使用默认的全部发布权限。
    service = Service(channel_id, user_id)
    appToken.set_service(service)
    token = appToken.build()
    print(token)

    # 仅音频或视频场景按需调用 add_audio_publish_privilege / add_video_publish_privilege。
    # 附加选项由 AppTokenOptions 传入，凭据应仅返回给已获授权的参与者。
