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
const uploadForm = document.querySelector("#upload-form");
const databaseFile = document.querySelector("#database-file");
const uploadMessage = document.querySelector("#upload-message");
const stagedUploadStatus = document.querySelector("#staged-upload-status");
const restoreConfirmation = document.querySelector("#restore-confirmation");
const restoreButton = document.querySelector("#restore-button");
const restoreMessage = document.querySelector("#restore-message");
let uploadIsStaged = false;

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
    const [infoResponse, backupsResponse, uploadResponse, autoBackupResponse] = await Promise.all([
        api("/admin/db-info"),
        api("/admin/backups"),
        api("/admin/upload-db"),
        api("/admin/auto-backup-status"),
    ]);
    const info = await infoResponse.json();
    const backups = await backupsResponse.json();
    const stagedUpload = await uploadResponse.json();
    const autoBackup = await autoBackupResponse.json();
    setText("#player-count", info.players);
    setText("#match-count", info.matches);
    setText("#database-size", info.size_mb);
    setText("#backup-count", info.backup_count);
    renderBackups(backups);
    renderStagedUpload(stagedUpload);
    renderAutoBackupStatus(autoBackup);
    loginPanel.hidden = true;
    dashboard.hidden = false;
}

function renderAutoBackupStatus(status) {
    const badge = document.querySelector("#auto-backup-badge");
    const detail = document.querySelector("#auto-backup-detail");
    badge.className = "admin-status-badge";
    const hour = String(status.scheduled_hour_kst).padStart(2, "0");
    if (!status.enabled || status.status === "disabled") {
        badge.textContent = "사용 안 함";
        badge.classList.add("status-disabled");
        detail.textContent = "자동 백업이 비활성화되어 있습니다.";
    } else if (status.status === "success") {
        badge.textContent = "정상";
        badge.classList.add("status-success");
        const successTime = new Date(status.last_success_at).toLocaleString("ko-KR");
        detail.textContent = `마지막 성공: ${successTime} · ${status.backup} · 매일 ${hour}:00 KST`;
    } else if (status.status === "failed") {
        badge.textContent = "실패";
        badge.classList.add("status-failed");
        const attemptTime = new Date(status.last_attempt_at).toLocaleString("ko-KR");
        detail.textContent = `마지막 시도: ${attemptTime} · ${status.error || "오류 발생"}`;
    } else {
        badge.textContent = "대기 중";
        detail.textContent = `아직 자동 백업 실행 기록이 없습니다. 매일 ${hour}:00 KST에 실행됩니다.`;
    }
}

function renderStagedUpload(upload) {
    uploadIsStaged = upload.staged;
    restoreConfirmation.disabled = !uploadIsStaged;
    restoreConfirmation.value = "";
    restoreButton.disabled = true;
    stagedUploadStatus.textContent = uploadIsStaged
        ? `${upload.upload} (${upload.size_mb} MB) — 업로드 및 기본 검사가 완료되었습니다.`
        : "현재 복원 대기 중인 DB가 없습니다.";
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
        const cleanup = result.deleted_old_backups
            ? ` 오래된 백업 ${result.deleted_old_backups}개를 정리했습니다.`
            : "";
        showMessage(actionMessage, `백업을 만들었습니다: ${result.backup}.${cleanup}`);
        await loadDashboard();
    } catch (error) { showMessage(actionMessage, error.message, true); }
    finally { button.disabled = false; }
});

uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!databaseFile.files.length) return;
    const button = document.querySelector("#upload-button");
    const formData = new FormData();
    formData.append("database", databaseFile.files[0]);
    button.disabled = true;
    hideMessage(uploadMessage);
    try {
        const response = await api("/admin/upload-db", { method: "POST", body: formData });
        const result = await response.json();
        showMessage(uploadMessage, `업로드와 무결성 검사가 완료되었습니다: ${result.upload}`);
        databaseFile.value = "";
        renderStagedUpload({ staged: true, upload: result.upload, size_mb: result.size_mb });
    } catch (error) { showMessage(uploadMessage, error.message, true); }
    finally { button.disabled = false; }
});

restoreConfirmation.addEventListener("input", () => {
    restoreButton.disabled = !uploadIsStaged || restoreConfirmation.value.trim() !== "복원";
});

restoreButton.addEventListener("click", async () => {
    if (!uploadIsStaged || restoreConfirmation.value.trim() !== "복원") return;
    if (!window.confirm("업로드된 DB로 교체하고 서비스를 재시작할까요?")) return;
    restoreButton.disabled = true;
    hideMessage(restoreMessage);
    try {
        await api("/admin/restore", { method: "POST" });
        showMessage(restoreMessage, "복원을 시작했습니다. 서비스가 재시작되므로 약 1분 후 새로고침하세요.");
        stagedUploadStatus.textContent = "복원 처리 및 서비스 재시작 중입니다.";
        uploadForm.querySelectorAll("input, button").forEach((element) => { element.disabled = true; });
    } catch (error) {
        showMessage(restoreMessage, error.message, true);
        restoreButton.disabled = false;
    }
});

if (token()) loadDashboard().catch(() => sessionStorage.removeItem(tokenKey));
