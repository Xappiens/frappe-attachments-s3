# frappe_s3_attachment/patches/file_get_content.py

import frappe
import mimetypes
from frappe.core.doctype.file.file import File
from frappe_s3_attachment.controller import S3Operations

# Guardamos referencia a la implementación original
_original_get_content = File.get_content

def patched_get_content(self):
    """
    Si tiene content_hash: descargar de S3.
    En otro caso: caer en el get_content original (local).
    """
    # 1) Si no hay content_hash, delegamos
    if not getattr(self, "content_hash", None):
        return _original_get_content(self)

    s3op = S3Operations()
    try:
        obj = s3op.read_file_from_s3(self.content_hash)
        data = obj["Body"].read()
        return data

    except Exception as e:
        # Si por alguna razón falla en S3,
        # intentamos caer en la versión local
        return _original_get_content(self)

# Hacemos el override global
File.get_content = patched_get_content
