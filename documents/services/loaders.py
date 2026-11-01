import os
import re
from django.conf import settings
from django.core.exceptions import ValidationError

def validate_uploaded_file(file_obj):
    """
    Validates the uploaded file extension and size.
    Raises ValidationError with a friendly message if invalid.
    """
    # 1. Check filename and extension
    name = getattr(file_obj, 'name', '')
    if not name or '.' not in name:
        raise ValidationError("Invalid filename. Files must have a valid extension.")

    extension = name.rsplit('.', 1)[-1].lower().strip()
    allowed_extensions = settings.ALLOWED_FILE_EXTENSIONS

    if extension not in allowed_extensions:
        raise ValidationError(
            f"Unsupported file type '.{extension}'. Allowed types: {', '.join(allowed_extensions).upper()}"
        )

    # 2. Check file size
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file_obj.size > max_bytes:
        raise ValidationError(
            f"File '{name}' exceeds the maximum allowed size of {settings.MAX_UPLOAD_SIZE_MB} MB."
        )

    return extension

def sanitize_filename(filename: str) -> str:
    """
    Strips directory traversal characters and unsafe characters.
    """
    cleaned = os.path.basename(filename)
    cleaned = re.sub(r'[^a-zA-Z0-9_.-]', '_', cleaned)
    return cleaned or "unnamed_document"
