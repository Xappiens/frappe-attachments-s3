import frappe

def custom_get_attachments(dt, dn):
    return frappe.get_all(
        "File",
        fields=["name", "file_name", "file_url", "is_private", "is_folder", "folder", "content_hash", "parent"],
        filters={"attached_to_name": dn, "attached_to_doctype": dt},
        order_by="creation desc"
    )

# Sobrescribir la función get_attachments globalmente
frappe.desk.form.load.get_attachments = custom_get_attachments

