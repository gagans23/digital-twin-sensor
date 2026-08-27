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


if __name__ == "__main__":
    unittest.main()
