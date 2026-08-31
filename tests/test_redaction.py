import unittest

from digital_twin_sensor.redaction import redact_text


class RedactionTests(unittest.TestCase):
    def test_masks_common_pii_and_secrets(self):
        config = {
            "mask_pii": True,
            "mask_configured_names": True,
            "mask_ip_addresses": True,
            "redact_url_paths": True,
            "name_terms_to_mask": ["Gagan", "Acme Client"],
        }
        text = (
            "Gagan emailed Acme Client at test@example.com from 192.168.1.8. "
            "Card 4111 1111 1111 1111, SSN 123-45-6789, phone +1 415-555-1212. "
            "See https://example.com/private/Gagan?token=abc and sk-abcdefghijklmnop1234"
        )

        result = redact_text(text, config)

        self.assertNotIn("Gagan", result.text)
        self.assertNotIn("test@example.com", result.text)
        self.assertNotIn("4111 1111 1111 1111", result.text)
        self.assertNotIn("123-45-6789", result.text)
        self.assertNotIn("415-555-1212", result.text)
        self.assertNotIn("192.168.1.8", result.text)
        self.assertNotIn("token=abc", result.text)
        self.assertNotIn("sk-abcdefghijklmnop1234", result.text)
        self.assertIn("[credit-card]", result.text)
        self.assertEqual(result.findings["credit_card"], 1)
        self.assertEqual(result.findings["email"], 1)
        self.assertEqual(result.findings["name"], 2)

    def test_does_not_mask_invalid_card_like_number_as_card(self):
        result = redact_text("reference 4111 1111 1111 1112", {"mask_pii": True})
        self.assertNotIn("[credit-card]", result.text)


class EvasionRegressionTests(unittest.TestCase):
    """Named regressions for the two leaks the property tests found.

    Both had been live since the first commit and both passed the golden set,
    which only ever planted well-formed values standing on their own.
    """

    def test_neighbouring_digit_does_not_hide_a_card(self):
        # The greedy candidate used to swallow the "3", fail Luhn as a unit,
        # and hand the whole card back unmasked.
        result = redact_text("Invoice 3 4111 1111 1111 1111", {"mask_pii": True})
        self.assertNotIn("4111 1111 1111 1111", result.text)
        self.assertIn("[credit-card]", result.text)
        self.assertIn("Invoice 3", result.text)

    def test_fifteen_digit_card_after_a_stray_digit(self):
        result = redact_text("draft 3 378282246310005 review", {"mask_pii": True})
        self.assertNotIn("378282246310005", result.text)
        self.assertIn("[credit-card]", result.text)

    def test_grouped_amex_is_masked(self):
        result = redact_text("amex 3782 822463 10005", {"mask_pii": True})
        self.assertIn("[credit-card]", result.text)

    def test_token_with_mixed_separators_is_masked(self):
        # Character classes were narrower than the token shapes in the wild.
        for token in (
            "xoxb-qzi16rvyqwe_6l2f-dhrhfl-o1234",
            "ghp_xa8d-c0br9agh5sisg-46e_h86d7",
        ):
            with self.subTest(token=token):
                result = redact_text(f"branch {token} pushed", {"mask_pii": True})
                self.assertNotIn(token, result.text)

    def test_ordinary_numbers_are_still_left_alone(self):
        for text in ("build 7 of 9 today", "reference 4111 1111 1111 1112", "sprint/42 ticket 118"):
            with self.subTest(text=text):
                self.assertEqual(redact_text(text, {"mask_pii": True}).text, text)


if __name__ == "__main__":
    unittest.main()
