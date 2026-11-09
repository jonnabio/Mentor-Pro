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

const PANELS = ["tutor-login", "tutor-queue", "tutor-detail", "tutor-practice", "tutor-practice-detail"];

function showPanel(name) {
  for (const id of PANELS) $(id).hidden = id !== `tutor-${name}`;
  $("tutor-nav").hidden = name === "login";
  const practice = name.startsWith("practice");
  $("tutor-nav-writing").setAttribute("aria-pressed", String(!practice));
  $("tutor-nav-practice").setAttribute("aria-pressed", String(practice));
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
      ...(s.attempt_number > 1 ? [el("span", { class: "tutor-badge revision" },
        `Mejora (versión ${s.attempt_number})`)] : []),
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
    `revisión ${data.exercise_revision} · ` + (data.attempt_number > 1 ? `Mejora (versión ${data.attempt_number}) · ` : "") +
    `entregado el ${new Date(data.submitted_at).toLocaleString("es-CR")}`;
  renderPrevious(data.previous);
  renderComparison(data.comparison);
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
  $("tutor-student-title").hidden = Boolean(data.sections) || Boolean(data.previous); // T038: titled above
  $("tutor-sections").replaceChildren(...sectionNodes(data.sections));
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

const sectionNodes = (sections) => (sections || []).map((s) => el("div", { class: "tutor-section",
  "data-section": s.key }, el("h4", {}, s.label_es), el("p", { class: "submitted-text" }, s.text_es || "(sin notas)")));

// T038: the response this revision improves, with its completed (locked) evaluation; nothing here is editable.
function renderPrevious(previous) {
  $("tutor-previous-block").hidden = !previous;
  if (!previous) return;
  $("tutor-previous-meta").textContent = `Entregada el ${new Date(previous.submitted_at).toLocaleString("es-CR")}`;
  $("tutor-previous-sections").replaceChildren(...sectionNodes(previous.sections));
  $("tutor-previous-text").textContent = previous.student_text;
  const evaluation = previous.evaluation || { scores: [], feedback_es: { strengths: [], improvements: [] } };
  $("tutor-previous-scores").replaceChildren(...evaluation.scores.map((s) => el("li", { "data-criterion": s.criterion },
    el("span", { class: "objective-text" }, `${s.criterion}. ${s.statement_es}`),
    el("strong", { class: "feedback-points" }, s.status === "scored" ? `${s.points} de 4` : "No evaluable"),
    ...(s.descriptor_es ? [el("span", { class: "meta-line" }, s.descriptor_es)] : []))));
  $("tutor-previous-strengths").replaceChildren(...evaluation.feedback_es.strengths.map((t) => el("li", {}, t)));
  $("tutor-previous-improvements").replaceChildren(...evaluation.feedback_es.improvements.map((t) => el("li", {}, t)));
  $("tutor-previous-next").textContent = evaluation.feedback_es.next_step
    ? `Próximo paso: ${evaluation.feedback_es.next_step}` : "";
  $("tutor-previous-next").hidden = !evaluation.feedback_es.next_step;
}

// T039: first versus improved version per criterion, once both evaluations are completed.
function renderComparison(comparison) {
  $("tutor-comparison").hidden = !comparison;
  if (!comparison) return;
  $("tutor-comparison-summary").textContent = comparison.summary_es;
  $("tutor-comparison-criteria").replaceChildren(...comparison.criteria.map((c) => el("li", { "data-criterion": c.code },
    el("span", { class: "objective-text" }, `${c.code}. ${c.statement_es}`),
    el("strong", { class: "feedback-points" }, c.change_es),
    el("span", { class: "meta-line" }, `Primera: ${c.first_points ?? "sin puntaje"} · Mejora: ${c.improved_points ?? "sin puntaje"}`))));
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

// ------------------------------------------------------------------ practice results (T060, read-only)
// History, each answer and per-question accuracy. Only GET requests; nothing here changes stored data.

const PRACTICE_STATE_ES = { completed: "Completada", left: "Abandonada", in_progress: "En curso",
  not_started: "Sin responder", preparing: "Preparando", failed: "Falló la preparación" };
const DIFFICULTY_ES = { easy: "Fácil", medium: "Media", hard: "Difícil", mixed: "Mixta" };
const SOURCE_ES = { bank: "Banco", generated: "Generada" };
const RESULT_ES = { correct: "Correcta", incorrect: "Incorrecta", unanswered: "Sin responder" };
const practice = { subjects: {} };

const percent = (rate) => (rate === null || rate === undefined ? "sin respuestas" : `${Math.round(rate * 100)} %`);
const when = (iso) => new Date(iso).toLocaleString("es-CR", { dateStyle: "medium", timeStyle: "short" });
const subjectName = (code) => practice.subjects[code] || code;

function practiceQuery() {
  const params = new URLSearchParams();
  for (const [key, id] of [["subject", "pf-subject"], ["objective", "pf-objective"], ["from", "pf-from"],
    ["to", "pf-to"], ["source", "pf-source"]]) {
    const value = $(id).value.trim();
    if (value) params.set(key, value);
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

function composition(c) {
  return `Banco ${c.bank} · Generadas ${c.generated}`;
}

async function openPractice() {
  showError("");
  const query = practiceQuery();
  let history;
  let analytics;
  try {
    [history, analytics] = await Promise.all([api(`/api/tutor/practice/sessions${query}`),
      api(`/api/tutor/practice/questions${query}`)]);
  } catch (error) {
    showError(error.message);
    return;
  }
  showPanel("practice");
  const select = $("pf-subject");
  if (select.options.length === 1) {
    for (const s of history.subjects) select.append(el("option", { value: s.code }, s.name_es));
  }
  for (const s of history.subjects) practice.subjects[s.code] = s.name_es;
  $("practice-list").dataset.query = query; // which filters the list shows (also used by browser tests)
  $("practice-empty").hidden = history.sessions.length > 0;
  $("practice-list").replaceChildren(...history.sessions.map((s) => {
    const objectives = s.objectives.length ? s.objectives.join(", ") : "Toda la materia";
    const button = el("button", { type: "button", class: "exercise-choice", "data-session": s.session_id },
      el("span", { class: "level-label" }, `${subjectName(s.subject)} · ${when(s.created_at)}`),
      el("span", { class: "meta-line" }, `Objetivos: ${objectives} · Dificultad: ${DIFFICULTY_ES[s.difficulty] || s.difficulty}`),
      el("span", { class: "meta-line" }, `${composition(s.composition)} · Respondidas ${s.answered} de ${s.questions}` +
        ` · Correctas ${s.correct} · Precisión ${percent(s.accuracy)}`),
      el("span", { class: `tutor-badge practice-${s.state}` }, PRACTICE_STATE_ES[s.state] || s.state));
    button.addEventListener("click", () => openPracticeSession(s.session_id));
    return el("li", {}, button);
  }));
  const counts = (x) => `Presentadas ${x.served} · Respondidas ${x.answered} · Correctas ${x.correct}` +
    ` · Incorrectas ${x.incorrect} · Sin responder ${x.unanswered}`;
  $("practice-groups-empty").hidden = analytics.groups.length > 0;
  $("practice-groups").replaceChildren(...analytics.groups.map((g) => el("li", { "data-group": `${g.objective_code}-${g.difficulty}` },
    el("span", { class: "objective-text" }, `${subjectName(g.subject)} · ${g.objective_code} · ${DIFFICULTY_ES[g.difficulty] || "Sin nivel"}`),
    el("strong", { class: "feedback-points" }, percent(g.success_rate)),
    el("span", { class: "meta-line" }, `${g.questions} preguntas · ${counts(g)}`))));
  $("practice-questions").replaceChildren(...analytics.questions.map((q) => el("li", { "data-source": q.source },
    el("span", { class: "objective-text" }, q.stem),
    el("strong", { class: "feedback-points" }, percent(q.success_rate)),
    el("span", { class: "meta-line" }, `${q.objective_code} · ${DIFFICULTY_ES[q.difficulty] || "Sin nivel"} · ` +
      `${SOURCE_ES[q.source]} · ${counts(q)}`))));
}

async function openPracticeSession(id) {
  showError("");
  let s;
  try {
    s = await api(`/api/tutor/practice/sessions/${encodeURIComponent(id)}`);
  } catch (error) {
    showError(error.message);
    return;
  }
  showPanel("practice-detail");
  $("pd-meta").textContent = `${when(s.created_at)} · ${composition(s.composition)}`;
  $("pd-title").textContent = `${subjectName(s.subject)} · ${PRACTICE_STATE_ES[s.state] || s.state}`;
  $("pd-summary").textContent = `Respondidas ${s.answered} de ${s.questions} · Correctas ${s.correct} · ` +
    `Incorrectas ${s.incorrect} · Sin responder ${s.unanswered} · Precisión ${percent(s.accuracy)}`;
  $("pd-items").replaceChildren(...s.items.map((q) => {
    const options = el("ul", { class: "plain-list review-options" }, ...q.options.map((o) => {
      const tags = [];
      if (o.label === q.chosen_label) tags.push("Respuesta del estudiante");
      if (o.label === q.correct_label) tags.push("Correcta");
      const cls = o.label === q.correct_label ? "is-correct" : (o.label === q.chosen_label ? "is-wrong" : "");
      return el("li", { class: cls, "data-label": o.label }, `${o.label}. ${o.text}`,
        ...tags.map((t) => el("span", { class: "option-tag" }, t)));
    }));
    const stimulus = q.stimulus && q.stimulus.text ? [el("p", { class: "source-text" }, q.stimulus.text)] : [];
    return el("li", { "data-slot": String(q.slot), "data-result": q.result },
      el("p", { class: "meta-line" }, `${q.objective_code} · ${DIFFICULTY_ES[q.difficulty] || "Sin nivel"} · ${SOURCE_ES[q.source]}`),
      ...stimulus, el("p", { class: "objective-text" }, q.stem), options,
      el("span", { class: `tutor-badge result-${q.result}` }, RESULT_ES[q.result]),
      el("p", { class: "muted small" }, `Explicación: ${q.explanation}`));
  }));
}

$("tutor-nav-writing").addEventListener("click", openQueue);
$("tutor-nav-practice").addEventListener("click", openPractice);
$("practice-filters").addEventListener("submit", (event) => { event.preventDefault(); openPractice(); });
$("pf-clear").addEventListener("click", () => { $("practice-filters").reset(); openPractice(); });
$("pd-back").addEventListener("click", openPractice);

if (token()) openQueue();
