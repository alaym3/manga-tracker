import requests


def send_notification(webhook_url: str, title: str, message: str) -> None:
    """POST a message to a Discord channel via incoming webhook. Fails silently."""
    try:
        requests.post(
            webhook_url,
            json={"content": f"**{title}**\n{message}"},
            timeout=10,
        ).raise_for_status()
    except Exception as e:
        print(f"[discord] Failed to send notification: {e}")
