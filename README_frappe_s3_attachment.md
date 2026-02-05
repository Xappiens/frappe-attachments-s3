# Frappe S3 Attachment - README Técnico

## Información General

**App:** Frappe S3 Attachment
**Versión:** 0.0.1
**Rama:** custom-endpoint-s3
**Repositorio:** [Xappiens/frappe-attachments-s3](https://github.com/Xappiens/frappe-attachments-s3)
**Tamaño:** 780K
**Tipo:** Integración Amazon S3

---

## Descripción

Frappe S3 Attachment es la integración con Amazon S3 para el almacenamiento de archivos adjuntos del proyecto ERA Digital Murcia. Proporciona funcionalidades para subir, gestionar y servir archivos desde Amazon S3, mejorando la escalabilidad y rendimiento del sistema.

### Características Principales
- **Almacenamiento S3:** Almacenamiento en Amazon S3
- **CDN Integration:** Integración con CloudFront
- **Backup Automático:** Backup automático de archivos
- **Escalabilidad:** Escalabilidad ilimitada
- **Seguridad:** Control de acceso y permisos
- **Optimización:** Optimización de archivos
- **Migración:** Migración desde almacenamiento local

---

## Estructura de la App

```
frappe_s3_attachment/
├── frappe_s3_attachment/    # Módulo principal de S3
│   ├── frappe_s3_attachment/ # Submódulo principal
│   │   ├── doctype/         # Doctypes del sistema S3
│   │   │   ├── s3_file/     # Archivos S3
│   │   │   ├── s3_settings/ # Configuración S3
│   │   │   └── [otros]      # Doctypes adicionales
│   │   ├── api/             # APIs de S3
│   │   ├── utils/           # Utilidades
│   │   └── [otros módulos]  # Módulos adicionales
│   └── [otros módulos]      # Módulos adicionales
├── node_modules/            # Dependencias Node.js
├── package.json             # Configuración Node.js
├── requirements.txt         # Dependencias Python
├── hooks.py                # Configuración de hooks
└── [archivos de config]    # Archivos de configuración
```

---

## Doctypes Principales

### S3 File
- **Descripción:** Archivos almacenados en S3
- **Funcionalidades:**
  - Metadatos de archivos
  - URLs de acceso
  - Control de permisos
  - Historial de versiones
- **Campos Principales:**
  - Nombre del archivo
  - URL de S3
  - Tamaño del archivo
  - Tipo de archivo
  - Fecha de subida

### S3 Settings
- **Descripción:** Configuración de la integración S3
- **Funcionalidades:**
  - Configuración de AWS
  - Bucket de S3
  - Región de AWS
  - Configuración de CDN
- **Campos Principales:**
  - AWS Access Key
  - AWS Secret Key
  - S3 Bucket
  - AWS Region
  - CDN URL

---

## Configuración y Hooks

### hooks.py
```python
app_name = "frappe_s3_attachment"
app_title = "Frappe S3 Attachment"
app_publisher = "Frappe"
app_description = "Frappe app to make file upload to S3 through attach file option."
app_icon = "octicon octicon-file-directory"
app_color = "grey"
app_email = "ramesh.ravi@zerodha.com"
app_license = "MIT"
```

### Características Especiales
- **Licencia:** MIT
- **Publisher:** Frappe
- **Email:** ramesh.ravi@zerodha.com
- **Icono:** Octicon file-directory

---

## Dependencias

### Python
- **Boto3:** SDK de AWS para Python
- **Libmagic:** Detección de tipos de archivo
- **Urllib3:** Cliente HTTP
- **Python Magic:** Detección de tipos de archivo

### Node.js
- **AWS SDK:** SDK de AWS para Node.js
- **Webpack:** Bundling de assets

---

## Desarrollo y Customización

### Estructura de Desarrollo
```bash
# Navegar a la app
cd /home/frappe/frappe-bench/apps/frappe_s3_attachment

# Activar entorno virtual
source ../env/bin/activate

# Instalar dependencias de desarrollo
pip install -e .
npm install
```

### Comandos de Desarrollo
```bash
# Compilar assets
npm run build

# Compilar en modo desarrollo
npm run dev

# Ejecutar tests
python -m pytest
```

### Customizaciones Específicas del Proyecto

#### Modificaciones Realizadas
1. **Endpoint Personalizado:** custom-endpoint-s3
2. **Configuración Específica:** Adaptada para ERA Digital Murcia
3. **Seguridad:** Configuración de seguridad personalizada
4. **CDN:** Integración con CloudFront

#### Archivos de Customización
- `frappe_s3_attachment/frappe_s3_attachment/doctype/` - Doctypes personalizados
- `frappe_s3_attachment/frappe_s3_attachment/api/` - APIs personalizadas
- `frappe_s3_attachment/frappe_s3_attachment/utils/` - Utilidades personalizadas

---

## API y Endpoints

### Endpoints Principales
```bash
# Archivos S3
GET    /api/resource/S3 File
POST   /api/resource/S3 File
GET    /api/resource/S3 File/{name}

# Configuración
GET    /api/resource/S3 Settings
POST   /api/resource/S3 Settings
GET    /api/resource/S3 Settings/{name}

# APIs específicas
POST   /api/method/frappe_s3_attachment.api.upload_file
GET    /api/method/frappe_s3_attachment.api.get_file_url
POST   /api/method/frappe_s3_attachment.api.delete_file
```

### Ejemplos de Uso
```python
# En consola de Frappe
>>> frappe.get_doc("S3 File", "FILE-001")
>>> frappe.db.sql("SELECT * FROM `tabS3 File` WHERE file_name LIKE '%.pdf'")
>>> frappe.get_value("S3 Settings", "S3 Settings", "bucket_name")
```

---

## Configuración de AWS S3

### Requisitos
- **Cuenta de AWS:** Cuenta de Amazon Web Services
- **S3 Bucket:** Bucket de S3 configurado
- **IAM User:** Usuario con permisos de S3
- **Access Keys:** Claves de acceso de AWS

### Configuración Inicial
```python
# Configurar S3 Settings
settings = frappe.get_doc("S3 Settings")
settings.aws_access_key_id = "YOUR_ACCESS_KEY"
settings.aws_secret_access_key = "YOUR_SECRET_KEY"
settings.bucket_name = "your-bucket-name"
settings.region = "us-east-1"
settings.save()
```

### Configuración de Bucket
```bash
# Crear bucket
aws s3 mb s3://your-bucket-name

# Configurar CORS
aws s3api put-bucket-cors --bucket your-bucket-name --cors-configuration file://cors.json

# Configurar políticas
aws s3api put-bucket-policy --bucket your-bucket-name --policy file://policy.json
```

---

## Funcionalidades Principales

### Subida de Archivos
- **Subida Automática:** Subida automática a S3
- **Validación:** Validación de tipos de archivo
- **Compresión:** Compresión automática
- **Cifrado:** Cifrado de archivos

### Gestión de Archivos
- **Metadatos:** Almacenamiento de metadatos
- **Versionado:** Control de versiones
- **Eliminación:** Eliminación segura
- **Migración:** Migración desde local

### CDN Integration
- **CloudFront:** Integración con CloudFront
- **Cache:** Configuración de cache
- **HTTPS:** Soporte para HTTPS
- **Optimización:** Optimización de entrega

---

## Reportes Principales

### Reportes de Archivos
- **File Usage Report:** Uso de archivos
- **File Size Report:** Tamaño de archivos
- **File Type Report:** Tipos de archivo
- **Storage Report:** Uso de almacenamiento

### Reportes de Configuración
- **S3 Usage Report:** Uso de S3
- **CDN Performance Report:** Rendimiento de CDN
- **Error Report:** Reporte de errores
- **Cost Report:** Reporte de costos

---

## Testing

### Tests Unitarios
```bash
# Ejecutar todos los tests
python -m pytest

# Tests específicos de archivos
python -m pytest frappe_s3_attachment/tests/test_s3_file.py

# Tests de configuración
python -m pytest frappe_s3_attachment/tests/test_s3_settings.py

# Tests de API
python -m pytest frappe_s3_attachment/tests/test_api.py
```

### Tests de Integración
```bash
# Tests de S3
python -m pytest frappe_s3_attachment/tests/test_s3_integration.py

# Tests de CDN
python -m pytest frappe_s3_attachment/tests/test_cdn_integration.py

# Tests de migración
python -m pytest frappe_s3_attachment/tests/test_migration.py
```

---

## Monitoreo y Logs

### Logs Específicos
- `logs/frappe.log` - Logs principales de S3
- `logs/web.log` - Logs del servidor web
- `logs/worker.log` - Logs de workers

### Métricas Importantes
- **Tiempo de subida:** < 5 segundos para archivos < 10MB
- **Disponibilidad:** 99.9% de disponibilidad
- **Latencia:** < 100ms para archivos en cache
- **Throughput:** > 100MB/s de subida

---

## Troubleshooting

### Problemas Comunes

#### Error de AWS
```bash
# Verificar configuración
bench --site erp.grupoatu.com console
>>> frappe.get_doc("S3 Settings")

# Verificar credenciales
>>> frappe.get_system_settings("aws_access_key_id")
```

#### Problemas de Bucket
```bash
# Verificar bucket
bench --site erp.grupoatu.com console
>>> frappe.get_system_settings("s3_bucket_name")

# Verificar permisos
>>> frappe.get_system_settings("s3_region")
```

#### Problemas de Archivos
```bash
# Verificar archivos
bench --site erp.grupoatu.com console
>>> frappe.db.sql("SELECT * FROM `tabS3 File` ORDER BY creation DESC LIMIT 10")

# Verificar URLs
>>> frappe.get_doc("S3 File", "FILE-001").file_url
```

---

## Documentación Adicional

### Recursos Oficiales
- **AWS S3:** [https://docs.aws.amazon.com/s3/](https://docs.aws.amazon.com/s3/)
- **Boto3:** [https://boto3.amazonaws.com/v1/documentation/api/latest/index.html](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html)
- **Documentación:** [https://github.com/Xappiens/frappe-attachments-s3](https://github.com/Xappiens/frappe-attachments-s3)

### Repositorios
- **Proyecto:** [https://github.com/Xappiens/frappe-attachments-s3](https://github.com/Xappiens/frappe-attachments-s3)

---

## Contacto y Soporte

**Desarrollador Principal:** Xappiens
**Email:** xappiens@xappiens.com
**Proyecto:** ERA Digital Murcia - Grupo ATU
**Ubicación:** `/home/frappe/frappe-bench/apps/frappe_s3_attachment/`

---

*Documento generado el 16 de Septiembre de 2025*
