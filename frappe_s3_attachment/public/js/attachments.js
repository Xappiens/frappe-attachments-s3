frappe.provide('frappe.ui.form');

const OriginalAttachments = frappe.ui.form.Attachments;

frappe.ui.form.Attachments = class CustomAttachments extends OriginalAttachments {
    make() {
        // Inserta el menú al lado del botón +
        const $addBtn = this.parent.find(".add-attachment-btn");
        // Evita duplicados
        if (!$addBtn.siblings('.ellipsis-dropdown-menu.root').length) {
            $addBtn.after(`
            <ul class="ellipsis-dropdown-menu root" style="display:none;position:absolute;z-index:1000;background:#fff;border:1px solid #ccc;padding:8px 0;min-width:160px;box-shadow:0 2px 8px rgba(0,0,0,0.08);margin-top:4px;">
                <li><a href="#" class="upload-file">Subir archivo</a></li>
                <li><a href="#" class="create-subfolder">Crear carpeta</a></li>
            </ul>
        `);
        }

        // Mostrar/ocultar menú al hacer click en +
        $addBtn.off('click.attachmenu').on('click.attachmenu', (e) => {
            e.preventDefault(); e.stopPropagation();
            const $menu = $addBtn.siblings('.ellipsis-dropdown-menu.root');
            $('.ellipsis-dropdown-menu').not($menu).hide();
            $menu.toggle();
        });

        // Cerrar menú al hacer click fuera
        $(document).on('click.attachmenu', function () {
            $('.ellipsis-dropdown-menu').hide();
        });

        // Acciones del menú raíz
        const me = this;
        this.parent.find('.ellipsis-dropdown-menu.root .upload-file').off('click').on('click', function (e) {
            e.preventDefault(); e.stopPropagation();
            me.prompt_upload(null); // null para raíz
            $('.ellipsis-dropdown-menu').hide();
        });
        /* this.parent.find('.ellipsis-dropdown-menu.root .create-subfolder').off('click').on('click', function (e) {
            e.preventDefault(); e.stopPropagation();
            frappe.prompt(
                { fieldtype: 'Data', fieldname: 'subname', label: 'Nombre de la nueva carpeta', reqd: 1 },
                values => me.create_subfolder(null, values.subname),
                'Crear carpeta vacía', 'Crear'
            );
            $('.ellipsis-dropdown-menu').hide();
        }); */
        this.parent.find('.ellipsis-dropdown-menu.root .create-subfolder')
            .off('click')
            .on('click', function (e) {
                e.preventDefault(); e.stopPropagation();
                frappe.prompt(
                    { fieldtype: 'Data', fieldname: 'subname', label: 'Nombre de la nueva carpeta', reqd: 1 },
                    values => {
                        // Aquí ya solo llamas a get_doc_folder si parent_folder es Home
                        // 1) Obtén la carpeta lógica del documento
                        frappe.call({
                            method: "frappe.client.get_list",
                            args: {
                                doctype: "File",
                                filters: [
                                    ["file_name", "=", me.frm.docname],
                                    ["folder", "=", me.frm.doctype]
                                ],
                                fields: ["name"]
                            },
                            callback: r => {
                                let parent_folder = (r.message && r.message.length)
                                    ? r.message[0].name
                                    : "Home";

                                // 2) Si parent_folder sigue siendo "Home", pide tu get_doc_folder
                                if (parent_folder === "Home") {
                                    frappe.call({
                                        method: 'frappe_s3_attachment.methods.get_doc_folder',
                                        args: {
                                            doctype: me.frm.doctype,
                                            docname: me.frm.docname
                                        },
                                        callback: resp => {
                                            // resp.message es el File.name de Home/Doctype/DocName
                                            me.create_subfolder(resp.message, values.subname);
                                        }
                                    });
                                } else {
                                    // Ya tenemos la carpeta de nivel 1 o superior
                                    me.create_subfolder(parent_folder, values.subname);
                                }
                            }
                        });
                    },
                    'Crear carpeta vacía', 'Crear'
                );
                $('.ellipsis-dropdown-menu').hide();
            });
    }

    refresh() {
        // Limpiar contenedor
        this.parent.toggle(!this.frm.doc.__islocal);
        this.parent.find('.attachment-row').remove();
        // Obtener adjuntos desde docinfo
        const attachments = this.get_attachments();
        // console.log('Adjuntos obtenidos:', attachments);
        // Reconstruir árbol
        this.render_tree(attachments);
    }

    render_tree(attachments) {
        // 1) Convertir lista a nodos con children
        const nodes = attachments.map(a => ({ ...a, children: [] }));
        // console.log("NODES? ", nodes)

        const byId = Object.fromEntries(nodes.map(n => [n.name, n]));
        // console.log("BYID ?", byId)

        const roots = [];
        nodes.forEach(n => {
            if (byId[n.folder]) {
                byId[n.folder].children.push(n);
            } else {
                roots.push(n);
            }
        });
        // console.log("ROOTS?", roots)

        // 2) Función recursiva de renderizado
        const renderNode = (node, $container) => {
            const me = this;
            if (node.is_folder) {
                const $details = $(`
                    <details class="attachment-row" data-folder-id="${node.name}">
                        <summary></summary>
                        <ul class="folder-files-list"></ul>
                    </details>
                `).appendTo($container);

                const $summary = $details.find('> summary');
                $summary.append(`
                        <span class="ellipsis" style="max-width: calc(100% - 40px); display:inline-block;">
                            ${frappe.ellipsis(node.file_name, 10)}
                        </span>
                        <button class="ellipsis-menu-btn btn" style="background:none;border:none;cursor:pointer;padding:0 8px;vertical-align:middle;">
                            <svg width="20" height="20" viewBox="0 0 100 20" style="display:inline-block;">
                            <circle cx="15" cy="10" r="5" fill="#3c4a56"/>
                            <circle cx="50" cy="10" r="5" fill="#3c4a56"/>
                            <circle cx="85" cy="10" r="5" fill="#3c4a56"/>
                            </svg>
                        </button>
                        <ul class="ellipsis-dropdown-menu" style="display:none;position:absolute;left:0;z-index:1000;background:#fff;border:1px solid #ccc;padding:8px 0;min-width:160px;box-shadow:0 2px 8px rgba(0,0,0,0.08);margin-top:4px;">
                            <li><a href="#" class="upload-file">Subir archivo</a></li>
                            <li><a href="#" class="create-subfolder">Crear subcarpeta</a></li>
                            <li><a href="#" class="delete-folder">Eliminar carpeta</a></li>
                        </ul>
                `);

                const style = document.createElement('style');
                style.innerHTML = `
                    .ellipsis-dropdown-menu li {
                        padding: 6px 18px;
                        margin: 0;
                    }

                    .ellipsis-dropdown-menu li:not(:last-child) {
                        margin-bottom: 4px;
                    }
                    
                    .ellipsis-dropdown-menu ul{
                        list-style: none;
                    }

                    .ellipsis-dropdown-menu li a {
                        color: #222;
                        text-decoration: none;
                        display: block;
                        transition: border-bottom 0.2s;
                        border-bottom: 2px solid transparent;
                        padding-bottom: 2px;
                    }

                    .ellipsis-dropdown-menu li a:hover {
                        border-bottom: 2px solid #111;
                        background: #f8f8f8;
                    }
                `;
                document.head.appendChild(style);


                // Mostrar/ocultar menú al hacer click en los puntos
                $summary.find('.ellipsis-menu-btn').on('click', function (e) {
                    e.preventDefault(); e.stopPropagation();
                    const $menu = $(this).siblings('.ellipsis-dropdown-menu');
                    $('.ellipsis-dropdown-menu').not($menu).hide();
                    $menu.toggle();
                });

                // Cerrar menú al hacer click fuera
                $(document).on('click', function () {
                    $('.ellipsis-dropdown-menu').hide();
                });

                // Acciones
                $summary.find('.upload-file').on('click', e => {
                    e.preventDefault(); e.stopPropagation();
                    me.prompt_upload(node.name);
                    $('.ellipsis-dropdown-menu').hide();
                });
                $summary.find('.create-subfolder').on('click', e => {
                    e.preventDefault(); e.stopPropagation();
                    frappe.prompt(
                        { fieldtype: 'Data', fieldname: 'subname', label: 'Nombre subcarpeta', reqd: 1 },
                        values => me.create_subfolder(node.name, values.subname),
                        'Crear subcarpeta', 'Crear'
                    );
                    $('.ellipsis-dropdown-menu').hide();
                });
                $summary.find('.delete-folder').on('click', e => {
                    e.preventDefault(); e.stopPropagation();
                    frappe.confirm(
                        `¿Eliminar la carpeta “${node.file_name}”?`,
                        () => me.delete_folder(node.name)
                    );
                    $('.ellipsis-dropdown-menu').hide();
                });

                // Renderizar hijos
                const $childContainer = $details.find('> ul.folder-files-list');
                node.children.forEach(child => renderNode(child, $childContainer));
            } else {
                const remove_action = frappe.model.can_write(this.frm.doctype, this.frm.name)
                    ? target_id => {
                        frappe.confirm(
                            __("Are you sure you want to delete the attachment?"),
                            () => me.remove_attachment(target_id)
                        );
                        return false;
                    }
                    : null;

                const file_url = this.get_file_url(node);
                const file_label = `
                    <a href="${file_url}" target="_blank" title="${frappe.utils.escape_html(node.file_name)}">
                        <span>${frappe.ellipsis(node.file_name, 10)}</span>
                    </a>`;

                const icon = `<a href="/app/file/${node.name}">
                  ${frappe.utils.icon(node.is_folder ? "folder-normal" : "file", "sm ml-0")}
                </a>`;

                // Insertar <li> dentro del contenedor actual
                $(`<li class="attachment-row">`)
                    .append(frappe.get_data_pill(file_label, node.name, remove_action, icon))
                    .appendTo($container);
            }
        };

        // 4) Arrancar por las raíces (las carpetas de más alto nivel / archivos si los hubiera)
        roots.forEach(root => renderNode(root, this.parent));
    }

    // Métodos auxiliares
    create_subfolder(parent_folder_id, subfolder_name) {
        console.log("Creating subfolder:", subfolder_name, "in parent folder:", parent_folder_id);
        frappe.call({
            method: 'frappe_s3_attachment.methods.create_folder',
            args: {
                doctype: this.frm.doctype,
                docname: this.frm.docname,
                parent: parent_folder_id,
                folder_name: subfolder_name
            },
            callback: () => this.frm.reload_doc()
        });
    }
    get_file_url(attachment) {
        // Si está marcado como privado, usamos nuestro proxy interno
        if (attachment.is_private) {
            return `/api/method/frappe_s3_attachment.controller.download_file?key=${attachment.content_hash}`;
        }
        // En caso contrario, delegamos al método original
        return super.get_file_url(attachment);
    }


    /*
     Este método es el original que gestionaba el upload de archivos y carpetas. 
     Se ha comentado para evitar conflictos con la estructura de carpetas de custom_education.
     
    prompt_upload(parent_folder_id) {
        //console.log("PARENT FOLDER ID: ", parent_folder_id);
        const folder = parent_folder_id || "Home";
        new frappe.ui.FileUploader({
            doctype: this.frm.doctype,
            docname: this.frm.docname,
            folder: folder,
            on_success: () => {
                this.frm.reload_doc().then(() => {
                    this.refresh();
                });
            }
        });
    } */

    prompt_upload(parent_folder_id) {
        const me = this;

        // Crear input file manualmente
        const input = document.createElement('input');
        input.type = 'file';
        input.multiple = false;
        input.accept = '*/*';

        input.onchange = function (e) {
            const file = e.target.files[0];
            if (!file) return;

            // Función para subir el archivo usando XHR
            const uploadFile = function(folder_name) {
                // Crear FormData para enviar el archivo correctamente
                const formData = new FormData();
                formData.append('file', file, file.name);
                formData.append('doctype', me.frm.doctype);
                formData.append('docname', me.frm.docname);
                formData.append('subfolders', folder_name || '');
                formData.append('is_private', '0');
                
                // Mostrar indicador de carga
                frappe.show_progress('Subiendo archivo...', 0, 100, 'Por favor espere');
                
                // Usar XMLHttpRequest para enviar multipart/form-data
                const xhr = new XMLHttpRequest();
                xhr.open('POST', '/api/method/frappe_s3_attachment.methods.upload_file_to_folder', true);
                xhr.setRequestHeader('X-Frappe-CSRF-Token', frappe.csrf_token);
                
                xhr.upload.onprogress = function(e) {
                    if (e.lengthComputable) {
                        const percent = Math.round((e.loaded / e.total) * 100);
                        frappe.show_progress('Subiendo archivo...', percent, 100, 'Por favor espere');
                    }
                };
                
                xhr.onload = function() {
                    frappe.hide_progress();
                    if (xhr.status === 200) {
                        try {
                            const response = JSON.parse(xhr.responseText);
                            if (response.exc) {
                                frappe.msgprint(__('Error al subir archivo'));
                            } else {
                                frappe.show_alert({
                                    message: __('Archivo subido correctamente'),
                                    indicator: 'green'
                                });
                                // Recargar el documento y refrescar el árbol
                                me.frm.reload_doc().then(() => {
                                    me.refresh();
                                });
                            }
                        } catch (parseError) {
                            frappe.msgprint(__('Error al procesar la respuesta'));
                        }
                    } else {
                        frappe.msgprint(__('Error al subir archivo'));
                    }
                };
                
                xhr.onerror = function() {
                    frappe.hide_progress();
                    frappe.msgprint(__('Error de conexión al subir archivo'));
                };
                
                xhr.send(formData);
            };

            // Determinar el nombre de la carpeta basado en parent_folder_id
            if (parent_folder_id && parent_folder_id !== "Home") {
                // Obtener el nombre de la carpeta desde la base de datos
                frappe.call({
                    method: 'frappe.client.get_value',
                    args: {
                        doctype: 'File',
                        name: parent_folder_id,
                        fieldname: 'file_name'
                    },
                    callback: function (r) {
                        const folder_name = (r.message && r.message.file_name) ? r.message.file_name : null;
                        uploadFile(folder_name);
                    }
                });
            } else {
                // Si no hay carpeta específica, subir a la raíz del documento
                uploadFile(null);
            }
        };

        input.click();
    }


    upload_file(dataUrl, filename, parent_folder_id) {
        //console.log("Uploading file:", filename, "to folder:", parent_folder_id);
        frappe.call({
            method: 'frappe_s3_attachment.methods.upload_file_to_folder',
            args: {
                doctype: this.frm.doctype,
                docname: this.frm.docname,
                parent: parent_folder_id,
                filename: filename,
                filedata: dataUrl,
                is_private: 1
            },
            callback: () => this.frm.reload_doc()
        });
    }

    delete_folder(folder_id) {
        frappe.call({
            method: 'frappe_s3_attachment.methods.delete_empty_folder',
            args: { folder_id },
            callback: r => {
                if (r.exc) {
                    frappe.msgprint(__('No se puede eliminar la carpeta porque no está vacía'));
                } else {
                    this.frm.reload_doc();
                }
            }
        });
    }
};


