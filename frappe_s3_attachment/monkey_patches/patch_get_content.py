# frappe_s3_attachment/patches/file_patches.py

import os
import frappe
import errno
from botocore.exceptions import ClientError
from frappe.core.doctype.file.file import File as CoreFile
from frappe_s3_attachment.controller import S3Operations
from frappe.utils import get_site_path

# -----------------------------------------
# Parche único para File: lectura y validación
# -----------------------------------------

# Guardamos métodos originales
_original_get_content = CoreFile.get_content



def patched_get_content(self):
    """
    1) Si file_url apunta a /files o /private/files, intenta leer local.
    2) Luego, si falla y hay content_hash, intenta S3.
    3) Fallback al get_content original.
    4) Si todo falla, devuelve b''.
    Siempre asigna self._content.
    """
    data = None

    # 1) Leer local
    local_url = (self.file_url or "").lstrip("/")
    if local_url.startswith("files") or local_url.startswith("private/files"):
        site_path = get_site_path()
        file_path = os.path.join(site_path, local_url)
        if os.path.exists(file_path):
            try:
                with open(file_path, "rb") as f:
                    data = f.read()
            except Exception:
                data = None

    # 2) Leer S3
    if data is None and getattr(self, "content_hash", None):
        try:
            s3op = S3Operations()
            obj = s3op.read_file_from_s3(self.content_hash)
            data = obj["Body"].read()
        except Exception:
            # Logueamos pero no rompemos
            frappe.log_error(f"S3 read failed for key {self.content_hash}", "frappe_s3_attachment")
            data = None

    # 3) Fallback original
    if data is None:
        try:
            data = _original_get_content(self)
        except Exception:
            frappe.log_error(f"Original get_content failed for File {self.name}", "frappe_s3_attachment")
            data = None

    # 4) Aseguramos self._content even if empty
    self._content = data or b''
    return self._content


# Aplicamos los parches
CoreFile.get_content = patched_get_content
