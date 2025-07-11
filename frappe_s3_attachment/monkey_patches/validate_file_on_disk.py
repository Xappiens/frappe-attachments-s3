# frappe_s3_attachment/patches/patch_validate_file_on_disk.py

import frappe
from frappe.core.doctype.file.file import File as CoreFile

# Guarda referencia al original
_original_validate = CoreFile.validate_file_on_disk

def patched_validate_file_on_disk(self):
    """
    Ignorar cualquier IOError/OSError de 'fichero no existe' y seguir.
    """
    try:
        _original_validate(self)
    except (IOError, OSError) as e:
        # Logueamos para rastrear, pero no relanzamos
        frappe.log_error(
            message=f"Ignoring missing file on disk during validate: {self.file_url} — {e}",
            title="patched_validate_file_on_disk"
        )
        return

# Aplicamos el parche
CoreFile.validate_file_on_disk = patched_validate_file_on_disk
