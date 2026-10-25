// Mentor Pro practice page (T003 configuration, T010 practice). Plain JavaScript; no framework.
// All student-facing text is Spanish (Costa Rica). Curricular and question text is rendered
// exactly as returned by the API (textContent, never innerHTML). Answer keys are never sent to
// the browser before an answer is submitted; the server evaluates every answer.
"use strict";

const SESSION_KEY = "mentorpro.session";
const WRITING_KEY = "mentorpro.writing"; // exercise open in Producción escrita, restored after a reload
const BROWSER_KEY = "mentorpro.browser"; // anonymous per-tab token: prefer bank questions not seen yet
const POLL_MS = 3000;

const $ = (id) => document.getElementById(id);
const form = $("practice-form");
const state = {
  objectives: [],
  subjectNames: {},
  requestId: null,      // reused if the same submission is retried (server deduplicates)
  session: null,
  current: 0,           // index into session.questions
  pollTimer: null,
};

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
}

function showError(target, message) {
  target.textContent = message || "";
  target.hidden = !message;
}

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  } catch {
    throw new ApiError("No hay conexión con el servidor. Revise su conexión e intente de nuevo.", 0);
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(body.message_es || "No fue posible completar la solicitud. Intente de nuevo.", response.status);
  }
  return body;
}

function newRequestId() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  return `r-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function storeSession(id) {
  try {
    if (id) sessionStorage.setItem(SESSION_KEY, id);
    else sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // Storage may be unavailable (private mode); the practice still works without resume.
  }
}

function browserToken() {
  try {
    let token = sessionStorage.getItem(BROWSER_KEY);
    if (!token) {
      token = `b-${newRequestId()}`.replace(/[^A-Za-z0-9-]/g, "").slice(0, 64);
      sessionStorage.setItem(BROWSER_KEY, token);
    }
    return token;
  } catch {
    return undefined; // without storage every practice is treated as a new browser
  }
}

function storedSession() {
  try {
    return sessionStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

function show(view) {
  for (const id of ["practice-form", "progress-view", "quiz-view", "result-view", "dashboard-view",
    "writing-view"]) {
    $(id).hidden = id !== view;
  }
  window.scrollTo({ top: 0 });
}

// ------------------------------------------------------------------ configuration

const scope = () => form.elements.scope.value;
const selectedCodes = () =>
  [...form.querySelectorAll('input[name="objective"]:checked')].map((input) => input.value);

async function loadSubjects() {
  try {
    const data = await api("/api/subjects");
    $("notice").textContent = data.notice_es;
    const container = $("subjects");
    container.replaceChildren();
    for (const subject of data.subjects) {
      state.subjectNames[subject.code] = subject.name_es;
      const input = el("input", { type: "radio", name: "subject", value: subject.code });
      input.addEventListener("change", () => loadObjectives(subject.code));
      container.append(el("label", {}, input, subject.name_es,
        el("small", {}, `${subject.objective_count} objetivos`)));
    }
  } catch (error) {
    showError($("load-error"), error.message);
  }
}

async function loadObjectives(subjectCode) {
  showError($("form-error"), "");
  $("objectives-hint").textContent = "Cargando objetivos…";
  try {
    const data = await api(`/api/objectives?subject=${encodeURIComponent(subjectCode)}`);
    state.objectives = data.objectives;
    $("objectives-card").disabled = false;
    $("settings-card").disabled = false;
    renderObjectives();
  } catch (error) {
    showError($("load-error"), error.message);
  }
}

function renderObjectives() {
  const list = $("objectives");
  const mode = scope();
  const previous = new Set(selectedCodes());
  list.replaceChildren();
  let currentBlock = null;
  for (const objective of state.objectives) {
    if (objective.block_name_es !== currentBlock) {
      currentBlock = objective.block_name_es;
      list.append(el("p", { class: "block-title" }, currentBlock));
    }
    const input = el("input", {
      type: mode === "single_objective" ? "radio" : "checkbox",
      name: "objective",
      value: objective.code,
      "aria-describedby": `obj-${objective.code}`,
    });
    if (mode === "subject_simulation") {
      input.checked = true;
      input.disabled = true;
    } else if (previous.has(objective.code) && (mode !== "single_objective" || previous.size === 1)) {
      input.checked = true;
    }
    const text = el("span", { id: `obj-${objective.code}` }, objective.text_es,
      el("span", { class: "meta-line" }, `${objective.numbering_es} · ${objective.evidence_count} evidencias`));
    list.append(el("label", { class: "objective" }, input, el("span", { class: "code" }, objective.code), text));
  }
  updateState();
}

function updateState() {
  const mode = scope();
  const count = selectedCodes().length;
  const hints = {
    single_objective: "Seleccione un objetivo.",
    selected_objectives: `Seleccione dos o más objetivos. Seleccionados: ${count}.`,
    subject_simulation: `Se incluyen los ${state.objectives.length} objetivos de la materia.`,
  };
  $("objectives-hint").textContent = state.objectives.length ? hints[mode] : "Elija primero una materia.";
  const ready =
    state.objectives.length > 0 &&
    (mode === "subject_simulation" || (mode === "single_objective" ? count === 1 : count >= 2));
  $("submit").disabled = !ready;
}

form.addEventListener("change", (event) => {
  state.requestId = null; // a changed configuration is a new request
  if (event.target.name === "subject") $("dashboard-choice").hidden = true;
  if (event.target.name === "scope") renderObjectives();
  else updateState();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("submit");
  if (button.disabled) return;
  button.disabled = true; // blocks repeated clicks while the request is in flight
  button.textContent = "Enviando…";
  showError($("form-error"), "");
  state.requestId = state.requestId || newRequestId();
  const payload = {
    subject: form.elements.subject.value,
    scope: scope(),
    objective_codes: scope() === "subject_simulation" ? [] : selectedCodes(),
    difficulty: form.elements.difficulty.value,
    question_count: Number(form.elements.question_count.value),
    client_request_id: state.requestId,
    browser_token: browserToken(),
  };
  // The server first fills the practice from the validated question bank.
  renderPreparing();
  try {
    const session = await api("/api/practice/sessions", { method: "POST", body: JSON.stringify(payload) });
    state.requestId = null;
    storeSession(session.session_id);
    handleSession(session);
  } catch (error) {
    show("practice-form");
    showError($("form-error"), error.message);
    updateState();
  } finally {
    button.textContent = "Generar práctica";
  }
});

function renderPreparing() {
  show("progress-view");
  $("progress-title").textContent = "Preparando su práctica";
  $("progress-message").textContent = "Preparando práctica con preguntas disponibles…";
  showError($("progress-error"), "");
  $("progress-actions").hidden = true;
  $("progress-hint").hidden = true;
  document.querySelector(".progress").hidden = true;
  $("progress-count").textContent = "";
  $("progress-objectives").replaceChildren();
}

// ------------------------------------------------------------------ generation progress

function handleSession(session) {
  if (session.cancelled) {
    resetToForm(""); // a cancelled practice is never resumed
    return;
  }
  state.session = session;
  if (session.status === "queued" || session.status === "running") {
    renderProgress(session);
    schedulePoll(session.session_id);
  } else if (session.status === "failed") {
    renderProgress(session);
  } else {
    startQuiz(session);
  }
}

function renderProgress(session) {
  show("progress-view");
  const failed = session.status === "failed";
  $("progress-message").textContent = failed ? "" : session.message_es;
  showError($("progress-error"), failed ? session.message_es : "");
  $("progress-actions").hidden = !failed;
  $("progress-title").textContent = failed ? "No se pudo preparar la práctica" : "Preparando su práctica";
  $("progress-hint").hidden = failed;
  document.querySelector(".progress").hidden = failed;
  const total = session.slots_total || 5;
  const done = Math.min(session.slots_done, total);
  $("progress-bar").style.width = `${Math.round((100 * done) / total)}%`;
  document.querySelector(".progress").setAttribute("aria-valuenow", String(done));
  document.querySelector(".progress").setAttribute("aria-valuemax", String(total));
  $("progress-count").textContent = failed ? "" : `Preguntas revisadas: ${done} de ${total}.`;
  const list = $("progress-objectives");
  list.replaceChildren();
  for (const objective of session.objectives) {
    const count = objective.questions === 1 ? "1 pregunta" : `${objective.questions} preguntas`;
    list.append(el("li", {}, el("span", { class: "code" }, objective.code), ` ${objective.text_es} · ${count}`));
  }
}

function schedulePoll(sessionId) {
  clearTimeout(state.pollTimer);
  state.pollTimer = setTimeout(() => poll(sessionId), POLL_MS);
}

async function poll(sessionId) {
  try {
    handleSession(await api(`/api/practice/sessions/${sessionId}`));
  } catch (error) {
    if (error.status === 404) {
      storeSession(null);
      resetToForm(error.message);
      return;
    }
    $("progress-message").textContent = "Reintentando la conexión con el servidor…";
    schedulePoll(sessionId);
  }
}

// ------------------------------------------------------------------ questions

function startQuiz(session) {
  const firstOpen = session.questions.findIndex((q) => !q.answered);
  if (firstOpen === -1 && session.summary) {
    renderResult(session.summary);
    return;
  }
  state.current = firstOpen === -1 ? 0 : firstOpen;
  renderQuestion();
}

function renderQuestion() {
  const session = state.session;
  const question = session.questions[state.current];
  show("quiz-view");
  const notice = session.status === "partial" ? session.message_es : "";
  $("quiz-notice").textContent = notice;
  $("quiz-notice").hidden = !notice;
  $("quiz-position").textContent = `Pregunta ${state.current + 1} de ${session.questions.length}`;
  $("quiz-objective").textContent = question.objective_code;
  const stimulus = question.stimulus && question.stimulus.text ? question.stimulus.text : "";
  $("quiz-stimulus").textContent = stimulus;
  $("quiz-stimulus").hidden = !stimulus;
  $("quiz-stem").textContent = question.stem;
  const options = $("quiz-options");
  options.replaceChildren();
  for (const option of question.options) {
    const input = el("input", { type: "radio", name: "answer", value: option.label });
    input.addEventListener("change", () => { $("answer-submit").disabled = false; });
    options.append(el("label", { class: "option", "data-label": option.label }, input,
      el("span", { class: "option-letter" }, option.label), el("span", {}, option.text)));
  }
  showError($("answer-error"), "");
  $("answer-submit").disabled = true;
  $("answer-submit").hidden = false;
  $("feedback").hidden = true;
  if (question.answered) showFeedback(question);
}

function showFeedback(result) {
  const options = $("quiz-options");
  for (const label of options.querySelectorAll(".option")) {
    const input = label.querySelector("input");
    input.disabled = true;
    input.checked = label.dataset.label === result.chosen_label;
    const isCorrect = label.dataset.label === result.correct_label;
    const isChosen = label.dataset.label === result.chosen_label;
    label.classList.toggle("is-correct", isCorrect);
    label.classList.toggle("is-wrong", isChosen && !result.correct);
    // Not colour alone: a text tag marks the student's answer and the correct one.
    const tag = isCorrect ? (isChosen ? "Su respuesta · correcta" : "Respuesta correcta")
      : isChosen ? "Su respuesta" : "";
    label.querySelector(".option-tag")?.remove();
    if (tag) label.append(el("span", { class: "option-tag" }, tag));
  }
  $("answer-submit").hidden = true;
  const resultText = result.correct
    ? "¡Correcto!"
    : `Incorrecto. La respuesta correcta es la opción ${result.correct_label}.`;
  $("feedback-result").textContent = resultText;
  $("feedback-result").className = `feedback-result ${result.correct ? "ok" : "bad"}`;
  $("feedback-explanation").textContent = result.explanation;
  const last = state.current >= state.session.questions.length - 1;
  $("next").textContent = last ? "Ver resultados" : "Siguiente pregunta";
  $("feedback").hidden = false;
  $("next").focus();
}

$("answer-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const chosen = $("answer-form").elements.answer.value;
  const button = $("answer-submit");
  if (!chosen || button.disabled) return;
  button.disabled = true; // one submission per question; the server also keeps only the first
  showError($("answer-error"), "");
  const question = state.session.questions[state.current];
  try {
    const result = await api(`/api/practice/sessions/${state.session.session_id}/answers`, {
      method: "POST", body: JSON.stringify({ slot: question.slot, label: chosen }),
    });
    Object.assign(question, { answered: true, chosen_label: result.chosen_label, correct: result.correct,
      correct_label: result.correct_label, explanation: result.explanation });
    state.session.summary = result.summary;
    showFeedback(question);
  } catch (error) {
    showError($("answer-error"), error.message);
    button.disabled = false;
  }
});

$("next").addEventListener("click", () => {
  const session = state.session;
  if (state.current < session.questions.length - 1) {
    state.current += 1;
    renderQuestion();
  } else if (session.summary) {
    renderResult(session.summary);
  } else {
    startQuiz(session); // an unanswered question remains
  }
});

// ------------------------------------------------------------------ result

function renderResult(summary) {
  show("result-view");
  $("result-correct").textContent = String(summary.correct);
  $("result-incorrect").textContent = String(summary.incorrect);
  $("result-percentage").textContent = `${summary.percentage} %`;
  const list = $("result-objectives");
  list.replaceChildren();
  for (const objective of summary.objectives) {
    const evidences = el("ul", { class: "plain-list nested" });
    for (const evidence of objective.evidences) {
      evidences.append(el("li", {}, `${evidence.text_es} · ${evidence.correct} de ${evidence.total} correctas`));
    }
    list.append(el("li", {}, el("span", { class: "code" }, objective.code), ` ${objective.text_es}`, evidences));
  }
}

// Leaving a practice never calls the server: its result stays stored, and a new generation job
// starts only when the student presses "Generar práctica" again.
function resetToForm(message) {
  clearTimeout(state.pollTimer);
  state.session = null;
  state.requestId = null;
  storeSession(null);
  show("practice-form");
  showError($("form-error"), message || "");
  updateState();
}

// "Volver al menú principal": the initial screen, with no subject or objectives selected.
function backToMenu() {
  resetToForm("");
  $("dashboard-choice").hidden = true;
  form.reset();
  state.objectives = [];
  $("objectives").replaceChildren();
  $("objectives-card").disabled = true;
  $("settings-card").disabled = true;
  updateState();
}

$("progress-new").addEventListener("click", () => resetToForm(""));
$("result-new").addEventListener("click", () => resetToForm(""));
$("progress-menu").addEventListener("click", backToMenu);
$("result-menu").addEventListener("click", backToMenu);

// ------------------------------------------------------------------ leaving an active practice
// The server marks the practice as cancelled; submitted answers are kept and still count for progress,
// unanswered questions stay unanswered, and no generation is started.

const exitDialog = $("exit-dialog");

$("quiz-exit").addEventListener("click", () => {
  showError($("exit-error"), "");
  $("exit-confirm").disabled = false;
  exitDialog.showModal();
  $("exit-stay").focus();
});

$("exit-stay").addEventListener("click", () => exitDialog.close());

$("exit-confirm").addEventListener("click", async () => {
  const button = $("exit-confirm");
  if (button.disabled || !state.session) return;
  button.disabled = true; // one cancellation request; the server is also idempotent
  try {
    await api(`/api/practice/sessions/${state.session.session_id}/cancel`, { method: "POST" });
  } catch (error) {
    if (error.status !== 404) {
      showError($("exit-error"), error.message);
      button.disabled = false;
      return;
    }
  }
  exitDialog.close();
  backToMenu();
});

// ------------------------------------------------------------------ learning dashboard (T014)
// Statuses come from the server, computed from first attempts on distinct questions; percentages are
// rounded here only for display.

const pct = (value) => (value === null || value === undefined ? "—" : `${Math.round(value * 100)} %`);

async function openDashboard(subjectCode) {
  clearTimeout(state.pollTimer);
  show("dashboard-view");
  showError($("dashboard-error"), "");
  try {
    state.dashboard = await api("/api/dashboard");
  } catch (error) {
    showError($("dashboard-error"), error.message);
    return;
  }
  const data = state.dashboard;
  $("dashboard-notice").textContent = data.notice_es;
  $("dashboard-rule").textContent =
    "El estado de cada objetivo se calcula con el primer intento en preguntas distintas; se necesitan al menos " +
    `${data.min_distinct_questions} preguntas distintas. Las preguntas repetidas cuentan en la precisión de ` +
    "práctica, pero no en el dominio.";
  const tabs = $("dashboard-subjects");
  tabs.replaceChildren();
  const practiced = data.subjects.find((s) => s.total_answers > 0);
  const initial = subjectCode || (practiced || data.subjects[0]).subject;
  for (const subject of data.subjects) {
    const input = el("input", { type: "radio", name: "dashboard-subject", value: subject.subject });
    input.checked = subject.subject === initial;
    input.addEventListener("change", () => renderDashboardSubject(subject.subject));
    tabs.append(el("label", {}, input, subject.name_es));
  }
  // T027: Producción escrita is the fifth component, with its own data and no multiple-choice metrics.
  const input = el("input", { type: "radio", name: "dashboard-subject", value: WRITING_TAB });
  input.checked = initial === WRITING_TAB;
  input.addEventListener("change", () => renderDashboardSubject(WRITING_TAB));
  tabs.append(el("label", {}, input, "Producción escrita"));
  renderDashboardSubject(initial);
}

function renderDashboardSubject(code) {
  $("dashboard-mc").hidden = code === WRITING_TAB;
  $("dashboard-writing").hidden = code !== WRITING_TAB;
  $("dashboard-notice").hidden = code === WRITING_TAB;
  if (code === WRITING_TAB) {
    renderWritingProgress();
    return;
  }
  const data = state.dashboard;
  const subject = data.subjects.find((s) => s.subject === code);
  $("dash-practice").textContent = `${pct(subject.practice_accuracy)} (${subject.total_answers} respuestas)`;
  $("dash-mastery").textContent = pct(subject.mastery_accuracy);
  $("dash-distinct").textContent = String(subject.distinct_questions);
  const counts = $("dashboard-counts");
  counts.replaceChildren();
  for (const status of data.statuses) {
    counts.append(el("li", { class: `status status-${status.code}` }, status.label_es,
      el("strong", {}, String(subject.status_counts[status.code]))));
  }
  const list = $("dashboard-objectives");
  list.replaceChildren();
  for (const objective of subject.objectives) {
    let detail = "Todavía no hay respuestas.";
    if (objective.total_answers) {
      detail = `Dominio ${pct(objective.mastery_accuracy)} · ${objective.distinct_questions} preguntas distintas · ` +
        `${objective.total_answers} respuestas · precisión en la práctica ${pct(objective.practice_accuracy)}`;
      if (objective.repeat_answers) detail += ` · ${objective.repeat_answers} repetidas`;
    }
    const head = el("div", { class: "objective-head" }, el("span", { class: "code" }, objective.code));
    if (objective.status === "needs_reinforcement") head.append(el("span", { class: "priority-tag" }, "Prioridad"));
    head.append(el("span", { class: `status status-${objective.status}` }, objective.status_es));
    const item = el("li", { class: `dash-objective dash-${objective.status}`, "data-code": objective.code },
      head,
      el("span", { class: "objective-text" }, objective.text_es),
      el("span", { class: "meta-line" }, detail));
    if (objective.recommendation_es) item.append(el("p", { class: "recommendation" }, objective.recommendation_es));
    // T019: the action only fills the practice form; the student starts the practice explicitly.
    const label = objective.status === "consolidated_mastery" ? "Repasar este objetivo" : "Practicar este objetivo";
    const action = el("button", { type: "button", class: "secondary dash-practice",
      "aria-label": `${label} ${objective.code}` }, label);
    action.addEventListener("click", () => practiceObjective(code, objective.code));
    item.append(action);
    list.append(item);
  }
}

// ------------------------------------------------------------------ writing progress (T027, ADR-025)
// Scores come only from completed tutor evaluations (0–4, official criterion wording). Coverage is shown apart
// from performance; an unassessed criterion shows no number. No mastery statuses, weights or grade.

const WRITING_TAB = "produccion_escrita";
const shortDate = (iso) => new Date(iso).toLocaleDateString("es-CR", { day: "numeric", month: "long", year: "numeric" });
const points = (value) => value.toLocaleString("es-CR", { maximumFractionDigits: 1 });
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

async function renderWritingProgress() {
  showError($("dw-error"), "");
  let data;
  try {
    data = await api("/api/writing/progress");
  } catch (error) {
    showError($("dw-error"), error.message);
    return;
  }
  const activity = data.activity;
  $("dw-notice").textContent = data.notice_es;
  $("dw-submitted").textContent = String(activity.submitted);
  $("dw-completed").textContent = String(activity.evaluations_completed);
  $("dw-pending").textContent = String(activity.evaluations_pending);
  $("dw-last").textContent = activity.last_practice_at ? shortDate(activity.last_practice_at) : "Todavía no hay práctica";
  $("dw-levels").replaceChildren(...activity.levels.map((level) => el("li", { "data-level": level.code },
    el("span", {}, level.label_es),
    el("span", { class: "meta-line" },
      `${plural(level.evaluated, "evaluado", "evaluados")} · ${plural(level.submitted, "entregado", "entregados")}`))));
  const coverage = data.coverage;
  $("dw-coverage").replaceChildren(...[["evaluated", "Evaluado"], ["pending", "Evaluación pendiente"],
    ["unassessed", "Sin evaluar"]].map(([status, label]) => el("li", { class: `status crit-${status}` }, label,
    el("strong", {}, `${coverage[status]} de ${coverage.total}`))));

  const byDimension = {};
  for (const criterion of data.criteria) (byDimension[criterion.dimension] ||= []).push(criterion);
  $("dw-dimensions").replaceChildren(...data.dimensions.map((dim) => {
    const summary = dim.average_latest_points === null
      ? `Sin evaluar · 0 de ${dim.criteria} criterios evaluados`
      : `Promedio ${points(dim.average_latest_points)} de 4 · ` +
        `${dim.criteria_with_evidence} de ${dim.criteria} criterios evaluados`;
    return el("section", { class: "dw-dimension", "data-dimension": String(dim.ordinal) },
      el("h4", {}, dim.name_es), el("p", { class: "dw-dimension-summary" }, summary),
      el("ul", { class: "plain-list objective-status" }, ...byDimension[dim.ordinal].map(criterionItem)));
  }));
}

function criterionItem(c) {
  const head = el("div", { class: "objective-head" }, el("span", { class: "code" }, c.code),
    el("span", { class: `status crit-${c.status}` }, c.status_es));
  const item = el("li", { class: `dw-criterion dw-${c.status}`, "data-code": c.code }, head,
    el("span", { class: "objective-text" }, c.statement_es));
  let detail = c.status === "pending" ? "Entregado; el tutor todavía no lo ha revisado." : "Todavía no hay evaluación.";
  if (c.evaluations) {
    detail = `Última calificación: ${c.latest_points} de 4 · Mejor: ${c.best_points} de 4 · ` +
      `${plural(c.evaluations, "evaluación", "evaluaciones")} · Última evaluación: ${shortDate(c.latest_at)}`;
    if (c.pending) detail += ` · ${plural(c.pending, "entrega pendiente", "entregas pendientes")}`;
  }
  item.append(el("span", { class: "meta-line" }, detail));
  if (c.not_evaluable) {
    item.append(el("span", { class: "meta-line" }, `No evaluable en ${plural(c.not_evaluable, "texto escrito",
      "textos escritos")} en la computadora (se revisa la letra a mano).`));
  }
  return item;
}

$("dw-open-writing").addEventListener("click", () => openWriting());

// Dashboard → practice form (T019): subject, "Un objetivo", only this objective, Intermedia, 5 questions.
// Nothing is sent to the server here; "Generar práctica" starts the usual bank-then-generation flow.
async function practiceObjective(subjectCode, objectiveCode) {
  backToMenu();
  await subjectsReady;
  const subject = form.querySelector(`input[name="subject"][value="${subjectCode}"]`);
  if (!subject) return;
  subject.checked = true;
  form.querySelector('input[name="scope"][value="single_objective"]').checked = true;
  form.querySelector('input[name="difficulty"][value="medium"]').checked = true;
  form.querySelector('input[name="question_count"][value="5"]').checked = true;
  await loadObjectives(subjectCode);
  const objective = form.querySelector(`input[name="objective"][value="${objectiveCode}"]`);
  if (!objective) return;
  objective.checked = true;
  updateState();
  const chosen = state.objectives.find((o) => o.code === objectiveCode);
  const notice = $("dashboard-choice");
  notice.textContent = `Objetivo elegido desde «Mi progreso»: ${objectiveCode} · ${chosen.text_es} ` +
    "Podés ajustar la dificultad y luego presioná «Generar práctica».";
  notice.hidden = false;
  objective.closest("label").scrollIntoView({ block: "center" });
}

// The subject radios exist only once /api/subjects has answered; the dashboard must open before that too.
$("form-progress").addEventListener("click", () => openDashboard(form.elements.subject?.value || null));
$("result-progress").addEventListener("click", () => openDashboard(state.session && state.session.subject));
$("dashboard-menu").addEventListener("click", () => backToMenu());

// ------------------------------------------------------------------ Producción escrita (T022)
// Stored, validated exercises only; nothing here generates. Typed work: draft saved in PostgreSQL,
// submitted once, then "Pendiente de revisión del tutor". Handwritten (L5) work shows its conditions only.
// The editor disables spell checking and autocorrection so spelling errors stay visible to the tutor.

const writing = { level: null, exercise: null, savedText: "", requestId: null, busy: false, view: 0 };

function rememberWriting(exerciseId) {
  try {
    if (exerciseId) sessionStorage.setItem(WRITING_KEY, exerciseId);
    else sessionStorage.removeItem(WRITING_KEY);
  } catch {
    // Without storage a reload returns to the main menu; the draft is still in PostgreSQL.
  }
}

function rememberedWriting() {
  try {
    return sessionStorage.getItem(WRITING_KEY);
  } catch {
    return null;
  }
}

const countWords = (text) => (text.trim() ? text.trim().split(/\s+/).length : 0);
const difficultyLabel = (code) => ({ easy: "Fácil", medium: "Intermedia", hard: "Difícil" })[code] || code;
const writingDirty = () =>
  Boolean(writing.exercise) && !writing.exercise.submission && !writing.exercise.handwritten &&
  (writing.exercise.guided ? JSON.stringify(guidedSections()) !== writing.savedSections
    : $("writing-text").value !== writing.savedText);

// ------------------------------------------------------------------ guided composition (T028, ADR-026)
// Five stages; one text area per section. Sections are saved in PostgreSQL (draft) on demand, when the stage
// changes, after a pause in typing and before leaving. Nothing generated is ever written into a section.

const GUIDED_STAGE_KEY = "mentorpro.writing.stage";
const AUTOSAVE_MS = 2000;
const guidedFields = () => [...document.querySelectorAll("#writing-guided textarea[data-section]")];

function guidedSections() {
  return Object.fromEntries(guidedFields().map((field) => [field.dataset.section, field.value]));
}

// Same rule as the server: the four paragraphs in order, one blank line apart; the plan is not part of it.
function guidedComposition(sections) {
  return writing.exercise.guided.paragraphs.map((key) => sections[key].trim()).filter(Boolean).join("\n\n");
}

function rememberStage(index) {
  try {
    sessionStorage.setItem(GUIDED_STAGE_KEY, `${writing.exercise.exercise_id}:${index}`);
  } catch {
    // The stage is only a convenience; the sections themselves are in PostgreSQL.
  }
}

function rememberedStage(exerciseId) {
  try {
    const [id, index] = (sessionStorage.getItem(GUIDED_STAGE_KEY) || "").split(":");
    return id === exerciseId ? Number(index) || 0 : 0;
  } catch {
    return 0;
  }
}

function renderGuided() {
  const data = writing.exercise;
  const saved = (data.draft && data.draft.sections) || {};
  for (const field of guidedFields()) field.value = saved[field.dataset.section] || "";
  writing.savedSections = JSON.stringify(guidedSections());
  $("guided-steps").replaceChildren(...data.guided.stages.map((stage, index) => {
    const button = el("button", { type: "button", class: "guided-step", "data-stage": stage.key }, stage.title_es);
    button.addEventListener("click", () => goToStage(index));
    return el("li", {}, button);
  }));
  if (data.draft) saveSeq = Math.max(saveSeq, data.draft.client_seq || 0);
  saveStatus(data.draft ? "saved" : null, data.draft && data.draft.saved_at);
  renderStage(rememberedStage(data.exercise_id));
}

function renderStage(index) {
  const stages = writing.exercise.guided.stages;
  writing.stage = Math.max(0, Math.min(index, stages.length - 1));
  const stage = stages[writing.stage];
  rememberStage(writing.stage);
  for (const button of document.querySelectorAll(".guided-step")) {
    if (button.dataset.stage === stage.key) button.setAttribute("aria-current", "step");
    else button.removeAttribute("aria-current");
  }
  $("guided-title").textContent = stage.title_es;
  $("guided-guidance").textContent = stage.guidance_es;
  $("guided-plan").replaceChildren(...stage.plan_es.map((hint) => el("li", {}, hint)));
  $("guided-plan-block").hidden = stage.plan_es.length === 0;
  for (const box of document.querySelectorAll(".guided-field")) box.hidden = !stage.sections.includes(box.dataset.section);
  const review = stage.key === "review";
  $("guided-review").hidden = !review;
  $("guided-prev").disabled = writing.stage === 0;
  $("guided-next").hidden = review;
  $("guided-submit").hidden = !review;
  updateGuided();
}

function updateGuided() {
  const sections = guidedSections();
  const words = countWords(guidedComposition(sections));
  $("guided-words").textContent = words === 1 ? "1 palabra" : `${words} palabras`;
  const labels = writing.exercise.guided.section_labels_es;
  const missing = writing.exercise.guided.paragraphs.filter((key) => !sections[key].trim()).map((key) => labels[key]);
  $("guided-missing").textContent = missing.length ? `Falta escribir: ${missing.join(", ")}.` : "";
  $("guided-missing").hidden = missing.length === 0;
  $("guided-submit").disabled = missing.length > 0 || writing.busy;
  $("guided-preview").replaceChildren(...writing.exercise.guided.paragraphs
    .filter((key) => sections[key].trim()).map((key) => el("p", { "data-section": key }, sections[key].trim())));
}

async function goToStage(index) {
  if (writingDirty() && !(await saveWritingDraft())) {
    showError($("writing-error"), SAVE_FAILED_ES);
    return;
  }
  showError($("writing-error"), "");
  renderStage(index);
  window.scrollTo({ top: $("writing-guided").offsetTop - 8 });
}

for (const field of guidedFields()) {
  field.addEventListener("input", () => {
    updateGuided();
    scheduleAutosave();
  });
}
$("guided-prev").addEventListener("click", () => goToStage(writing.stage - 1));
$("guided-next").addEventListener("click", () => goToStage(writing.stage + 1));
$("guided-save").addEventListener("click", () => saveWritingDraft());
$("guided-submit").addEventListener("click", async () => {
  updateGuided();
  if (!$("guided-missing").hidden) return;
  if (writingDirty() && !(await saveWritingDraft())) {
    showError($("writing-error"), SAVE_FAILED_ES);
    return;
  }
  showError($("writing-dialog-error"), "");
  $("writing-dialog-confirm").disabled = false;
  writingDialog.showModal();
});

function writingPanel(name) {
  for (const id of ["writing-levels-panel", "writing-list-panel", "writing-exercise-panel"]) {
    $(id).hidden = id !== `writing-${name}-panel`;
  }
  showError($("writing-error"), "");
  window.scrollTo({ top: 0 });
}

async function openWriting() {
  clearTimeout(state.pollTimer);
  show("writing-view");
  writingPanel("levels");
  writing.exercise = null;
  rememberWriting(null);
  const list = $("writing-levels");
  list.replaceChildren(el("li", { class: "muted" }, "Cargando niveles…"));
  const view = ++writing.view;
  try {
    const data = await api("/api/writing/levels");
    if (view !== writing.view) return; // the student moved on before the answer arrived
    list.replaceChildren();
    for (const level of data.levels) {
      const count = level.exercise_count === 1 ? "1 ejercicio" : `${level.exercise_count} ejercicios`;
      const button = el("button", { type: "button", class: "level-choice", "data-level": level.code },
        el("span", { class: "level-label" }, level.label_es),
        el("span", { class: "level-text" }, level.description_es),
        el("span", { class: "meta-line" }, count + (level.handwritten ? " · se escribe a mano" : "")));
      button.addEventListener("click", () => openWritingLevel(level));
      list.append(el("li", {}, button));
    }
  } catch (error) {
    list.replaceChildren();
    showError($("writing-error"), error.message);
  }
}

async function openWritingLevel(level) {
  writing.level = level;
  writingPanel("list");
  $("writing-list-title").textContent = level.label_es;
  const list = $("writing-exercises");
  list.replaceChildren();
  $("writing-empty").hidden = true;
  const view = ++writing.view;
  try {
    const data = await api(`/api/writing/levels/${encodeURIComponent(level.code)}/exercises`);
    // A late answer for a level the student already left must not fill the current list (T027).
    if (view !== writing.view) return;
    $("writing-empty").hidden = data.exercises.length > 0;
    const states = { new: "Sin empezar", draft: "Borrador guardado", submitted: "Pendiente de revisión del tutor" };
    for (const exercise of data.exercises) {
      const button = el("button", { type: "button", class: "exercise-choice", "data-exercise": exercise.exercise_id },
        el("span", { class: "level-label" }, exercise.topic_es),
        el("span", { class: "meta-line" },
          `${difficultyLabel(exercise.difficulty)} · ${states[exercise.state]}` +
          (exercise.evidence_mode === "handwritten" ? " · a mano" : "")));
      button.addEventListener("click", () => openWritingExercise(exercise.exercise_id));
      list.append(el("li", {}, button));
    }
  } catch (error) {
    showError($("writing-error"), error.message);
  }
}

async function openWritingExercise(exerciseId) {
  let data;
  try {
    data = await api(`/api/writing/exercises/${encodeURIComponent(exerciseId)}`);
  } catch (error) {
    rememberWriting(null);
    showError($("writing-error"), error.message);
    return;
  }
  show("writing-view");
  writingPanel("exercise");
  writing.exercise = data;
  writing.requestId = null;
  if (!writing.level || writing.level.code !== data.level) {
    writing.level = { code: data.level, label_es: data.level_label_es }; // after a reload
  }
  rememberWriting(exerciseId);
  $("writing-ex-level").textContent = `${data.level_label_es} · ${difficultyLabel(data.difficulty)}`;
  $("writing-ex-topic").textContent = data.title_es || data.topic_es;
  $("writing-ex-subtitle").textContent = data.title_es ? `Tema: ${data.topic_es}` : "";
  $("writing-ex-subtitle").hidden = !data.title_es;
  // T023 correction exercises: the text with errors stays visible above the editor.
  $("writing-source-text").textContent = data.source_text_es || "";
  $("writing-source").hidden = !data.source_text_es;
  $("writing-ex-situation").textContent = data.communicative_situation_es;
  $("writing-ex-ideas").replaceChildren(...data.suggested_ideas_es.map((idea) => el("li", {}, idea)));
  $("writing-ex-ideas-title").hidden = data.suggested_ideas_es.length === 0;
  $("writing-ex-instructions").replaceChildren(...data.instructions_es.map((text) => el("li", {}, text)));
  $("writing-ex-deliverable").textContent = data.deliverable.description_es;
  $("writing-ex-requirements").replaceChildren(...data.deliverable.requirements_es.map((r) => el("li", {}, r)));
  $("writing-handwritten").textContent = data.handwritten_es || "";
  $("writing-handwritten").hidden = !data.handwritten;
  renderWritingState();
}

function renderWritingState() {
  const data = writing.exercise;
  const submitted = Boolean(data.submission);
  $("writing-editor").hidden = data.handwritten || submitted || Boolean(data.guided);
  $("writing-guided").hidden = data.handwritten || submitted || !data.guided;
  $("writing-submitted").hidden = !submitted;
  if (submitted) {
    $("writing-pending").textContent = `${data.submission.status_es}. Entregado el ` +
      `${new Date(data.submission.submitted_at).toLocaleString("es-CR")} (${data.submission.word_count} palabras).`;
    $("writing-submitted-text").textContent = data.draft ? data.draft.text : "";
    renderWritingFeedback(data.feedback);
    return;
  }
  if (data.handwritten) return;
  if (data.guided) {
    renderGuided();
    return;
  }
  // T024: L1 correction exercises start from a copy of the text with errors; a saved draft always wins.
  // L2-L5 start empty. The copy is not "unsaved work" until the student changes it.
  const text = data.draft ? data.draft.text : (data.editable_source ? data.source_text_es : "");
  $("writing-text").value = text;
  writing.savedText = text;
  $("writing-restore").hidden = !data.editable_source;
  $("writing-text").placeholder = data.source_text_es
    ? "Corregí aquí el texto completo." : "";
  if (data.draft) saveSeq = Math.max(saveSeq, data.draft.client_seq || 0);
  saveStatus(data.draft ? "saved" : null, data.draft && data.draft.saved_at);
  updateWordCount();
}

// T026: the completed tutor review. Scores use the official rubric descriptors; no grade is computed.
function renderWritingFeedback(feedback) {
  $("writing-feedback").hidden = !feedback;
  if (!feedback) return;
  $("writing-feedback-date").textContent =
    `Revisado el ${new Date(feedback.evaluated_at).toLocaleString("es-CR")}`;
  $("writing-feedback-scores").replaceChildren(...feedback.scores.map((s) => el("li", {},
    el("span", { class: "objective-text" }, s.statement_es),
    el("strong", { class: "feedback-points" }, s.status === "scored" ? `${s.points} de ${s.max_points}` : "No evaluable"),
    el("span", { class: "meta-line" }, s.status === "scored" ? s.descriptor_es : s.note_es))));
  for (const [key, title] of [["strengths", "writing-feedback-strengths"], ["improvements", "writing-feedback-improvements"]]) {
    const items = feedback[`${key}_es`];
    $(title).replaceChildren(...items.map((text) => el("li", {}, text)));
    $(title).hidden = items.length === 0;
    $(`${title}-title`).hidden = items.length === 0;
  }
  $("writing-feedback-next").textContent = feedback.next_step_es ? `Próximo paso: ${feedback.next_step_es}` : "";
  $("writing-feedback-next").hidden = !feedback.next_step_es;
}

function updateWordCount() {
  const words = countWords($("writing-text").value);
  $("writing-words").textContent = words === 1 ? "1 palabra" : `${words} palabras`;
  $("writing-submit").disabled = words === 0 || writing.busy;
}

// ------------------------------------------------------------------ draft saving (T030, ADR-028)
// One save in flight at a time; edits made meanwhile are saved right after it. Every request carries an
// increasing client_seq, so the server ignores a delayed older save. "Guardado" appears only after the server
// confirmed; a failed save keeps the text on screen, leaves the earlier draft untouched and offers "Reintentar".
// When the tab is hidden or the page closes, pending edits are sent with a keepalive request.

const SAVE_TEXT = { saving: "Guardando…", saved: "Guardado", error: "No se pudo guardar", dirty: "Cambios sin guardar" };
const KEEPALIVE_LIMIT = 60000; // bytes; browsers cap keepalive bodies at 64 KiB
let saveSeq = 0;
let autosaveTimer = null;
const nextSeq = () => (saveSeq = Math.max(Date.now(), saveSeq + 1));
const draftUrl = (exercise) => `/api/writing/exercises/${encodeURIComponent(exercise.exercise_id)}/draft`;

function saveStatus(state, savedAt) {
  const guided = Boolean(writing.exercise && writing.exercise.guided);
  const target = $(guided ? "guided-saved" : "writing-saved");
  const time = state === "saved" && savedAt
    ? ` ${new Date(savedAt).toLocaleTimeString("es-CR", { hour: "2-digit", minute: "2-digit" })}` : "";
  target.dataset.state = state || "";
  target.textContent = state ? ` · ${SAVE_TEXT[state]}${time}` : "";
  $(guided ? "guided-retry" : "writing-retry").hidden = state !== "error";
}

function currentDraft() {
  const guided = Boolean(writing.exercise.guided);
  const sections = guided ? guidedSections() : null;
  const text = guided ? guidedComposition(sections) : $("writing-text").value;
  const body = JSON.stringify({ ...(guided ? { sections } : { text }), client_seq: nextSeq() });
  return { guided, sections, text, key: guided ? JSON.stringify(sections) : text, body };
}

function markSaved(exercise, draft, saved) {
  if (writing.exercise !== exercise) return; // the student opened another exercise meanwhile
  if (draft.guided) writing.savedSections = draft.key;
  else writing.savedText = draft.text;
  exercise.draft = { text: draft.text, sections: draft.sections, word_count: saved.word_count,
    saved_at: saved.saved_at, client_seq: saved.client_seq };
  saveStatus(writingDirty() ? "dirty" : "saved", saved.saved_at);
}

async function sendDraft() {
  const exercise = writing.exercise;
  const draft = currentDraft();
  saveStatus("saving");
  try {
    markSaved(exercise, draft, await api(draftUrl(exercise), { method: "PUT", body: draft.body }));
    return true;
  } catch {
    if (writing.exercise === exercise) saveStatus("error");
    return false;
  }
}

async function saveWritingDraft() {
  const exercise = writing.exercise;
  if (!exercise || exercise.submission || exercise.handwritten) return true;
  clearTimeout(autosaveTimer);
  if (writing.saving) {
    writing.saveAgain = true;
    return writing.saving;
  }
  writing.saving = (async () => {
    let ok;
    do {
      writing.saveAgain = false;
      ok = await sendDraft();
    } while (ok && writing.saveAgain && writingDirty());
    return ok;
  })();
  try {
    return await writing.saving;
  } finally {
    writing.saving = null;
  }
}

function scheduleAutosave() {
  clearTimeout(autosaveTimer);
  if (!writingDirty()) return;
  saveStatus("dirty");
  autosaveTimer = setTimeout(() => { if (writingDirty()) saveWritingDraft(); }, AUTOSAVE_MS);
}

// Tab hidden or page closing: send pending edits now. keepalive lets the request outlive the page; a body over
// the keepalive limit is sent normally (it may not complete if the page is already gone).
function flushDraft() {
  if (!writingDirty()) return;
  clearTimeout(autosaveTimer);
  const exercise = writing.exercise;
  const draft = currentDraft();
  try {
    fetch(draftUrl(exercise), { method: "PUT", headers: { "Content-Type": "application/json" }, body: draft.body,
      keepalive: new Blob([draft.body]).size < KEEPALIVE_LIMIT })
      .then((response) => (response.ok ? response.json() : Promise.reject(response)))
      .then((saved) => markSaved(exercise, draft, saved))
      .catch(() => { if (writing.exercise === exercise && writingDirty()) saveStatus("error"); });
  } catch {
    saveStatus("error");
  }
}

const SAVE_FAILED_ES = "No se pudo guardar. Tu texto sigue en pantalla; presioná «Reintentar».";

// Leaving keeps the work: unsaved changes are saved as a draft first; a failed save keeps the student here.
async function leaveWriting(target) {
  if (writingDirty() && !(await saveWritingDraft())) {
    showError($("writing-error"), SAVE_FAILED_ES);
    return;
  }
  showError($("writing-error"), "");
  if (target === "list" && writing.level) {
    rememberWriting(null);
    writing.exercise = null;
    openWritingLevel(writing.level);
  } else if (target === "levels" || target === "list") {
    openWriting();
  } else {
    rememberWriting(null);
    writing.exercise = null;
    backToMenu();
  }
}

const writingDialog = $("writing-dialog");
$("form-writing").addEventListener("click", openWriting);
$("writing-text").addEventListener("input", () => {
  updateWordCount();
  scheduleAutosave();
});
$("writing-save").addEventListener("click", saveWritingDraft);
$("writing-retry").addEventListener("click", saveWritingDraft);
$("guided-retry").addEventListener("click", saveWritingDraft);
$("writing-back-levels").addEventListener("click", () => leaveWriting("levels"));
$("writing-back-list").addEventListener("click", () => leaveWriting("list"));
$("writing-menu").addEventListener("click", () => leaveWriting("menu"));
$("writing-submit").addEventListener("click", () => {
  if (countWords($("writing-text").value) === 0) return;
  showError($("writing-dialog-error"), "");
  $("writing-dialog-confirm").disabled = false;
  writingDialog.showModal();
});
$("writing-dialog-stay").addEventListener("click", () => writingDialog.close());
const restoreDialog = $("writing-restore-dialog");
$("writing-restore").addEventListener("click", () => restoreDialog.showModal());
$("writing-restore-stay").addEventListener("click", () => restoreDialog.close());
$("writing-restore-confirm").addEventListener("click", () => {
  // Only the editor changes; the original text above it is never editable and the saved draft stays
  // until the student saves again.
  $("writing-text").value = writing.exercise.source_text_es;
  restoreDialog.close();
  updateWordCount();
  scheduleAutosave();
});
$("writing-dialog-confirm").addEventListener("click", async () => {
  const button = $("writing-dialog-confirm");
  if (button.disabled) return;
  button.disabled = true; // one submission; the server also keeps only the first
  writing.busy = true;
  clearTimeout(autosaveTimer); // the submission carries the full text; no draft save after it
  writing.requestId = writing.requestId || newRequestId();
  const sections = writing.exercise.guided ? guidedSections() : null;
  const text = sections ? guidedComposition(sections) : $("writing-text").value;
  try {
    const submission = await api(`/api/writing/exercises/${encodeURIComponent(writing.exercise.exercise_id)}/submit`,
      { method: "POST", body: JSON.stringify(sections ? { sections, client_request_id: writing.requestId }
        : { text, client_request_id: writing.requestId }) });
    writing.exercise.submission = submission;
    writing.exercise.draft = { text, sections, word_count: submission.word_count, saved_at: submission.submitted_at };
    writing.savedText = text;
    if (sections) writing.savedSections = JSON.stringify(sections);
    writingDialog.close();
    renderWritingState();
  } catch (error) {
    showError($("writing-dialog-error"), error.message);
    button.disabled = false;
  } finally {
    writing.busy = false;
  }
});
window.addEventListener("beforeunload", (event) => {
  if (writingDirty()) event.preventDefault(); // the browser asks before discarding unsaved text
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") flushDraft();
});
window.addEventListener("pagehide", flushDraft);

// ------------------------------------------------------------------ start

async function resume() {
  const sessionId = storedSession();
  const writingId = rememberedWriting();
  if (!sessionId && writingId) {
    openWritingExercise(writingId);
    return;
  }
  if (!sessionId) return;
  try {
    handleSession(await api(`/api/practice/sessions/${sessionId}`));
  } catch (error) {
    storeSession(null);
    if (error.status !== 404) showError($("form-error"), error.message);
  }
}

const subjectsReady = loadSubjects();
subjectsReady.then(resume);
