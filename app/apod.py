"""Normaliza el contrato antiguo y el nuevo de APOD sin insertar HTML remoto."""
from html.parser import HTMLParser
from urllib.parse import urlsplit


class _Content(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.video_url = ""

    def handle_data(self, data):
        self.text.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in ("iframe", "video", "source") and not self.video_url:
            self.video_url = dict(attrs).get("src", "")


def _plain_text(value):
    parser = _Content()
    parser.feed(str(value or ""))
    return " ".join(" ".join(parser.text).split())


def normalize_apod(data, requested_date=None):
    """Rechaza respuestas genéricas y separa publicación y recurso multimedia."""
    if not isinstance(data, dict):
        raise ValueError("APOD devolvió una estructura inesperada.")
    title = _plain_text(data.get("title"))
    if not title or title.lower() == "nasa science":
        raise ValueError("APOD devolvió la página genérica de NASA en lugar de la publicación.")
    if requested_date and data.get("date") != requested_date:
        raise ValueError("APOD devolvió una fecha diferente a la solicitada.")
    media_type = data.get("media_type", "image")
    source_url = data.get("permalink", "")
    if media_type == "image":
        # En WordPress, url es el artículo y hdurl es la imagen.
        media_url = (data.get("hdurl") or "") if source_url or data.get("post_id") else (data.get("url") or data.get("hdurl") or "")
    elif media_type in ("video", "iframe"):
        media_url = data.get("url", "")
        if source_url or data.get("post_id"):
            parser = _Content()
            parser.feed(data.get("basic_html") or "")
            media_url = parser.video_url
        media_type = "video"
    else:
        raise ValueError("APOD devolvió un tipo de contenido no compatible.")
    parsed = urlsplit(media_url)
    if parsed.scheme != "https" or not parsed.netloc or "nasa-logo" in parsed.path.lower():
        raise ValueError("APOD no incluye una URL multimedia válida.")
    return {
        "title": title, "date": data.get("date", ""),
        "explanation": _plain_text(data.get("explanation")),
        "url": media_url, "hdurl": data.get("hdurl") or media_url,
        "media_type": media_type, "source_url": source_url,
        "copyright": _plain_text(data.get("copyright") or data.get("credit") or "NASA"),
        "alt": _plain_text(data.get("alt") or title),
    }
