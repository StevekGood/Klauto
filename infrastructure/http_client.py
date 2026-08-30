import hashlib
import json
import os
import time
import zlib
import gzip
from typing import Dict, List, Optional, Any

import requests

from core.ports import GameClientPort, LoggerPort
from infrastructure.logger import get_logger


class KlondikeGameClient(GameClientPort):
    """Low‑level HTTP client for Klondike game."""

    def __init__(self, user_id: str, auth_key: str, vk_metadata: Optional[Dict] = None, logger: LoggerPort = None):
        self.user_id = user_id
        self.auth_key = auth_key
        self.logger = logger or get_logger()

        self.url_auth = "https://klone-vk-4.k8s-release-ru.gametech-app.ru/klonevk/auth"
        self.url_game = "https://klone-vk-4.k8s-release-ru.gametech-app.ru/klonevk/game"
        self.current_seq_id = int(time.time()) - 1700000000
        self.start_bot_time = time.time()
        self.session_key = None

        vk_metadata = vk_metadata or {
            "bdate": os.environ.get("VK_USER_BD"),
            "sex": os.environ.get("VK_USER_SEX"),
            "first_name": os.environ.get("VK_USER_FIRST_NAME"),
            "last_name": os.environ.get("VK_USER_LAST_NAME"),
        }
        self.vk_info = {
            "id": int(user_id),
            "bdate": vk_metadata.get("bdate", "14.11.1987"),
            "sex": int(vk_metadata.get("sex", 2)),
            "first_name": vk_metadata.get("first_name", "VK"),
            "last_name": vk_metadata.get("last_name", "Account"),
            "uid": int(user_id),
            "bpc": f"bpc.{user_id}",
            "device_os": "Windows 10",
            "is_mobile": False,
            "engine": "gl",
            "browser_name": "Chrome",
            "browser_version": "151",
            "dpi": 1.25,
            "orientation": "desktop",
            "compressions": {"webp": True, "bptc": True, "astc": False, "s3tc": True}
        }

    def _md5(self, s: str) -> str:
        return hashlib.md5(s.encode('utf-8')).hexdigest()

    def _salt(self, s: str) -> str:
        return str(len(s)) + self._md5(s + "stufff...")

    def _decode_response(self, response: requests.Response) -> Dict:
        text_data = ""
        try:
            text_data = zlib.decompress(response.content, zlib.MAX_WBITS).decode('utf-8', errors='replace')
        except Exception:
            try:
                text_data = gzip.decompress(response.content).decode('utf-8', errors='replace')
            except Exception:
                text_data = response.text

        if not text_data.strip():
            return {"error": "empty_payload"}

        json_start = text_data.find('{')
        if json_start != -1:
            text_data = text_data[json_start:]
        else:
            return {"server_message": text_data.strip()}

        try:
            return json.loads(text_data)
        except json.JSONDecodeError:
            return {"raw_text": text_data}

    def is_error_response(self, response: Dict) -> bool:
        """Return True if response indicates an error or maintenance."""
        if response.get("cmd") == "ERR":
            return True
        if response.get("status") == "maintenance":
            return True
        # Possibly other error indicators
        if "error" in response:
            return True
        return False

    def login(self) -> Dict:
        self.current_seq_id += 1
        i_str = f"{self.current_seq_id}{self.auth_key}"
        auth_hash = self._md5(i_str + self._salt(i_str))

        time_packet = {
            "type": "TIME",
            "clientVersion": 0,
            "id": self.current_seq_id,
            "pluginVersion": "Mozilla/5.0",
            "user": self.user_id,
            "auth": auth_hash
        }
        g_json = json.dumps(time_packet, separators=(',', ':'))
        payload = {"data": g_json, "crc": self._md5(g_json + self._salt(g_json))}

        self.logger.log_truncated("HTTPClient", "sending_TIME", user=self.user_id)
        self.logger.log_full("HTTPClient", "TIME_payload", payload=time_packet)

        res = requests.post(self.url_auth, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
        res_data = self._decode_response(res)

        self.logger.log_truncated("HTTPClient", "received_TIME_response", user=self.user_id)
        self.logger.log_full("HTTPClient", "TIME_response", payload=res_data)
        if self.is_error_response(res_data):
            self.logger.log_full("HTTPClient", "login_error_response", payload=res_data)

        if res_data.get("cmd") == "REDIRECT" and "redirect" in res_data:
            new_base = res_data["redirect"]
            self.url_auth = f"{new_base}/auth"
            self.url_game = f"{new_base}/game"
            return self.login()

        self.session_key = res_data.get("key")
        server_time = res_data.get("time")
        if not self.session_key or not server_time:
            return {"error": "handshake_time_failed", "details": res_data}

        self.current_seq_id = int(server_time)
        t_str = f"{self.session_key}{self.current_seq_id}{self.auth_key}"
        sig_hash = self._md5(t_str + self._salt(t_str))

        start_packet = {
            "type": "START",
            "clientTime": 6101,
            "serverTime": self.current_seq_id,
            "lang": "ru",
            "info": self.vk_info,
            "ad": "unknown",
            "id": self.current_seq_id,
            "user": self.user_id,
            "sig": sig_hash
        }
        g_json = json.dumps(start_packet, separators=(',', ':'))
        payload = {"data": g_json, "crc": self._md5(g_json + self._salt(g_json)), "gz": "y"}

        self.logger.log_truncated("HTTPClient", "sending_START", user=self.user_id)
        self.logger.log_full("HTTPClient", "START_payload", payload=start_packet)

        res = requests.post(self.url_auth, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
        profile = self._decode_response(res)

        self.logger.log_truncated("HTTPClient", "received_START_response", user=self.user_id)
        self.logger.log_full("HTTPClient", "START_response", payload=profile)
        return profile

    def execute_raw_action(self, events: List[Dict]) -> Dict:
        if not self.session_key:
            self.logger.log_truncated("HTTPClient", "session_missing_auto_login", user=self.user_id)
            login_res = self.login()
            if "error" in login_res:
                return login_res

        self.current_seq_id += 1
        elapsed_ms = int((time.time() - self.start_bot_time) * 1000)
        t_str = f"{self.session_key}{self.current_seq_id}{self.auth_key}"
        sig = self._md5(t_str + self._salt(t_str))

        action_packet = {
            "type": "EVT",
            "events": events,
            "time": 6500 + elapsed_ms,
            "id": self.current_seq_id,
            "user": self.user_id,
            "sig": sig
        }
        g_json = json.dumps(action_packet, separators=(',', ':'))
        payload = {"data": g_json, "crc": self._md5(g_json + self._salt(g_json)), "gz": "y"}

        self.logger.log_truncated("HTTPClient", "sending_events", user=self.user_id, count=len(events))
        self.logger.log_full("HTTPClient", "events_payload", payload=action_packet)

        res = requests.post(self.url_game, data=payload, headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/x-www-form-urlencoded"
        })
        response = self._decode_response(res)

        self.logger.log_truncated("HTTPClient", "received_events_response", user=self.user_id)
        self.logger.log_full("HTTPClient", "events_response", payload=response)
        if self.is_error_response(response):
            self.logger.log_full("HTTPClient", "action_error_response", payload=response)
        
        return response