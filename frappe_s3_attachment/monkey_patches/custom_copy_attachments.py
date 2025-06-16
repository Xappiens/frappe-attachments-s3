import frappe
from frappe.model.document import Document
from frappe.desk.form.load import get_attachments
from frappe_s3_attachment.controller import S3Operations

def custom_copy_attachments(self):
    """Copy attachments from `amended_from`, descargando de S3 cuando haya content_hash."""
    s3op = S3Operations()
    for attach_item in get_attachments(self.doctype, self.amended_from):
        # si está en S3, lo descargamos y lo volvemos a subir por bytes
        if getattr(attach_item, "content_hash", None):
            obj = s3op.read_file_from_s3(attach_item.content_hash)
            data = obj["Body"].read()
            _file = frappe.get_doc({
                "doctype": "File",
                "file_name": attach_item.file_name,
                "is_private": attach_item.is_private,
                "content": data,  # sube desde bytes
                "attached_to_doctype": self.doctype,
                "attached_to_name": self.name,
            })
        else:
            # si no, referenciamos la URL local
            _file = frappe.get_doc({
                "doctype": "File",
                "file_url": attach_item.file_url,
                "file_name": attach_item.file_name,
                "is_private": attach_item.is_private,
                "attached_to_doctype": self.doctype,
                "attached_to_name": self.name,
            })
        _file.save()

# Monkey-patch del método original
Document.copy_attachments_from_amended_from = custom_copy_attachments
