// Mentor Pro practice page (T003 configuration, T010 practice). Plain JavaScript; no framework.
// All student-facing text is Spanish (Costa Rica). Curricular and question text is rendered
// exactly as returned by the API (textContent, never innerHTML). Answer keys are never sent to
// the browser before an answer is submitted; the server evaluates every answer.
"use strict";

const SESSION_KEY = "mentorpro.session";
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
  for (const id of ["practice-form", "progress-view", "quiz-view", "result-view"]) $(id).hidden = id !== view;
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

// ------------------------------------------------------------------ start

async function resume() {
  const sessionId = storedSession();
  if (!sessionId) return;
  try {
    handleSession(await api(`/api/practice/sessions/${sessionId}`));
  } catch (error) {
    storeSession(null);
    if (error.status !== 404) showError($("form-error"), error.message);
  }
}

loadSubjects().then(resume);
