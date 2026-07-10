import os
import unittest
from unittest.mock import patch

from backend.src.main import QwenRealtimeTtsError, _qwen_realtime_webrtc_url


class QwenWebrtcUrlTests(unittest.TestCase):
    def build_url(self, region: str) -> str:
        with patch.dict(
            os.environ,
            {
                "QWEN_OMNI_REALTIME_WEBRTC_URL": "",
                "QWEN_OMNI_REALTIME_WEBRTC_ENDPOINT": "",
                "QWEN_OMNI_REALTIME_WORKSPACE_ID": "workspace-test",
                "QWEN_OMNI_REALTIME_REGION": region,
            },
            clear=False,
        ):
            return _qwen_realtime_webrtc_url("qwen-test-realtime")

    def test_builds_beijing_endpoint(self):
        self.assertEqual(
            self.build_url("beijing"),
            "https://workspace-test.cn-beijing.maas.aliyuncs.com/api/v1/webrtc/realtime?model=qwen-test-realtime",
        )

    def test_builds_singapore_endpoint(self):
        self.assertEqual(
            self.build_url("ap-southeast-1"),
            "https://workspace-test.ap-southeast-1.maas.aliyuncs.com/api/v1/webrtc/realtime?model=qwen-test-realtime",
        )

    def test_rejects_unknown_region(self):
        with self.assertRaises(QwenRealtimeTtsError):
            self.build_url("unknown-region")


if __name__ == "__main__":
    unittest.main()
