/* CondoIA — rondas */
'use strict';

async function loadRonda() {
  try {
    const r = await api('GET', '/api/rondas/atual');
    S.ronda = r.ronda;
    renderRonda();
    await processPendingQr();
  } catch (e) { fail(e); }
}

function renderRonda() {
  const r = S.ronda;
  const pend = sessionStorage.getItem('condoia_qr');
  $('rondaInicio').style.display = r ? 'none' : 'block';
  $('rondaAtiva').style.display = r ? 'grid' : 'none';
  if (!r) {
    $('rondaQrAviso').innerHTML = pend ? '<div class="alert-card" style="margin-top:12px">📷 QR Code lido. Inicie a ronda para validar o bloco.</div>' : '';
    return;
  }
  const p = r.progresso;
  $('roundProgress').textContent = `${p.pontos_ok} de ${p.pontos_total} pontos`;
  $('roundProgress').className = 'badge ' + (p.pontos_ok === p.pontos_total ? 'ok' : 'warn');
  $('blocksProgress').textContent = `${p.blocos_ok} de ${p.blocos_total} blocos`;
  $('rondaInfo').textContent = `Iniciada em ${fmtDT(r.iniciada_em)} por ${r.usuario}.`;
  const grupo = g => r.pontos.filter(x => x.grupo === g).map(x => pointHTML('ponto', x)).join('') || '<p class="empty">Nenhum ponto.</p>';
  $('northPoints').innerHTML = grupo('guarita_norte');
  $('southPoints').innerHTML = grupo('guarita_sul');
  $('commonPoints').innerHTML = grupo('area_comum');
  $('qrGrid').innerHTML = r.blocos.map(blockCard).join('');
  const aberto = r.blocos.find(b => b.id === S.blocoAberto && b.validado);
  if (aberto) renderBlock(aberto);
  else $('blockDetail').innerHTML = `<div class="card-head"><h2>Bloco selecionado</h2></div><p class="note">${r.exigir_qr ? 'Escaneie o QR Code de um bloco para iniciar a verificação dos andares.' : 'Selecione um bloco para verificar os andares.'}</p>`;
}

function pointHTML(kind, item, readOnly) {
  const key = `${kind}-${item.id}`;
  const reg = item.registro;
  const wrapCls = kind === 'andar' ? 'floor-box' : 'round-point';
  const head = `<div style="display:flex;justify-content:space-between;gap:10px"><b>${esc(item.nome)}</b>${reg ? badge(PT_ST, reg.status) : '<span class="status pend">PENDENTE</span>'}</div>`;
  const obs = kind === 'ponto' && item.observacao ? `<div class="round-done">${esc(item.observacao)}</div>` : '';
  if (reg) {
    const partes = [`Registrado às ${fmtH(reg.registrado_em)}`];
    if (reg.observacao) partes.push(esc(reg.observacao));
    const oc = reg.ocorrencia ? ` · <button class="link link-btn" onclick="openOcorrencia(${Number(reg.ocorrencia_id)})">Ocorrência ${esc(reg.ocorrencia)}</button>` : '';
    return `<div class="${wrapCls}">${head}${obs}<div class="round-done">${partes.join(' · ')}${oc}</div>${thumbs(reg.fotos)}</div>`;
  }
  if (readOnly) return `<div class="${wrapCls}">${head}${obs}</div>`;
  return `<div class="${wrapCls}">${head}${obs}<div class="round-actions">
    <button onclick="pickStatus('${kind}',${Number(item.id)},'ok',this)">🟢 OK</button>
    <button onclick="pickStatus('${kind}',${Number(item.id)},'atencao',this)">🟡 Atenção</button>
    <button onclick="pickStatus('${kind}',${Number(item.id)},'problema',this)">🔴 Problema</button></div>
    <div class="round-form" id="rf-${key}" style="display:none"></div></div>`;
}

function pickStatus(kind, id, status, btn) {
  const key = `${kind}-${id}`;
  btn.parentElement.querySelectorAll('button').forEach(b => { b.className = ''; });
  btn.className = status === 'ok' ? 'sel-ok' : status === 'atencao' ? 'sel-warn' : 'sel-prob';
  const form = $(`rf-${key}`);
  if (status === 'ok') { form.style.display = 'none'; form.innerHTML = ''; submitRonda(kind, id, 'ok', btn); return; }
  const prob = status === 'problema';
  form.style.display = 'block';
  form.innerHTML = `<label class="form-label" for="rfo-${key}">${prob ? 'Descreva o problema *' : 'Observação'}</label>
    <textarea id="rfo-${key}" rows="3" maxlength="1000" placeholder="${prob ? 'O que foi encontrado?' : 'Opcional'}"></textarea>
    <div id="rfp-${key}"></div>${prob ? '<div class="photo-required">⚠ Foto obrigatória para registrar o problema.</div>' : ''}
    <div class="wizard-actions" style="margin-top:12px;padding-top:12px"><button class="btn" onclick="cancelStatus('${key}')">Cancelar</button><button class="btn primary" onclick="submitRonda('${kind}',${id},'${status}',this)">Registrar ${prob ? 'problema' : 'atenção'}</button></div>`;
  photoPicker(`rfp-${key}`, { label: prob ? 'Tirar foto do problema' : 'Adicionar foto (opcional)' });
  $(`rfo-${key}`).focus();
}
function cancelStatus(key) {
  const form = $(`rf-${key}`);
  form.style.display = 'none'; form.innerHTML = '';
  form.previousElementSibling.querySelectorAll('button').forEach(b => { b.className = ''; });
}

function submitRonda(kind, id, status, btn) {
  const key = `${kind}-${id}`;
  const obsEl = $(`rfo-${key}`);
  const obs = obsEl ? obsEl.value.trim() : '';
  if (status === 'problema') {
    if (!obs) { obsEl.classList.add('field-error'); return toast('Descreva o problema encontrado.', 'error'); }
    if (!pickerFiles(`rfp-${key}`).length) { markPickerError(`rfp-${key}`); return toast('Adicione uma foto para registrar este problema.', 'error'); }
  }
  const fd = new FormData();
  fd.append(kind === 'ponto' ? 'ponto_id' : 'andar_id', id);
  fd.append('status', status);
  fd.append('observacao', obs);
  if (status !== 'ok') addFiles(fd, `rfp-${key}`);
  const url = `/api/rondas/${S.ronda.id}/${kind === 'ponto' ? 'pontos' : 'andares'}`;
  const antes = S.ronda.blocos.filter(b => b.concluido).length;
  return busy(btn, async () => {
    try {
      const r = await api('POST', url, fd);
      S.ronda = r.ronda;
      renderRonda();
      const depois = S.ronda.blocos.filter(b => b.concluido).length;
      if (depois > antes) toast('✓ Todos os andares verificados. Bloco concluído!');
      else toast(status === 'problema' ? 'Problema registrado e ocorrência criada.' : 'Registrado.');
    } catch (e) {
      if (status === 'ok') renderRonda();
      throw e;
    }
  });
}

function blockCard(b) {
  const feitos = b.andares.filter(a => a.registro).length;
  let st, cls = '';
  if (!b.andares.length) st = '<span class="status pend">SEM ANDARES</span>';
  else if (b.concluido) { st = '<span class="status ok">CONCLUÍDO</span>'; cls = 'done'; }
  else if (b.validado) { st = '<span class="status info">QR VALIDADO</span>'; cls = 'valid'; }
  else st = '<span class="status pend">PENDENTE</span>';
  let botao;
  if (b.validado) botao = `<button class="btn primary" style="width:100%" onclick="openBlock(${b.id})">Ver andares</button>`;
  else if (S.ronda.exigir_qr) botao = `<button class="btn primary" style="width:100%" onclick="openScanner()">📷 Escanear QR Code</button>`;
  else botao = `<button class="btn primary" style="width:100%" onclick="manualBlock(${b.id},this)">Verificar bloco</button>`;
  return `<div class="qr-card ${cls}"><div class="qr"></div><b>${esc(b.nome)}</b><br>${st}<p class="note" style="margin:0 0 10px">${b.andares.length ? `${feitos} de ${b.andares.length} andares` : 'Andares não cadastrados'}</p>${botao}</div>`;
}
function openBlock(id) {
  S.blocoAberto = id;
  renderRonda();
  $('blockDetail').scrollIntoView({ behavior: 'smooth', block: 'start' });
}
function renderBlock(b) {
  const head = `<div class="card-head"><h2>${esc(b.nome)}</h2>${b.concluido ? '<span class="badge ok">Ronda concluída</span>' : `<span class="badge info">${b.via_qr ? 'QR validado' : 'Sem QR'} às ${fmtH(b.validado_em)}</span>`}</div>`;
  if (!b.andares.length) {
    $('blockDetail').innerHTML = head + '<p class="note">Nenhum andar cadastrado neste bloco. Peça à Administração para configurar em “Blocos e QR Codes”.</p>';
    return;
  }
  $('blockDetail').innerHTML = head + `<p class="note">Verifique cada andar separadamente. O bloco é concluído quando todos os ${b.andares.length} andares forem registrados.</p>`
    + b.andares.map(a => pointHTML('andar', a)).join('');
}
function manualBlock(id, btn) {
  busy(btn, async () => {
    const r = await api('POST', `/api/rondas/${S.ronda.id}/blocos/${id}/manual`);
    S.ronda = r.ronda; openBlock(r.bloco_id);
  });
}

/* ------------------------------------------------------------ QR Code */
async function processPendingQr() {
  const pend = sessionStorage.getItem('condoia_qr');
  if (!pend || !S.ronda) return;
  sessionStorage.removeItem('condoia_qr');
  try { await submitQr(pend); } catch (e) { fail(e); }
}
function startRonda() {
  const btn = document.querySelector('#rondaInicio .big-btn');
  return busy(btn, async () => {
    const r = await api('POST', '/api/rondas');
    S.ronda = r.ronda; S.blocoAberto = null;
    toast('Ronda iniciada.');
    renderRonda();
    await processPendingQr();
  });
}

function openScanner() {
  if (!S.ronda) return toast('Inicie a ronda antes de escanear.', 'error');
  const suporte = 'BarcodeDetector' in window && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  openModal('Escanear QR Code do bloco', `
    ${suporte ? '<video id="scanVideo" class="scanner-video" playsinline muted></video>' : ''}
    <p class="note" id="scanMsg" style="margin-top:10px">${suporte ? 'Aponte a câmera para o QR Code do bloco.' : 'Este navegador não lê QR Code dentro do sistema. Use a câmera do celular: aponte para o QR Code e toque no link — o CondoIA abre e valida o bloco automaticamente. Ou digite o código impresso abaixo do QR Code.'}</p>
    <label class="form-label" style="margin-top:14px" for="scanCode">Código impresso abaixo do QR Code</label>
    <div style="display:flex;gap:8px"><input class="field" id="scanCode" autocapitalize="none" autocomplete="off" onkeydown="if(event.key==='Enter')$('scanBtn').click()"><button class="btn primary" id="scanBtn" onclick="busy(this,()=>submitQr($('scanCode').value))">Validar</button></div>`, stopScanner);
  if (suporte) startScanner();
}
async function startScanner() {
  try {
    const detector = new BarcodeDetector({ formats: ['qr_code'] });
    S.scanStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
    const video = $('scanVideo');
    if (!video) { stopScanner(); return; }
    video.srcObject = S.scanStream;
    await video.play();
    const loop = async () => {
      if (!S.scanStream || !$('scanVideo')) return;
      try {
        const codes = await detector.detect(video);
        if (codes.length) { const valor = codes[0].rawValue; stopScanner(); await submitQr(valor).catch(fail); return; }
      } catch (e) { /* quadro ainda não disponível */ }
      S.timers.scan = setTimeout(loop, 250);
    };
    loop();
  } catch (e) {
    stopScanner();
    if ($('scanVideo')) $('scanVideo').style.display = 'none';
    if ($('scanMsg')) $('scanMsg').textContent = 'Não foi possível acessar a câmera (permissão negada ou conexão sem HTTPS). Use a câmera do celular para abrir o link do QR Code, ou digite o código impresso.';
  }
}
function stopScanner() {
  clearTimeout(S.timers.scan);
  if (S.scanStream) { S.scanStream.getTracks().forEach(t => t.stop()); S.scanStream = null; }
}
async function submitQr(codigo) {
  if (!codigo || !codigo.trim()) { toast('Informe o código do QR Code.', 'error'); return; }
  const r = await api('POST', `/api/rondas/${S.ronda.id}/blocos/validar`, { codigo: codigo.trim() });
  S.ronda = r.ronda;
  if ($('modal').style.display !== 'none') closeModal();
  const b = S.ronda.blocos.find(x => x.id === r.bloco_id);
  toast(`QR Code validado: ${b ? b.nome : 'bloco'}.`);
  openBlock(r.bloco_id);
}

/* ------------------------------------------------------------ finalizar */
function finishRonda() {
  const r = S.ronda;
  if (!r) return;
  const pend = r.pontos.filter(p => !p.registro).map(p => p.nome).concat(r.blocos.filter(b => !b.concluido).map(b => b.nome));
  const corpo = pend.length
    ? `<div class="alert-card">Ainda há ${pend.length} item(ns) pendente(s): <b>${esc(pend.join(', '))}</b>.</div><label class="form-label" for="finObs">Motivo para finalizar com pendências *</label><textarea id="finObs" name="observacao" rows="3" maxlength="1000"></textarea>`
    : '<p class="note">Todos os pontos e blocos foram verificados.</p><label class="form-label" for="finObs">Observação (opcional)</label><textarea id="finObs" name="observacao" rows="3" maxlength="1000"></textarea>';
  openModal('Finalizar ronda', corpo + `<div class="form-msg" id="finMsg"></div><div class="wizard-actions"><button class="btn" onclick="closeModal()">Continuar ronda</button><button class="btn primary" id="finBtn" onclick="confirmFinish()">Finalizar ronda</button></div>`);
}
function confirmFinish() {
  busy($('finBtn'), async () => {
    try {
      const r = await api('POST', `/api/rondas/${S.ronda.id}/finalizar`, { observacao: $('finObs').value.trim() });
      closeModal();
      S.ronda = null; S.blocoAberto = null;
      toast(r.ronda.status === 'concluida' ? 'Ronda concluída e registrada.' : 'Ronda finalizada com pendências.');
      go('rondadetalhe', r.ronda.id);
    } catch (e) { formError($('finMsg'), e); }
  });
}

/* ------------------------------------------------------------ histórico */
async function loadRondaHist() {
  const admin = S.user.perfil === 'admin';
  $('rondaHistTitle').textContent = admin ? '✓ Rondas' : '✓ Minhas rondas';
  try {
    if (admin && $('rhUser').options.length === 1) {
      const us = await api('GET', '/api/admin/usuarios');
      us.filter(u => u.perfil === 'ronda').forEach(u => $('rhUser').add(new Option(u.nome, u.id)));
      $('rhUser').style.display = 'inline-block';
    }
    const q = new URLSearchParams({ de: $('rhDe').value, ate: $('rhAte').value, usuario: admin ? $('rhUser').value : '' });
    const lista = await api('GET', '/api/rondas?' + q);
    $('rondaHistBody').innerHTML = lista.length ? lista.map(r => `<tr class="clickable" onclick="go('rondadetalhe',${r.id})"><td><b>#${r.id}</b></td><td>${esc(r.usuario)}</td><td>${fmtDT(r.iniciada_em)}</td><td>${fmtDT(r.finalizada_em)}</td><td>${r.registros}</td><td>${r.problemas ? `<span class="status danger">${r.problemas}</span>` : '0'}</td><td>${badge(RD_ST, r.status)}</td></tr>`).join('')
      : emptyRow(7, 'Nenhuma ronda encontrada.');
  } catch (e) { fail(e); }
}

async function loadRondaDetail(id) {
  const box = $('rondaDetContent');
  box.innerHTML = '<div class="card"><p class="empty">Carregando…</p></div>';
  try {
    const { ronda: r } = await api('GET', `/api/rondas/${Number(id)}`);
    const p = r.progresso;
    const grupos = [['guarita_norte', '🛡️ Guarita Norte'], ['guarita_sul', '🛡️ Guarita Sul'], ['area_comum', '🏖️ Áreas comuns']];
    const continuar = S.user.perfil === 'ronda' && r.status === 'em_andamento' ? `<button class="btn primary big-btn" style="margin-top:12px" onclick="go('rondas')">Continuar ronda</button>` : '';
    box.innerHTML = `<div class="card"><div class="card-head"><h2>Ronda #${r.id}</h2>${badge(RD_ST, r.status)}</div>
      <div class="review"><div><span>Usuário</span><b>${esc(r.usuario)}</b></div><div><span>Início</span><b>${fmtDT(r.iniciada_em)}</b></div>
      <div><span>Término</span><b>${fmtDT(r.finalizada_em)}</b></div><div><span>Pontos verificados</span><b>${p.pontos_ok} de ${p.pontos_total}</b></div>
      <div><span>Blocos concluídos</span><b>${p.blocos_ok} de ${p.blocos_total}</b></div>${r.observacao ? `<div><span>Observação</span><b>${esc(r.observacao)}</b></div>` : ''}</div>${continuar}</div>
      <div class="two-col"><div>${grupos.map(([g, t]) => `<div class="card"><div class="card-head"><h2>${t}</h2></div>${r.pontos.filter(x => x.grupo === g).map(x => pointHTML('ponto', x, true)).join('')}</div>`).join('')}</div>
      <div>${r.blocos.map(b => `<div class="card"><div class="card-head"><h2>🏢 ${esc(b.nome)}</h2>${b.concluido ? '<span class="badge ok">Concluído</span>' : b.validado ? '<span class="badge info">Incompleto</span>' : '<span class="badge warn">Não verificado</span>'}</div>
        ${b.validado ? `<p class="note">${b.via_qr ? 'QR Code validado' : 'Verificado sem QR Code'} às ${fmtH(b.validado_em)}${b.concluido_em ? ' · concluído às ' + fmtH(b.concluido_em) : ''}</p>` : '<p class="note">QR Code não escaneado nesta ronda.</p>'}
        ${b.andares.map(a => pointHTML('andar', a, true)).join('')}</div>`).join('')}</div></div>`;
  } catch (e) { box.innerHTML = `<div class="card"><p class="empty">${esc(e.message)}</p></div>`; }
}
