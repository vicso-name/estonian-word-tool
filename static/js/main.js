/* ═══════════════════════════════════════════════════════
   Eesti Sõnad — main.js
   ═══════════════════════════════════════════════════════ */

/* ── THEME ──────────────────────────────────────────────── */
const THEME_KEY   = 'eesti_theme_v1';
const LEARNED_KEY = 'eesti_learned_v1';

function getStoredTheme() {
  return localStorage.getItem(THEME_KEY) || 'light';
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme === 'dark' ? 'dark' : '');
  const btn = document.getElementById('themeBtn');
  if (btn) btn.textContent = theme === 'dark' ? '☀️' : '🌙';
  localStorage.setItem(THEME_KEY, theme);
}

function toggleTheme() {
  const current = getStoredTheme();
  applyTheme(current === 'dark' ? 'light' : 'dark');
}

/* Apply theme immediately to avoid flash */
applyTheme(getStoredTheme());

/* ── LEARNED WORDS ──────────────────────────────────────── */
function getLearnedSet() {
  try {
    return new Set(JSON.parse(localStorage.getItem(LEARNED_KEY) || '[]'));
  } catch {
    return new Set();
  }
}

function saveLearnedSet(s) {
  localStorage.setItem(LEARNED_KEY, JSON.stringify([...s]));
}

let learned = getLearnedSet();
const totalWords = parseInt(document.body.dataset.total || '0', 10);

/* ── PROGRESS ───────────────────────────────────────────── */
function updateProgress() {
  if (!totalWords) return;
  const count  = learned.size;
  const pct    = Math.round((count / totalWords) * 100);
  const fill   = document.getElementById('progressFill');
  const text   = document.getElementById('progressText');
  if (fill) fill.style.width = pct + '%';
  if (text) text.textContent = count;
}

const SECTION_IDS = ['nouns', 'adjectives', 'verbs', 'adverbs', 'pronouns', 'other'];

function updateSectionProgress() {
  SECTION_IDS.forEach(id => {
    const sec = document.getElementById('sec-' + id);
    const sp  = document.getElementById('sp-' + id);
    if (!sec || !sp) return;
    const rows = sec.querySelectorAll('.word-row');
    const done = [...rows].filter(r => learned.has(r.dataset.word)).length;
    sp.textContent  = done + ' / ' + rows.length;
    sp.style.color  = (done === rows.length && rows.length > 0)
      ? 'var(--green)' : 'var(--text3)';
  });
}

/* ── APPLY LEARNED STATE ON LOAD ────────────────────────── */
function applyLearnedState() {
  document.querySelectorAll('.word-row').forEach(row => {
    const word = row.dataset.word;
    const btn  = row.querySelector('.learned-btn');
    const isLearned = learned.has(word);
    row.classList.toggle('is-learned', isLearned);
    if (btn) btn.classList.toggle('is-learned', isLearned);
  });
  updateProgress();
  updateSectionProgress();
}

/* ── TOGGLE LEARNED ─────────────────────────────────────── */
function toggleLearned(word) {
  if (learned.has(word)) {
    learned.delete(word);
  } else {
    learned.add(word);
  }
  saveLearnedSet(learned);

  document.querySelectorAll(`.word-row[data-word="${CSS.escape(word)}"]`).forEach(row => {
    const isLearned = learned.has(word);
    row.classList.toggle('is-learned', isLearned);
    const btn = row.querySelector('.learned-btn');
    if (btn) btn.classList.toggle('is-learned', isLearned);
  });

  updateProgress();
  updateSectionProgress();
}

/* ── GLOBAL STUDY MODE ──────────────────────────────────── */
let globalMode = 'read';

function setGlobalMode(mode, btn) {
  globalMode = mode;
  document.body.classList.remove('mode-read', 'mode-hide-ru', 'mode-hide-et');
  document.body.classList.add('mode-' + mode);

  document.querySelectorAll('#globalModePill .mode-btn').forEach(b => {
    b.classList.toggle('active', b === btn);
  });

  if (mode !== 'read') {
    document.querySelectorAll('.maskable.revealed').forEach(el => {
      const sec = el.closest('.section');
      if (!sec || sec.dataset.sectionMode === 'inherit') {
        el.classList.remove('revealed');
      }
    });
  }
}

/* ── PER-SECTION MODE ───────────────────────────────────── */
function setSectionMode(sectionId, mode, btn) {
  const sec = document.getElementById('sec-' + sectionId);
  if (!sec) return;
  sec.dataset.sectionMode = mode;

  sec.querySelectorAll('.sec-btn').forEach(b => {
    b.classList.toggle('active', b === btn);
  });

  if (mode !== 'read') {
    sec.querySelectorAll('.maskable.revealed').forEach(el => el.classList.remove('revealed'));
  }
}

/* ── REVEAL ON CLICK ────────────────────────────────────── */
document.addEventListener('click', function (e) {
  const maskable = e.target.closest('.maskable');
  if (!maskable) return;

  const cell = maskable.closest('.cell-ru, .cell-et');
  if (!cell) return;

  const isRu  = cell.classList.contains('cell-ru');
  const isEt  = cell.classList.contains('cell-et');
  const sec   = maskable.closest('.section');
  const secMode = sec ? sec.dataset.sectionMode : 'inherit';
  const effectiveMode = (secMode !== 'inherit') ? secMode : globalMode;

  const shouldReveal =
    (isRu && effectiveMode === 'hide-ru') ||
    (isEt && effectiveMode === 'hide-et');

  if (shouldReveal) {
    maskable.classList.toggle('revealed');
  }
});

/* ── REVEAL ALL (per section toggle) ────────────────────── */
function revealAll(secId) {
  const sec = document.getElementById(secId);
  if (!sec) return;
  const maskables  = sec.querySelectorAll('.maskable');
  const anyHidden  = [...maskables].some(m => !m.classList.contains('revealed'));
  maskables.forEach(m => m.classList.toggle('revealed', anyHidden));
}

/* ── FILE INPUT LABEL ───────────────────────────────────── */
const fileInput = document.getElementById('word_file');
if (fileInput) {
  fileInput.addEventListener('change', function () {
    const label = document.getElementById('file-name');
    if (label) label.textContent = this.files[0]?.name || '';
  });
}

/* ── INIT ───────────────────────────────────────────────── */
applyLearnedState();