import os
import frappe
from frappe.model.document import Document
from frappe.desk.form.load import get_attachments
from frappe_s3_attachment.controller import S3Operations
from frappe.utils import get_site_path
from frappe.utils.file_manager import save_file
from botocore.exceptions import ClientError

def custom_copy_attachments(self):
    """Copy attachments from `amended_from`, descargando de S3 cuando haya content_hash."""
    s3op = S3Operations()

    for attach_item in get_attachments(self.doctype, self.amended_from):
        key = getattr(attach_item, "content_hash", None)
        url = getattr(attach_item, "file_url", "")
        fname = attach_item.file_name
        is_priv = attach_item.is_private

        # 1) Intento S3 solo si hay content_hash y NO es URL local
        if key and not url.startswith(("/files", "/private/files")):
            if "?fid=" in key:
                key = key.split("?fid=", 1)[0]
            try:
                obj = s3op.read_file_from_s3(key)
                data = obj["Body"].read()
                save_file(
                    fname=fname,
                    content=data,
                    dt=self.doctype,
                    dn=self.name,
                    folder=None,
                    is_private=is_priv
                )
                continue
            except ClientError as e:
                frappe.log_error(
                    message=f"NoSuchKey en S3 para key={key}: {e}",
                    title="custom_copy_attachments"
                )
            except Exception as e:
                frappe.log_error(
                    message=f"Error genérico S3 para key={key}: {e}",
                    title="custom_copy_attachments"
                )

        # 2) Si es URL local, leo del disco y manejo FileNotFoundError
        if url.startswith(("/files", "/private/files")):
            rel = url.lstrip("/")
            if url.startswith("/files"):
                local_path = os.path.join(get_site_path(), "public", rel)
            else:
                local_path = os.path.join(get_site_path(), rel)
            try:
                with open(local_path, "rb") as lf:
                    data = lf.read()
                save_file(
                    fname=fname,
                    content=data,
                    dt=self.doctype,
                    dn=self.name,
                    folder=None,
                    is_private=is_priv
                )
                continue
            except FileNotFoundError:
                frappe.log_error(
                    message=f"Archivo local no existe: {local_path}",
                    title="custom_copy_attachments"
                )
                # saltamos este attachment
                continue
            except Exception as e:
                frappe.log_error(
                    message=f"Error leyendo archivo local {local_path}: {e}",
                    title="custom_copy_attachments"
                )
                continue

        # 3) Fallback remoto
        try:
            save_file(
                fname=fname,
                content=None,
                dt=self.doctype,
                dn=self.name,
                folder=None,
                is_private=is_priv,
                decode=False,
                from_url=url
            )
        except Exception as e:
            frappe.log_error(
                message=f"Fallo descarga remota para URL={url}: {e}",
                title="custom_copy_attachments"
            )

# Monkey-patch
Document.copy_attachments_from_amended_from = custom_copy_attachments
