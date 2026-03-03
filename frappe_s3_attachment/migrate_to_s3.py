"""
Script de migración masiva de archivos locales a S3.
Ejecutar con: bench --site <tu_sitio> execute frappe_s3_attachment.migrate_to_s3.run

Opciones:
- run(batch_size=100, max_files=None, delete_local=False)
- get_stats()
"""

import frappe
import os
import boto3
import mimetypes
import hashlib
from datetime import datetime


def get_s3_client():
    """Obtener cliente S3 configurado."""
    cfg = frappe.db.get_value('S3 File Attachment', 'S3 File Attachment', 
        ['bucket_name', 'region_name', 'endpoint_url', 'aws_key', 'aws_secret'], as_dict=True)
    
    endpoint = (cfg.endpoint_url or '').strip().rstrip('/') or f'https://s3.{cfg.region_name}.amazonaws.com'
    
    client = boto3.client(
        's3',
        endpoint_url=endpoint,
        aws_access_key_id=cfg.aws_key,
        aws_secret_access_key=cfg.aws_secret
    )
    
    return client, cfg.bucket_name, endpoint


def get_stats():
    """Obtener estadísticas de migración pendiente."""
    total = frappe.db.count('File', {'is_folder': 0})
    
    in_s3 = frappe.db.sql("""
        SELECT COUNT(*) FROM `tabFile` 
        WHERE content_hash LIKE '%/%' AND is_folder=0
    """)[0][0]
    
    local = frappe.db.sql("""
        SELECT COUNT(*) FROM `tabFile` 
        WHERE (content_hash NOT LIKE '%/%' OR content_hash IS NULL OR content_hash = '')
        AND (file_url LIKE '/files/%' OR file_url LIKE '/private/%')
        AND is_folder=0
    """)[0][0]
    
    print(f"=== Estadísticas de Migración ===")
    print(f"Total archivos: {total:,}")
    print(f"Ya en S3: {in_s3:,}")
    print(f"Pendientes de migrar: {local:,}")
    
    return {"total": total, "in_s3": in_s3, "pending": local}


def get_pending_files(limit=100):
    """Obtener archivos pendientes de migrar."""
    return frappe.db.sql("""
        SELECT name, file_name, file_url, is_private, 
               attached_to_doctype, attached_to_name, folder
        FROM `tabFile` 
        WHERE (content_hash NOT LIKE '%/%' OR content_hash IS NULL OR content_hash = '')
        AND (file_url LIKE '/files/%' OR file_url LIKE '/private/%')
        AND is_folder=0
        ORDER BY creation ASC
        LIMIT %s
    """, (limit,), as_dict=True)


def migrate_single_file(f, client, bucket, endpoint, site_path, delete_local=False):
    """Migrar un solo archivo a S3."""
    result = {"status": "pending", "file": f.file_name}
    
    try:
        # Determinar path local
        if f.is_private:
            local_path = os.path.join(site_path, f.file_url.lstrip('/'))
        else:
            local_path = os.path.join(site_path, 'public', f.file_url.lstrip('/'))
        
        # Verificar que existe
        if not os.path.exists(local_path):
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
        
        # Subir a S3
        mime_type = mimetypes.guess_type(local_path)[0] or 'application/octet-stream'
        extra_args = {'ContentType': mime_type}
        if not f.is_private:
            extra_args['ACL'] = 'public-read'
        
        client.upload_file(local_path, bucket, s3_key, ExtraArgs=extra_args)
        
        # Verificar en S3
        client.head_object(Bucket=bucket, Key=s3_key)
        
        # Construir nueva URL
        if f.is_private:
            new_url = f'/api/method/frappe_s3_attachment.controller.download_file?key={s3_key}'
        else:
            host = endpoint.split('://', 1)[1]
            new_url = f'https://{bucket}.{host}/{s3_key}'
        
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


def run(batch_size=100, max_files=None, delete_local=False):
    """
    Ejecutar migración masiva.
    
    Args:
        batch_size: Número de archivos por commit
        max_files: Límite total de archivos a migrar (None = todos)
        delete_local: Si True, borra archivos locales después de migrar
    """
    print(f"=== Iniciando migración ===")
    print(f"Batch size: {batch_size}")
    print(f"Max files: {max_files or 'sin límite'}")
    print(f"Borrar locales: {delete_local}")
    
    stats = get_stats()
    if stats["pending"] == 0:
        print("No hay archivos pendientes de migrar.")
        return
    
    client, bucket, endpoint = get_s3_client()
    site_path = frappe.get_site_path()
    
    total_success = 0
    total_errors = 0
    total_skipped = 0
    processed = 0
    
    while True:
        # Verificar límite
        if max_files and processed >= max_files:
            print(f"\nAlcanzado límite de {max_files} archivos.")
            break
        
        # Calcular cuántos archivos obtener
        remaining = (max_files - processed) if max_files else batch_size
        fetch_count = min(batch_size, remaining)
        
        files = get_pending_files(fetch_count)
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
    
    print(f"\n=== Migración completada ===")
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
