"""Telegram media classification, metadata extraction, and naming utilities."""

import mimetypes

from telethon import utils
from telethon.tl import types

from tg_downloader.utils.filename import sanitize_filename


def get_media_type(message: types.Message) -> str | None:
    """Identify the specific media classification for a Telegram message.

    Returns: 'photo', 'video', 'document', 'audio', 'voice', 'animation', 'sticker', or None.
    """
    if not message or not message.media:
        return None

    media = message.media

    if isinstance(media, types.MessageMediaPhoto):
        return "photo"

    if isinstance(media, types.MessageMediaDocument):
        doc = media.document
        if not isinstance(doc, types.Document):
            return None

        # Check attributes
        is_animated = False
        is_video = False
        is_voice = False
        is_audio = False
        is_sticker = False

        for attr in doc.attributes:
            if isinstance(attr, types.DocumentAttributeAnimated):
                is_animated = True
            elif isinstance(attr, types.DocumentAttributeVideo):
                is_video = True
            elif isinstance(attr, types.DocumentAttributeAudio):
                if attr.voice:
                    is_voice = True
                else:
                    is_audio = True
            elif isinstance(attr, types.DocumentAttributeSticker):
                is_sticker = True

        is_pdf = bool(doc.mime_type and "pdf" in doc.mime_type.lower())
        for attr in doc.attributes:
            if isinstance(
                attr, types.DocumentAttributeFilename
            ) and attr.file_name.lower().endswith(".pdf"):
                is_pdf = True

        if is_sticker:
            return "sticker"
        if is_animated:
            return "animation"
        if is_voice:
            return "voice"
        if is_audio:
            return "audio"
        if is_video or (doc.mime_type and doc.mime_type.startswith("video/")):
            return "video"
        if is_pdf:
            return "pdf"

        return "document"

    return None


def is_media_match(
    message: types.Message,
    media_types: set[str] | None = None,
    extensions: set[str] | None = None,
) -> bool:
    """Check if message media satisfies media type and extension filters."""
    if not message or not message.media:
        return False

    m_type = get_media_type(message)
    if not m_type:
        return False

    filename = get_media_filename(message)
    dot_idx = filename.rfind(".")
    ext = filename[dot_idx + 1 :].lower() if dot_idx != -1 else ""

    # Check extension filter
    if extensions:
        clean_exts = {e.lstrip(".").lower() for e in extensions}
        if ext not in clean_exts:
            return False

    # Check media type filter
    if media_types and "all" not in media_types:
        clean_types = {t.lower() for t in media_types}
        # If user asked for document, PDF also qualifies as a document
        if m_type == "pdf" and "document" in clean_types:
            return True
        if m_type not in clean_types:
            return False

    return True


def get_media_size(message: types.Message) -> int:
    """Extract total byte size of the media within a message."""
    if not message or not message.media:
        return 0

    media = message.media
    if isinstance(media, types.MessageMediaDocument):
        doc = media.document
        if isinstance(doc, types.Document):
            return doc.size
    elif isinstance(media, types.MessageMediaPhoto):
        photo = media.photo
        if isinstance(photo, types.Photo) and photo.sizes:
            # Largest size
            largest = photo.sizes[-1]
            size = utils._photo_size_byte_count(largest)
            return size or 0

    return 0


def get_media_mime_type(message: types.Message) -> str:
    """Extract MIME type for the media in a message."""
    if not message or not message.media:
        return "application/octet-stream"

    media = message.media
    if isinstance(media, types.MessageMediaDocument):
        doc = media.document
        if isinstance(doc, types.Document) and doc.mime_type:
            return doc.mime_type
    elif isinstance(media, types.MessageMediaPhoto):
        return "image/jpeg"

    return "application/octet-stream"


def get_media_filename(message: types.Message, chat_prefix: str = "") -> str:
    """Determine a safe, descriptive filename for the media in a message."""
    media_type = get_media_type(message) or "media"
    mime = get_media_mime_type(message)
    default_ext = mimetypes.guess_extension(mime) or ""
    if default_ext == ".jpe":
        default_ext = ".jpg"

    prefix = f"{chat_prefix}_" if chat_prefix else ""
    synthetic_name = f"{prefix}msg_{message.id}_{media_type}{default_ext}"

    if not message or not message.media:
        return sanitize_filename(synthetic_name)

    media = message.media
    if isinstance(media, types.MessageMediaDocument):
        doc = media.document
        if isinstance(doc, types.Document):
            # Check for explicit filename attribute
            for attr in doc.attributes:
                if isinstance(attr, types.DocumentAttributeFilename) and attr.file_name:
                    return sanitize_filename(attr.file_name)

            # Check audio title/performer
            for attr in doc.attributes:
                if isinstance(attr, types.DocumentAttributeAudio):
                    performer = attr.performer or ""
                    title = attr.title or ""
                    if performer and title:
                        return sanitize_filename(f"{performer} - {title}{default_ext}")
                    if title:
                        return sanitize_filename(f"{title}{default_ext}")

    elif isinstance(media, types.MessageMediaPhoto):
        return sanitize_filename(f"{prefix}msg_{message.id}_photo.jpg")

    return sanitize_filename(synthetic_name)
