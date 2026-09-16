/* CondoIA — dashboard, ordens de serviço e ocorrências */
'use strict';

function plural(n, um, varios) { return `${n} ${n === 1 ? um : varios}`; }
function row(ico, title, sub, badgeHtml, onclick) {
  return `<div class="row${onclick ? ' clickable' : ''}"${onclick ? ` onclick="${onclick}"` : ''}><div class="ico">${ico}</div><div class="row-main"><b>${esc(title)}</b><small>${esc(sub)}</small></div>${badgeHtml || ''}</div>`;
}

/* ============================================================ DASHBOARD */
async function loadDashboard() {
  try {
    const d = await api('GET', '/api/dashboard');
    $('mUnidades').textContent = d.unidades;
    $('mUnidadesB').textContent = plural(d.unidades_ocupadas, 'ocupada', 'ocupadas');
    $('mOsAbertas').textContent = d.os_abertas;
    $('mOsAbertasB').textContent = plural(d.os_criticas, 'crítica', 'críticas');
    $('mOsAndamento').textContent = d.os_andamento;
    $('mOsConcluidas').textContent = d.os_concluidas_mes;
    $('mRondas').textContent = d.rondas_mes;
    $('mRondasB').textContent = plural(d.problemas_mes, 'problema', 'problemas');
    $('mRondasB').className = 'badge ' + (d.problemas_mes ? 'danger' : 'ok');
    $('mRondasPend').textContent = d.rondas_andamento;
    $('mRondasPendB').textContent = plural(d.rondas_hoje, 'finalizada hoje', 'finalizadas hoje');
    $('mBlocos').textContent = `${d.blocos_verificados_hoje}/${d.blocos_total}`;
    $('mBlocosB').textContent = 'ronda concluída';
    $('mEmpresas').textContent = d.empresas_ativas;
    $('mDocs').textContent = d.documentos_vencendo;
    $('mDocsB').textContent = d.documentos_vencidos ? plural(d.documentos_vencidos, 'vencido', 'vencidos') : `próximos ${d.dias_alerta} dias`;
    $('mDocsB').className = 'badge ' + (d.documentos_vencidos ? 'danger' : 'warn');

    $('dashAlerts').innerHTML = d.blocos_sem_andares.length
      ? `<div class="alert-card">⚠ Blocos sem andares cadastrados: <b>${esc(d.blocos_sem_andares.join(', '))}</b>. A ronda não consegue concluir esses blocos até que os andares sejam configurados.<button class="btn" onclick="go('blocos')">Configurar blocos</button></div>` : '';

    const icoOS = { aberta: '!', em_andamento: '⚙', concluida: '✓' };
    $('dashOS').innerHTML = d.os_recentes.length ? d.os_recentes.map(o =>
      row(icoOS[o.status], `${o.numero} · ${o.descricao}`, `${ago(o.criado_em)} · ${o.local}`, badge(OS_ST, o.status), `go('osdetalhe',${o.id})`)).join('')
      : '<p class="empty">Nenhuma ordem de serviço registrada ainda.</p>';

    const r = d.ultima_ronda;
    if (!r) {
      $('dashRonda').innerHTML = '<p class="empty">Nenhuma ronda registrada ainda.</p>';
      $('dashRondaLink').onclick = () => go('rondahist');
    } else {
      $('dashRondaLink').onclick = () => go('rondadetalhe', r.id);
      $('dashRonda').innerHTML = row('✓', r.usuario, `Início ${fmtDT(r.iniciada_em)}${r.finalizada_em ? ' · término ' + fmtH(r.finalizada_em) : ''}`, badge(RD_ST, r.status))
        + (r.registros.length ? r.registros.map(p => row(p.status === 'ok' ? '✓' : '!', p.local, fmtH(p.registrado_em), badge(PT_ST, p.status))).join('')
          : '<p class="empty">Nenhum ponto registrado nesta ronda ainda.</p>');
    }

    $('dashOc').innerHTML = d.ocorrencias_recentes.length ? d.ocorrencias_recentes.map(o =>
      row('⚠', `${o.numero} · ${o.descricao}`, `${ago(o.criado_em)} · ${o.local}`, badge(OC_ST, o.status), `openOcorrencia(${o.id})`)).join('')
      : '<p class="empty">Nenhuma ocorrência registrada.</p>';

    const hoje = todayISO();
    $('dashDocs').innerHTML = d.documentos_alerta.length ? d.documentos_alerta.map(x =>
      row('▤', x.nome, `${x.categoria} · validade ${fmtD(x.validade)}`, x.validade < hoje ? '<span class="status danger">VENCIDO</span>' : '<span class="status warn">A VENCER</span>')).join('')
      : `<p class="empty">Nenhum documento vence nos próximos ${d.dias_alerta} dias.</p>`;
  } catch (e) { fail(e); }
}

/* ======================================================== WIZARD DE OS */
const wiz = { step: 1, local: '', equipamento: '', prioridade: '', category: 'Portões', description: '', createdId: null };

function resetWizard() {
  Object.assign(wiz, { step: 1, local: '', equipamento: '', prioridade: '', category: 'Portões', description: '', createdId: null });
  document.querySelectorAll('#os .option').forEach(x => x.classList.remove('selected'));
  $('description').value = '';
  $('category').selectedIndex = 0;
  photoPicker('osPhotos');
  renderWizard();
}
function renderWizard() {
  document.querySelectorAll('.step-page').forEach(p => p.classList.toggle('active', Number(p.dataset.step) === wiz.step));
  const bars = $('stepBars');
  bars.innerHTML = '';
  for (let i = 1; i <= 7; i++) { const d = document.createElement('div'); d.className = 'stepdot ' + (i <= wiz.step ? 'on' : ''); bars.appendChild(d); }
  $('backBtn').style.visibility = (wiz.step === 1 || wiz.step === 7) ? 'hidden' : 'visible';
  $('nextBtn').style.display = wiz.step === 7 ? 'none' : 'inline-block';
  $('nextBtn').innerHTML = wiz.step === 6 ? '✓ Abrir OS' : 'Continuar →';
  $('viewOSBtn').style.display = wiz.step === 7 ? 'inline-block' : 'none';
  if (wiz.step === 6) $('review').innerHTML = reviewHTML();
  if (wiz.step === 7) $('successReview').innerHTML = reviewHTML();
}
function selectOption(el, key, value) {
  el.parentElement.querySelectorAll('.option').forEach(x => x.classList.remove('selected'));
  el.classList.add('selected');
  wiz[key] = value;
}
async function nextStep() {
  if (wiz.step === 1 && !wiz.local) return toast('Escolha um local para continuar.', 'error');
  if (wiz.step === 2 && !wiz.equipamento) return toast('Escolha um equipamento para continuar.', 'error');
  if (wiz.step === 3) {
    wiz.category = $('category').value;
    wiz.description = $('description').value.trim();
    if (!wiz.description) return toast('Descreva o problema antes de continuar.', 'error');
  }
  if (wiz.step === 4 && pickerFiles('osPhotos').length < 1) { markPickerError('osPhotos'); return toast('Adicione a foto do problema. Ela é obrigatória.', 'error'); }
  if (wiz.step === 5 && !wiz.prioridade) return toast('Selecione a prioridade.', 'error');
  if (wiz.step === 6) {
    return busy($('nextBtn'), async () => {
      const fd = new FormData();
      fd.append('local', wiz.local); fd.append('equipamento', wiz.equipamento); fd.append('categoria', wiz.category);
      fd.append('descricao', wiz.description); fd.append('prioridade', wiz.prioridade);
      addFiles(fd, 'osPhotos');
      const r = await api('POST', '/api/os', fd);
      wiz.createdId = r.id;
      $('osNumber').textContent = r.numero;
      wiz.step = 7;
      renderWizard();
    });
  }
  wiz.step++;
  renderWizard();
}
function prevStep() { if (wiz.step > 1 && wiz.step < 7) { wiz.step--; renderWizard(); } }
function reviewHTML() {
  const n = pickerFiles('osPhotos').length;
  return `<div><span>Local</span><b>${esc(wiz.local)}</b></div><div><span>Equipamento</span><b>${esc(wiz.equipamento)}</b></div><div><span>Categoria</span><b>${esc(wiz.category)}</b></div><div><span>Qual o problema?</span><b>${esc(wiz.description)}</b></div><div><span>Prioridade</span><b>${esc(wiz.prioridade)}</b></div><div><span>Foto do problema</span><b>📷 ${n} foto(s) anexada(s)</b></div>`;
}
function openCreatedOS() { if (wiz.createdId) go('osdetalhe', wiz.createdId); }

/* ========================================================= LISTA DE OS */
async function loadOSList() {
  try {
    const q = new URLSearchParams({ busca: $('osBusca').value.trim(), status: $('osStatus').value });
    const lista = await api('GET', '/api/os?' + q);
    $('osListBody').innerHTML = lista.length ? lista.map(o => `<tr class="clickable" onclick="go('osdetalhe',${o.id})"><td><b>${o.numero}</b></td><td>${esc(o.descricao)}</td><td>${esc(o.local)}</td><td>${priBadge(o.prioridade)}</td><td>${esc(o.responsavel_nome || '—')}</td><td>${badge(OS_ST, o.status)}</td><td>${fmtDT(o.criado_em)}</td></tr>`).join('')
      : emptyRow(7, 'Nenhuma ordem de serviço encontrada.');
  } catch (e) { fail(e); }
}

/* ======================================================== DETALHE DA OS */
const HIST_LABEL = { abertura: 'OS aberta', responsavel: 'Responsável definido', servico: 'O que foi feito', status: 'Status alterado' };
const ST_TXT = { aberta: 'Aberta', em_andamento: 'Em andamento', concluida: 'Concluída' };

async function loadOSDetail(id) {
  $('osDetMain').innerHTML = '<p class="empty">Carregando…</p>';
  $('osDetHist').innerHTML = '';
  try {
    const o = await api('GET', `/api/os/${Number(id)}`);
    const antes = o.fotos.filter(f => f.tipo === 'os_antes').map(f => f.id);
    const depois = o.fotos.filter(f => f.tipo === 'os_depois').map(f => f.id);
    const u = S.user;
    let acoes = '';
    if (u.perfil === 'manutencao') {
      if (o.status === 'aberta' && !o.responsavel_id) acoes += `<button class="btn primary big-btn" onclick="assumirOS(${o.id},this)">Assumir OS</button>`;
      if (o.status === 'aberta' && o.responsavel_id === u.id) acoes += `<button class="btn primary big-btn" onclick="iniciarOS(${o.id},this)">Colocar em andamento</button>`;
      if (o.status === 'em_andamento' && o.responsavel_id === u.id) acoes += `<button class="btn primary big-btn" onclick="go('concluiros',${o.id})">✓ Concluir OS</button>`;
    }
    if (u.perfil === 'admin' && o.status !== 'concluida') {
      const est = await getEstrutura();
      acoes += `<label class="form-label" style="margin-top:6px">Responsável (Manutenção)</label><div style="display:flex;gap:8px"><select class="field" id="osResp"><option value="">Selecione…</option>${est.manutencao.map(m => `<option value="${m.id}" ${m.id === o.responsavel_id ? 'selected' : ''}>${esc(m.nome)}</option>`).join('')}</select><button class="btn" onclick="atribuirOS(${o.id},this)">Atribuir</button></div>`;
      if (o.status === 'aberta' && o.responsavel_id) acoes += `<button class="btn primary big-btn" style="margin-top:10px" onclick="iniciarOS(${o.id},this)">Colocar em andamento</button>`;
      if (o.status === 'em_andamento') acoes += `<button class="btn primary big-btn" style="margin-top:10px" onclick="go('concluiros',${o.id})">✓ Concluir OS</button>`;
    }
    $('osDetMain').innerHTML = `<div class="card-head"><h2>OS ${o.numero}</h2>${badge(OS_ST, o.status)}</div>
      <div class="review">
        <div><span>Qual o problema?</span><b>${esc(o.descricao)}</b></div>
        <div><span>Local</span><b>${esc(o.local)}</b></div>
        <div><span>Equipamento</span><b>${esc(o.equipamento || '—')}</b></div>
        <div><span>Categoria</span><b>${esc(o.categoria)}</b></div>
        <div><span>Prioridade</span><b>${priBadge(o.prioridade)}</b></div>
        <div><span>Aberta por</span><b>${esc(o.aberta_por_nome)} · ${fmtDT(o.criado_em)}</b></div>
        <div><span>Responsável</span><b>${esc(o.responsavel_nome || '—')}</b></div>
        ${o.ocorrencia_id ? `<div><span>Ocorrência vinculada</span><b><button class="link link-btn" onclick="openOcorrencia(${o.ocorrencia_id})">${esc(o.ocorrencia_numero)}</button></b></div>` : ''}
        ${o.concluida_em ? `<div><span>Concluída em</span><b>${fmtDT(o.concluida_em)}</b></div>` : ''}
      </div>
      <label class="form-label" style="margin-top:14px">Foto do problema</label>${thumbs(antes) || '<p class="empty">Sem foto.</p>'}
      ${o.servico_realizado ? `<label class="form-label" style="margin-top:14px">O que foi feito?</label><p class="note">${esc(o.servico_realizado)}</p>` : ''}
      ${depois.length ? `<label class="form-label" style="margin-top:14px">Foto depois de feito</label>${thumbs(depois)}` : ''}
      ${acoes ? `<div style="margin-top:18px;padding-top:16px;border-top:1px solid var(--line)">${acoes}</div>` : ''}`;
    $('osDetHist').innerHTML = '<div class="timeline">' + o.historico.map(h => {
      let titulo = HIST_LABEL[h.acao] || h.acao, corpo = h.detalhe ? `<p>${esc(h.detalhe)}</p>` : '';
      if (h.acao === 'status') titulo = `Status: ${ST_TXT[h.status_novo] || h.status_novo}`;
      if (h.acao === 'abertura') corpo += thumbs(antes);
      if (h.acao === 'servico') corpo += thumbs(depois);
      return `<div class="tl-item"><b>${esc(titulo)}</b><small>${fmtDT(h.criado_em)} · ${esc(h.usuario_nome)}</small>${corpo}</div>`;
    }).join('') + '</div>';
  } catch (e) {
    $('osDetMain').innerHTML = `<p class="empty">${esc(e.message)}</p>`;
  }
}
function assumirOS(id, btn) {
  busy(btn, async () => { await api('POST', `/api/os/${id}/assumir`); toast('OS assumida. Agora você é o responsável.'); reloadOSContext(id); });
}
function iniciarOS(id, btn) {
  busy(btn, async () => { await api('POST', `/api/os/${id}/iniciar`); toast('OS em andamento.'); reloadOSContext(id); });
}
function atribuirOS(id, btn) {
  const rid = $('osResp').value;
  if (!rid) return toast('Selecione um responsável.', 'error');
  busy(btn, async () => { await api('POST', `/api/os/${id}/atribuir`, { responsavel_id: Number(rid) }); toast('Responsável atribuído.'); loadOSDetail(id); });
}
function reloadOSContext(id) {
  if ($('minhasos').classList.contains('active')) loadMinhasOS(); else loadOSDetail(id);
  refreshBell();
}

/* ======================================================= MANUTENÇÃO */
async function loadMinhasOS() {
  try {
    const [minhas, disp] = await Promise.all([api('GET', '/api/os?escopo=minhas'), api('GET', '/api/os?escopo=disponiveis')]);
    const ativas = minhas.filter(o => o.status !== 'concluida');
    const ordenadas = ativas.concat(minhas.filter(o => o.status === 'concluida'));
    $('minhasBadge').textContent = `${minhas.filter(o => o.status === 'em_andamento').length} em andamento`;
    $('minhasBody').innerHTML = ordenadas.length ? ordenadas.map(o => {
      let acao = `<button class="btn" onclick="event.stopPropagation();go('osdetalhe',${o.id})">Ver</button>`;
      if (o.status === 'aberta') acao = `<button class="btn primary" onclick="event.stopPropagation();iniciarOS(${o.id},this)">Iniciar</button>`;
      if (o.status === 'em_andamento') acao = `<button class="btn primary" onclick="event.stopPropagation();go('concluiros',${o.id})">Concluir</button>`;
      return `<tr class="clickable" onclick="go('osdetalhe',${o.id})"><td><b>${o.numero}</b></td><td>${esc(o.descricao)}</td><td>${esc(o.local)}</td><td>${priBadge(o.prioridade)}</td><td>${badge(OS_ST, o.status)}</td><td>${acao}</td></tr>`;
    }).join('') : emptyRow(6, 'Você ainda não assumiu nenhuma OS.');
    $('dispBadge').textContent = `${disp.length} disponíveis`;
    $('dispBody').innerHTML = disp.length ? disp.map(o => `<tr class="clickable" onclick="go('osdetalhe',${o.id})"><td><b>${o.numero}</b></td><td>${esc(o.descricao)}</td><td>${esc(o.local)}</td><td>${priBadge(o.prioridade)}</td><td>${fmtDT(o.criado_em)}</td><td><button class="btn primary" onclick="event.stopPropagation();assumirOS(${o.id},this)">Assumir</button></td></tr>`).join('')
      : emptyRow(6, 'Nenhuma OS disponível no momento.');
  } catch (e) { fail(e); }
}

let closingOS = null;
async function loadConcluirOS(id) {
  closingOS = null;
  $('closeReview').innerHTML = '<div><span>Carregando…</span></div>';
  $('serviceDone').value = '';
  $('serviceDone').classList.remove('field-error');
  photoPicker('finalUpload', { label: 'Adicionar foto após o serviço' });
  try {
    const o = await api('GET', `/api/os/${Number(id)}`);
    if (o.status !== 'em_andamento') {
      toast(o.status === 'concluida' ? 'Esta OS já foi concluída.' : 'Coloque a OS em andamento antes de concluir.', 'error');
      location.replace(`#osdetalhe/${o.id}`);
      return;
    }
    closingOS = o;
    $('closeTitle').textContent = `Concluir OS ${o.numero}`;
    const antes = o.fotos.filter(f => f.tipo === 'os_antes').map(f => f.id);
    $('closeReview').innerHTML = `<div><span>Qual o problema?</span><b>${esc(o.descricao)}</b></div><div><span>Local</span><b>${esc(o.local)}</b></div><div style="display:block"><span>Foto do problema</span>${thumbs(antes)}</div>`;
  } catch (e) { fail(e); }
}
function finishOS() {
  if (!closingOS) return;
  const servico = $('serviceDone').value.trim();
  const faltas = [];
  if (!servico) { faltas.push('preencha “O que foi feito?”'); $('serviceDone').classList.add('field-error'); }
  if (!pickerFiles('finalUpload').length) { faltas.push('adicione a foto depois de feito'); markPickerError('finalUpload'); }
  if (faltas.length) return toast('Para concluir a OS: ' + faltas.join(' e ') + '.', 'error');
  busy($('finishOSBtn'), async () => {
    const fd = new FormData();
    fd.append('servico_realizado', servico);
    addFiles(fd, 'finalUpload');
    await api('POST', `/api/os/${closingOS.id}/concluir`, fd);
    toast(`OS ${closingOS.numero} concluída com sucesso!`);
    location.replace(`#osdetalhe/${closingOS.id}`);
  });
}

/* ========================================================= OCORRÊNCIAS */
async function loadOcorrencias() {
  $('newOcBtn').style.display = ['admin', 'ronda'].includes(S.user.perfil) ? 'inline-block' : 'none';
  try {
    const q = new URLSearchParams({ busca: $('ocBusca').value.trim(), status: $('ocStatus').value });
    const lista = await api('GET', '/api/ocorrencias?' + q);
    $('ocBody').innerHTML = lista.length ? lista.map(o => `<tr class="clickable" onclick="openOcorrencia(${o.id})"><td><b>${o.numero}</b></td><td>${fmtDT(o.criado_em)}</td><td>${esc(o.local)}</td><td>${esc(o.descricao)}${o.total_fotos ? ' 📷' : ''}</td><td>${esc(o.usuario_nome)}</td><td>${badge(OC_ST, o.status)}</td><td>${o.os_numero ? esc(o.os_numero) : '—'}</td></tr>`).join('')
      : emptyRow(7, 'Nenhuma ocorrência encontrada.');
  } catch (e) { fail(e); }
}

async function openOcorrenciaForm() {
  try {
    const est = await getEstrutura();
    openModal('Nova ocorrência', `<div class="form-grid">
      <div class="full"><label for="ocLocal">Local *</label><input class="field" name="local" id="ocLocal" maxlength="150" placeholder="Ex.: Garagem do subsolo"></div>
      <div><label for="ocBloco">Bloco</label><select class="field" id="ocBloco" name="bloco_id" onchange="fillAndares('ocBloco','ocAndar')"><option value="">Não se aplica</option>${est.blocos.map(b => `<option value="${b.id}">${esc(b.nome)}</option>`).join('')}</select></div>
      <div><label for="ocAndar">Andar</label><select class="field" id="ocAndar" name="andar_id"><option value="">Não se aplica</option></select></div>
      <div class="full"><label for="ocDesc">Descrição *</label><textarea id="ocDesc" name="descricao" rows="4" maxlength="2000" placeholder="O que aconteceu?"></textarea></div>
      <div class="full"><label>Fotos</label><div id="ocFotos"></div></div></div>
      <div class="form-msg" id="ocMsg"></div>
      <div class="wizard-actions"><button class="btn" onclick="closeModal()">Cancelar</button><button class="btn primary" id="ocSave" onclick="saveOcorrencia()">Registrar ocorrência</button></div>`);
    photoPicker('ocFotos', { label: 'Adicionar fotos (opcional)' });
  } catch (e) { fail(e); }
}
function fillAndares(blocoSel, andarSel, selecionado) {
  const b = (S.estrutura.blocos || []).find(x => String(x.id) === $(blocoSel).value);
  $(andarSel).innerHTML = '<option value="">Não se aplica</option>' + (b ? b.andares.map(a => `<option value="${a.id}" ${a.id === selecionado ? 'selected' : ''}>${esc(a.nome)}</option>`).join('') : '');
}
function saveOcorrencia() {
  busy($('ocSave'), async () => {
    const fd = new FormData();
    fd.append('local', $('ocLocal').value); fd.append('descricao', $('ocDesc').value);
    fd.append('bloco_id', $('ocBloco').value); fd.append('andar_id', $('ocAndar').value);
    addFiles(fd, 'ocFotos');
    try {
      const r = await api('POST', '/api/ocorrencias', fd);
      closeModal();
      toast(`Ocorrência ${r.numero} registrada.`);
      if ($('ocorrencias').classList.contains('active')) loadOcorrencias();
      refreshBell();
    } catch (e) { formError($('ocMsg'), e); }
  });
}

async function openOcorrencia(id) {
  try {
    const o = await api('GET', `/api/ocorrencias/${Number(id)}`);
    const admin = S.user.perfil === 'admin';
    const local = [o.local, o.bloco_nome && !o.local.includes(o.bloco_nome) ? o.bloco_nome : '', o.andar_nome && !o.local.includes(o.andar_nome) ? o.andar_nome : ''].filter(Boolean).join(' · ');
    let extra = '';
    if (admin) {
      extra += `<label class="form-label" style="margin-top:16px">Status</label><div style="display:flex;gap:8px"><select class="field" id="ocNovoStatus">${Object.keys(OC_ST).map(k => `<option value="${k}" ${k === o.status ? 'selected' : ''}>${OC_ST[k][1]}</option>`).join('')}</select><button class="btn" onclick="saveOcStatus(${o.id},this)">Salvar</button></div>`;
      if (!o.os_id) {
        extra += `<div style="margin-top:18px;padding-top:14px;border-top:1px solid var(--line)"><b style="font-size:13px">Gerar ordem de serviço</b><div class="form-grid" style="margin-top:10px">
          <div><label for="goCat">Categoria</label><select class="field" id="goCat" name="categoria">${['Portões', 'Elétrica', 'Hidráulica', 'Iluminação', 'CFTV', 'Jardinagem', 'Limpeza', 'Civil', 'Outros'].map(c => `<option>${c}</option>`).join('')}</select></div>
          <div><label for="goPri">Prioridade</label><select class="field" id="goPri" name="prioridade"><option>Crítica</option><option>Alta</option><option selected>Média</option><option>Baixa</option></select></div>
          <div class="full"><label for="goEq">Equipamento</label><input class="field" id="goEq" maxlength="150"></div>
          ${o.fotos.length ? '' : '<div class="full"><label>Foto do problema *</label><div id="goFotos"></div></div>'}</div>
          <div class="form-msg" id="goMsg"></div><button class="btn primary big-btn" style="margin-top:10px" id="goBtn" onclick="gerarOS(${o.id})">Gerar OS a partir da ocorrência</button></div>`;
      }
    }
    openModal(`Ocorrência ${o.numero}`, `<div class="review">
      <div><span>Status</span><b>${badge(OC_ST, o.status)}</b></div>
      <div><span>Data e horário</span><b>${fmtDT(o.criado_em)}</b></div>
      <div><span>Registrada por</span><b>${esc(o.usuario_nome)}</b></div>
      <div><span>Local</span><b>${esc(local)}</b></div>
      <div><span>Descrição</span><b>${esc(o.descricao)}</b></div>
      ${o.ronda_id ? `<div><span>Ronda</span><b>#${o.ronda_id}</b></div>` : ''}
      ${o.os_id ? `<div><span>Ordem de serviço</span><b><button class="link link-btn" onclick="closeModal();go('osdetalhe',${o.os_id})">${esc(o.os_numero)}</button></b></div>` : ''}
    </div>${o.fotos.length ? '<label class="form-label" style="margin-top:14px">Fotos</label>' + thumbs(o.fotos.map(f => f.id)) : ''}${extra}`);
    if ($('goFotos')) photoPicker('goFotos', { label: 'Adicionar foto do problema' });
  } catch (e) { fail(e); }
}
function saveOcStatus(id, btn) {
  busy(btn, async () => {
    await api('POST', `/api/ocorrencias/${id}/status`, { status: $('ocNovoStatus').value });
    toast('Status atualizado.'); closeModal(); route();
  });
}
function gerarOS(id) {
  busy($('goBtn'), async () => {
    const fd = new FormData();
    fd.append('categoria', $('goCat').value); fd.append('prioridade', $('goPri').value); fd.append('equipamento', $('goEq').value);
    if ($('goFotos')) addFiles(fd, 'goFotos');
    try {
      const r = await api('POST', `/api/ocorrencias/${id}/gerar-os`, fd);
      closeModal(); toast(`OS ${r.numero} criada e vinculada à ocorrência.`); go('osdetalhe', r.id);
    } catch (e) { formError($('goMsg'), e); }
  });
}
