import hashlib
import json
import time
import requests
import zlib
import sys
import os
import logging
from logging.handlers import RotatingFileHandler

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

class KlondikeGameClient:
    def __init__(self, user_id: str | None = None, auth_key: str | None = None, vk_metadata: dict | None = None):
        self.user_id = user_id or os.environ.get("KLONDIKE_USER_ID")
        self.auth_key = auth_key or os.environ.get("KLONDIKE_AUTH_KEY")

        if not self.auth_key:
            print("[Client FATAL]: Auth key missing. Please set KLONDIKE_AUTH_KEY variable.")
        
        # Base router settings (K8s proxies)
        self.url_auth = "https://klone-vk-4.k8s-release-ru.gametech-app.ru/klonevk/auth"
        self.url_game = "https://klone-vk-4.k8s-release-ru.gametech-app.ru/klonevk/game"
        
        # Microservice sequence counters
        self.current_seq_id = int(time.time()) - 1700000000 
        self.start_bot_time = time.time()
        self.session_key = None

        self.log_file = "client_network.log"
        self.logger = logging.getLogger("KlondikeClientLogger")
        self.logger.setLevel(logging.INFO)

        if self.logger.hasHandlers():
            self.logger.handlers.clear()
            
        handler = RotatingFileHandler(self.log_file, maxBytes=10 * 1024 * 1024, backupCount=2, encoding="utf-8")
        formatter = logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.logger.info("=== NEW ARCHITECTURE CLIENT RUNTIME SESSION STARTED ===")

        vk_metadata = vk_metadata or {
            "bdate": os.environ.get("VK_USER_BD"),
            "sex": os.environ.get("VK_USER_SEX"),
            "first_name": os.environ.get("VK_USER_FIRST_NAME"),
            "last_name": os.environ.get("VK_USER_LAST_NAME"),
        }
        self.vk_info = {
            "id": int(self.user_id),
            "bdate": vk_metadata.get("bdate", "14.11.1987"),
            "sex": int(vk_metadata.get("sex", 2)),
            "first_name": vk_metadata.get("first_name", "VK"),
            "last_name": vk_metadata.get("last_name", "Account"),
            "uid": int(self.user_id),
            "bpc": f"bpc.{self.user_id}",
            "device_os": "Windows 10",
            "is_mobile": False,
            "engine": "gl",
            "browser_name": "Chrome",
            "browser_version": "151",
            "dpi": 1.25,
            "orientation": "desktop",
            "compressions": {"webp": True, "bptc": True, "astc": False, "s3tc": True}
        }

    def _log_to_file(self, tag: str, message: str, payload: dict = None):
        """Writes thread-safe entries directly managed by the rotating file supervisor."""
        log_entry = f"[{tag}] {message}"
        if payload is not None:
            truncated_json = json.dumps(payload, ensure_ascii=False, indent=2)
            if len(truncated_json) > 10000:
                log_entry += f"\n--- Data Blueprint (Truncated {len(truncated_json)} bytes for size efficiency) ---\n{truncated_json[:2000]}\n... [MAPPING TRUNCATED TO PROTECT DISK SPACE] ...\n"
            else:
                log_entry += f"\n--- Data Blueprint ---\n{truncated_json}\n----------------------"
        self.logger.info(log_entry)

    def _get_md5(self, string_data: str) -> str:
        return hashlib.md5(string_data.encode('utf-8')).hexdigest()

    def _salt_func(self, e: str) -> str:
        return str(len(e)) + self._get_md5(e + "stufff...")

    def _decode_response(self, response: requests.Response) -> dict:
        text_data = ""
        try:
            decompressed = zlib.decompress(response.content, zlib.MAX_WBITS)
            text_data = decompressed.decode('utf-8', errors='replace')
        except Exception:
            try:
                import gzip
                decompressed = gzip.decompress(response.content)
                text_data = decompressed.decode('utf-8', errors='replace')
            except Exception:
                text_data = response.text

        if not text_data or text_data.strip() == "":
            self._log_to_file("DECODE_ERROR", f"Received completely empty byte buffer from target server endpoint.")
            return {"error": "empty_payload"}

        json_start = text_data.find('{')
        if json_start != -1:
            text_data = text_data[json_start:]
        else:
            self._log_to_file("DECODE_WARNING", f"Response contains non-JSON content string: {text_data.strip()}")
            return {"server_message": text_data.strip()}
            
        try:
            parsed_json = json.loads(text_data)
            return parsed_json
        except json.JSONDecodeError:
            self._log_to_file("JSON_PARSE_ERROR", f"Failed to structure raw text stream into objects map.", {"raw_text_stream": text_data[:1000]})
            return {"raw_text": text_data}

    def login(self) -> dict:
        """Executes full handshake lifecycle (TIME + START) and returns the profile state."""
        # Step 1: TIME sync
        self.current_seq_id += 1
        i_str = str(self.current_seq_id) + self.auth_key
        auth_hash = self._get_md5(i_str + self._salt_func(i_str))
        
        time_packet = {
            "type": "TIME", "clientVersion": 0, "id": self.current_seq_id,
            "pluginVersion": "Mozilla/5.0", "user": self.user_id, "auth": auth_hash
        }
        g_json = json.dumps(time_packet, separators=(',', ':'))
        payload = {"data": g_json, "crc": self._get_md5(g_json + self._salt_func(g_json))}
        
        self._log_to_file("REQ_TIME", f"Posting handshake phase 1 (TIME) initialization to URL: {self.url_auth}", time_packet)
        print(f"[Client]: Posting TIME payload handshake parameters (ID: {self.current_seq_id})...")
        
        res = requests.post(self.url_auth, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
        res_data = self._decode_response(res)
        
        self._log_to_file("RES_TIME", "Received payload resolution map from endpoint routing interface.", res_data)
        
        # Dynamic K8s Server Redirect balancing routing
        if res_data.get("cmd") == "REDIRECT" and "redirect" in res_data:
            new_base_url = res_data["redirect"]
            self._log_to_file("REDIRECT_TRIGGERED", f"Cluster router initiated balancing redirection path -> {new_base_url}")
            self.url_auth = f"{new_base_url}/auth"
            self.url_game = f"{new_base_url}/game"
            return self.login()

        self.session_key = res_data.get("key")
        server_time = res_data.get("time")
        
        if not self.session_key or not server_time:
            self._log_to_file("HANDSHAKE_FATAL", "Unable to extract active runtime validation session keys.", res_data)
            return {"error": "handshake_time_failed", "details": res_data}
            
        # Step 2: START session activation
        self.current_seq_id = int(server_time)
        t_str = self.session_key + str(self.current_seq_id) + self.auth_key
        sig_hash = self._get_md5(t_str + self._salt_func(t_str))
        
        start_packet = {
            "type": "START", "clientTime": 6101, "serverTime": self.current_seq_id,
            "lang": "ru", "info": self.vk_info, "ad": "unknown",
            "id": self.current_seq_id, "user": self.user_id, "sig": sig_hash
        }
        g_json = json.dumps(start_packet, separators=(',', ':'))
        payload = {"data": g_json, "crc": self._get_md5(g_json + self._salt_func(g_json)), "gz": "y"}
        
        self._log_to_file("REQ_START", f"Posting handshake phase 2 (START) session initialization to URL: {self.url_auth}", start_packet)
        print(f"[Client]: Posting START payload profile sync data (ID: {self.current_seq_id})...")
        
        res = requests.post(self.url_auth, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
        final_profile_state = self._decode_response(res)
        
        self._log_to_file("RES_START", "Received root game profile snapshot mapping initialization packet.", final_profile_state)
        return final_profile_state

    def execute_raw_action(self, events: list) -> dict:
        """Signs and posts an array of raw low-level execution events to the /game pipeline."""
        if not self.session_key:
            self._log_to_file("SESSION_MISSING", "Client transaction ordered before authentication lifecycle. Auto-logging in...")
            login_res = self.login()
            if "error" in login_res:
                return login_res
                
        self.current_seq_id += 1
        elapsed_ms = int((time.time() - self.start_bot_time) * 1000)
        
        t_str = self.session_key + str(self.current_seq_id) + self.auth_key
        sig = self._get_md5(t_str + self._salt_func(t_str))
        
        action_packet = {
            "type": "EVT", "events": events, "time": 6500 + elapsed_ms,
            "id": self.current_seq_id, "user": self.user_id, "sig": sig
        }
        g_json = json.dumps(action_packet, separators=(',', ':'))
        payload = {"data": g_json, "crc": self._get_md5(g_json + self._salt_func(g_json)), "gz": "y"}
        
        self._log_to_file("REQ_GAME_ACTION", f"Posting interactive operational macro commands batch to URL: {self.url_game}", action_packet)
        print(f"[Client]: Posting game transaction block containing {len(events)} operational rows (ID: {self.current_seq_id})...")
        
        res = requests.post(self.url_game, data=payload, headers={
            "User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded"
        })
        action_response = self._decode_response(res)
        
        self._log_to_file("RES_GAME_ACTION", "Received confirmation execution transaction map log row from data nodes.", action_response)
        return action_response
