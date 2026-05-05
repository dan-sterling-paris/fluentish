import base64
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

CLICKSEND_BASE = "https://rest.clicksend.com/v3"


def _auth_header() -> dict:
    token = base64.b64encode(
        f"{settings.clicksend_username}:{settings.clicksend_api_key}".encode()
    ).decode()
    return {"Authorization": f"Basic {token}"}


async def send_sms(phone: str, body: str) -> dict:
    """
    Send an SMS via ClickSend. Phone must be in E.164 format.
    Raises httpx.HTTPStatusError on 4xx/5xx responses.
    """
    payload = {
        "messages": [
            {
                "source": "sdk",
                "from": settings.clicksend_from,
                "to": phone,
                "body": body,
            }
        ]
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{CLICKSEND_BASE}/sms/send",
            json=payload,
            headers=_auth_header(),
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info("ClickSend response: %s", data)
        return data
