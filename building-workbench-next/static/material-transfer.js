/* A file describes one saved material. Each receiving library assigns its own identity. */
function exportMaterialFile(row) {
    const file = {schema: 'workbench-material/v1', source_revision: row.revision, material: row.content};
    const origin = mcExampleOrigin(row);
    if (origin) file.example_origin = origin;
    const name = row.name.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_');
    rlDownload(name + '-v' + row.revision + '.material.json',
        JSON.stringify(file, null, 2) + '\n', 'application/json;charset=utf-8');
}

function openMaterialImport() {
    mcCheckDraft();
    const dialog = document.createElement('dialog');
    dialog.className = 'library-adoption';
    dialog.setAttribute('aria-label', '导入材料 JSON');
    dialog.innerHTML = `<header class="viewer-head"><h2>导入材料 JSON</h2></header>
        <div class="mc-preview-body">
            <label class="field">选择材料文件<input type="file" accept=".json,application/json"></label>
            <p>核对后将在本机材料库登记独立的 v1。同名材料会保留。</p>
            <p role="status"></p><div data-preview></div>
        </div><footer class="actions"><button data-cancel>取消</button>
        <button data-save class="primary" disabled>确认登记为新材料</button></footer>`;
    dialog.addEventListener('click', event => event.stopPropagation());
    document.body.append(dialog);
    const picker = dialog.querySelector('input');
    const save = dialog.querySelector('[data-save]');
    const cancel = dialog.querySelector('[data-cancel]');
    const status = dialog.querySelector('[role=status]');
    const preview = dialog.querySelector('[data-preview]');
    let content = null;
    let exampleOrigin = null;
    let saving = false;
    cancel.onclick = () => dialog.close();
    dialog.oncancel = event => { if (saving) event.preventDefault(); };
    dialog.onclose = () => dialog.remove();
    picker.onchange = async () => {
        const file = picker.files[0];
        content = null;
        exampleOrigin = null;
        save.disabled = true;
        preview.replaceChildren();
        status.className = '';
        status.textContent = file ? '正在核对材料文件…' : '';
        if (!file) return;
        try {
            if (file.size > 1024 * 1024) throw Error('请选择单份材料 JSON（最大 1 MiB）。');
            let documentData;
            try { documentData = JSON.parse((await file.text()).replace(/^\uFEFF/, '')); }
            catch { throw Error('文件不是有效的 JSON。请选择材料库导出的 JSON 文件。'); }
            const checked = await api('/api/material-library/import-preview', documentData);
            if (!dialog.open || file !== picker.files[0]) return;
            preview.innerHTML = muSummary(checked) + mcTable(checked);
            const source = [checked.property_source?.note, checked.source_note].filter(Boolean).join(' · ');
            if (source) {
                const note = document.createElement('p');
                note.textContent = '来源说明 · ' + source;
                preview.append(note);
            }
            const duplicate = mc().data.versions.some(row => row.name === checked.name);
            status.textContent = checked.name + ' · 来源 v' + documentData.source_revision +
                (duplicate ? '。本机已有同名材料，本次将另建一份。' : '。请核对下列参数。');
            content = checked;
            exampleOrigin = documentData.example_origin || null;
            save.disabled = false;
        } catch (error) {
            if (dialog.open && file === picker.files[0]) {
                status.className = 'warning';
                status.textContent = error.message;
            }
        }
    };
    save.onclick = async () => {
        if (!content || saving) return;
        saving = true;
        save.disabled = cancel.disabled = picker.disabled = true;
        try {
            const row = await api('/api/components', {kind: 'material', name: content.name, content, parent: null, example_origin: exampleOrigin});
            const v = mc();
            v.data.versions.unshift(row);
            v.selected = row.id + ':' + row.revision;
            v.query = '';
            v.filter = 'all';
            v.message = '已导入 ' + row.name + '，本机材料版本 v' + row.revision + '。';
            v.error = '';
            dialog.close();
            render();
        } catch (error) {
            status.className = 'warning';
            status.textContent = error.message;
        } finally {
            saving = false;
            save.disabled = cancel.disabled = picker.disabled = false;
        }
    };
    dialog.showModal();
}

const materialTransferPreviousAction = action;
action = async function(button) {
    const op = button.dataset.materialTransfer;
    if (!op) return materialTransferPreviousAction(button);
    if (mc().pending || !mc().data) throw Error('材料库正在加载，请稍后再试。');
    if (op === 'import') openMaterialImport();
    if (op === 'export') exportMaterialFile(mcRow());
};
