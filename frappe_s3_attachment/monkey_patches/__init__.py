# import frappe_s3_attachment.monkey_patches.importer
# import frappe_s3_attachment.monkey_patches.custom_get_attachments
# import frappe_s3_attachment.monkey_patches.custom_copy_attachments
# import frappe_s3_attachment.monkey_patches.patch_get_content
# import frappe_s3_attachment.monkey_patches.validate_file_on_disk


# frappe_s3_attachment/monkey_patches/__init__.py

def apply_monkey_patches():
    """Apply all monkey patches safely after Frappe is loaded"""
    try:
        import frappe_s3_attachment.monkey_patches.importer
        import frappe_s3_attachment.monkey_patches.custom_get_attachments
        import frappe_s3_attachment.monkey_patches.custom_copy_attachments
        import frappe_s3_attachment.monkey_patches.patch_get_content
        import frappe_s3_attachment.monkey_patches.validate_file_on_disk
    except Exception as e:
        # Don't crash imports if something fails, just log it
        try:
            import frappe
            frappe.log_error(f"frappe_s3_attachment monkey patch failed: {e}")
        except Exception:
            print("[frappe_s3_attachment] monkey patch failed:", e)

