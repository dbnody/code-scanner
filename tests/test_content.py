import json
import unittest

from scanner.content import classify, extract_fields, format_row, render_copy, type_label


class ClassifyTest(unittest.TestCase):
    def test_detects_common_types(self):
        cases = {
            "https://example.com/a?x=1": "url",
            "www.example.com": "url",
            "WIFI:T:WPA;S:Home;P:12345678;;": "wifi",
            "BEGIN:VCARD\nVERSION:3.0\nFN:张三\nEND:VCARD": "vcard",
            "mailto:someone@example.com?subject=hi": "email",
            "someone@example.com": "email",
            "tel:+8613800000000": "phone",
            "SMSTO:10086:hello": "sms",
            "sms:+8613800000000?body=hi": "sms",
            "geo:39.9,116.4": "geo",
            "otpauth://totp/ACME:alice?secret=ABC": "otpauth",
            "(01)09501101530003(17)250101": "gs1",
            "010950110153000317250101": "gs1",
            "just some text": "text",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(classify(text), expected)
                self.assertTrue(type_label(expected))

    def test_fields_for_each_type(self):
        wifi = dict(extract_fields("WIFI:T:WPA;S:Home;P:12345678;H:false;;"))
        self.assertEqual(wifi["名称"], "Home")
        self.assertEqual(wifi["密码"], "12345678")

        url = dict(extract_fields("https://example.com/path?q=1&lang=zh"))
        self.assertEqual(url["协议"], "https")
        self.assertEqual(url["地址"], "example.com")
        self.assertEqual(url["路径"], "/path")
        self.assertEqual(url["q"], "1")

        tel = dict(extract_fields("tel:+8613800000000"))
        self.assertEqual(tel["号码"], "+8613800000000")

        sms = dict(extract_fields("SMSTO:10086:hello"))
        self.assertEqual(sms["号码"], "10086")
        self.assertEqual(sms["内容"], "hello")

        geo = dict(extract_fields("geo:39.9,116.4"))
        self.assertEqual(geo["纬度"], "39.9")
        self.assertEqual(geo["经度"], "116.4")

        otp = dict(extract_fields("otpauth://totp/ACME:alice?secret=ABC&digits=6&period=30"))
        self.assertEqual(otp["类型"], "TOTP")
        self.assertEqual(otp["发行方"], "ACME")
        self.assertEqual(otp["账户"], "alice")
        self.assertEqual(otp["密钥"], "ABC")

        gs1 = dict(extract_fields("(01)09501101530003(17)250101"))
        self.assertEqual(gs1["GTIN"], "09501101530003")
        self.assertEqual(gs1["有效期"], "250101")

        card = dict(extract_fields("BEGIN:VCARD\nVERSION:3.0\nFN:张三\nORG:示例公司\nTEL:123456\nEND:VCARD"))
        self.assertEqual(card["姓名"], "张三")
        self.assertEqual(card["公司"], "示例公司")

        mail = dict(extract_fields("mailto:a@b.com?subject=hi&body=body"))
        self.assertEqual(mail["收件人"], "a@b.com")
        self.assertEqual(mail["主题"], "hi")

    def test_unknown_text_falls_back_to_content(self):
        self.assertEqual(extract_fields("hello"), [("内容", "hello")])


class TemplateTest(unittest.TestCase):
    row = {
        "time": "10:00:00",
        "source": "a.png",
        "type": "WiFi",
        "format": "QRCode",
        "text": "WIFI:T:WPA;S:Home;P:1234;;",
        "fields": [("名称", "Home"), ("密码", "1234")],
    }

    def test_plain_and_source_templates(self):
        self.assertEqual(render_copy([self.row], "仅内容"), self.row["text"])
        self.assertEqual(render_copy([self.row], "内容+来源"), f"a.png: {self.row['text']}")

    def test_tsv_template_has_all_columns(self):
        line = render_copy([self.row], "TSV")
        self.assertEqual(line.split("\t"), ["10:00:00", "a.png", "WiFi", "QRCode", self.row["text"]])

    def test_json_template_is_valid_json(self):
        data = json.loads(render_copy([self.row], "JSON"))
        self.assertEqual(data[0]["source"], "a.png")
        self.assertEqual(data[0]["fields"]["名称"], "Home")

    def test_custom_template_uses_fields_and_ignores_unknown(self):
        template = "{text} / {名称} / 缺失{missing}"
        self.assertEqual(format_row(self.row, template), f"{self.row['text']} / Home / 缺失")

    def test_bad_template_falls_back_to_text(self):
        self.assertEqual(format_row(self.row, "{text"), self.row["text"])


if __name__ == "__main__":
    unittest.main()
