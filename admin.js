const loginForm = document.querySelector("#admin-login");
const tokenInput = document.querySelector("#admin-token");
const feedback = document.querySelector("#admin-feedback");
const results = document.querySelector("#admin-results");
const resultsCount = document.querySelector("#results-count");
const submissionList = document.querySelector("#submission-list");
const logoutButton = document.querySelector("#admin-logout");
const contentForm = document.querySelector("#content-form");
const contentFeedback = document.querySelector("#content-feedback");
const contentList = document.querySelector("#content-list");
const cancelEditButton = document.querySelector("#cancel-edit");
let adminToken = "";
let entries = [];
let contentItems = [];
const apiBaseUrl = (window.PNG_HUB_API_BASE_URL || "").replace(/\/+$/, "");

function apiUrl(path) {
  return `${apiBaseUrl}${path}`;
}

function showFeedback(element, message, isError = false) {
  element.textContent = message;
  element.classList.toggle("is-error", isError);
}

async function adminRequest(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    ...options,
    headers: {
      Authorization: `Bearer ${adminToken}`,
      ...(options.body && !(options.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...options.headers,
    },
  });
  if (!response.headers.get("content-type")?.includes("application/json")) {
    throw new Error("The admin API returned a webpage. Open this site at http://127.0.0.1:8000/admin.html.");
  }
  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.error || "The request could not be completed.");
  }
  return result;
}

function addCell(row, child) {
  const cell = document.createElement("td");
  if (child instanceof Node) {
    cell.append(child);
  } else {
    cell.textContent = child;
  }
  row.append(cell);
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function createRoleSelect(selectedRole) {
  const select = document.createElement("select");
  for (const [value, label] of Object.entries({
    student: "Student",
    sponsor: "Sponsor",
    employer: "Employer",
    other: "Community member",
  })) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = value === selectedRole;
    select.append(option);
  }
  return select;
}

function renderEntries() {
  submissionList.replaceChildren();
  for (const [role, label] of Object.entries({
    student: "Students",
    sponsor: "Sponsors",
    employer: "Employers",
    other: "Community members",
  })) {
    const group = entries.filter((entry) => entry.role === role);
    if (group.length === 0) continue;
    const groupRow = document.createElement("tr");
    groupRow.className = "category-group";
    const groupHeading = document.createElement("th");
    groupHeading.scope = "rowgroup";
    groupHeading.colSpan = 6;
    groupHeading.textContent = `${label} (${group.length})`;
    groupRow.append(groupHeading);
    submissionList.append(groupRow);
    for (const entry of group) {
      const row = document.createElement("tr");
      const nameInput = document.createElement("input");
      nameInput.type = "text";
      nameInput.value = entry.name;
      nameInput.maxLength = 120;
      nameInput.setAttribute("aria-label", `Name for ${entry.name}`);
      const roleSelect = createRoleSelect(entry.role);
      const selectedCheckbox = document.createElement("input");
      selectedCheckbox.type = "checkbox";
      selectedCheckbox.checked = Boolean(entry.selected);
      selectedCheckbox.disabled = entry.role !== "student";
      selectedCheckbox.setAttribute("aria-label", `Select ${entry.name} for benefit notification`);
      const saveButton = document.createElement("button");
      saveButton.type = "button";
      saveButton.className = "button button-dark button-small";
      saveButton.textContent = "Save";
      saveButton.addEventListener("click", async () => {
        saveButton.disabled = true;
        try {
          await adminRequest(`/api/admin/interests/${entry.id}`, {
            method: "PATCH",
            body: JSON.stringify({
              name: nameInput.value,
              role: roleSelect.value,
              selected: roleSelect.value === "student" && selectedCheckbox.checked,
            }),
          });
          showFeedback(feedback, "Submission updated.");
          await loadDashboard();
        } catch (error) {
          showFeedback(feedback, error.message, true);
        } finally {
          saveButton.disabled = false;
        }
      });
      addCell(row, nameInput);
      addCell(row, entry.email);
      addCell(row, roleSelect);
      addCell(row, formatDate(entry.submitted_at));
      addCell(row, selectedCheckbox);
      addCell(row, saveButton);
      submissionList.append(row);
    }
  }
}

function resetContentForm() {
  contentForm.reset();
  document.querySelector("#content-id").value = "";
  document.querySelector("#editor-heading").textContent = "Create a post or profile";
  cancelEditButton.hidden = true;
  showFeedback(contentFeedback, "");
}

function editContent(item) {
  document.querySelector("#content-id").value = item.id;
  document.querySelector("#content-kind").value = item.kind;
  document.querySelector("#content-title").value = item.title;
  document.querySelector("#content-author").value = item.author;
  document.querySelector("#content-role").value = item.role;
  document.querySelector("#content-body").value = item.body;
  document.querySelector("#media-url").value = item.media_url;
  document.querySelector("#media-kind").value = item.media_kind;
  document.querySelector("#content-consent").checked = Boolean(item.consent);
  document.querySelector("#content-published").checked = Boolean(item.published);
  document.querySelector("#editor-heading").textContent = "Edit content";
  cancelEditButton.hidden = false;
  document.querySelector("#admin-publish").scrollIntoView({ behavior: "smooth" });
}

function renderContent() {
  contentList.replaceChildren();
  if (contentItems.length === 0) {
    const empty = document.createElement("p");
    empty.className = "privacy-note";
    empty.textContent = "No content yet. Create an announcement, article, profile or media post above.";
    contentList.append(empty);
    return;
  }
  for (const item of contentItems) {
    const card = document.createElement("article");
    card.className = "content-item";
    const heading = document.createElement("h3");
    heading.textContent = item.title;
    const metadata = document.createElement("p");
    metadata.className = "content-meta";
    metadata.textContent = `${item.kind} · ${item.published ? "Published" : "Draft"}${item.author ? ` · ${item.author}` : ""}`;
    const body = document.createElement("p");
    body.textContent = item.body;
    const controls = document.createElement("div");
    controls.className = "form-actions";
    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.className = "button button-dark button-small";
    editButton.textContent = "Edit";
    editButton.addEventListener("click", () => editContent(item));
    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "button button-outline button-small";
    deleteButton.textContent = "Delete";
    deleteButton.addEventListener("click", async () => {
      if (!window.confirm(`Delete “${item.title}”? This cannot be undone.`)) return;
      deleteButton.disabled = true;
      try {
        await adminRequest(`/api/admin/content/${item.id}`, { method: "DELETE" });
        showFeedback(contentFeedback, "Content deleted.");
        await loadDashboard();
      } catch (error) {
        showFeedback(contentFeedback, error.message, true);
      } finally {
        deleteButton.disabled = false;
      }
    });
    controls.append(editButton, deleteButton);
    card.append(heading, metadata);
    if (item.body) card.append(body);
    card.append(controls);
    contentList.append(card);
  }
}

async function loadDashboard() {
  const [dashboard, library] = await Promise.all([
    adminRequest("/api/admin/interests"),
    adminRequest("/api/admin/content"),
  ]);
  entries = dashboard.entries;
  contentItems = library.items;
  renderEntries();
  renderContent();
  resultsCount.textContent = `${dashboard.total} submission${dashboard.total === 1 ? "" : "s"} · ${contentItems.length} content item${contentItems.length === 1 ? "" : "s"}`;
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  adminToken = tokenInput.value;
  const submitButton = loginForm.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  showFeedback(feedback, "Checking access…");
  try {
    await loadDashboard();
    loginForm.hidden = true;
    results.hidden = false;
    tokenInput.value = "";
    showFeedback(feedback, "");
  } catch (error) {
    adminToken = "";
    console.error("Could not open the admin dashboard.", error);
    showFeedback(feedback, error.message, true);
  } finally {
    submitButton.disabled = false;
  }
});

contentForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    id: document.querySelector("#content-id").value
      ? Number(document.querySelector("#content-id").value)
      : undefined,
    kind: document.querySelector("#content-kind").value,
    title: document.querySelector("#content-title").value,
    author: document.querySelector("#content-author").value,
    role: document.querySelector("#content-role").value,
    body: document.querySelector("#content-body").value,
    media_url: document.querySelector("#media-url").value,
    media_kind: document.querySelector("#media-kind").value,
    consent: document.querySelector("#content-consent").checked,
    published: document.querySelector("#content-published").checked,
  };
  const mediaFile = document.querySelector("#media-file").files[0];
  const saveButton = contentForm.querySelector('button[type="submit"]');
  saveButton.disabled = true;
  try {
    if (mediaFile) {
      const uploadData = new FormData();
      uploadData.append("media", mediaFile);
      const upload = await adminRequest("/api/admin/media", {
        method: "POST",
        body: uploadData,
      });
      payload.media_url = upload.url;
      payload.media_kind = upload.media_kind;
    }
    await adminRequest("/api/admin/content", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    resetContentForm();
    showFeedback(contentFeedback, "Content saved.");
    await loadDashboard();
  } catch (error) {
    showFeedback(contentFeedback, error.message, true);
  } finally {
    saveButton.disabled = false;
  }
});

cancelEditButton.addEventListener("click", resetContentForm);

document.querySelector("#draft-email").addEventListener("click", () => {
  const selected = entries.filter((entry) => entry.role === "student" && entry.selected);
  if (selected.length === 0) {
    showFeedback(feedback, "Select and save at least one student first.", true);
    return;
  }
  const query = new URLSearchParams({
    bcc: selected.map((entry) => entry.email).join(","),
    subject: document.querySelector("#email-subject").value,
    body: document.querySelector("#email-message").value,
  });
  const draft = `mailto:?${query.toString()}`;
  if (draft.length > 1800) {
    showFeedback(feedback, "Too many recipients for one email draft. Select a smaller group and create separate drafts.", true);
    return;
  }
  window.location.href = draft;
});

logoutButton.addEventListener("click", () => {
  adminToken = "";
  entries = [];
  contentItems = [];
  loginForm.hidden = false;
  results.hidden = true;
  submissionList.replaceChildren();
  contentList.replaceChildren();
  resetContentForm();
  showFeedback(feedback, "Workspace locked.");
});
