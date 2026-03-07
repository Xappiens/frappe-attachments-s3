"""
Script de migración masiva de archivos locales a S3.
Solo considera archivos vinculados a un DocType (attached_to_doctype) para no tocar huérfanos.

Uso:
  bench --site <sitio> execute frappe_s3_attachment.migrate_to_s3.get_stats
  bench --site <sitio> execute frappe_s3_attachment.migrate_to_s3.run --kwargs '{"batch_size": 200, "delete_local": true}'

Fases recomendadas:
  1) get_stats(only_attached=True)  → ver pendientes
  2) run(..., delete_local=False)   → prueba con un lote
  3) run(..., delete_local=True)    → migrar y borrar del disco (comprobación = head_object tras subir)
"""

import frappe
import os
import boto3
import mimetypes
import hashlib
from datetime import datetime

# Solo migrar archivos que estén vinculados a algún DocType (evita huérfanos)
ONLY_ATTACHED_DEFAULT = True


def get_s3_client():
    """Obtener cliente S3 configurado."""
    cfg = frappe.db.get_value('S3 File Attachment', 'S3 File Attachment',
        ['bucket_name', 'region_name', 'endpoint_url', 'aws_key', 'aws_secret'], as_dict=True)
    if not cfg or not cfg.get('bucket_name'):
        frappe.throw("Configura el DocType S3 File Attachment con bucket y credenciales.")

    endpoint = (cfg.endpoint_url or '').strip().rstrip('/') or f'https://s3.{cfg.region_name}.amazonaws.com'

    client = boto3.client(
        's3',
        endpoint_url=endpoint,
        aws_access_key_id=cfg.aws_key,
        aws_secret_access_key=cfg.aws_secret
    )
    return client, cfg.bucket_name, endpoint


def _attached_filter(only_attached):
    """Condición SQL para filtrar por attached_to_doctype."""
    if only_attached:
        return " AND attached_to_doctype IS NOT NULL AND TRIM(COALESCE(attached_to_doctype, '')) != ''"
    return ""


def count_existing_on_disk(only_attached=None):
    """
    Cuenta cuántos archivos pendientes de migrar REALMENTE existen en disco.
    Devuelve el conteo y tamaño total.
    """
    if only_attached is None:
        only_attached = ONLY_ATTACHED_DEFAULT
    af = _attached_filter(only_attached)
    site_path = frappe.get_site_path()

    sql = """
        SELECT name, file_name, file_url, is_private
        FROM `tabFile`
        WHERE (content_hash NOT LIKE '%%/%%' OR content_hash IS NULL OR content_hash = '')
        AND (file_url LIKE '/files/%%' OR file_url LIKE '/private/%%')
        AND is_folder=0
    """ + af
    rows = frappe.db.sql(sql, as_dict=True)

    total_db = len(rows)
    exist_count = 0
    missing_count = 0
    total_size = 0

    print(f"Analizando {total_db:,} registros de la BD...")

    for i, f in enumerate(rows):
        path = _local_path_for_file(f, site_path)
        if os.path.isfile(path):
            exist_count += 1
            try:
                total_size += os.path.getsize(path)
            except:
                pass
        else:
            missing_count += 1
        
        if (i + 1) % 10000 == 0:
            print(f"  Procesados {i+1:,}... ({exist_count:,} existen)")

    print(f"\n=== Análisis de archivos pendientes ===")
    print(f"Registros en BD pendientes de migrar: {total_db:,}")
    print(f"Existen en disco: {exist_count:,}")
    print(f"NO existen (huérfanos): {missing_count:,}")
    print(f"Tamaño total en disco: {total_size / (1024**3):.2f} GB")
    
    return {
        "total_db": total_db,
        "exist_on_disk": exist_count,
        "missing": missing_count,
        "size_bytes": total_size,
        "size_gb": round(total_size / (1024**3), 2)
    }


def sample_disk_files():
    """
    Muestreo de archivos en disco clasificados por tipo.
    """
    import random
    site_path = frappe.get_site_path()
    public_files = os.path.join(site_path, 'public', 'files')
    private_files = os.path.join(site_path, 'private', 'files')

    all_files = frappe.db.sql("""
        SELECT file_url, content_hash, attached_to_doctype, attached_to_name, file_name
        FROM `tabFile`
        WHERE is_folder=0
        AND (file_url LIKE '/files/%%' OR file_url LIKE '/private/%%')
    """, as_dict=True)
    file_map = {f.file_url: f for f in all_files}

    huerfanos = []
    sin_doctype = []
    con_doctype = []

    for folder, is_private in [(public_files, False), (private_files, True)]:
        for fname in os.listdir(folder):
            fpath = os.path.join(folder, fname)
            if not os.path.isfile(fpath):
                continue
            url = f'/private/files/{fname}' if is_private else f'/files/{fname}'
            size = os.path.getsize(fpath)
            rec = file_map.get(url)
            
            info = {'file': fname, 'url': url, 'size_mb': round(size/1024/1024, 2)}
            
            if not rec:
                huerfanos.append(info)
            elif rec.attached_to_doctype and rec.attached_to_doctype.strip():
                info['doctype'] = rec.attached_to_doctype
                info['docname'] = rec.attached_to_name
                con_doctype.append(info)
            else:
                sin_doctype.append(info)

    print("=== MUESTREO DE ARCHIVOS EN DISCO ===")
    print("")
    print(f"--- HUÉRFANOS (sin registro en BD): {len(huerfanos):,} archivos ---")
    random.shuffle(huerfanos)
    for f in huerfanos[:15]:
        print(f"  {f['size_mb']:>6} MB  {f['file'][:70]}")

    print("")
    print(f"--- SIN DOCTYPE (con registro, sin vincular): {len(sin_doctype):,} archivos ---")
    random.shuffle(sin_doctype)
    for f in sin_doctype[:15]:
        print(f"  {f['size_mb']:>6} MB  {f['file'][:70]}")

    print("")
    print(f"--- CON DOCTYPE (pendientes migrar): {len(con_doctype):,} archivos ---")
    for f in con_doctype[:10]:
        print(f"  {f['size_mb']:>6} MB  {f['file'][:50]} -> {f['doctype']}")
    
    # Totales
    total_huerfanos_mb = sum(f['size_mb'] for f in huerfanos)
    total_sin_mb = sum(f['size_mb'] for f in sin_doctype)
    total_con_mb = sum(f['size_mb'] for f in con_doctype)
    
    print("")
    print("=== RESUMEN ===")
    print(f"  Huérfanos: {len(huerfanos):,} archivos ({total_huerfanos_mb:.1f} MB)")
    print(f"  Sin DocType: {len(sin_doctype):,} archivos ({total_sin_mb:.1f} MB)")
    print(f"  Con DocType: {len(con_doctype):,} archivos ({total_con_mb:.1f} MB)")
    
    return {
        "huerfanos": len(huerfanos),
        "sin_doctype": len(sin_doctype),
        "con_doctype": len(con_doctype)
    }


def analyze_physical_files():
    """
    Analiza los archivos FÍSICOS en disco y los clasifica según su estado en BD.
    Versión optimizada: carga todos los File de la BD en memoria primero.
    """
    site_path = frappe.get_site_path()
    public_files = os.path.join(site_path, 'public', 'files')
    private_files = os.path.join(site_path, 'private', 'files')

    # Cargar TODOS los registros File en un dict por file_url (una sola consulta)
    print("Cargando registros de BD...")
    all_files = frappe.db.sql("""
        SELECT file_url, content_hash, attached_to_doctype
        FROM `tabFile`
        WHERE is_folder=0
        AND (file_url LIKE '/files/%%' OR file_url LIKE '/private/%%')
    """, as_dict=True)
    
    file_map = {f.file_url: f for f in all_files}
    print(f"  {len(file_map):,} registros cargados")

    # Contar archivos físicos
    public_list = [f for f in os.listdir(public_files) if os.path.isfile(os.path.join(public_files, f))]
    private_list = [f for f in os.listdir(private_files) if os.path.isfile(os.path.join(private_files, f))]

    print(f"\nArchivos físicos en disco:")
    print(f"  public/files: {len(public_list):,}")
    print(f"  private/files: {len(private_list):,}")
    print(f"  TOTAL: {len(public_list) + len(private_list):,}")

    in_s3_with_local = 0
    not_in_db = 0
    pending_attached = 0
    pending_unattached = 0
    residual_examples = []
    orphan_examples = []

    for fname in public_list:
        url = f'/files/{fname}'
        rec = file_map.get(url)
        if not rec:
            not_in_db += 1
            if len(orphan_examples) < 15:
                orphan_examples.append(url)
        elif rec.content_hash and '/' in rec.content_hash:
            in_s3_with_local += 1
            if len(residual_examples) < 10:
                residual_examples.append(url)
        elif rec.attached_to_doctype and rec.attached_to_doctype.strip():
            pending_attached += 1
        else:
            pending_unattached += 1

    for fname in private_list:
        url = f'/private/files/{fname}'
        rec = file_map.get(url)
        if not rec:
            not_in_db += 1
            if len(orphan_examples) < 15:
                orphan_examples.append(url)
        elif rec.content_hash and '/' in rec.content_hash:
            in_s3_with_local += 1
            if len(residual_examples) < 10:
                residual_examples.append(url)
        elif rec.attached_to_doctype and rec.attached_to_doctype.strip():
            pending_attached += 1
        else:
            pending_unattached += 1

    print(f"\nClasificación de archivos en disco:")
    print(f"  Ya en S3 (residuales, se pueden borrar): {in_s3_with_local:,}")
    print(f"  Pendientes (con DocType): {pending_attached:,}")
    print(f"  Pendientes (sin DocType): {pending_unattached:,}")
    print(f"  Sin registro en BD (huérfanos disco): {not_in_db:,}")
    
    if residual_examples:
        print(f"\nEjemplos de archivos residuales (ya en S3):")
        for ex in residual_examples[:5]:
            print(f"  {ex}")
    
    if orphan_examples:
        print(f"\nEjemplos de archivos huérfanos (sin registro en BD):")
        for ex in orphan_examples[:10]:
            print(f"  {ex}")
    
    return {
        "in_s3_residual": in_s3_with_local,
        "pending_attached": pending_attached,
        "pending_unattached": pending_unattached,
        "orphan_on_disk": not_in_db
    }


def analyze_disk_files():
    """
    Analiza los archivos físicos en disco vs los registros en BD.
    Útil para entender qué archivos quedan pendientes y por qué.
    """
    site_path = frappe.get_site_path()
    
    # Obtener TODOS los archivos pendientes (sin filtrar por attached)
    rows = frappe.db.sql("""
        SELECT name, file_url, is_private, attached_to_doctype, attached_to_name, file_name
        FROM `tabFile`
        WHERE (content_hash NOT LIKE '%%/%%' OR content_hash IS NULL OR content_hash = '')
        AND (file_url LIKE '/files/%%' OR file_url LIKE '/private/%%')
        AND is_folder=0
    """, as_dict=True)
    
    attached_exist = 0
    attached_missing = 0
    unattached_exist = 0
    unattached_missing = 0
    unattached_examples = []
    attached_examples = []
    
    for f in rows:
        path = _local_path_for_file(f, site_path)
        exists = os.path.isfile(path)
        has_doctype = f.attached_to_doctype and f.attached_to_doctype.strip()
        
        if has_doctype:
            if exists:
                attached_exist += 1
                if len(attached_examples) < 10:
                    attached_examples.append({
                        'name': f.name, 
                        'file': f.file_name, 
                        'doctype': f.attached_to_doctype
                    })
            else:
                attached_missing += 1
        else:
            if exists:
                unattached_exist += 1
                if len(unattached_examples) < 20:
                    unattached_examples.append({
                        'name': f.name, 
                        'file': f.file_name, 
                        'url': f.file_url
                    })
            else:
                unattached_missing += 1
    
    print("=== Análisis de archivos pendientes de migrar ===")
    print(f"\nVinculados a DocType:")
    print(f"  - Existen en disco: {attached_exist:,}")
    print(f"  - No existen (huérfanos BD): {attached_missing:,}")
    print(f"\nSIN DocType vinculado:")
    print(f"  - Existen en disco: {unattached_exist:,}")
    print(f"  - No existen (huérfanos BD): {unattached_missing:,}")
    
    if unattached_examples:
        print(f"\nEjemplos de archivos SIN DocType que existen en disco:")
        for uf in unattached_examples:
            print(f"  - {uf['file']} ({uf['url']})")
    
    if attached_examples:
        print(f"\nEjemplos de archivos CON DocType que existen en disco:")
        for af in attached_examples:
            print(f"  - {af['file']} -> {af['doctype']}")
    
    return {
        "attached_exist": attached_exist,
        "attached_missing": attached_missing,
        "unattached_exist": unattached_exist,
        "unattached_missing": unattached_missing
    }


def get_stats(only_attached=None):
    """
    Estadísticas de migración.
    only_attached: si True (default), solo cuenta archivos vinculados a un DocType.
    """
    if only_attached is None:
        only_attached = ONLY_ATTACHED_DEFAULT
    af = _attached_filter(only_attached)

    total = frappe.db.sql("SELECT COUNT(*) FROM `tabFile` WHERE is_folder=0" + af, as_dict=False)[0][0]
    in_s3 = frappe.db.sql(
        "SELECT COUNT(*) FROM `tabFile` WHERE content_hash LIKE '%/%' AND is_folder=0" + af,
        as_dict=False
    )[0][0]
    local = frappe.db.sql("""
        SELECT COUNT(*) FROM `tabFile`
        WHERE (content_hash NOT LIKE '%/%' OR content_hash IS NULL OR content_hash = '')
        AND (file_url LIKE '/files/%' OR file_url LIKE '/private/%')
        AND is_folder=0
    """ + af, as_dict=False)[0][0]

    print("=== Estadísticas (solo vinculados a DocType) ===" if only_attached else "=== Estadísticas de Migración ===")
    print(f"Total archivos: {total:,}")
    print(f"Ya en S3: {in_s3:,}")
    print(f"Pendientes de migrar: {local:,}")
    return {"total": total, "in_s3": in_s3, "pending": local}


def _local_path_for_file(f, site_path):
    """Ruta en disco del File (solo lectura)."""
    if f.is_private:
        return os.path.join(site_path, (f.file_url or "").lstrip("/"))
    return os.path.join(site_path, "public", (f.file_url or "").lstrip("/"))


def get_pending_files(limit=100, only_attached=None, only_existing_on_disk=True):
    """
    Archivos pendientes de migrar (vinculados a DocType por defecto).
    Si only_existing_on_disk=True (default), solo devuelve File cuyo archivo existe en disco,
    para que el script no falle al intentar subir archivos que ya no están.
    
    IMPORTANTE: Devuelve exactamente `limit` archivos que existen en disco,
    iterando por la BD hasta encontrarlos.
    """
    if only_attached is None:
        only_attached = ONLY_ATTACHED_DEFAULT
    af = _attached_filter(only_attached)
    site_path = frappe.get_site_path()

    if not only_existing_on_disk:
        sql = """
            SELECT name, file_name, file_url, is_private,
                   attached_to_doctype, attached_to_name, folder
            FROM `tabFile`
            WHERE (content_hash NOT LIKE '%%/%%' OR content_hash IS NULL OR content_hash = '')
            AND (file_url LIKE '/files/%%' OR file_url LIKE '/private/%%')
            AND is_folder=0
        """ + af + """
            ORDER BY modified DESC
            LIMIT %s
        """
        return frappe.db.sql(sql, (limit,), as_dict=True)

    # Iterar por la BD en lotes hasta encontrar `limit` archivos que existan en disco
    existing = []
    offset = 0
    batch_size = 5000
    max_iterations = 100  # máximo 500k registros revisados
    
    for _ in range(max_iterations):
        sql = """
            SELECT name, file_name, file_url, is_private,
                   attached_to_doctype, attached_to_name, folder
            FROM `tabFile`
            WHERE (content_hash NOT LIKE '%%/%%' OR content_hash IS NULL OR content_hash = '')
            AND (file_url LIKE '/files/%%' OR file_url LIKE '/private/%%')
            AND is_folder=0
        """ + af + """
            ORDER BY modified DESC
            LIMIT %s OFFSET %s
        """
        rows = frappe.db.sql(sql, (batch_size, offset), as_dict=True)
        
        if not rows:
            break  # No hay más registros
        
        for f in rows:
            path = _local_path_for_file(f, site_path)
            if os.path.isfile(path):
                existing.append(f)
                if len(existing) >= limit:
                    return existing
        
        offset += batch_size
    
    return existing


def migrate_single_file(f, client, bucket, endpoint, site_path, delete_local=False):
    """Migrar un solo archivo a S3 (solo si existe en disco)."""
    result = {"status": "pending", "file": f.file_name}
    local_path = _local_path_for_file(f, site_path)

    try:
        if not os.path.isfile(local_path):
            result["status"] = "skip"
            result["reason"] = "file_not_found"
            return result
        
        # Generar key S3
        today = datetime.now()
        parent_doctype = (f.attached_to_doctype or 'Unattached').replace(' ', '_')
        parent_name = (f.attached_to_name or 'Unknown').replace(' ', '_')[:50]
        unique_id = hashlib.md5(f.name.encode()).hexdigest()[:8]
        safe_filename = f.file_name.replace(' ', '_')
        s3_key = f'{today.year}/{today.month:02d}/{today.day:02d}/{parent_doctype}/{parent_name}/{unique_id}_{safe_filename}'
        
        # Subir a S3 siempre como PRIVADO (sin ACL público)
        # Los archivos solo serán accesibles via presigned URL generada por Frappe
        mime_type = mimetypes.guess_type(local_path)[0] or 'application/octet-stream'
        extra_args = {'ContentType': mime_type}
        # NO usamos ACL='public-read' para que no sea accesible desde internet directamente
        
        client.upload_file(local_path, bucket, s3_key, ExtraArgs=extra_args)
        
        # Verificar en S3
        client.head_object(Bucket=bucket, Key=s3_key)
        
        # URL siempre via API de Frappe (presigned URL con control de permisos)
        new_url = f'/api/method/frappe_s3_attachment.controller.download_file?key={s3_key}'
        
        # Actualizar BD
        frappe.db.sql("""
            UPDATE `tabFile`
            SET file_url=%s, content_hash=%s
            WHERE name=%s
        """, (new_url, s3_key, f.name))
        
        # Borrar archivo local si se solicita
        if delete_local:
            try:
                os.remove(local_path)
            except OSError:
                pass
        
        result["status"] = "success"
        result["key"] = s3_key
        
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
    
    return result


def run(batch_size=100, max_files=None, delete_local=False, only_attached=None, only_existing_on_disk=True):
    """
    Ejecutar migración masiva a S3.
    Solo se intentan subir File cuyo archivo existe en disco (only_existing_on_disk=True por defecto).
    Tras cada subida se comprueba con head_object; si delete_local=True, se borra el archivo del disco.

    Args:
        batch_size: Archivos por lote (commit tras cada lote)
        max_files: Límite total (None = todos los pendientes)
        delete_local: Si True, borra del disco tras subir y comprobar en S3
        only_attached: Si True (default), solo archivos con attached_to_doctype
        only_existing_on_disk: Si True (default), solo incluir File que existan en disco (evita fallos)
    """
    if only_attached is None:
        only_attached = ONLY_ATTACHED_DEFAULT

    print("=== Iniciando migración ===")
    print(f"Batch size: {batch_size}")
    print(f"Max files: {max_files or 'sin límite'}")
    print(f"Borrar del disco tras subir: {delete_local}")
    print(f"Solo vinculados a DocType: {only_attached}")
    print(f"Solo existentes en disco: {only_existing_on_disk}")

    stats = get_stats(only_attached=only_attached)
    if stats["pending"] == 0:
        print("No hay archivos pendientes de migrar.")
        return {"processed": 0, "success": 0, "errors": 0, "skipped": 0}

    client, bucket, endpoint = get_s3_client()
    site_path = frappe.get_site_path()

    total_success = 0
    total_errors = 0
    total_skipped = 0
    processed = 0

    while True:
        if max_files and processed >= max_files:
            print(f"\nAlcanzado límite de {max_files} archivos.")
            break

        remaining = (max_files - processed) if max_files else batch_size
        fetch_count = min(batch_size, remaining)

        files = get_pending_files(limit=fetch_count, only_attached=only_attached, only_existing_on_disk=only_existing_on_disk)
        if not files:
            break
        
        batch_success = 0
        batch_errors = 0
        batch_skipped = 0
        
        for f in files:
            result = migrate_single_file(f, client, bucket, endpoint, site_path, delete_local)
            
            if result["status"] == "success":
                batch_success += 1
                total_success += 1
            elif result["status"] == "error":
                batch_errors += 1
                total_errors += 1
                print(f"  ERROR: {f.file_name[:40]}: {result.get('error', 'unknown')[:50]}")
            else:
                batch_skipped += 1
                total_skipped += 1
            
            processed += 1
        
        # Commit después de cada lote
        frappe.db.commit()
        
        print(f"Lote: +{batch_success} OK, +{batch_errors} err, +{batch_skipped} skip | Total: {total_success}/{processed}")
    
    print("\n=== Migración completada ===")
    print(f"Total procesados: {processed}")
    print(f"Éxitos: {total_success}")
    print(f"Errores: {total_errors}")
    print(f"Saltados (no existen): {total_skipped}")

    return {
        "processed": processed,
        "success": total_success,
        "errors": total_errors,
        "skipped": total_skipped
    }


def verify_migrated_sample(size=20):
    """
    Comprueba que una muestra de archivos ya en S3 (content_hash con /) existen en el bucket.
    Útil tras una migración con delete_local=False antes de pasar a delete_local=True.
    """
    client, bucket, _ = get_s3_client()
    rows = frappe.db.sql(
        "SELECT name, file_name, content_hash FROM `tabFile` "
        "WHERE content_hash LIKE %s AND is_folder=0 ORDER BY RAND() LIMIT %s",
        ("%/%", size),
        as_dict=True
    )
    ok = 0
    fail = 0
    for r in rows:
        try:
            client.head_object(Bucket=bucket, Key=r.content_hash)
            ok += 1
        except Exception as e:
            fail += 1
            print(f"  FALLO: {r.file_name}: {e}")
    print(f"Verificación: {ok} OK, {fail} fallos de {len(rows)}")
    return {"ok": ok, "fail": fail, "total": len(rows)}
