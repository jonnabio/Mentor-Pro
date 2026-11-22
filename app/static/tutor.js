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

// T071: a question's stimulus is {type: "none"} or {type: "text" | "table", text} (generation/parsing.py), or a
// plain string in older records. Returns a node (or null when there is nothing to show). Built only with DOM nodes
// and text, never innerHTML, so model-authored content cannot inject markup. A table's text becomes a <table> when
// at least two lines are pipe- or tab-delimited; anything else keeps its line breaks, so no content is dropped.
function stimulusText(stimulus) {
  if (typeof stimulus === "string") return stimulus;
  if (stimulus && typeof stimulus === "object" && stimulus.type !== "none" && typeof stimulus.text === "string") {
    return stimulus.text;
  }
  return "";
}

function tableCells(line) {
  const trimmed = line.trim();
  if (trimmed.includes("\t")) return trimmed.split("\t").map((c) => c.trim());
  if (!trimmed.includes("|")) return null;
  return trimmed.replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
}

function renderStimulus(stimulus) {
  const text = stimulusText(stimulus).trim();
  if (!text) return null;
  const box = el("div", { class: "source-text stimulus", "data-stimulus": stimulus.type || "text" });
  const lines = text.split(/\r?\n/);
  const rows = lines.map(tableCells);
  if (stimulus.type !== "table" || rows.filter(Boolean).length < 2) {
    box.textContent = text;
    return box;
  }
  let table = null;
  let header = true;
  lines.forEach((line, i) => {
    const cells = rows[i];
    if (!cells) {
      table = null;
      header = true;
      if (line.trim()) box.append(el("p", {}, line.trim()));
      return;
    }
    if (cells.every((c) => /^:?-{2,}:?$/.test(c))) return; // markdown separator row
    if (!table) {
      table = el("table", { class: "stimulus-table" });
      box.append(table);
    }
    table.append(el("tr", {}, ...cells.map((c) => el(header ? "th" : "td", {}, c))));
    header = false;
  });
  return box;
}

function showStimulus(target, stimulus) {
  const node = renderStimulus(stimulus);
  target.replaceChildren(...(node ? [node] : []));
  target.hidden = !node;
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

const PANELS = ["tutor-login", "tutor-queue", "tutor-detail", "tutor-practice", "tutor-practice-detail",
  "tutor-review", "tutor-coverage"];

function showPanel(name) {
  for (const id of PANELS) $(id).hidden = id !== `tutor-${name}`;
  $("tutor-nav").hidden = name === "login";
  const practice = name.startsWith("practice");
  $("tutor-nav-writing").setAttribute("aria-pressed", String(!practice && name !== "review" && name !== "coverage"));
  $("tutor-nav-practice").setAttribute("aria-pressed", String(practice));
  $("tutor-nav-review").setAttribute("aria-pressed", String(name === "review"));
  $("tutor-nav-coverage").setAttribute("aria-pressed", String(name === "coverage"));
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
  api("/api/tutor/practice/bank").then(renderBank).catch(() => { $("bank-empty").hidden = false; });
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

const TRIGGER_ES = {
  coverage: "Sin preguntas disponibles",
  low_inventory: "Pocas preguntas disponibles",
  performance: "Alta precisión con suficientes respuestas",
};
const REQUEST_STATUS_ES = { open: "Por generar", candidates_generated: "Generadas, esperan su revisión" };

function renderBank(bank) {
  $("bank-empty").hidden = bank.subjects.length > 0;
  $("bank-subjects").replaceChildren(...bank.subjects.map((s) => {
    const t = s.totals;
    const cells = el("ul", { class: "plain-list" }, ...s.cells.filter((c) => c.eligible || c.pending_review ||
      c.served).map((c) => el("li", { class: "meta-line", "data-cell": `${c.objective_code}-${c.difficulty}` },
      `${c.objective_code} · ${DIFFICULTY_ES[c.difficulty]}: disponibles ${c.eligible} · por revisar ` +
      `${c.pending_review} · en cuarentena ${c.quarantined} · respondidas ${c.answered} · precisión ${percent(c.accuracy)}`)));
    return el("li", { "data-bank-subject": s.subject },
      el("span", { class: "objective-text" }, subjectName(s.subject)),
      el("strong", { class: "feedback-points" }, String(t.eligible)),
      el("span", { class: "meta-line" }, `Disponibles ${t.eligible} · Por revisar ${t.pending_review} · ` +
        `En cuarentena ${t.quarantined} · Rechazadas por validación ${t.rejected} · ` +
        `Celdas cubiertas ${t.covered_cells} de ${t.cells} · Medido ${when(s.taken_at)}`), cells);
  }));
  $("bank-pending-empty").hidden = bank.pending.length > 0;
  $("bank-pending").replaceChildren(...bank.pending.map((r) => el("li", { "data-request": r.replenishment_id },
    el("span", { class: "objective-text" }, `${subjectName(r.subject)} · ${r.objective_code} · ${DIFFICULTY_ES[r.difficulty]}`),
    el("span", { class: "tutor-badge" }, REQUEST_STATUS_ES[r.status] || r.status),
    el("span", { class: "meta-line" }, `Motivo: ${TRIGGER_ES[r.trigger] || r.trigger}` +
      (r.evidence.answered ? ` (${r.evidence.answered} respuestas, precisión ${percent(r.evidence.accuracy)})` : "") +
      ` · Preguntas generadas ${r.candidates}`))));
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
    const stimulus = [renderStimulus(q.stimulus)].filter(Boolean);
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

// ---------------------------------------------------------------- T068 question review
// Verdicts go through the existing individual review (one per question, recorded once). The tutor decides;
// the page never preselects a verdict and never approves anything by itself.
const review = { questions: [], index: 0, busy: false, reasons: [] };
const REASON_ES = { wrong_key: "Clave incorrecta", ambiguous: "Ambigua", off_curriculum: "Fuera del programa",
  level: "Nivel o dificultad inadecuados", other: "Otro" };

function reviewQuery() {
  const params = new URLSearchParams();
  for (const [key, id] of [["subject", "rf-subject"], ["objective", "rf-objective"], ["difficulty", "rf-difficulty"],
    ["batch", "rf-batch"]]) {
    const value = $(id).value.trim();
    if (value) params.set(key, value);
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

function renderReviewCounts(counts) {
  $("review-counts").replaceChildren(...counts.map((c) => el("li", { "data-subject": c.subject },
    `${c.name_es}: por revisar ${c.pending} · aprobadas ${c.approved} · en cuarentena ${c.quarantined}`)));
  for (const c of counts) practice.subjects[c.subject] = c.name_es;
  const select = $("rf-subject");
  if (select.options.length === 1) for (const c of counts) select.append(el("option", { value: c.subject }, c.name_es));
}

async function openReview() {
  showError("");
  const data = await api(`/api/tutor/review/queue${reviewQuery()}`)
    .catch((error) => { showError(error.message); return null; });
  if (!data) return;
  showPanel("review");
  review.questions = data.questions;
  review.index = 0;
  review.reasons = data.reasons;
  renderReviewCounts(data.counts);
  const reason = $("review-reason");
  if (reason.options.length === 1) for (const r of data.reasons) reason.append(el("option", { value: r }, REASON_ES[r] || r));
  const batch = $("rf-batch");
  const known = new Set([...batch.options].map((o) => o.value));
  for (const q of data.questions) {
    if (!known.has(q.batch_id)) { batch.append(el("option", { value: q.batch_id }, q.batch_id)); known.add(q.batch_id); }
  }
  $("review-saved").textContent = "";
  $("review-policy").textContent = data.auto_eligibility
    ? "Revisión opcional: las preguntas validadas automáticamente ya están disponibles para el estudiante."
    : "Las preguntas por revisar no se muestran al estudiante hasta que las aprobés.";
  showReviewItem();
  bulk.page = 1; // T071: any filter change or reload starts on page 1 with an empty selection
  $("bulk-result").textContent = "";
  await Promise.all([loadBulk(), loadReports()]);
}

// ------------------------------------------------------------------ student reports (T072, ADR-038)
const REPORT_REASON_ES = { wrong_answer: "La respuesta parece incorrecta", confusing: "La pregunta es confusa",
  missing_info: "Falta información", display: "La imagen o tabla no se muestra bien", other: "Otro problema" };
const reports = { busy: false, reasons: [] };

async function loadReports() {
  const data = await api("/api/tutor/reports").catch((error) => { showError(error.message); return null; });
  if (!data) return;
  reports.reasons = data.reasons;
  $("reports-empty").hidden = data.questions.length > 0;
  $("reports-list").replaceChildren(...data.questions.map(reportRow));
}

function reportRow(q) {
  const options = el("ol", { class: "plain-list review-options" }, ...q.options.map((o) => {
    const key = o.label === q.answer_key;
    return el("li", { class: key ? "review-key" : "" }, `${o.label}. ${o.text}${key ? " ✓ Respuesta propuesta" : ""}`);
  }));
  const v = q.validation || {};
  const evidence = `Validación automática: ${v.checker_verdict || "sin dato"} (${v.checker_version || "?"})` +
    (v.independent_solve_agrees === true ? " · resolución independiente coincide" : "") +
    (v.rubric ? ` · rúbrica ${Object.values(v.rubric).join("/")}` : "") +
    (q.tutor_verdict ? ` · decisión del tutor: ${q.tutor_verdict === "approved" ? "aprobada" : "en cuarentena"}` : "");
  const use = q.used_in || {};
  const items = q.reports.map((r) => el("li", {}, `${when(r.created_at)} · ${REPORT_REASON_ES[r.reason] || r.reason}` +
    (r.comment ? ` · «${r.comment}»` : "") + (r.same_content ? "" : " · (versión distinta de la actual)")));
  const reason = el("select", { class: "report-reason", "aria-label": "Motivo de cuarentena" },
    el("option", { value: "" }, "Motivo de cuarentena"),
    ...reports.reasons.map((r) => el("option", { value: r }, REASON_ES[r] || r)));
  const comment = el("input", { type: "text", class: "report-comment", maxlength: "1000",
    placeholder: "Comentario (opcional)", "aria-label": "Comentario" });
  const keep = el("button", { type: "button", class: "secondary report-retain" }, "Mantener (pregunta válida)");
  const quarantine = el("button", { type: "button", class: "primary report-quarantine" }, "Cuarentena");
  keep.addEventListener("click", () => resolveReport(q.request_id, "retain", "", comment.value));
  quarantine.addEventListener("click", () => {
    if (!reason.value) { $("reports-result").textContent = "Elegí el motivo de la cuarentena."; reason.focus(); return; }
    resolveReport(q.request_id, "quarantine", reason.value, comment.value);
  });
  return el("li", { class: "report-item", "data-request": q.request_id },
    el("details", { open: "" },
      el("summary", {}, `${subjectName(q.subject)} · ${q.objective_code} · ${DIFFICULTY_ES[q.difficulty] || q.difficulty}` +
        ` · ${q.reports.length} reporte(s)`),
      el("ul", { class: "plain-list report-reasons-list" }, ...items),
      ...[renderStimulus(q.stimulus)].filter(Boolean),
      el("p", { class: "submitted-text" }, q.stem || ""), options,
      el("p", { class: "bulk-explanation" }, `Explicación: ${q.explanation || "Sin explicación."}`),
      el("p", { class: "muted small" }, evidence),
      el("p", { class: "muted small" }, `Usada en ${use.sessions || 0} práctica(s) · respondida ${use.answered || 0}` +
        ` vez/veces · correctas ${use.correct || 0}. Las calificaciones anteriores no cambian.`),
      el("div", { class: "actions" }, reason, comment, keep, quarantine)));
}

async function resolveReport(requestId, action, reason, comment) {
  if (reports.busy) return;
  reports.busy = true;
  try {
    const out = await api(`/api/tutor/reports/${encodeURIComponent(requestId)}/resolve`, {
      method: "POST", body: JSON.stringify({ action, reason, comment }),
    });
    $("reports-result").textContent = out.status === "retained"
      ? "Pregunta mantenida: vuelve a estar disponible para prácticas nuevas."
      : "Pregunta en cuarentena: ya no se usará.";
  } catch (error) {
    $("reports-result").textContent = error.message;
  } finally {
    reports.busy = false;
  }
  await Promise.all([loadReports(), loadBulk()]);
}

function showReviewItem() {
  const q = review.questions[review.index];
  $("review-empty").hidden = Boolean(q);
  $("review-item").hidden = !q;
  if (!q) return;
  $("review-item").dataset.request = q.request_id;
  $("review-progress").textContent = `Pregunta ${review.index + 1} de ${review.questions.length}`;
  $("review-meta").textContent = `${subjectName(q.subject)} · ${q.objective_code} · ` +
    `${DIFFICULTY_ES[q.difficulty] || q.difficulty} · Lote ${q.batch_id} · Solicitud ${q.request_id}`;
  $("review-objective").textContent = `Objetivo ${q.objective_code}: ${q.objective_es}`;
  $("review-evidence").textContent = q.evidencia_es ? `Evidencia: ${q.evidencia_es}` : "";
  showStimulus($("review-stimulus"), q.stimulus);
  $("review-stem").textContent = q.stem;
  $("review-options").replaceChildren(...q.options.map((o) => {
    const key = o.label === q.answer_key;
    return el("li", { class: key ? "review-key" : "", "data-label": o.label },
      `${o.label}. ${o.text}${key ? " ✓ Respuesta propuesta" : ""}`);
  }));
  $("review-explanation").textContent = q.explanation || "Sin explicación.";
  for (const input of document.querySelectorAll('input[name="review-verdict"]')) input.checked = false;
  $("review-reason").value = "";
  $("review-reason").disabled = true;
  $("review-comment").value = "";
  $("review-submit").disabled = false;
}

async function submitReview() {
  const q = review.questions[review.index];
  const chosen = document.querySelector('input[name="review-verdict"]:checked');
  if (!q || review.busy) return;
  if (!chosen) { showError("Elegí aprobar o cuarentena."); return; }
  const verdict = chosen.value;
  const reason = verdict === "quarantined" ? $("review-reason").value : "";
  if (verdict === "quarantined" && !reason) { showError("Elegí el motivo de la cuarentena."); return; }
  showError("");
  review.busy = true;
  $("review-submit").disabled = true; // no second submission while one is in flight
  try {
    const out = await api("/api/tutor/review/decisions", { method: "POST", body: JSON.stringify({
      request_id: q.request_id, verdict, reason, comment: $("review-comment").value.trim() }) });
    renderReviewCounts(out.counts);
    $("review-saved").textContent = verdict === "approved" ? `Aprobada: ${q.request_id}`
      : `En cuarentena (${REASON_ES[reason] || reason}): ${q.request_id}`;
    review.questions.splice(review.index, 1);
    if (review.index >= review.questions.length) review.index = 0;
    showReviewItem();
    loadBulk(); // T071: refresh the bulk list without holding `busy` (the next question is already shown)
  } catch (error) {
    showError(error.message);
    $("review-submit").disabled = false;
  } finally {
    review.busy = false;
  }
}

for (const input of document.querySelectorAll('input[name="review-verdict"]')) {
  input.addEventListener("change", () => { $("review-reason").disabled = input.value !== "quarantined" || !input.checked; });
}
$("tutor-nav-review").addEventListener("click", openReview);
$("review-filters").addEventListener("submit", (event) => { event.preventDefault(); openReview(); });
$("rf-clear").addEventListener("click", () => { $("review-filters").reset(); openReview(); });
$("review-submit").addEventListener("click", submitReview);
$("review-skip").addEventListener("click", () => {
  if (!review.questions.length) return;
  review.index = (review.index + 1) % review.questions.length;
  $("review-saved").textContent = "";
  showReviewItem();
});

// ---------------------------------------------------------------- T069: quiz-size coverage (read-only)

const LEVEL_ES = { easy: "fácil", medium: "media", hard: "difícil" };
const BLOCKER_ES = {
  structural: "el plan de generación no tiene celdas suficientes",
  generation: "faltan preguntas por generar",
  review: "hay preguntas generadas que esperan tu revisión",
  duplicates: "las preguntas alcanzan, pero hay preguntas demasiado parecidas",
};

function sizeLine(s) {
  if (s.available) return el("li", { "data-size": String(s.size), class: "coverage-ok" }, `${s.size} preguntas: disponible`);
  const why = BLOCKER_ES[s.blocker] || "faltan preguntas aprobadas";
  return el("li", { "data-size": String(s.size) },
    `${s.size} preguntas: no disponible. Faltan ${s.missing.approved} aprobadas; ${why}.`);
}

function blockerLine(b, kind) {
  const name = kind === "objective" ? b.objective_code : `Nivel ${LEVEL_ES[b.difficulty] || b.difficulty}`;
  const pending = b.pending ? ` · por revisar ${b.pending} que podrían cubrirlo` : "";
  return el("li", { "data-blocker": kind === "objective" ? b.objective_code : b.difficulty },
    `${name}: necesita ${b.needed}, aprobadas ${b.approved}, faltan ${b.missing}${pending}`);
}

function cellText(c) {
  return `${c.approved} / ${c.pending} / ${c.plan}`;
}

async function openCoverage() {
  showError("");
  const select = $("cv-subject");
  const subject = select.value || "matematicas";
  const data = await api(`/api/tutor/coverage?subject=${encodeURIComponent(subject)}`)
    .catch((error) => { showError(error.message); return null; });
  if (!data) return;
  showPanel("coverage");
  if (!select.options.length) {
    for (const s of data.subjects) select.append(el("option", { value: s.subject }, s.name_es));
  }
  select.value = data.subject;
  const sizes = data.available_sizes.length ? data.available_sizes.join(", ") : "ninguno";
  $("cv-summary").textContent = `${data.name_es}: tamaños disponibles ${sizes}. Aprobadas ${data.approved}, `
    + `por revisar ${data.pending}, ${data.objectives} objetivos.`;
  const p = data.progress;
  $("cv-progress").textContent = `Hacia ${p.size} preguntas: ${p.approved_fill} de ${p.size} lugares cubiertos `
    + `con aprobadas; ${p.with_pending_fill} si se aprobaran todas las que esperan revisión.`;
  $("cv-sizes").replaceChildren(...data.sizes.map(sizeLine));
  const next = data.sizes.find((s) => !s.available);
  $("cv-next-title").hidden = $("cv-next-note").hidden = !next;
  if (next) {
    $("cv-next-title").textContent = `Qué falta para ${next.size} preguntas`;
    $("cv-next-note").textContent = "Cada objetivo y nivel tiene un mínimo; las preguntas por revisar solo cuentan "
      + "después de que las aprobés.";
    $("cv-blockers").replaceChildren(...next.gap.objectives.map((b) => blockerLine(b, "objective")),
      ...next.gap.levels.map((b) => blockerLine(b, "level")));
  } else {
    $("cv-blockers").replaceChildren();
  }
  $("cv-cells").querySelector("tbody").replaceChildren(...data.cells.map((c) => el("tr",
    { "data-objective": c.objective_code }, el("th", { scope: "row" }, c.objective_code),
    el("td", {}, cellText(c.easy)), el("td", {}, cellText(c.medium)), el("td", {}, cellText(c.hard)))));
}

$("tutor-nav-coverage").addEventListener("click", openCoverage);
$("cv-subject").addEventListener("change", openCoverage);

// ---------------------------------------------------------------- T071 bulk approval
// Explicit IDs only. A page selection resets on every filter, page or result change; "Seleccionar todas las
// pendientes" selects every pending question of the applied filters (all pages) and survives page changes. Nothing is
// preselected and nothing is approved without the tutor confirming the exact count. Approvals use the existing
// bulk-approve endpoint in sequential batches of at most BULK_MAX IDs.
const BULK_PAGE_SIZE = Number(window.__bulkPageSize) || 10; // the override exists only for the browser regression
const BULK_MAX = 50; // the API limit per request (tutor_review.BULK_MAX) and the queue's page_size maximum
const bulk = { page: 1, pages: 1, total: 0, query: "", questions: [], selected: new Set(), all: null, busy: false };
const BULK_STATUS_ES = { already_reviewed: "ya tenía una decisión", not_pending: "ya no está pendiente",
  error: "no se pudo registrar" };

async function loadBulk({ keepAll = false } = {}) {
  const query = reviewQuery();
  const params = new URLSearchParams(query.slice(1));
  params.set("page", String(bulk.page));
  params.set("page_size", String(BULK_PAGE_SIZE));
  const data = await api(`/api/tutor/review/queue?${params}`).catch((error) => { showError(error.message); return null; });
  if (!data) return;
  bulk.query = query;
  bulk.questions = data.questions;
  bulk.page = data.pagination.page;
  bulk.pages = data.pagination.pages;
  bulk.total = data.total;
  if (!(keepAll && bulk.all)) clearBulkSelection();
  renderBulk();
}

function clearBulkSelection() {
  bulk.selected.clear();
  bulk.all = null;
}

// Every pending question of the applied filters, page by page: [{request_id, subject}], without duplicates.
async function fetchAllPending(query) {
  const found = new Map();
  for (let page = 1, pages = 1; page <= pages; page += 1) {
    const params = new URLSearchParams(query.slice(1));
    params.set("page", String(page));
    params.set("page_size", String(BULK_MAX));
    const data = await api(`/api/tutor/review/queue?${params}`);
    pages = data.pagination.pages;
    for (const q of data.questions) found.set(q.request_id, q.subject);
  }
  return [...found].map(([request_id, subject]) => ({ request_id, subject }));
}

function scopeText(query) {
  const params = new URLSearchParams(query.slice(1));
  if (![...params.keys()].length) return "Alcance: todas las materias, sin filtros.";
  const parts = [];
  if (params.get("subject")) parts.push(`materia ${subjectName(params.get("subject"))}`);
  if (params.get("objective")) parts.push(`objetivo ${params.get("objective")}`);
  if (params.get("difficulty")) parts.push(`dificultad ${DIFFICULTY_ES[params.get("difficulty")] || params.get("difficulty")}`);
  if (params.get("batch")) parts.push(`lote ${params.get("batch")}`);
  return `Alcance: solo las preguntas filtradas (${parts.join(", ")}).`;
}

function renderBulk() {
  $("bulk").hidden = bulk.questions.length === 0;
  $("bulk-list").replaceChildren(...bulk.questions.map((q) => {
    const box = el("input", { type: "checkbox", class: "bulk-check", "data-request": q.request_id,
      "aria-label": `Seleccionar ${q.request_id}` });
    box.checked = bulk.selected.has(q.request_id);
    box.addEventListener("change", () => {
      if (box.checked) bulk.selected.add(q.request_id); else bulk.selected.delete(q.request_id);
      updateBulkButton();
    });
    const options = el("ol", { class: "plain-list review-options" }, ...q.options.map((o) => {
      const key = o.label === q.answer_key;
      return el("li", { class: key ? "review-key" : "" }, `${o.label}. ${o.text}${key ? " ✓ Respuesta propuesta" : ""}`);
    }));
    const details = el("details", {},
      el("summary", {}, `${subjectName(q.subject)} · ${q.objective_code} · ` +
        `${DIFFICULTY_ES[q.difficulty] || q.difficulty} · ${q.stem.slice(0, 80)}`),
      el("p", { class: "muted small" }, `Objetivo ${q.objective_code}: ${q.objective_es}`),
      el("p", { class: "muted small" }, q.evidencia_es ? `Evidencia: ${q.evidencia_es}` : ""),
      ...[renderStimulus(q.stimulus)].filter(Boolean),
      el("p", { class: "submitted-text" }, q.stem), options,
      el("p", { class: "bulk-explanation" }, `Explicación: ${q.explanation || "Sin explicación."}`),
      el("p", { class: "muted small" }, `Lote ${q.batch_id} · Solicitud ${q.request_id}`));
    return el("li", { class: "bulk-row", "data-request": q.request_id }, box, details);
  }));
  $("bulk-page").textContent = `Página ${bulk.page} de ${bulk.pages} · ${bulk.total} por revisar`;
  $("bulk-prev").disabled = bulk.page <= 1;
  $("bulk-next").disabled = bulk.page >= bulk.pages;
  updateBulkButton();
}

function updateBulkButton() {
  $("bulk-approve").textContent = `Aprobar seleccionadas (${bulk.selected.size})`;
  $("bulk-approve").disabled = bulk.busy || bulk.selected.size === 0;
  $("bulk-select-all").textContent = `Seleccionar todas las pendientes (${bulk.total})`;
  $("bulk-select-all").disabled = bulk.busy || bulk.total === 0;
  $("bulk-select-page").disabled = bulk.busy;
  $("bulk-clear").disabled = bulk.busy;
  $("bulk-scope").textContent = bulk.all
    ? `Seleccionadas ${bulk.selected.size} de ${bulk.all.items.length} pendientes en todas las páginas. ` +
      scopeText(bulk.all.query)
    : "";
}

function setAllBulk(checked) {
  if (bulk.busy) return;
  if (!checked) clearBulkSelection();
  for (const box of document.querySelectorAll(".bulk-check")) {
    box.checked = checked;
    if (checked) bulk.selected.add(box.dataset.request);
  }
  updateBulkButton();
}

async function selectAllPending() {
  if (bulk.busy) return;
  showError("");
  bulk.busy = true;
  updateBulkButton();
  try {
    const query = bulk.query; // the filters the list shows, not unapplied form edits
    const items = await fetchAllPending(query);
    bulk.selected = new Set(items.map((i) => i.request_id));
    bulk.all = { query, items };
    for (const box of document.querySelectorAll(".bulk-check")) box.checked = bulk.selected.has(box.dataset.request);
  } catch (error) {
    showError(error.message);
  } finally {
    bulk.busy = false;
    updateBulkButton();
  }
}

// Resolves true only on "Aprobar"; Cancelar, Escape or closing the dialog resolve false.
function confirmBulk({ count, subjects, scope, dropped }) {
  const dialog = $("bulk-dialog");
  $("bulk-dialog-message").textContent = `¿Aprobar ${count} pregunta${count === 1 ? "" : "s"}?`;
  $("bulk-dialog-subjects").textContent = `Materias: ${subjects.map(subjectName).join(", ")}.`;
  $("bulk-dialog-scope").textContent = scope;
  $("bulk-dialog-dropped").hidden = dropped === 0;
  $("bulk-dialog-dropped").textContent = `${dropped} de las seleccionadas ya no están pendientes y no se enviarán.`;
  return new Promise((resolve) => {
    let answer = false;
    const confirm = () => { answer = true; dialog.close(); };
    const cancel = () => dialog.close();
    $("bulk-dialog-confirm").addEventListener("click", confirm, { once: true });
    $("bulk-dialog-cancel").addEventListener("click", cancel, { once: true });
    dialog.addEventListener("close", () => {
      $("bulk-dialog-confirm").removeEventListener("click", confirm);
      $("bulk-dialog-cancel").removeEventListener("click", cancel);
      resolve(answer);
    }, { once: true });
    dialog.showModal();
  });
}

// Sends `ids` in sequential batches; stops at the first failed request, so nothing already sent is sent again.
async function approveInBatches(ids) {
  const out = { approved: 0, requested: ids.length, refused: [], unsent: 0, error: "" };
  for (let start = 0; start < ids.length; start += BULK_MAX) {
    const chunk = ids.slice(start, start + BULK_MAX);
    $("bulk-result").textContent = `Aprobando… ${start} de ${ids.length} enviadas.`;
    let result;
    try {
      result = await api("/api/tutor/review/bulk-approve", { method: "POST", body: JSON.stringify({ request_ids: chunk }) });
    } catch (error) {
      out.unsent = ids.length - start;
      out.error = error.message;
      break;
    }
    out.approved += result.approved;
    out.refused.push(...result.results.filter((r) => r.status !== "approved")
      .map((r) => `${r.request_id} (${BULK_STATUS_ES[r.status] || r.status})`));
  }
  return out;
}

async function approveBulk() {
  if (!bulk.selected.size || bulk.busy) return;
  showError("");
  bulk.busy = true; // no second submission, selection or confirmation while one is in flight
  updateBulkButton();
  try {
    let ids = [...bulk.selected];
    if (bulk.all) {
      // Revalidate against the live queue: drop what is no longer pending, never add what appeared since.
      const pending = new Map((await fetchAllPending(bulk.all.query)).map((i) => [i.request_id, i.subject]));
      const kept = ids.filter((id) => pending.has(id));
      const subjects = [...new Set(kept.map((id) => pending.get(id)))];
      if (!kept.length) {
        clearBulkSelection();
        await openReview();
        $("bulk-result").textContent = "Ninguna de las preguntas seleccionadas sigue pendiente. No se aprobó nada.";
        return;
      }
      if (!(await confirmBulk({ count: kept.length, subjects, scope: scopeText(bulk.all.query),
        dropped: ids.length - kept.length }))) return;
      ids = kept;
    } else if (!window.confirm(`¿Aprobar ${ids.length} pregunta${ids.length === 1 ? "" : "s"}? ` +
      "Quedarán disponibles para el estudiante.")) return;
    const out = await approveInBatches(ids);
    const parts = [`Se aprobaron ${out.approved} de ${out.requested} preguntas.`];
    if (out.refused.length) parts.push(`No se aprobaron: ${out.refused.join(", ")}.`);
    if (out.unsent) parts.push(`Sin enviar por un error (${out.error}): ${out.unsent}; siguen pendientes.`);
    clearBulkSelection();
    await openReview();
    parts.push(`Quedan ${bulk.total} por revisar.`);
    $("bulk-result").textContent = parts.join(" ");
  } catch (error) {
    showError(error.message);
  } finally {
    bulk.busy = false;
    updateBulkButton();
  }
}

$("bulk-select-page").addEventListener("click", () => setAllBulk(true));
$("bulk-select-all").addEventListener("click", selectAllPending);
$("bulk-clear").addEventListener("click", () => setAllBulk(false));
$("bulk-approve").addEventListener("click", approveBulk);
$("bulk-prev").addEventListener("click", () => { if (bulk.page > 1) { bulk.page -= 1; loadBulk({ keepAll: true }); } });
$("bulk-next").addEventListener("click", () => { if (bulk.page < bulk.pages) { bulk.page += 1; loadBulk({ keepAll: true }); } });

if (token()) openQueue();
