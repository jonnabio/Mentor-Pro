// Mentor Pro tutor review (T026, ADR-024). Plain JavaScript; no framework.
// Every request carries the tutor code (X-Tutor-Token); the server also requires a local (loopback) address.
// Scores are the official 0-4 rubric descriptors; nothing is graded automatically.
"use strict";

const TOKEN_KEY = "mentorpro.tutor";
const $ = (id) => document.getElementById(id);
const tutor = { submission: null, busy: false };
const STATUS_ES = { pending: "Pendiente", in_progress: "En revisión", completed: "Completada" };
const LEVEL_TYPE = { conventions_editing: "Corrección de texto", introduction_paragraph: "Párrafo de introducción",
  development_paragraphs: "Párrafos de desarrollo", conclusion_paragraph: "Párrafo de conclusión",
  guided_composition: "Composición guiada" };

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
}

function token() {
  try {
    return sessionStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return tutor.token || "";
  }
}

function showError(message) {
  $("tutor-error").textContent = message || "";
  $("tutor-error").hidden = !message;
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { ...options,
      headers: { "Content-Type": "application/json", "X-Tutor-Token": token() } });
  } catch {
    throw new Error("No hay conexión con el servidor.");
  }
  const body = await response.json().catch(() => ({}));
  if (response.status === 403 || response.status === 404 && !body.error) {
    try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
    showPanel("login");
    throw new Error("Código de tutor incorrecto o revisión no disponible en este equipo.");
  }
  if (!response.ok) throw new Error(body.message_es || "No fue posible completar la solicitud.");
  return body;
}

function showPanel(name) {
  for (const id of ["tutor-login", "tutor-queue", "tutor-detail"]) $(id).hidden = id !== `tutor-${name}`;
  window.scrollTo({ top: 0 });
}

async function openQueue() {
  showError("");
  const data = await api("/api/tutor/queue").catch((error) => { showError(error.message); return null; });
  if (!data) return;
  showPanel("queue");
  $("tutor-queue-empty").hidden = data.submissions.length > 0;
  $("tutor-list").replaceChildren(...data.submissions.map((s) => {
    const button = el("button", { type: "button", class: "exercise-choice", "data-submission": s.submission_id },
      el("span", { class: "level-label" }, s.title_es),
      el("span", { class: "meta-line" }, `${s.level_es} · Entregado el ${new Date(s.submitted_at).toLocaleString("es-CR")}`),
      el("span", { class: "meta-line" }, `Criterios: ${s.target_criteria.join(", ")}`),
      el("span", { class: `tutor-badge ${s.status}` }, STATUS_ES[s.status]));
    button.addEventListener("click", () => openSubmission(s.submission_id));
    return el("li", {}, button);
  }));
}

async function openSubmission(id) {
  showError("");
  const data = await api(`/api/tutor/submissions/${encodeURIComponent(id)}`)
    .catch((error) => { showError(error.message); return null; });
  if (!data) return;
  tutor.submission = data;
  const ex = data.exercise;
  showPanel("detail");
  $("tutor-meta").textContent = `${ex.level_es} · ${LEVEL_TYPE[ex.exercise_type] || ex.exercise_type} · ` +
    `revisión ${data.exercise_revision} · entregado el ${new Date(data.submitted_at).toLocaleString("es-CR")}`;
  $("tutor-title").textContent = ex.title_es || ex.topic_es;
  $("tutor-situation").textContent = ex.communicative_situation_es;
  $("tutor-instructions").replaceChildren(...ex.instructions_es.map((t) => el("li", {}, t)));
  $("tutor-deliverable").textContent = `Producto esperado: ${ex.deliverable_es}`;
  $("tutor-source").textContent = ex.source_text_es || "";
  $("tutor-source-block").hidden = !ex.source_text_es;
  $("tutor-student").textContent = data.student_text;
  // T028: guided composition: the exercise's paragraph plan, the planning notes and each paragraph.
  $("tutor-plan").replaceChildren(...ex.scaffolding_es.map((t) => el("li", {}, t)));
  $("tutor-plan-block").hidden = ex.scaffolding_es.length === 0;
  $("tutor-sections-block").hidden = !data.sections;
  $("tutor-student-title").hidden = Boolean(data.sections);
  $("tutor-sections").replaceChildren(...(data.sections || []).map((s) => el("div", { class: "tutor-section",
    "data-section": s.key }, el("h4", {}, s.label_es),
    el("p", { class: "submitted-text" }, s.text_es || "(sin notas)"))));
  const ref = data.reference;
  $("tutor-reference-block").hidden = !ref;
  if (ref) {
    $("tutor-reference").textContent = ref.corrected_text_es;
    $("tutor-corrections").replaceChildren(...ref.corrections.map((c) =>
      el("li", {}, `${c.criterion}: «${c.error}» → «${c.correction}»`)));
    $("tutor-ambiguities").textContent = ref.ambiguities_es.length
      ? `Correcciones alternativas aceptadas: ${ref.ambiguities_es.join(" ")}` : "";
  }
  $("tutor-note").textContent = `Rúbrica ${data.rubric.rubric_id}. ${data.rubric.counting_note_es}`;
  const saved = data.evaluation ? data.evaluation.record : null;
  const scores = Object.fromEntries((saved ? saved.criterion_scores : []).map((s) => [s.criterion, s]));
  const firstOptional = data.criteria.find((c) => c.optional);
  $("tutor-criteria").replaceChildren(...data.criteria.flatMap((c) => {
    const box = el("fieldset", { class: "tutor-criterion", "data-criterion": c.code },
      el("legend", {}, `${c.code}. ${c.statement_es}${c.optional ? " (opcional)" : ""}`));
    // T028: optional conventions criteria can stay unscored ("Sin calificar").
    if (c.optional) {
      const none = el("input", { type: "radio", name: `score-${c.code}`, value: "" });
      if (!scores[c.code]) none.checked = true;
      box.append(el("label", { class: "tutor-option" }, none, el("span", { class: "points" }, "–"),
        el("span", {}, "Sin calificar")));
    }
    if (c.applicability === "not_evaluable") {
      box.append(el("p", { class: "muted" }, "No evaluable: este criterio requiere evidencia manuscrita y la " +
        "entrega fue escrita en la computadora."));
      return box;
    }
    c.descriptors_es.forEach((text, points) => {
      const input = el("input", { type: "radio", name: `score-${c.code}`, value: String(points) });
      if (scores[c.code] && scores[c.code].points === points) input.checked = true;
      box.append(el("label", { class: "tutor-option" }, input, el("span", { class: "points" }, String(points)),
        el("span", {}, text)));
    });
    if (c !== firstOptional) return [box];
    return [el("h4", { class: "tutor-optional-title" }, "Convenciones (opcional)"),
      el("p", { class: "muted small" }, "Calificá estos criterios solo si el texto da evidencia suficiente. " +
        "No son necesarios para completar la evaluación."), box];
  }));
  const feedback = saved ? saved.feedback_es : { strengths: [], improvements: [] };
  $("tutor-strengths").value = feedback.strengths.join("\n");
  $("tutor-improvements").value = feedback.improvements.join("\n");
  $("tutor-next").value = feedback.next_step || "";
  const locked = data.evaluation && data.evaluation.status === "completed";
  for (const node of $("tutor-form").querySelectorAll("input, textarea, button")) node.disabled = locked;
  $("tutor-locked").hidden = !locked;
  $("tutor-saved").textContent = data.evaluation && !locked
    ? `Evaluación parcial guardada ${new Date(data.evaluation.updated_at).toLocaleString("es-CR")}` : "";
}

function payload(complete) {
  const scores = {};
  for (const c of tutor.submission.criteria) {
    if (c.applicability === "not_evaluable") continue;
    const checked = document.querySelector(`input[name="score-${c.code}"]:checked`);
    scores[c.code] = checked && checked.value !== "" ? Number(checked.value) : null;
  }
  const lines = (id) => $(id).value.split("\n").map((x) => x.trim()).filter(Boolean);
  return { scores, strengths: lines("tutor-strengths"), improvements: lines("tutor-improvements"),
    next_step: $("tutor-next").value.trim() || null, complete };
}

async function save(complete) {
  if (tutor.busy) return;
  tutor.busy = true;
  $("tutor-save").disabled = $("tutor-complete").disabled = true;
  showError("");
  try {
    await api(`/api/tutor/submissions/${encodeURIComponent(tutor.submission.submission_id)}/evaluation`,
      { method: "PUT", body: JSON.stringify(payload(complete)) });
    await openSubmission(tutor.submission.submission_id);
  } catch (error) {
    showError(error.message);
    $("tutor-save").disabled = $("tutor-complete").disabled = false;
  } finally {
    tutor.busy = false;
  }
}

const dialog = $("tutor-dialog");
$("tutor-enter").addEventListener("click", () => {
  const value = $("tutor-token").value.trim();
  try { sessionStorage.setItem(TOKEN_KEY, value); } catch { tutor.token = value; }
  $("tutor-token").value = "";
  openQueue();
});
$("tutor-save").addEventListener("click", () => save(false));
$("tutor-complete").addEventListener("click", () => {
  const missing = tutor.submission.criteria.filter((c) => c.applicability !== "not_evaluable" && !c.optional &&
    !document.querySelector(`input[name="score-${c.code}"]:checked`));
  if (missing.length) {
    showError(`Calificá todos los criterios antes de completar: ${missing.map((c) => c.code).join(", ")}.`);
    return;
  }
  dialog.showModal();
});
$("tutor-dialog-stay").addEventListener("click", () => dialog.close());
$("tutor-dialog-confirm").addEventListener("click", () => { dialog.close(); save(true); });
$("tutor-back").addEventListener("click", openQueue);

if (token()) openQueue();
