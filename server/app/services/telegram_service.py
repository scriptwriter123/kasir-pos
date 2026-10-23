from httpx import AsyncClient

from server.app.config import settings


class TelegramService:
    def __init__(self):
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.base_url = settings.telegram_api_base

    def is_enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def _headers(self) -> dict:
        return {"Content-Type": "application/json"}

    def _api_url(self, method: str) -> str:
        return f"{self.base_url}/{method}"

    async def send_message(self, chat_id: str | None = None, text: str = "", parse_mode: str | None = None) -> dict:
        if not self.token:
            return {"ok": False, "error": "Telegram bot token not configured"}
        target_chat_id = chat_id or self.chat_id
        if not target_chat_id:
            return {"ok": False, "error": "Chat ID not configured"}
        payload = {
            "chat_id": target_chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if not parse_mode:
            del payload["parse_mode"]
        async with AsyncClient(timeout=10) as client:
            response = await client.post(self._api_url("sendMessage"), json=payload, headers=self._headers())
            return response.json()

    async def send_notification(self, message: str, chat_id: str | None = None) -> dict:
        return await self.send_message(chat_id=chat_id, text=message, parse_mode="HTML")

    async def get_updates(self, offset: int | None = None) -> list[dict]:
        if not self.token:
            return []
        params = {"limit": 100, "timeout": 0}
        if offset is not None:
            params["offset"] = offset
        async with AsyncClient(timeout=10) as client:
            response = await client.get(self._api_url("getUpdates"), params=params)
            return response.json().get("result", [])

    async def set_webhook(self, url: str) -> dict:
        if not self.token:
            return {"ok": False, "error": "Telegram bot token not configured"}
        async with AsyncClient(timeout=10) as client:
            response = await client.get(
                self._api_url("setWebhook"), params={"url": url}
            )
            return response.json()

    async def delete_webhook(self) -> dict:
        if not self.token:
            return {"ok": False, "error": "Telegram bot token not configured"}
        async with AsyncClient(timeout=10) as client:
            response = await client.get(self._api_url("deleteWebhook"))
            return response.json()

    async def get_me(self) -> dict:
        if not self.token:
            return {"ok": False, "error": "Telegram bot token not configured"}
        async with AsyncClient(timeout=10) as client:
            response = await client.get(self._api_url("getMe"))
            return response.json()

    async def set_my_commands(self) -> dict:
        if not self.token:
            return {"ok": False, "error": "Telegram bot token not configured"}
        async with AsyncClient(timeout=10) as client:
            response = await client.post(
                self._api_url("setMyCommands"), json=self._commands_payload()
            )
            return response.json()

    def _commands_payload(self) -> list[dict]:
        return [
            {"command": "start", "description": "Mulai bot & lihat bantuan"},
            {"command": "status", "description": "Cek status langganan Anda"},
        ]
