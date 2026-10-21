// Mentor Pro practice configuration (T003). Plain JavaScript; no framework.
// All student-facing text is Spanish (Costa Rica). Curricular text is rendered
// exactly as returned by the API (textContent, never innerHTML).
"use strict";

const DIFFICULTY_ES = { easy: "Fácil", medium: "Intermedia", hard: "Difícil", mixed: "Mixta" };
const SCOPE_ES = {
  single_objective: "Un objetivo",
  selected_objectives: "Varios objetivos",
  subject_simulation: "Todos los objetivos",
};

const $ = (id) => document.getElementById(id);
const form = $("practice-form");
const state = { subjects: [], objectives: [], subjectNames: {} };

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
  target.textContent = message;
  target.hidden = !message;
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.message_es || "No fue posible completar la solicitud. Intente de nuevo.");
  }
  return body;
}

const scope = () => form.elements.scope.value;
const selectedCodes = () =>
  [...form.querySelectorAll('input[name="objective"]:checked')].map((input) => input.value);

async function loadSubjects() {
  try {
    const data = await api("/api/subjects");
    state.subjects = data.subjects;
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
  $("summary").hidden = true;
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
    input.addEventListener("change", updateState);
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

function renderSummary(result) {
  const meta = $("summary-meta");
  meta.replaceChildren();
  const rows = [
    ["Materia", state.subjectNames[result.subject]],
    ["Alcance", SCOPE_ES[result.scope]],
    ["Dificultad", DIFFICULTY_ES[result.difficulty]],
    ["Preguntas", String(result.question_count)],
    ["Objetivos cubiertos", `${result.covered_codes.length} de ${result.objectives_selected}`],
  ];
  for (const [term, value] of rows) meta.append(el("div", {}, el("dt", {}, term), el("dd", {}, value)));

  $("summary-coverage").textContent = result.uncovered_codes.length
    ? `Con ${result.question_count} preguntas no se cubren todos los objetivos. Sin preguntas en esta práctica: ${result.uncovered_codes.join(", ")}.`
    : "Todos los objetivos seleccionados tienen al menos una pregunta.";

  const body = $("summary-rows");
  body.replaceChildren();
  for (const row of result.allocation) {
    body.append(el("tr", {},
      el("td", {}, el("span", { class: "code" }, row.workbook_code), el("span", { class: "objective-text" }, row.text_es)),
      el("td", {}, String(row.questions)),
      el("td", {}, `${row.evidences_covered} de ${row.evidences_total}`)));
  }
  $("summary").hidden = false;
  $("summary").scrollIntoView({ behavior: "smooth", block: "start" });
}

form.addEventListener("change", (event) => {
  if (event.target.name === "scope") renderObjectives();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  showError($("form-error"), "");
  const payload = {
    subject: form.elements.subject.value,
    scope: scope(),
    objective_codes: scope() === "subject_simulation" ? [] : selectedCodes(),
    difficulty: form.elements.difficulty.value,
    question_count: Number(form.elements.question_count.value),
  };
  $("submit").disabled = true;
  try {
    renderSummary(await api("/api/practice/configure", { method: "POST", body: JSON.stringify(payload) }));
  } catch (error) {
    showError($("form-error"), error.message);
  } finally {
    updateState();
  }
});

loadSubjects();
