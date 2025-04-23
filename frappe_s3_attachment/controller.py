from __future__ import unicode_literals

import random
import string
import datetime
import re
import os
from frappe.utils import get_url
import boto3
import frappe
from botocore.config import Config
from botocore.exceptions import ClientError
from frappe import _
import magic


class S3Operations(object):
    def __init__(self):
        """
        Initialize boto3 client pointing either to AWS S3 or your custom OVH endpoint.
        """
        # 1) Load settings from the “S3 File Attachment” doctype
        cfg = frappe.get_doc('S3 File Attachment', 'S3 File Attachment')
        self.cfg = cfg

        # 2) Determine endpoint: use custom endpoint_url if set, otherwise default AWS URL
        endpoint_url = (cfg.endpoint_url or '').strip()
        default_url = f"https://s3.{cfg.region_name}.amazonaws.com"
        endpoint = endpoint_url if endpoint_url else default_url


        # 3) Build boto3 client arguments, forcing path-style addressing for OVH compatibility
        client_args = {
            'service_name': 's3',
            'endpoint_url': endpoint,
        }

        # 4) Always include credentials if provided
        if cfg.aws_key and cfg.aws_secret:
            client_args['aws_access_key_id'] = cfg.aws_key
            client_args['aws_secret_access_key'] = cfg.aws_secret

        # 5) Instantiate the S3 client once
        self.S3_CLIENT = boto3.client(**client_args)
        frappe.log_error(f"[S3Operations] boto3 client endpoint: {self.S3_CLIENT.meta.endpoint_url}")

        # Store bucket and optional root folder
        self.BUCKET = cfg.bucket_name
        self.folder_name = cfg.folder_name

    def strip_special_chars(self, file_name):
        """
        Remove any characters not allowed in S3 keys (alphanumeric, dot, underscore, hyphen).
        """
        regex = re.compile('[^0-9a-zA-Z._-]')
        return regex.sub('', file_name or '')

    def key_generator(self, file_name, parent_doctype, parent_name):
        """
        Generate unique keys for S3 objects based on the file name and document context.
        Handles None file names and supports custom key generator hooks.
        """
        # 1) Custom hook override
        hook = frappe.get_hooks().get("s3_key_generator")
        if hook:
            try:
                custom_key = frappe.get_attr(hook[0])(
                    file_name=file_name,
                    parent_doctype=parent_doctype,
                    parent_name=parent_name
                )
                if custom_key:
                    return custom_key.strip("/")
            except:
                pass

        # 2) Sanitize file_name and generate random suffix
        sanitized = self.strip_special_chars(file_name.replace(" ", "_") if file_name else "")
        random_part = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(8))

        # 3) Date-based path
        today = datetime.datetime.now()
        year, month, day = today.strftime("%Y"), today.strftime("%m"), today.strftime("%d")

        # 4) Optionally read a custom s3_folder_path from the parent document
        try:
            doc_path = frappe.db.get_value(
                parent_doctype, {"name": parent_name}, "s3_folder_path"
            ) or ""
            doc_path = doc_path.strip("/")
        except:
            doc_path = ""

        # 5) Build suffix with file name if present
        suffix = f"_{sanitized}" if sanitized else ""

        # 6) Assemble final key
        if doc_path:
            final = f"{doc_path}/{random_part}{suffix}"
        else:
            base = f"{year}/{month}/{day}/{parent_doctype}/{random_part}{suffix}"
            final = f"{self.folder_name}/{base}" if self.folder_name else base

        return final

    def upload_files_to_s3_with_key(self, file_path, file_name, is_private, parent_doctype, parent_name):
        """
        Uploads a file to S3 using the generated key.
        Sets ContentType and optional ACL/public-read.
        """
        mime_type = magic.from_file(file_path, mime=True)
        # Ensure file_name is ASCII-friendly
        file_name_clean = file_name.encode('ascii', 'replace').decode('utf-8')
        key = self.key_generator(file_name_clean, parent_doctype, parent_name)

        extra = {
            "ContentType": mime_type,
            "Metadata": {"ContentType": mime_type}
        }
        if not is_private:
            extra["ACL"] = "public-read"

        try:
            self.S3_CLIENT.upload_file(file_path, self.BUCKET, key, ExtraArgs=extra)
        except boto3.exceptions.S3UploadFailedError:
            frappe.throw(_("File Upload Failed. Please try again."))

        return key, file_name_clean

    def delete_from_s3(self, key):
        """
        Delete an object from S3 using the same configured client.
        """
        if self.cfg.delete_file_from_cloud:
            try:
                self.S3_CLIENT.delete_object(Bucket=self.BUCKET, Key=key)
            except ClientError:
                frappe.throw(_("Access denied: Could not delete file"))

    def read_file_from_s3(self, key):
        """
        Download/get an object from S3.
        """
        return self.S3_CLIENT.get_object(Bucket=self.BUCKET, Key=key)

    def get_url(self, key, file_name=None):
        """
        Generate a presigned URL for the given S3 key.
        """
        expiry = self.cfg.signed_url_expiry_time or 120
        params = {"Bucket": self.BUCKET, "Key": key}
        if file_name:
            params["ResponseContentDisposition"] = f"filename={file_name}"

        return self.S3_CLIENT.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=expiry
        )


@frappe.whitelist()
def file_upload_to_s3(doc, method):
    """
    Hook: upload a File doctype attachment to S3.
    """
    s3op = S3Operations()

    # Determine local file path
    site_path = frappe.utils.get_site_path()
    if doc.is_private:
        local_path = os.path.join(site_path, doc.file_url.lstrip("/"))
    else:
        local_path = os.path.join(site_path, "public", doc.file_url)

    # Determine parent context
    if doc.doctype == "File" and not doc.attached_to_doctype:
        parent_doctype, parent_name = doc.doctype, doc.name
    else:
        parent_doctype, parent_name = doc.attached_to_doctype, doc.attached_to_name

    # Upload and update record
    key, fname = s3op.upload_files_to_s3_with_key(
        local_path, doc.file_name, doc.is_private, parent_doctype, parent_name
    )

    # Build absolute URL
    if doc.is_private:
        private_path = f"/api/method/frappe_s3_attachment.controller.generate_file?key={key}&file_name={fname}"
        url = get_url(private_path)
    else:
        url = f"{s3op.S3_CLIENT.meta.endpoint_url}/{s3op.BUCKET}/{key}"

    frappe.db.sql("""
        UPDATE `tabFile`
        SET file_url=%s, folder=%s, old_parent=%s, content_hash=%s
        WHERE name=%s
    """, (url, "Home/Attachments", "Home/Attachments", key, doc.name))
    frappe.db.commit()

    # Remove local copy and reload
    os.remove(local_path)
    doc.reload()


@frappe.whitelist()
def generate_file(key=None, file_name=None):
    """
    Redirects to a signed URL for a private file.
    """
    if not key:
        frappe.local.response["body"] = "Key not found."
        return

    signed = S3Operations().get_url(key, file_name)
    frappe.local.response.update({
        "type": "redirect",
        "location": signed
    })


@frappe.whitelist()
def generate_signed_url(key=None, file_name=None):
    """
    Return a presigned URL for an S3 object.
    """
    if not key:
        frappe.throw(_("Key not found."))
    return S3Operations().get_url(key, file_name)


def upload_existing_files_s3(name, file_name):
    """
    Migrate all existing File records to S3.
    """
    doc = frappe.get_doc("File", name)
    s3op = S3Operations()

    # Build absolute path
    site_path = frappe.utils.get_site_path()
    relative = doc.file_url.lstrip("/")
    local = os.path.join(site_path, relative)

    # Upload
    key, fname = s3op.upload_files_to_s3_with_key(
        local, doc.file_name, doc.is_private,
        doc.attached_to_doctype, doc.attached_to_name
    )

    # Build absolute URL
    if doc.is_private:
        private_path = f"/api/method/frappe_s3_attachment.controller.generate_file?key={key}"
        url = get_url(private_path)
    else:
        url = f"{s3op.S3_CLIENT.meta.endpoint_url}/{s3op.BUCKET}/{key}"

    # Update record and cleanup
    frappe.db.sql("""
        UPDATE `tabFile`
        SET file_url=%s, folder=%s, old_parent=%s, content_hash=%s
        WHERE name=%s
    """, (url, "Home/Attachments", "Home/Attachments", key, doc.name))
    frappe.db.commit()
    os.remove(local)


def s3_file_regex_match(file_url):
    """
    Detect if a file_url already points to S3.
    """
    return re.match(r'^(https:|/api/method/frappe_s3_attachment.controller.generate_file)', file_url)


@frappe.whitelist()
def migrate_existing_files():
    """
    API method to migrate all File records not yet on S3.
    """
    for f in frappe.get_all("File", ["name", "file_url", "file_name"]):
        if f.file_url and not s3_file_regex_match(f.file_url):
            upload_existing_files_s3(f.name, f.file_name)
    return True


def delete_from_cloud(doc, method):
    """
    Delete hook: remove an S3 object when a File is deleted.
    """
    S3Operations().delete_from_s3(doc.content_hash)


@frappe.whitelist()
def ping():
    """
    Simple healthcheck.
    """
    return "pong"
