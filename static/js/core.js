/* CondoIA — núcleo: utilidades, API, autenticação, navegação e componentes */
'use strict';

const $ = id => document.getElementById(id);
const S = { user: null, condo: null, estrutura: null, ronda: null, blocoAberto: null, timers: {} };

function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function fmtD(s) { return s ? `${s.slice(8, 10)}/${s.slice(5, 7)}/${s.slice(0, 4)}` : '—'; }
function fmtH(s) { return s && s.length > 10 ? s.slice(11, 16) : ''; }
function fmtDT(s) { return s ? `${fmtD(s)} ${fmtH(s)}`.trim() : '—'; }
function todayISO() { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); }
function ago(s) {
  if (!s) return '';
  const min = Math.round((Date.now() - new Date(s).getTime()) / 60000);
  if (isNaN(min)) return fmtDT(s);
  if (min < 1) return 'Agora';
  if (min < 60) return `Há ${min} min`;
  if (min < 1440) return `Há ${Math.floor(min / 60)}h`;
  return `Há ${Math.floor(min / 1440)}d`;
}
function debounce(key, fn, ms = 350) { clearTimeout(S.timers[key]); S.timers[key] = setTimeout(fn, ms); }

const OS_ST = { aberta: ['danger', 'ABERTA'], em_andamento: ['warn', 'EM ANDAMENTO'], concluida: ['ok', 'CONCLUÍDA'] };
const OC_ST = { aberta: ['danger', 'ABERTA'], em_atendimento: ['warn', 'EM ATENDIMENTO'], concluida: ['ok', 'CONCLUÍDA'] };
const RD_ST = { em_andamento: ['info', 'EM ANDAMENTO'], concluida: ['ok', 'CONCLUÍDA'], incompleta: ['warn', 'INCOMPLETA'] };
const PT_ST = { ok: ['ok', 'OK'], atencao: ['warn', 'ATENÇÃO'], problema: ['danger', 'PROBLEMA'] };
const PRI = { 'Crítica': 'danger', 'Alta': 'warn', 'Média': 'warn', 'Baixa': 'ok' };
function badge(map, key) { const b = map[key] || ['pend', key]; return `<span class="status ${b[0]}">${esc(b[1])}</span>`; }
function priBadge(p) { return `<span class="status ${PRI[p] || 'info'}">${esc((p || '').toUpperCase())}</span>`; }
function thumbs(ids) {
  if (!ids || !ids.length) return '';
  return '<div class="thumbs">' + ids.map(id => `<a href="/api/fotos/${Number(id)}" target="_blank" rel="noopener"><img src="/api/fotos/${Number(id)}" alt="Foto" loading="lazy"></a>`).join('') + '</div>';
}
function emptyRow(cols, txt) { return `<tr><td colspan="${cols}" class="empty">${esc(txt)}</td></tr>`; }

/* ------------------------------------------------------------------ API */
async function api(method, url, body) {
  const opt = { method, headers: { 'X-CondoIA': '1' }, credentials: 'same-origin' };
  if (body instanceof FormData) opt.body = body;
  else if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  let r;
  try { r = await fetch(url, opt); } catch (e) { throw new Error('Sem conexão com o servidor. Verifique a internet/rede.'); }
  let data = null;
  try { data = await r.json(); } catch (e) { /* resposta sem JSON */ }
  if (r.status === 401 && !url.startsWith('/api/auth/login')) {
    showLogin('Sua sessão expirou. Entre novamente.');
    throw new Error('Sessão expirada.');
  }
  if (!r.ok) {
    const err = new Error((data && data.erro) || 'Erro de comunicação com o servidor.');
    err.campos = data && data.campos; err.status = r.status;
    throw err;
  }
  return data;
}

function toast(msg, tipo) {
  const t = $('toast');
  t.textContent = msg;
  t.className = 'toast' + (tipo === 'error' ? ' error' : '');
  t.style.display = 'block';
  clearTimeout(S.timers.toast);
  S.timers.toast = setTimeout(() => { t.style.display = 'none'; }, tipo === 'error' ? 6000 : 3500);
}
function fail(e) { if (e && e.message !== 'Sessão expirada.') toast(e.message || 'Erro inesperado.', 'error'); }

async function busy(btn, fn) {
  if (btn && btn.disabled) return;
  const txt = btn ? btn.innerHTML : '';
  if (btn) { btn.disabled = true; btn.innerHTML = 'Enviando…'; }
  try { return await fn(); } catch (e) { fail(e); } finally { if (btn) { btn.disabled = false; btn.innerHTML = txt; } }
}

/* ---------------------------------------------------------------- modal */
let modalOnClose = null;
function openModal(title, html, onClose) {
  $('modalTitle').textContent = title;
  $('modalBody').innerHTML = html;
  $('modal').style.display = 'flex';
  modalOnClose = onClose || null;
}
function closeModal() {
  $('modal').style.display = 'none';
  $('modalBody').innerHTML = '';
  if (modalOnClose) { const f = modalOnClose; modalOnClose = null; f(); }
}
function confirmModal(title, text, btnLabel, onConfirm) {
  openModal(title, `<p class="note">${esc(text)}</p><div class="wizard-actions"><button class="btn" onclick="closeModal()">Cancelar</button><button class="btn primary" id="confirmBtn">${esc(btnLabel)}</button></div>`);
  $('confirmBtn').onclick = () => busy($('confirmBtn'), onConfirm);
}
function formError(msgEl, e) {
  if (!msgEl) return fail(e);
  msgEl.textContent = e.message; msgEl.style.display = 'block';
  document.querySelectorAll('.field-error').forEach(x => x.classList.remove('field-error'));
  (e.campos || []).forEach(c => { const f = document.querySelector(`[name="${c}"]`); if (f) f.classList.add('field-error'); });
}

/* ------------------------------------------------------ seletor de fotos */
const pickers = {};
function photoPicker(elId, opts = {}) {
  const el = $(elId);
  if (!el) return;
  pickers[elId] = [];
  const label = opts.label || 'Tirar foto ou escolher da galeria';
  el.innerHTML = `<div class="upload" tabindex="0" role="button">📷<br><b style="color:var(--navy)">${esc(label)}</b><br><small>JPG, PNG ou WEBP · até 10 MB</small></div>
    <input type="file" accept="image/jpeg,image/png,image/webp" ${opts.single ? '' : 'multiple'} hidden><div class="photos"></div>`;
  const up = el.querySelector('.upload'), input = el.querySelector('input');
  up.onclick = () => input.click();
  up.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } };
  input.onchange = () => {
    for (const f of input.files) {
      if (!/^image\/(jpeg|png|webp)$/.test(f.type)) { toast(`“${f.name}”: envie uma foto JPG, PNG ou WEBP.`, 'error'); continue; }
      if (f.size > 10 * 1024 * 1024) { toast(`“${f.name}” passa de 10 MB.`, 'error'); continue; }
      if (pickers[elId].length >= 5) { toast('Máximo de 5 fotos.', 'error'); break; }
      pickers[elId].push(f);
    }
    input.value = '';
    renderPicker(elId);
  };
}
function renderPicker(elId) {
  const el = $(elId); if (!el) return;
  const box = el.querySelector('.photos');
  box.innerHTML = pickers[elId].map((f, i) => `<div class="photo"><img src="${URL.createObjectURL(f)}" alt="Foto ${i + 1}"><button class="rm" type="button" aria-label="Remover foto" onclick="removePhoto('${elId}',${i})">✕</button></div>`).join('');
  el.querySelector('.upload').classList.remove('has-error');
}
function removePhoto(elId, i) { pickers[elId].splice(i, 1); renderPicker(elId); }
function pickerFiles(elId) { return pickers[elId] || []; }
function addFiles(fd, elId) { pickerFiles(elId).forEach(f => fd.append('fotos', f, f.name)); }
function markPickerError(elId) { const u = $(elId) && $(elId).querySelector('.upload'); if (u) u.classList.add('has-error'); }

/* -------------------------------------------------------- autenticação */
function togglePass() { const p = $('loginPass'); p.type = p.type === 'password' ? 'text' : 'password'; }
function forgotPassword() {
  const e = $('loginError');
  e.textContent = 'Por segurança, a senha é redefinida pela Administração. Procure a Administração do condomínio.';
  e.style.display = 'block';
}
function showLogin(msg) {
  S.user = null;
  closeModal();
  $('app').style.display = 'none';
  $('loginOverlay').style.display = 'grid';
  $('loginPass').value = '';
  const e = $('loginError');
  if (msg) { e.textContent = msg; e.style.display = 'block'; } else e.style.display = 'none';
}
async function login() {
  const btn = $('loginBtn'), e = $('loginError');
  const usuario = $('loginUser').value.trim(), senha = $('loginPass').value;
  if (!usuario || !senha) { e.textContent = 'Informe usuário e senha.'; e.style.display = 'block'; return; }
  btn.disabled = true; btn.textContent = 'Entrando…';
  try {
    await api('POST', '/api/auth/login', { usuario, senha, lembrar: $('loginRemember').checked });
    e.style.display = 'none';
    $('loginPass').value = '';
    await boot();
  } catch (err) {
    e.textContent = err.message; e.style.display = 'block';
  } finally { btn.disabled = false; btn.textContent = 'Entrar'; }
}
async function logout() {
  try { await api('POST', '/api/auth/logout'); } catch (e) { /* segue saindo */ }
  S.ronda = null; S.estrutura = null;
  history.replaceState(null, '', '/');
  showLogin();
}

async function boot() {
  const me = await api('GET', '/api/auth/me');
  S.condo = me.condominio;
  $('condoName').textContent = me.condominio.nome_condominio || 'Condomínio';
  $('condoInfo').textContent = me.condominio.descricao_condominio || '';
  if (!me.autenticado) { showLogin(); return; }
  S.user = me.usuario;
  $('loginOverlay').style.display = 'none';
  $('app').style.display = 'flex';
  $('userName').textContent = S.user.nome;
  $('userRole').textContent = S.user.perfil_nome;
  const partes = S.user.nome.trim().split(/\s+/);
  const ult = partes[partes.length - 1];
  $('avatar').textContent = (partes.length > 1 && /^\d+$/.test(ult) ? partes[0][0] + String(Number(ult)) : partes.map(x => x[0]).join('')).slice(0, 2).toUpperCase();
  $('topOS').style.display = ['admin', 'ronda'].includes(S.user.perfil) ? 'inline-block' : 'none';
  $('topBell').style.display = S.user.perfil === 'ronda' ? 'none' : 'inline-block';
  buildNav();
  if (sessionStorage.getItem('condoia_qr') && S.user.perfil !== 'ronda') {
    sessionStorage.removeItem('condoia_qr');
    toast('QR Codes de bloco são usados pelo perfil Ronda.', 'error');
  }
  const pend = sessionStorage.getItem('condoia_qr');
  if (pend && location.hash.slice(1) !== 'rondas') { location.hash = 'rondas'; return; }
  route();
}

/* ------------------------------------------------------------ navegação */
const TODOS = ['admin', 'ronda', 'manutencao'];
const PAGES = {
  dashboard: { t: 'Dashboard', r: ['admin'], load: () => loadDashboard() },
  os: { t: 'Nova Ordem de Serviço', r: ['admin', 'ronda'], load: () => resetWizard() },
  oslista: { t: 'Ordens de Serviço', r: ['admin'], load: () => loadOSList() },
  osdetalhe: { t: 'Ordem de Serviço', r: TODOS, load: p => loadOSDetail(p), nav: { admin: 'oslista', manutencao: 'minhasos' } },
  minhasos: { t: 'Minhas Ordens de Serviço', r: ['manutencao'], load: () => loadMinhasOS() },
  concluiros: { t: 'Concluir Ordem de Serviço', r: ['admin', 'manutencao'], load: p => loadConcluirOS(p), nav: { admin: 'oslista', manutencao: 'minhasos' } },
  rondas: { t: 'Rondas', r: ['ronda'], load: () => loadRonda() },
  rondahist: { t: 'Rondas', r: ['admin', 'ronda'], load: () => loadRondaHist() },
  rondadetalhe: { t: 'Detalhes da ronda', r: ['admin', 'ronda'], load: p => loadRondaDetail(p), nav: { admin: 'rondahist', ronda: 'rondahist' } },
  ocorrencias: { t: 'Ocorrências', r: TODOS, load: () => loadOcorrencias() },
  unidades: { t: 'Unidades', r: ['admin'], load: () => loadUnidades() },
  empresas: { t: 'Empresas Terceirizadas', r: ['admin'], load: () => loadEmpresas() },
  documentos: { t: 'Documentos', r: ['admin'], load: () => loadDocumentos() },
  relatorios: { t: 'Relatórios', r: ['admin'], load: () => loadRelatorios() },
  blocos: { t: 'Blocos e QR Codes', r: ['admin'], load: () => loadBlocosAdmin() },
  usuarios: { t: 'Usuários', r: ['admin'], load: () => loadUsuarios() },
  auditoria: { t: 'Histórico e auditoria', r: ['admin'], load: () => loadAuditoria() },
  configuracoes: { t: 'Configurações', r: ['admin'], load: () => loadConfig() },
  ia: { t: 'CondoIA — Assistente', r: TODOS, load: () => {} },
};
const HOME = { admin: 'dashboard', ronda: 'rondas', manutencao: 'minhasos' };

function buildNav() {
  const b = (page, ico, label) => `<button data-page="${page}" onclick="go('${page}')">${ico} <span>${label}</span></button>`;
  const t = txt => `<div class="nav-title">${txt}</div>`;
  let h = '';
  if (S.user.perfil === 'admin') {
    h = t('Principal') + b('dashboard', '▦', 'Dashboard') + b('oslista', '🛠', 'Ordens de Serviço') + b('rondahist', '✓', 'Rondas') + b('ocorrencias', '⚠', 'Ocorrências')
      + t('Gestão') + b('unidades', '⌂', 'Unidades') + b('empresas', '▣', 'Empresas Terceirizadas') + b('documentos', '▤', 'Documentos') + b('ia', '🤖', 'CondoIA') + b('relatorios', '▥', 'Relatórios')
      + t('Sistema') + b('blocos', '▦', 'Blocos e QR Codes') + b('usuarios', '👤', 'Usuários') + b('auditoria', '🧾', 'Auditoria') + b('configuracoes', '⚙', 'Configurações');
  } else if (S.user.perfil === 'ronda') {
    h = t('Ronda') + b('rondas', '✓', 'Iniciar Ronda') + b('rondahist', '🕘', 'Minhas Rondas') + b('ocorrencias', '⚠', 'Registrar Ocorrência') + b('os', '🛠', 'Abrir OS') + b('ia', '🤖', 'CondoIA');
  } else {
    h = t('Manutenção') + b('minhasos', '🛠', 'Minhas OS') + b('ocorrencias', '⚠', 'Ocorrências') + b('ia', '🤖', 'CondoIA');
  }
  $('nav').innerHTML = h;
}

function go(page, param) {
  const alvo = param !== undefined && param !== null ? `${page}/${param}` : page;
  if (location.hash.slice(1) === alvo) route(); else location.hash = alvo;
}
function startOS() { go('os'); }

function route() {
  if (!S.user) return;
  const [page, param] = location.hash.slice(1).split('/');
  const cfg = PAGES[page];
  if (!cfg || !cfg.r.includes(S.user.perfil)) {
    if (page && cfg) toast('Você não tem acesso a essa página.', 'error');
    location.replace('#' + HOME[S.user.perfil]);
    return;
  }
  if (S.scanStream) closeModal();
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  $(page).classList.add('active');
  const navPage = (cfg.nav && cfg.nav[S.user.perfil]) || page;
  document.querySelectorAll('.nav button').forEach(x => x.classList.toggle('active', x.dataset.page === navPage));
  let titulo = cfg.t;
  if (page === 'rondahist' && S.user.perfil === 'ronda') titulo = 'Minhas Rondas';
  if (page === 'ocorrencias' && S.user.perfil === 'ronda') titulo = 'Registrar Ocorrência';
  $('pageTitle').textContent = titulo;
  window.scrollTo(0, 0);
  try { cfg.load(param); } catch (e) { fail(e); }
  refreshBell();
}

async function refreshBell() {
  if (!S.user || S.user.perfil === 'ronda') return;
  try {
    const url = S.user.perfil === 'admin' ? '/api/ocorrencias?status=aberta' : '/api/os?escopo=disponiveis';
    const lista = await api('GET', url);
    $('bellCount').textContent = lista.length;
    $('topBell').title = S.user.perfil === 'admin' ? 'Ocorrências abertas' : 'OS disponíveis';
  } catch (e) { /* silencioso */ }
}
function bellClick() {
  if (S.user.perfil === 'admin') { $('ocStatus').value = 'aberta'; go('ocorrencias'); } else go('minhasos');
}
function searchClick() {
  if (S.user.perfil === 'admin') { go('oslista'); setTimeout(() => $('osBusca').focus(), 50); }
  else { go('ocorrencias'); setTimeout(() => $('ocBusca').focus(), 50); }
}

async function getEstrutura(force) {
  if (!S.estrutura || force) S.estrutura = await api('GET', '/api/estrutura');
  return S.estrutura;
}

window.addEventListener('hashchange', route);
window.addEventListener('DOMContentLoaded', () => {
  const qr = new URLSearchParams(location.search).get('qr');
  if (qr) {
    sessionStorage.setItem('condoia_qr', qr);
    history.replaceState(null, '', '/' + (location.hash || '#rondas'));
  }
  boot().catch(e => { showLogin(); fail(e); });
});
