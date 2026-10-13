import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from telegram_alerts import TelegramError, _protect, call, connection, discover, save_connection, send_test, send_message


class TelegramConnectionTests(unittest.TestCase):
    def test_review_button_is_sent_without_broker_command_or_credentials(self):
        markup={'inline_keyboard':[[{'text':'Abrir señal y operar','url':'https://jj.example/?operar=AAPL'}]]}
        with patch.dict('os.environ',{'TELEGRAM_BOT_TOKEN':'123:test','TELEGRAM_CHAT_ID':'1'}), \
                patch('telegram_alerts.call',return_value={'message_id':1}) as api:
            send_message('AAPL',reply_markup=markup)
        self.assertEqual(api.call_args.kwargs['reply_markup'],markup)

    def test_secret_is_encrypted_and_test_uses_selected_chat(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "connection.json"
            token = "123456:private_secret"
            save_connection(token, "JJTradeBot", {"id": "456", "name": "Joan"}, path)
            self.assertNotIn(token, path.read_text())
            self.assertEqual(connection(path)["chat_id"], "456")
            with patch("telegram_alerts.call", return_value={"message_id": 1}) as api:
                send_test(path)
            self.assertEqual(api.call_args.args, (token, "sendMessage"))
            self.assertEqual(api.call_args.kwargs["chat_id"], "456")

    def test_discovery_excludes_groups_and_requires_user_selection(self):
        updates = [{"message": {"chat": {"id": 1, "type": "group"}}},
                   {"message": {"chat": {"id": 2, "type": "private", "first_name": "Joan"}}},
                   {"message": {"chat": {"id": 3, "type": "private", "first_name": "Other"}}}]
        with patch("telegram_alerts.call", side_effect=[{"username": "JJTradeBot"}, updates]):
            name, chats = discover("123:secret")
        self.assertEqual(name, "JJTradeBot")
        self.assertEqual([chat["id"] for chat in chats], ["2", "3"])

    def test_missing_start_explains_next_step(self):
        with patch("telegram_alerts.call", side_effect=[{"username": "JJTradeBot"}, []]):
            with self.assertRaisesRegex(TelegramError, "hola"):
                discover("123:secret")

    def test_network_error_does_not_reveal_token(self):
        token = "123:secret"
        with patch("telegram_alerts.urlopen", side_effect=URLError(token)):
            with self.assertRaises(TelegramError) as raised:
                call(token, "getMe")
        self.assertNotIn(token, str(raised.exception))

    def test_invalid_token_does_not_make_request(self):
        with patch("telegram_alerts.urlopen") as api:
            with self.assertRaises(TelegramError):
                call("not a token", "getMe")
        api.assert_not_called()

    def test_no_connection_cannot_send(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("telegram_alerts.call") as api:
                with self.assertRaises(TelegramError):
                    send_test(Path(directory) / "absent.json")
            api.assert_not_called()
