from typing import Optional

import requests

_MANGADEX_COLOR = 0xFF6740  # MangaDex brand orange


def send_notification(webhook_url: str, title: str, message: str) -> None:
    """POST a plain-text message to a Discord channel via incoming webhook. Fails silently."""
    try:
        requests.post(
            webhook_url,
            json={"content": f"**{title}**\n{message}"},
            timeout=10,
        ).raise_for_status()
    except Exception as e:
        print(f"[discord] Failed to send notification: {e}")


def send_embed(
    webhook_url: str,
    title: str,
    title_url: str,
    description: str,
    thumbnail_url: Optional[str] = None,
) -> None:
    """
    POST a rich embed to a Discord channel via incoming webhook. Fails silently.

    The embed title is a clickable link (title_url). Description supports
    Discord markdown, including [text](url) hyperlinks for individual lines.
    thumbnail_url renders the manga cover as a small image on the right side.
    """
    embed = {
        "title": title,
        "url": title_url,
        "description": description,
        "color": _MANGADEX_COLOR,
    }
    if thumbnail_url:
        embed["thumbnail"] = {"url": thumbnail_url}

    try:
        requests.post(
            webhook_url,
            json={"embeds": [embed]},
            timeout=10,
        ).raise_for_status()
    except Exception as e:
        print(f"[discord] Failed to send embed: {e}")
