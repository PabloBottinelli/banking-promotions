import os

import httpx
from dotenv import load_dotenv


load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]


def get_headers() -> dict[str, str]:
    return {
        "apikey": SUPABASE_SECRET_KEY,
        "Content-Type": "application/json",
    }


def check_connection() -> int:
    response = httpx.get(
        f"{SUPABASE_URL}/rest/v1/promotions",
        headers=get_headers(),
        params={"select": "id", "limit": "1"},
        timeout=10.0,
    )

    response.raise_for_status()

    return response.status_code