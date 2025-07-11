# frappe_s3_attachment/methods.py

from email import message
import os, frappe, shutil
from frappe import _
from shutil import SameFileError
from frappe.core.doctype.file.file import File
from frappe.utils.file_manager import save_file
import re
from frappe_s3_attachment.controller import S3Operations

def sanitize_folder_name(text):
    """
    Normaliza el nombre de carpeta sustituyendo cada carácter que NO sea
    [0-9A-Za-z._-] por un guión (-). Además:
      1) Quita tildes/acentos (unidecode)
      2) Reemplaza espacios por guión bajo antes de la sustitución
    Ejemplos:
      "Mi Carpeta / Prueba!" → "Mi_Carpeta- -Prueba-"
      "Árbol/De/Prueba"     → "Arbol-De-Prueba"
    """
    if not text:
        return text
    text = str(text)

    # 2) Reemplazar espacios por guión bajo (para mantener separación visual)
    text = text.replace(" ", "_")

    # 3) Reemplazar todo lo que no esté en [0-9A-Za-z._-] por guión
    #    (incluye '/', signos de puntuación, caracteres extraños)
    text = re.sub(r'[^0-9A-Za-z._-]', "-", text)

    return text

@frappe.whitelist()
def ensure_file_folder(doc, method):
    """
    Hook before_save de File:
      1) Si es carpeta virtual (is_folder=True), no hace nada.
      2) Si no tiene attached_to_doctype/attached_to_name, tampoco crea nada.
      3) Siempre obtiene (o crea) la carpeta intermedia Home/Doctype/DocName.
      4) Si doc.folder viene con un ID distinto de ''/None/'Home':
           - Comprueba si esa carpeta está dentro de la jerarquía Home/Doctype/DocName.
           - Si está dentro, la respeta (no la sobrescribe).
           - Si NO está dentro, se lo asigna a la carpeta intermedia.
      5) Si doc.folder está vacío/None/"Home", se lo asigna directamente a la carpeta intermedia.
    """
    # (1) Si es una "carpeta virtual", salir sin tocar nada
    if getattr(doc, "is_folder", False):
        return

    # (2) Si no hay documento padre claro (sin attached_to_doctype/docname), salimos
    doctype = getattr(doc, "attached_to_doctype", None)
    docname = getattr(doc, "attached_to_name", None)
    if not doctype or not docname:
        return

    # (3) Creamos u obtenemos la carpeta intermedia "Home/Doctype/docname"
    parent_folder = ensure_folder_hierarchy(doctype, docname, subfolders=[])
    parent_id = parent_folder.name  # ID de "Home/Doctype/docname"

    # (4) Revisamos si doc.folder viene con algo distinto de ''/None/'Home'
    folder_id = getattr(doc, "folder", None) or None

    if folder_id and folder_id not in ("", "Home"):
        # Intentamos cargar ese folder_id
        try:
            current = frappe.get_doc("File", folder_id)
        except frappe.DoesNotExistError:
            # Si no existe, forzamos abajo la carpeta intermedia
            current = None

        # Si current existe y es carpeta, comprobamos que esté bajo parent_id
        if current and current.is_folder:
            temp = current
            while temp:
                # Si encontramos parent_id en la cadena de padres, respetamos folder_id
                if temp.name == parent_id:
                    return

                # Si llegamos a "Home" (o a un nodo sin padre válido), cortamos el bucle
                if not temp.folder or temp.folder == "Home":
                    break

                try:
                    temp = frappe.get_doc("File", temp.folder)
                except frappe.DoesNotExistError:
                    temp = None
                    break

        # Si llegamos aquí, quiere decir que:
        # - O bien folder_id no existía,
        # - O bien current.is_folder=False (no es carpeta),
        # - O bien NO estaba bajo parent_id
        # Por tanto, lo “cerramos” y pasamos a asignar la carpeta intermedia.
    
    # (5) Por defecto (folder vacío/"Home"/no válido o fuera de jerarquía),
    #     asignamos doc.folder = ID de la carpeta intermedia.
    doc.folder = parent_id
from frappe.exceptions import DuplicateEntryError
def create_folder_if_not_exists(folder_name, parent_folder=None,
                                attached_to_doctype=None, attached_to_name=None):
    parent = parent_folder or "Home"
    sanitanized_name = sanitize_folder_name(folder_name)
    existing = frappe.get_all('File',
        filters={'file_name': sanitanized_name, 'is_folder': 1, 'folder': parent},
        fields=['name'], limit=1)
    if existing:
        return frappe.get_doc('File', existing[0].name)

    f = frappe.new_doc('File')
    f.file_name = sanitanized_name
    f.is_folder = 1
    f.folder = parent
    if attached_to_doctype and attached_to_name:
        f.attached_to_doctype = attached_to_doctype
        f.attached_to_name = attached_to_name
    try:
        f.insert()
        frappe.db.commit()
        return f
    except DuplicateEntryError:
        frappe.db.rollback()
        # Ya existe, lo recuperamos
        return frappe.get_doc('File',
            {'file_name': sanitanized_name, 'is_folder': 1, 'folder': parent})


def ensure_folder_hierarchy(doctype, docname, subfolders=None):
    """
    Crea/retorna:
      Home/doctype
      Home/doctype/docname
      Home/doctype/docname/sub1/sub2/...
    """
    dt_folder = create_folder_if_not_exists(doctype)
    doc_folder = create_folder_if_not_exists(docname, parent_folder=dt_folder.name)
    parent = doc_folder
    for sf in (subfolders or []):
        parent = create_folder_if_not_exists(
            sf,
            parent_folder=parent.name,
            attached_to_doctype=doctype,
            attached_to_name=docname
        )
    return parent

@frappe.whitelist(allow_guest=False)
def get_doc_folder(doctype, docname):
    """
    Devuelve (creando si hace falta) la carpeta intermedia Home/doctype/docname.
    """
    folder = ensure_folder_hierarchy(doctype, docname, subfolders=[])
    return folder.name

@frappe.whitelist(allow_guest=False)
def upload_file_to_folder(doctype, docname, subfolders=None, is_private=0):
    """
    Endpoint para subir un archivo desde el frontend.
    - Recibe formData con 'file' (campo file).
    - Crea la jerarquía de carpetas: Doctype → docname → subfolders...
    - Guarda con save_file() y dispara tu hook S3.
    Devuelve el dict del File creado.
    """
    # subfolders puede llegar como JSON-string o lista
    if isinstance(subfolders, str):
        # formato "a,b,c"
        subfolders = [s.strip() for s in subfolders.split(',') if s.strip()]

    # 1) Asegura la carpeta destino
    folder = ensure_folder_hierarchy(doctype, docname, subfolders)

    # 2) Lee el fichero del request
    uploaded = frappe.local.request.files.get('file')
    if not uploaded:
        frappe.throw(_('No se ha enviado ningún fichero'), frappe.MandatoryError)

    # 3) Guarda usando file_manager (dispara after_insert → S3)
    content = uploaded.stream.read()
    file_doc = save_file(
        fname=uploaded.filename,
        content=content,
        dt=None,
        dn=None,
        folder=folder.name,
        is_private=bool(int(is_private))
    )

    # 4) Asocia al documento padre
    file_doc.db_set('attached_to_doctype', doctype)
    file_doc.db_set('attached_to_name', docname)

    return file_doc.as_dict()

@frappe.whitelist()
def create_folder(doctype, docname, parent, folder_name):
    """
    Crea una subcarpeta vacía (File with is_folder=1) bajo la carpeta `parent`.
    """
    if not parent or parent in ("null", "None", ""):
        parent = "Home"
    parent_doc = frappe.get_doc("File", parent)
    if not parent_doc.is_folder:
        frappe.throw(_("El registro padre no es una carpeta válida."))
    # evita duplicados
    if frappe.db.exists("File", {"file_name": folder_name, "folder": parent}):
        frappe.throw(_("Ya existe '{0}' en la carpeta.").format(folder_name))
    # crea la carpeta
    newf = frappe.get_doc({
        "doctype": "File",
        "file_name": folder_name,
        "is_folder": 1,
        "folder": parent,
        "attached_to_doctype": doctype,
        "attached_to_name": docname
    }).insert(ignore_permissions=True)
    return newf.name

@frappe.whitelist()
def delete_empty_folder(folder_id):
    """Elimina la carpeta dada si no tiene archivos ni subcarpetas. 
    Lanza un error si la carpeta no está vacía."""
    # Obtener el registro File de la carpeta
    folder_doc = frappe.get_doc("File", folder_id)
    # Verificar que realmente sea una carpeta
    if not folder_doc.is_folder:
        frappe.throw("El elemento seleccionado no es una carpeta.")
    # Buscar cualquier fichero o subcarpeta cuyo campo "folder" (carpeta padre) sea esta carpeta
    folder_path = f"{folder_doc.folder}/{folder_doc.file_name}"  # Ruta completa de la carpeta
    # Obtener cualquier File que tenga como carpeta padre la ruta de esta carpeta
    children = frappe.get_all("File", filters={"folder": folder_path})
    if children:
        # Si encontramos archivos o subcarpetas dentro, no permitimos eliminar
        frappe.throw("No se puede eliminar la carpeta porque no está vacía.")
    # Si está vacía, procedemos a eliminar el documento File de la carpeta
    frappe.delete_doc("File", folder_id, ignore_permissions=True)
    # (Opcional: también se podría eliminar del sistema de archivos físico si fuera necesario, pero 
    # Frappe no crea directorios reales para carpetas vacías en adjuntos, solo registros.)
    return {"message": "Carpeta eliminada exitosamente"}