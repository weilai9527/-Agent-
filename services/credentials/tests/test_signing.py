"""使用临时生成的测试密钥，在内存中验证签发和验签。"""
import json
import os
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.credentials.signing import SigningConfigurationError, sign_payload, verify_payload


def keypair():
    private = Ed25519PrivateKey.generate()
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    private_pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ).decode()
    return public_pem, private_pem


class CredentialSigningTests(unittest.TestCase):
    def setUp(self):
        # 清除继承的环境变量，确保只使用本次测试生成的学校密钥。
        env = patch.dict(os.environ, clear=True)
        env.start()
        self.addCleanup(env.stop)
        pub1, priv1 = keypair()
        pub2, self.priv2 = keypair()
        pub_b, priv_b = keypair()
        self.trust = {"school-a": {"v1": pub1, "v2": pub2, "alias": pub1}, "school-b": {"v1": pub_b}}
        self.active = {
            "school-a": {"kid": "v1", "private_key": priv1},
            "school-b": {"kid": "v1", "private_key": priv_b},
        }
        self.configure()
        self.payload = {"school_id": "school-a", "evidence": "测试草稿", "version": 1}

    def configure(self):
        os.environ["CREDENTIALS_PUBLIC_KEYS_JSON"] = json.dumps(self.trust)
        os.environ["CREDENTIALS_SIGNING_KEYS_JSON"] = json.dumps(self.active)

    def test_verification_needs_only_public_keys_and_preserves_binding(self):
        kid, sig = sign_payload("school-a", self.payload)
        del os.environ["CREDENTIALS_SIGNING_KEYS_JSON"]
        self.assertTrue(verify_payload("school-a", dict(reversed(self.payload.items())), kid, sig))
        for school, payload, key, signature in [
            ("school-b", self.payload, kid, sig),
            ("school-b", dict(self.payload, school_id="school-b"), kid, sig),
            ("school-a", dict(self.payload, version=2), kid, sig),
            ("school-a", self.payload, "alias", sig),
            ("school-a", self.payload, "unknown", sig),
            ("school-a", self.payload, kid, "a" * 86),
            ("school-a", self.payload, kid, "!" * 86),
        ]:
            with self.subTest(school=school, key=key, payload=payload):
                self.assertFalse(verify_payload(school, payload, key, signature))

    def test_signer_rejects_claims_for_another_school_and_unknown_school(self):
        with self.assertRaises(ValueError):
            sign_payload("school-b", self.payload)
        with self.assertRaises(SigningConfigurationError):
            sign_payload("unknown", {"school_id": "unknown"})

    def test_rotation_and_key_removal(self):
        old = sign_payload("school-a", self.payload)
        self.active["school-a"] = {"kid": "v2", "private_key": self.priv2}
        self.configure()
        new = sign_payload("school-a", self.payload)
        self.assertNotEqual(old, new)
        self.assertTrue(verify_payload("school-a", self.payload, *old))
        self.assertTrue(verify_payload("school-a", self.payload, *new))
        del self.trust["school-a"]["v1"]
        self.configure()
        self.assertFalse(verify_payload("school-a", self.payload, *old))

    def test_misconfigured_or_missing_keys_fail_closed(self):
        self.active["school-a"]["private_key"] = self.priv2
        self.configure()
        with self.assertRaises(SigningConfigurationError):
            sign_payload("school-a", self.payload)
        os.environ["CREDENTIALS_SIGNING_KEYS_JSON"] = "invalid json"
        with self.assertRaises(SigningConfigurationError):
            sign_payload("school-a", self.payload)
        old = "A" * 86
        for bad_trust in ["invalid json", "[]", '{"school-a":{"v1":"bad PEM"}}']:
            with self.subTest(config=bad_trust):
                os.environ["CREDENTIALS_PUBLIC_KEYS_JSON"] = bad_trust
                with self.assertRaises(SigningConfigurationError):
                    verify_payload("school-a", self.payload, "v1", old)
