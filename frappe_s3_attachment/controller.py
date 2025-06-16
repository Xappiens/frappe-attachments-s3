# frappe_s3_attachment/controller.py

from __future__ import unicode_literals

import os
import re
import random
import string
import datetime
from frappe.utils import get_url

import boto3
import magic
import frappe
from botocore.exceptions import ClientError
from frappe import _
from frappe.utils import get_url, get_site_path
import mimetypes


class S3Operations(object):
    def __init__(self):
        cfg = frappe.get_doc('S3 File Attachment', 'S3 File Attachment')
        self.cfg = cfg

        # Determine endpoint
        endpoint_url = (cfg.endpoint_url or '').strip()
        default_url = f"https://s3.{cfg.region_name}.amazonaws.com"
        endpoint = endpoint_url if endpoint_url else default_url

        client_args = {
            'service_name': 's3',
            'endpoint_url': endpoint
        }
        if cfg.aws_key and cfg.aws_secret:
            client_args['aws_access_key_id'] = cfg.aws_key
            client_args['aws_secret_access_key'] = cfg.aws_secret

        self.S3_CLIENT = boto3.client(**client_args)
        # frappe.log_error(f"[S3Operations] boto3 client endpoint: {self.S3_CLIENT.meta.endpoint_url}")

        self.BUCKET = cfg.bucket_name
        self.folder_name = cfg.folder_name

    def strip_special_chars(self, text):
        """Remove characters not allowed in S3 keys (alphanumeric, dot, underscore, hyphen)."""
        return re.sub(r'[^0-9A-Za-z._-]', '-', (text or '').replace(' ', '_'))

    def _get_folder_hierarchy(self, folder_docname):
        """
        Walk up the File-folder tree, collecting folder names (sanitized),
        stopping at Home.
        """
        parts = []
        while folder_docname:
            try:
                f = frappe.get_doc('File', folder_docname)
            except frappe.DoesNotExistError:
                break
            if f.is_folder and f.file_name != 'Home':
                parts.insert(0, self.strip_special_chars(f.file_name))
            folder_docname = f.folder
        return parts

    def key_generator(self, file_name, parent_doctype, parent_name, folder_docname=None):
        """
        YYYY/MM/DD/Doctype/Name[/subfolders...]/RANDOM_filename
        Does not duplicate Doctype or Name if they appear in subfolders.
        """
        # Hook override
        hook = frappe.get_hooks().get('s3_key_generator')
        if hook:
            try:
                custom = frappe.get_attr(hook[0])(
                    file_name=file_name,
                    parent_doctype=parent_doctype,
                    parent_name=parent_name
                )
                if custom:
                    return custom.strip('/')
            except Exception:
                pass

        dt = self.strip_special_chars(parent_doctype)
        nm = self.strip_special_chars(parent_name)
        fn = self.strip_special_chars(file_name)

        now = datetime.datetime.now()
        date_path = now.strftime('%Y/%m/%d')
        rand = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

        # Base = date + doctype + document name
        base = f"{date_path}/{dt}/{nm}"

        # Subfolder parts
        parts = self._get_folder_hierarchy(folder_docname) if folder_docname else []
        # Remove leading duplicates
        while parts and parts[0] in (dt, nm):
            parts.pop(0)
        if parts:
            base = f"{base}/" + "/".join(parts)

        # Prepend global root folder if configured
        if self.folder_name:
            base = f"{self.folder_name}/{base}"

        return f"{base}/{rand}_{fn}"

    def upload_files_to_s3_with_key(self, file_path, file_name, is_private,
                                    parent_doctype, parent_name, folder_docname=None):
        """
        Upload file to S3. Returns (key, sanitized_file_name).
        """
        mime_type = magic.from_file(file_path, mime=True)
        sanitized = file_name.encode('ascii', 'replace').decode('utf-8')
        key = self.key_generator(sanitized, parent_doctype, parent_name, folder_docname)

        extra_args = {
            'ContentType': mime_type,
            'Metadata': {'ContentType': mime_type}
        }
        if not is_private:
            extra_args['ACL'] = 'public-read'

        try:
            self.S3_CLIENT.upload_file(file_path, self.BUCKET, key, ExtraArgs=extra_args)
        except Exception:
            frappe.throw(_('File Upload Failed. Please try again.'))

        return key, sanitized

    def delete_from_s3(self, key):
        """Delete an object from S3 if delete_file_from_cloud is enabled."""
        if self.cfg.delete_file_from_cloud:
            try:
                self.S3_CLIENT.delete_object(Bucket=self.BUCKET, Key=key)
            except ClientError:
                frappe.throw(_('Access denied: Could not delete file'))

    def read_file_from_s3(self, key):
        """Download/get an object from S3."""
        return self.S3_CLIENT.get_object(Bucket=self.BUCKET, Key=key)

    def get_url(self, key, file_name=None):
        """Generate a presigned URL for the given S3 key."""
        expiry = self.cfg.signed_url_expiry_time or 120
        params = {'Bucket': self.BUCKET, 'Key': key}
        if file_name:
            params['ResponseContentDisposition'] = f"filename={file_name}"
        return self.S3_CLIENT.generate_presigned_url('get_object', Params=params, ExpiresIn=expiry)

@frappe.whitelist(allow_guest=False)
def download_file(key=None):
    if not key:
        frappe.throw(_("Key not found."), frappe.DoesNotExistError)

    # 1) Carga el documento File a partir del content_hash (key)
    file_doc = frappe.get_doc("File", {"content_hash": key})
    if not file_doc.has_permission("read"):
        frappe.throw(_("You do not have permission to access this file"), frappe.PermissionError)

    # 2) Si el file_url es local (no empieza por http) o no existe content_hash
    #    redirigimos a la URL interna (/files o /private/files) para que Frappe lo sirva.
    local_url = file_doc.file_url or ""
    if local_url.startswith("/files") or local_url.startswith("/private/files"):
        frappe.local.response.update({
            "type": "redirect",
            "location": local_url
        })
        return

    # 2) Read the object from S3 using S3Operations helper
    s3op = S3Operations()
    obj = s3op.read_file_from_s3(key)      # {'Body': StreamingBody, 'ContentType': 'application/pdf', ...}
    stream = obj["Body"]

    # 3) Build the response and force inline display
    frappe.local.response.update({
        "filecontent": stream.read(),
        "filename": file_doc.file_name,
        "type": "download",
        # This causes Frappe to send:
        #   Content-Disposition: inline; filename="your_file.pdf"
        "display_content_as": "inline"
    })
    # Optional: ensure the correct Content-Type header (e.g. application/pdf)
    frappe.local.response["content_type"] = obj.get("ContentType")


@frappe.whitelist()
def file_upload_to_s3(doc, method):
    """
    Hook: upload a File doctype attachment to S3.
    Skips folders and ignores the default "Attachments" folder.
    """
    if getattr(doc, 'is_folder', False):
        return

    s3op = S3Operations()
    site_path = frappe.utils.get_site_path()

    if doc.is_private and doc.file_url:
        local_path = os.path.join(site_path, doc.file_url.lstrip('/'))
    elif doc.file_url:
        local_path = os.path.join(site_path, 'public', doc.file_url.lstrip('/'))
    else:
        return
    if doc.attached_to_doctype == "Prepared Report":
        return
        # Cargamos el doc padre
    try:
        parent = frappe.get_doc(doc.attached_to_doctype, doc.attached_to_name)
    except frappe.DoesNotExistError:
        parent = None

    # Si NO es una corrección, nada que hacer
    if parent and getattr(parent, "amended_from", None):
        relocate_amended_file(doc, method)

    # Determine parent context
    if doc.attached_to_doctype == 'File' and doc.attached_to_name:
        fld = frappe.get_doc('File', doc.attached_to_name)
        if fld.is_folder:
            parent_doctype = fld.attached_to_doctype
            parent_name = fld.attached_to_name
            folder_docname = doc.folder
        else:
            parent_doctype = doc.attached_to_doctype
            parent_name = doc.attached_to_name
            folder_docname = doc.folder
    else:
        parent_doctype = doc.attached_to_doctype or doc.doctype
        parent_name = doc.attached_to_name or doc.name
        folder_docname = doc.folder

        # Ignore the default "Attachments" folder
        if folder_docname:
            f = frappe.get_doc('File', folder_docname)
            if f.is_folder and f.file_name == 'Attachments':
                folder_docname = None
    # Upload file to S3
    key, fname = s3op.upload_files_to_s3_with_key(
        local_path,
        doc.file_name,
        doc.is_private,
        parent_doctype,
        parent_name,
        folder_docname=folder_docname
    )

    # Build file URL
    if doc.is_private:
        # get_url() se encarga de prefijar el dominio y esquema
        url = get_url(f"/api/method/frappe_s3_attachment.controller.download_file?key={key}")
    else:
        # ya es una URL absoluta a S3, así que no hace falta get_url
        url = f"{s3op.S3_CLIENT.meta.endpoint_url}/{s3op.BUCKET}/{key}"

    # Update File record
    frappe.db.sql("""
        UPDATE `tabFile`
        SET file_url=%s, folder=%s, old_parent=%s, content_hash=%s
        WHERE name=%s
    """, (url, doc.folder, doc.folder, key, doc.name))
    frappe.db.commit()

    # Remove local copy and reload
    try:
        os.remove(local_path)
    except OSError:
        pass

    doc.reload()



@frappe.whitelist()
def generate_file(key=None, file_name=None):
    """Redirect to a signed URL for private files."""
    if not key:
        frappe.local.response['body'] = 'Key not found.'
        return
    signed = S3Operations().get_url(key, file_name)
    frappe.local.response.update({'type': 'redirect', 'location': signed})


@frappe.whitelist()
def generate_signed_url(key=None, file_name=None):
    """Return a presigned URL for an S3 object."""
    if not key:
        frappe.throw(_('Key not found.'))
    return S3Operations().get_url(key, file_name)


def upload_existing_files_s3(name, file_name):
    """Migrate an existing File record to S3."""
    doc = frappe.get_doc('File', name)
    s3op = S3Operations()
    site_path = frappe.utils.get_site_path()
    relative = doc.file_url.lstrip('/')
    local = os.path.join(site_path, relative)

    if not os.path.exists(local):
        frappe.log_error(
            title="Archivo no encontrado para migración a S3",
            message=f"No se encontró el archivo en el path local: {local} (File name: {name})"
        )
        return  # Salta este archivo y continúa

    # Determine context
    if doc.attached_to_doctype == 'File':
        try:
            fld = frappe.get_doc('File', doc.attached_to_name)
            if fld.is_folder:
                parent_doctype = fld.attached_to_doctype
                parent_name = fld.attached_to_name
            else:
                parent_doctype = doc.attached_to_doctype
                parent_name = doc.attached_to_name
        except frappe.DoesNotExistError:
            parent_doctype = doc.attached_to_doctype
            parent_name = doc.attached_to_name
    else:
        parent_doctype = doc.attached_to_doctype
        parent_name = doc.attached_to_name

    try:
        key, fname = s3op.upload_files_to_s3_with_key(
            local, doc.file_name, doc.is_private,
            parent_doctype, parent_name, doc.folder
        )

        if doc.is_private:
            url = f"/api/method/frappe_s3_attachment.controller.generate_file?key={key}"
        else:
            url = f"{s3op.S3_CLIENT.meta.endpoint_url}/{s3op.BUCKET}/{key}"

        frappe.db.set_value('File', doc.name, {
            'file_url': url,
            'folder': doc.folder,
            'old_parent': doc.folder,
            'content_hash': key
        })
        frappe.db.commit()

        try:
            os.remove(local)
        except OSError:
            pass
    except Exception as e:
        frappe.log_error(
            title="Error al migrar archivo a S3",
            message=f"Archivo: {name} | Error: {frappe.get_traceback()}"
        )


def s3_file_regex_match(file_url):
    return re.match(
        r'^(https:|/api/method/frappe_s3_attachment.controller.generate_file)',
        file_url
    )


@frappe.whitelist()
def migrate_existing_files():
    """Migrate all File records not yet on S3."""
    for f in frappe.get_all('File', ['name', 'file_url']):
        if f.file_url and not s3_file_regex_match(f.file_url):
            upload_existing_files_s3(f.name, f.file_url)
    return True


def delete_from_cloud(doc, method):
    """Hook: when File is deleted, remove object from S3 (ignore folders)."""
    if getattr(doc, 'is_folder', False):
        return
    key = getattr(doc, 'content_hash', None)
    if not key:
        #frappe.log("delete_from_cloud: no content_hash, skipping", "frappe_s3_attachment")
        return
    S3Operations().delete_from_s3(key)





def relocate_amended_file(doc, method):
    """
    Si este File se acaba de copiar desde un 'amended_from',
    lo movemos a Home/Doctype/<new_name> y apuntamos
    attached_to_doctype/name al documento corregido.
    """
    # Sólo nos interesa archivos ligados a un doctype/version
    if not (doc.attached_to_doctype and doc.attached_to_name):
        return

    from frappe_s3_attachment.methods import ensure_folder_hierarchy
    # 1) Obtener (o crear) Home/Doctype/<parent.name>
    target_folder = ensure_folder_hierarchy(parent.doctype, parent.name)

    # 2) Si el archivo no está ahí ya, movemos folder y attached_to_*
    if doc.folder != target_folder.name or \
       doc.attached_to_doctype != parent.doctype or \
       doc.attached_to_name != parent.name:

        frappe.db.set_value("File", doc.name, {
            "folder": target_folder.name,
            "old_parent": target_folder.name,
            "attached_to_doctype": parent.doctype,
            "attached_to_name": parent.name
        })
        frappe.db.commit()


@frappe.whitelist()
def ping():
    """Healthcheck."""
    return 'pong'


