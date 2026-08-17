"use strict";

const tokenKey = "kkobung_admin_token";
const loginPanel = document.querySelector("#login-panel");
const dashboard = document.querySelector("#dashboard");
const tokenForm = document.querySelector("#token-form");
const tokenInput = document.querySelector("#admin-token");
const loginError = document.querySelector("#login-error");
const actionMessage = document.querySelector("#action-message");
const backupList = document.querySelector("#backup-list");
const emptyBackups = document.querySelector("#empty-backups");

function token() { return sessionStorage.getItem(tokenKey) || ""; }
function headers() { return { Authorization: `Bearer ${token()}` }; }
function showMessage(element, message, error = false) {
    element.textContent = message;
    element.classList.toggle("admin-error", error);
    element.hidden = false;
}
function hideMessage(element) { element.hidden = true; }

async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: { ...headers(), ...(options.headers || {}) } });
    if (response.status === 401) throw new Error("관리자 토큰이 올바르지 않습니다.");
    if (!response.ok) {
        let detail = "요청을 처리하지 못했습니다.";
        try { detail = (await response.json()).detail || detail; } catch (_) {}
        throw new Error(detail);
    }
    return response;
}

function setText(selector, value) { document.querySelector(selector).textContent = value; }

async function loadDashboard() {
    const [infoResponse, backupsResponse] = await Promise.all([api("/admin/db-info"), api("/admin/backups")]);
    const info = await infoResponse.json();
    const backups = await backupsResponse.json();
    setText("#player-count", info.players);
    setText("#match-count", info.matches);
    setText("#database-size", info.size_mb);
    setText("#backup-count", info.backup_count);
    renderBackups(backups);
    loginPanel.hidden = true;
    dashboard.hidden = false;
}

function renderBackups(backups) {
    backupList.replaceChildren();
    emptyBackups.hidden = backups.length !== 0;
    for (const backup of backups) {
        const row = document.createElement("tr");
        const name = document.createElement("td");
        const created = document.createElement("td");
        const size = document.createElement("td");
        const actions = document.createElement("td");
        const button = document.createElement("button");
        name.textContent = backup.name;
        created.textContent = new Date(backup.created_at).toLocaleString("ko-KR");
        size.textContent = `${backup.size_mb} MB`;
        button.type = "button";
        button.className = "admin-download-button";
        button.textContent = "다운로드";
        button.addEventListener("click", () => downloadBackup(backup.name, button));
        actions.append(button);
        row.append(name, created, size, actions);
        backupList.append(row);
    }
}

async function downloadBackup(filename, button) {
    button.disabled = true;
    try {
        const response = await api(`/admin/backups/${encodeURIComponent(filename)}/download`);
        const url = URL.createObjectURL(await response.blob());
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        link.click();
        URL.revokeObjectURL(url);
    } catch (error) { showMessage(actionMessage, error.message, true); }
    finally { button.disabled = false; }
}

tokenForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    hideMessage(loginError);
    sessionStorage.setItem(tokenKey, tokenInput.value.trim());
    try { await loadDashboard(); }
    catch (error) { sessionStorage.removeItem(tokenKey); showMessage(loginError, error.message, true); }
});

document.querySelector("#refresh-button").addEventListener("click", () => loadDashboard().catch((error) => showMessage(actionMessage, error.message, true)));
document.querySelector("#logout-button").addEventListener("click", () => { sessionStorage.removeItem(tokenKey); location.reload(); });
document.querySelector("#create-backup-button").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    hideMessage(actionMessage);
    try {
        const response = await api("/admin/backup", { method: "POST" });
        const result = await response.json();
        showMessage(actionMessage, `백업을 만들었습니다: ${result.backup}`);
        await loadDashboard();
    } catch (error) { showMessage(actionMessage, error.message, true); }
    finally { button.disabled = false; }
});

if (token()) loadDashboard().catch(() => sessionStorage.removeItem(tokenKey));
