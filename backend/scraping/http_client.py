import time

import httpx


DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=8.0)

RETRYABLE_STATUS_CODES = {
    408,
    429,
    500,
    502,
    503,
    504,
}


def get_with_retries(client: httpx.Client, url: str, attempts: int = 3, base_delay: float = 1.0, **kwargs) -> httpx.Response:
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            response = client.get(url, timeout=DEFAULT_TIMEOUT, **kwargs)
            response.raise_for_status()
            return response

        except httpx.HTTPStatusError as error:
            last_error = error

            if error.response.status_code not in RETRYABLE_STATUS_CODES:
                raise

        except httpx.TransportError as error:
            last_error = error

        if attempt == attempts:
            break

        delay = base_delay * (2 ** (attempt - 1))

        print(f"Request falló. Reintentando en {delay:.0f}s ({attempt}/{attempts}): {last_error}")

        time.sleep(delay)

    raise last_error