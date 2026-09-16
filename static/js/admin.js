/* CondoIA — telas administrativas e assistente */
'use strict';

function val(id) { return $(id) ? $(id).value.trim() : ''; }
function opts(lista, selecionado, vazio) {
  return (vazio !== undefined ? `<option value="">${esc(vazio)}</option>` : '') + lista.map(o => {
    const [v, t] = Array.isArray(o) ? o : [o, o];
    return `<option value="${esc(v)}" ${String(v) === String(selecionado ?? '') ? 'selected' : ''}>${esc(t)}</option>`;
  }).join('');
}
function actions(saveLabel, onclick) {
  return `<div class="form-msg" id="fMsg"></div><div class="wizard-actions"><button class="btn" onclick="closeModal()">Cancelar</button><button class="btn primary" id="fSave" onclick="${onclick}">${esc(saveLabel)}</button></div>`;
}
function saveForm(fn) {
  busy($('fSave'), async () => { try { await fn(); } catch (e) { formError($('fMsg'), e); } });
}

/* ============================================================ UNIDADES */
let unidadesCache = [];
async function loadUnidades() {
  try {
    unidadesCache = await api('GET', '/api/admin/unidades');
    $('uniBody').innerHTML = unidadesCache.length ? unidadesCache.map(u => `<tr><td><b>${esc(u.numero)}</b></td><td>${esc(u.bloco_nome)}</td><td>${esc(u.andar_nome || '—')}</td><td><span class="status ${u.status === 'ocupada' ? 'ok' : 'pend'}">${u.status === 'ocupada' ? 'OCUPADA' : 'DESOCUPADA'}</span></td><td style="white-space:nowrap"><button class="btn" onclick="openUnidadeForm(${u.id})">Editar</button> <button class="btn" onclick="deleteUnidade(${u.id})">Excluir</button></td></tr>`).join('')
      : emptyRow(5, 'Nenhuma unidade cadastrada. Use “Adicionar unidade”.');
  } catch (e) { fail(e); }
}
async function openUnidadeForm(id) {
  const u = unidadesCache.find(x => x.id === id) || {};
  const est = await getEstrutura(true).catch(fail);
  if (!est) return;
  openModal(id ? `Editar unidade ${u.numero}` : 'Adicionar unidade', `<div class="form-grid">
    <div><label for="fNum">Unidade *</label><input class="field" id="fNum" name="numero" maxlength="20" value="${esc(u.numero || '')}" placeholder="Ex.: 101"></div>
    <div><label for="fSt">Status</label><select class="field" id="fSt" name="status">${opts([['ocupada', 'Ocupada'], ['desocupada', 'Desocupada']], u.status || 'ocupada')}</select></div>
    <div><label for="fBloco">Bloco *</label><select class="field" id="fBloco" name="bloco_id" onchange="fillAndares('fBloco','fAndar')">${opts(est.blocos.map(b => [b.id, b.nome]), u.bloco_id, 'Selecione…')}</select></div>
    <div><label for="fAndar">Andar</label><select class="field" id="fAndar" name="andar_id"></select></div>
    <div class="full"><label for="fObs">Observação</label><textarea id="fObs" name="observacao" rows="2" maxlength="500">${esc(u.observacao || '')}</textarea></div></div>`
    + actions('Salvar', `saveUnidade(${id || 0})`));
  fillAndares('fBloco', 'fAndar', u.andar_id);
}
function saveUnidade(id) {
  saveForm(async () => {
    const body = { numero: val('fNum'), status: val('fSt'), bloco_id: val('fBloco'), andar_id: val('fAndar'), observacao: val('fObs') };
    await api(id ? 'PUT' : 'POST', `/api/admin/unidades${id ? '/' + id : ''}`, body);
    closeModal(); toast('Unidade salva.'); loadUnidades();
  });
}
function deleteUnidade(id) {
  const u = unidadesCache.find(x => x.id === id);
  confirmModal('Excluir unidade', `Excluir a unidade ${u ? u.numero : ''}? Essa ação fica registrada na auditoria.`, 'Excluir', async () => {
    await api('DELETE', `/api/admin/unidades/${id}`); closeModal(); toast('Unidade excluída.'); loadUnidades();
  });
}

/* =============================================== EMPRESAS TERCEIRIZADAS */
const SERVICOS = ['Limpeza', 'Jardinagem', 'Elevadores', 'Elétrica', 'Hidráulica', 'Piscina', 'Segurança', 'Manutenção', 'Outros'];
let empresasCache = [];
async function loadEmpresas() {
  try {
    empresasCache = await api('GET', '/api/admin/empresas');
    const hoje = todayISO();
    $('empBody').innerHTML = empresasCache.length ? empresasCache.map(e => {
      const vencido = e.data_termino && e.data_termino < hoje;
      const st = !e.ativo ? '<span class="status pend">INATIVA</span>' : vencido ? '<span class="status danger">CONTRATO VENCIDO</span>' : '<span class="status ok">ATIVA</span>';
      const contato = [e.responsavel, e.telefone, e.email].filter(Boolean).map(esc).join(' · ') || '—';
      return `<tr class="clickable" onclick="openEmpresaForm(${e.id})"><td><b>${esc(e.nome)}</b></td><td>${esc(e.servico)}</td><td>${contato}</td><td>${esc(e.contrato || '—')}</td><td>${fmtD(e.data_termino)}</td><td>${st}</td></tr>`;
    }).join('') : emptyRow(6, 'Nenhuma empresa cadastrada. Use “Adicionar empresa”.');
  } catch (e) { fail(e); }
}
function openEmpresaForm(id) {
  const e = empresasCache.find(x => x.id === id) || { ativo: 1 };
  openModal(id ? 'Editar empresa' : 'Adicionar empresa', `<div class="form-grid">
    <div class="full"><label for="fNome">Empresa *</label><input class="field" id="fNome" name="nome" maxlength="150" value="${esc(e.nome || '')}"></div>
    <div><label for="fServ">Serviço prestado *</label><select class="field" id="fServ" name="servico">${opts(SERVICOS, e.servico, 'Selecione…')}</select></div>
    <div><label for="fResp">Responsável</label><input class="field" id="fResp" maxlength="120" value="${esc(e.responsavel || '')}"></div>
    <div><label for="fTel">Telefone</label><input class="field" id="fTel" type="tel" maxlength="40" value="${esc(e.telefone || '')}"></div>
    <div><label for="fEmail">E-mail</label><input class="field" id="fEmail" name="email" type="email" maxlength="150" value="${esc(e.email || '')}"></div>
    <div><label for="fContr">Contrato</label><input class="field" id="fContr" maxlength="120" value="${esc(e.contrato || '')}" placeholder="Nº ou referência"></div>
    <div></div>
    <div><label for="fIni">Data de início</label><input class="field" id="fIni" name="data_inicio" type="date" value="${esc(e.data_inicio || '')}"></div>
    <div><label for="fFim">Término / validade</label><input class="field" id="fFim" name="data_termino" type="date" value="${esc(e.data_termino || '')}"></div>
    <div class="full"><label for="fObs">Observações</label><textarea id="fObs" rows="3" maxlength="2000">${esc(e.observacoes || '')}</textarea></div>
    ${id ? `<div class="full"><label class="check-row"><input type="checkbox" id="fAtivo" ${e.ativo ? 'checked' : ''}> Empresa ativa</label><p class="note">Documentos relacionados: ${e.documentos || 0} (vincule em Documentos).</p></div>` : ''}</div>`
    + actions('Salvar', `saveEmpresa(${id || 0})`));
}
function saveEmpresa(id) {
  saveForm(async () => {
    const body = { nome: val('fNome'), servico: val('fServ'), responsavel: val('fResp'), telefone: val('fTel'), email: val('fEmail'), contrato: val('fContr'), data_inicio: val('fIni'), data_termino: val('fFim'), observacoes: val('fObs'), ativo: id ? $('fAtivo').checked : true };
    await api(id ? 'PUT' : 'POST', `/api/admin/empresas${id ? '/' + id : ''}`, body);
    closeModal(); toast('Empresa salva.'); loadEmpresas();
  });
}

/* =========================================================== DOCUMENTOS */
const CAT_DOC = ['Normas', 'Contratos', 'Laudos', 'Certificados', 'Terceirizados', 'Administrativo', 'Outros'];
let docsCache = [];
async function loadDocumentos() {
  try {
    docsCache = await api('GET', '/api/admin/documentos');
    const hoje = todayISO();
    const lim = new Date(); lim.setDate(lim.getDate() + 30);
    const limite = new Date(lim.getTime() - lim.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    $('docBody').innerHTML = docsCache.length ? docsCache.map(d => {
      let st = '<span class="status info">VIGENTE</span>';
      if (d.validade && d.validade < hoje) st = '<span class="status danger">VENCIDO</span>';
      else if (d.validade && d.validade <= limite) st = '<span class="status warn">A VENCER</span>';
      return `<tr><td><b>${esc(d.nome)}</b><br><small class="note">${esc(d.nome_original || '')}${d.empresa_nome ? ' · ' + esc(d.empresa_nome) : ''}</small></td><td>${esc(d.categoria)}</td><td>${esc(d.responsavel || '—')}</td><td>${fmtD(d.validade)}</td><td>${st}</td>
        <td style="white-space:nowrap"><a class="btn" href="/api/admin/documentos/${d.id}/arquivo">Baixar</a> <button class="btn" onclick="openDocumentoForm(${d.id})">Editar</button> <button class="btn" onclick="deleteDocumento(${d.id})">Excluir</button></td></tr>`;
    }).join('') : emptyRow(6, 'Nenhum documento cadastrado. Use “Adicionar documento”.');
  } catch (e) { fail(e); }
}
async function openDocumentoForm(id) {
  const d = docsCache.find(x => x.id === id) || {};
  const emps = empresasCache.length ? empresasCache : await api('GET', '/api/admin/empresas').catch(() => []);
  openModal(id ? 'Editar documento' : 'Adicionar documento', `<div class="form-grid">
    <div class="full"><label for="fNome">Nome *</label><input class="field" id="fNome" name="nome" maxlength="150" value="${esc(d.nome || '')}"></div>
    <div><label for="fCat">Categoria *</label><select class="field" id="fCat" name="categoria">${opts(CAT_DOC, d.categoria, 'Selecione…')}</select></div>
    <div><label for="fResp">Responsável</label><input class="field" id="fResp" maxlength="120" value="${esc(d.responsavel || '')}"></div>
    <div><label for="fData">Data</label><input class="field" id="fData" name="data_documento" type="date" value="${esc(d.data_documento || '')}"></div>
    <div><label for="fVal">Validade</label><input class="field" id="fVal" name="validade" type="date" value="${esc(d.validade || '')}"></div>
    <div class="full"><label for="fEmp">Empresa terceirizada relacionada</label><select class="field" id="fEmp">${opts(emps.map(e => [e.id, e.nome]), d.empresa_id, 'Nenhuma')}</select></div>
    <div class="full"><label for="fObs">Observação</label><textarea id="fObs" rows="2" maxlength="2000">${esc(d.observacao || '')}</textarea></div>
    <div class="full"><label for="fArq">Arquivo ${id ? '(envie apenas para substituir)' : '*'}</label><input class="field" id="fArq" name="arquivo" type="file" accept=".pdf,.jpg,.jpeg,.png,.docx,.xlsx"><p class="note">PDF, JPG, PNG, DOCX ou XLSX · até 20 MB</p></div></div>`
    + actions('Salvar', `saveDocumento(${id || 0})`));
}
function saveDocumento(id) {
  saveForm(async () => {
    const fd = new FormData();
    [['nome', 'fNome'], ['categoria', 'fCat'], ['responsavel', 'fResp'], ['data_documento', 'fData'], ['validade', 'fVal'], ['empresa_id', 'fEmp'], ['observacao', 'fObs']].forEach(([k, i]) => fd.append(k, val(i)));
    const f = $('fArq').files[0];
    if (f) fd.append('arquivo', f, f.name);
    await api(id ? 'PUT' : 'POST', `/api/admin/documentos${id ? '/' + id : ''}`, fd);
    closeModal(); toast('Documento salvo.'); loadDocumentos();
  });
}
function deleteDocumento(id) {
  const d = docsCache.find(x => x.id === id);
  confirmModal('Excluir documento', `Excluir “${d ? d.nome : ''}” e o arquivo anexado? A exclusão fica registrada na auditoria.`, 'Excluir', async () => {
    await api('DELETE', `/api/admin/documentos/${id}`); closeModal(); toast('Documento excluído.'); loadDocumentos();
  });
}

/* =========================================================== RELATÓRIOS */
async function loadRelatorios() {
  if (!$('relDe').value) { $('relDe').value = todayISO().slice(0, 8) + '01'; $('relAte').value = todayISO(); }
  try {
    const r = await api('GET', `/api/relatorios?de=${$('relDe').value}&ate=${$('relAte').value}`);
    const m = (n, t) => `<div class="metric"><div class="number">${esc(n)}</div><p>${esc(t)}</p></div>`;
    $('relMetrics').innerHTML = m(r.os_abertas_periodo, 'OS abertas no período') + m(r.os_concluidas_periodo, 'OS concluídas no período')
      + m(r.tempo_medio_horas === null ? '—' : r.tempo_medio_horas + 'h', 'Tempo médio até concluir') + m(r.rondas_finalizadas, 'Rondas finalizadas')
      + m(r.percentual_rondas === null ? '—' : r.percentual_rondas + '%', 'Rondas concluídas sem pendência') + m(r.problemas, 'Problemas nas rondas');
    const tabela = (lista, cols, vazio) => lista.length ? `<div class="table-wrap"><table class="table"><thead><tr>${cols.map(c => `<th>${c[0]}</th>`).join('')}</tr></thead><tbody>${lista.map(x => `<tr>${cols.map(c => `<td>${esc(x[c[1]] ?? 0)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : `<p class="empty">${vazio}</p>`;
    $('relCat').innerHTML = tabela(r.os_por_categoria, [['CATEGORIA', 'nome'], ['TOTAL', 'total']], 'Sem OS no período.');
    $('relLocal').innerHTML = tabela(r.ocorrencias_por_local, [['LOCAL / BLOCO', 'nome'], ['TOTAL', 'total']], 'Sem ocorrências no período.');
    $('relRondas').innerHTML = tabela(r.rondas_por_usuario, [['USUÁRIO', 'nome'], ['RONDAS', 'total'], ['SEM PENDÊNCIA', 'concluidas']], 'Sem rondas finalizadas no período.');
  } catch (e) { fail(e); }
}

/* ===================================================== BLOCOS E QR CODES */
let blocosCache = [];
async function loadBlocosAdmin() {
  try {
    blocosCache = await api('GET', '/api/admin/blocos');
    $('adminQrGrid').innerHTML = blocosCache.map(b => `<div class="qr-card">
      ${b.qr_token ? `<img class="qr-img" src="/api/admin/blocos/${b.id}/qr.svg?v=${encodeURIComponent(b.qr_token)}" alt="QR Code do ${esc(b.nome)}">` : '<div class="qr"></div>'}
      <b>${esc(b.nome)}</b><br><span class="status ${b.andares ? 'ok' : 'warn'}">${b.andares ? b.andares + ' ANDAR(ES)' : 'SEM ANDARES'}</span>
      <p class="note" style="margin:0 0 10px;word-break:break-all">Código: ${esc(b.qr_token || '—')}</p>
      <button class="btn primary" style="width:100%;margin-bottom:6px" onclick="openBlocoForm(${b.id})">Editar andares</button>
      <button class="btn" style="width:100%" onclick="regenerarQr(${b.id})">Gerar novo QR Code</button></div>`).join('');
  } catch (e) { fail(e); }
}
function openBlocoForm(id) {
  const b = blocosCache.find(x => x.id === id);
  openModal(`Editar ${b.nome}`, `<div class="form-grid"><div><label for="fNome">Nome</label><input class="field" id="fNome" name="nome" maxlength="60" value="${esc(b.nome)}"></div>
    <div><label for="fAnd">Quantidade de andares</label><input class="field" id="fAnd" name="andares" type="number" min="0" max="60" value="${b.andares}"></div>
    <div class="full"><p class="note">Os andares são criados como 1º, 2º, 3º… Reduzir a quantidade desativa os andares excedentes, sem apagar o histórico das rondas.</p></div></div>`
    + actions('Salvar', `saveBloco(${id})`));
}
function saveBloco(id) {
  saveForm(async () => {
    await api('PUT', `/api/admin/blocos/${id}`, { nome: val('fNome'), andares: val('fAnd') });
    S.estrutura = null; closeModal(); toast('Bloco atualizado.'); loadBlocosAdmin();
  });
}
function regenerarQr(id) {
  const b = blocosCache.find(x => x.id === id);
  confirmModal('Gerar novo QR Code', `O QR Code atual do ${b.nome} deixará de funcionar imediatamente. Será preciso imprimir e colar o novo. Continuar?`, 'Gerar novo QR Code', async () => {
    await api('POST', `/api/admin/blocos/${id}/qr/regenerar`); closeModal(); toast('Novo QR Code gerado.'); loadBlocosAdmin();
  });
}

/* ============================================================ USUÁRIOS */
const PERFIS = [['admin', 'Administração'], ['ronda', 'Ronda'], ['manutencao', 'Manutenção']];
let usuariosCache = [];
async function loadUsuarios() {
  try {
    usuariosCache = await api('GET', '/api/admin/usuarios');
    $('usrBody').innerHTML = usuariosCache.map(u => `<tr><td><b>${esc(u.nome)}</b>${u.email ? `<br><small class="note">${esc(u.email)}</small>` : ''}</td><td>${esc(u.usuario)}</td><td>${esc(u.perfil_nome)}</td><td>${fmtDT(u.ultimo_acesso)}</td><td><span class="status ${u.ativo ? 'ok' : 'pend'}">${u.ativo ? 'ATIVO' : 'INATIVO'}</span></td><td><button class="btn" onclick="openUsuarioForm(${u.id})">Editar</button></td></tr>`).join('');
  } catch (e) { fail(e); }
}
function openUsuarioForm(id) {
  const u = usuariosCache.find(x => x.id === id) || { ativo: 1, perfil: 'ronda' };
  const proprio = id === S.user.id;
  openModal(id ? `Editar ${u.usuario}` : 'Adicionar usuário', `<div class="form-grid">
    <div class="full"><label for="fNome">Nome *</label><input class="field" id="fNome" name="nome" maxlength="120" value="${esc(u.nome || '')}"></div>
    ${id ? '' : '<div><label for="fUser">Usuário (login) *</label><input class="field" id="fUser" name="usuario" maxlength="40" autocapitalize="none" placeholder="ex.: ronda05"></div>'}
    <div><label for="fEmail">E-mail</label><input class="field" id="fEmail" name="email" type="email" maxlength="150" value="${esc(u.email || '')}"></div>
    <div><label for="fPerfil">Perfil *</label><select class="field" id="fPerfil" name="perfil" ${proprio ? 'disabled' : ''}>${opts(PERFIS, u.perfil)}</select></div>
    ${id ? `<div><label class="check-row" style="margin-top:24px"><input type="checkbox" id="fAtivo" ${u.ativo ? 'checked' : ''} ${proprio ? 'disabled' : ''}> Usuário ativo</label></div>`
    : '<div><label for="fSenha">Senha inicial *</label><input class="field" id="fSenha" name="senha" type="password" minlength="8" autocomplete="new-password"></div>'}</div>`
    + actions('Salvar', `saveUsuario(${id || 0})`)
    + (id ? `<div style="margin-top:16px;padding-top:14px;border-top:1px solid var(--line)"><label class="form-label" for="fNova">Redefinir senha</label><div style="display:flex;gap:8px"><input class="field" id="fNova" name="senha" type="password" minlength="8" autocomplete="new-password" placeholder="Nova senha (mín. 8 caracteres)"><button class="btn" onclick="resetSenha(${id},this)">Redefinir</button></div><p class="note">O usuário será desconectado dos aparelhos em que estiver logado.</p></div>` : ''));
}
function saveUsuario(id) {
  saveForm(async () => {
    const body = { nome: val('fNome'), email: val('fEmail'), perfil: $('fPerfil').value };
    if (id) body.ativo = $('fAtivo').checked;
    else { body.usuario = val('fUser'); body.senha = $('fSenha').value; }
    await api(id ? 'PUT' : 'POST', `/api/admin/usuarios${id ? '/' + id : ''}`, body);
    closeModal(); toast('Usuário salvo.'); loadUsuarios();
  });
}
function resetSenha(id, btn) {
  busy(btn, async () => {
    try { await api('POST', `/api/admin/usuarios/${id}/senha`, { senha: $('fNova').value }); closeModal(); toast('Senha redefinida.'); }
    catch (e) { formError($('fMsg'), e); }
  });
}

/* ============================================================ AUDITORIA */
const ACOES = {
  login: 'Login', logout: 'Logout', login_falhou: 'Login recusado', login_bloqueado_inativo: 'Login de usuário inativo',
  os_aberta: 'OS aberta', os_assumida: 'OS assumida', os_atribuida: 'OS atribuída', os_status: 'Status da OS alterado', os_concluida: 'OS concluída',
  ronda_iniciada: 'Ronda iniciada', ronda_finalizada: 'Ronda finalizada', ronda_problema: 'Problema na ronda', bloco_concluido: 'Bloco concluído',
  qr_validado: 'QR Code validado', qr_invalido: 'QR Code inválido', qr_desativado: 'QR Code desativado usado', qr_regenerado: 'QR Code regenerado', bloco_sem_qr: 'Bloco sem QR',
  foto_enviada: 'Foto enviada', ocorrencia_registrada: 'Ocorrência registrada', ocorrencia_status: 'Status da ocorrência',
  usuario_criado: 'Usuário criado', usuario_alterado: 'Usuário alterado', senha_redefinida: 'Senha redefinida', senha_alterada: 'Senha alterada', acesso_alterado: 'Login/senha alterados',
  empresa_criada: 'Empresa cadastrada', empresa_alterada: 'Empresa alterada', documento_criado: 'Documento cadastrado', documento_alterado: 'Documento alterado', documento_excluido: 'Documento excluído',
  unidade_criada: 'Unidade cadastrada', unidade_alterada: 'Unidade alterada', unidade_excluida: 'Unidade excluída', config_alterada: 'Configurações alteradas', bloco_alterado: 'Bloco alterado',
};
async function loadAuditoria() {
  try {
    if ($('audUser').options.length === 1) {
      const us = usuariosCache.length ? usuariosCache : await api('GET', '/api/admin/usuarios');
      us.forEach(u => $('audUser').add(new Option(u.nome, u.id)));
    }
    const q = new URLSearchParams({ usuario: $('audUser').value, acao: $('audAcao').value, de: $('audDe').value, ate: $('audAte').value });
    const lista = await api('GET', '/api/admin/auditoria?' + q);
    $('audBody').innerHTML = lista.length ? lista.map(a => `<tr><td style="white-space:nowrap">${fmtDT(a.criado_em)}</td><td>${esc(a.usuario_nome || '—')}</td><td>${esc(ACOES[a.acao] || a.acao)}</td><td>${a.entidade ? esc(a.entidade.replace('_', ' ')) + (a.entidade_id ? ' #' + a.entidade_id : '') : '—'}</td><td>${esc(a.detalhe || '')}</td></tr>`).join('')
      : emptyRow(5, 'Nenhum registro encontrado.');
  } catch (e) { fail(e); }
}

/* ======================================================== CONFIGURAÇÕES */
async function loadConfig() {
  try {
    const c = await api('GET', '/api/admin/config');
    $('cfgForm').innerHTML = `
      <div><label for="cNome">Nome do condomínio</label><input class="field" id="cNome" name="nome_condominio" maxlength="120" value="${esc(c.nome_condominio || '')}"></div>
      <div><label for="cDesc">Descrição (menu lateral)</label><input class="field" id="cDesc" maxlength="120" value="${esc(c.descricao_condominio || '')}"></div>
      <div class="full"><label class="check-row"><input type="checkbox" id="cQr" ${c.exigir_qr === '1' ? 'checked' : ''}> Exigir leitura do QR Code para verificar os andares de um bloco</label></div>
      <div class="full"><label for="cUrl">Endereço do sistema usado nos QR Codes</label><input class="field" id="cUrl" name="url_base_qr" maxlength="200" value="${esc(c.url_base_qr || '')}" placeholder="Ex.: https://condoia.seudominio.com.br"><p class="note">Deixe vazio para usar o endereço atual do navegador (${esc(location.origin)}). Depois de mudar, imprima os QR Codes de novo.</p></div>
      <div><label for="cDias">Alertar documentos que vencem em (dias)</label><input class="field" id="cDias" name="dias_alerta_documentos" type="number" min="1" max="365" value="${esc(c.dias_alerta_documentos || 30)}"></div>
      <div class="full form-msg" id="cfgMsg"></div>`;
  } catch (e) { fail(e); }
  loadAcessos();
}

async function loadAcessos() {
  try {
    usuariosCache = await api('GET', '/api/admin/usuarios');
    $('acessoBody').innerHTML = usuariosCache.map(u => `<tr><td><b>${esc(u.nome)}</b>${u.ativo ? '' : ' <span class="status pend">INATIVO</span>'}</td><td>${esc(u.usuario)}</td><td>${esc(u.perfil_nome)}</td><td><button class="btn" onclick="openAcessoForm(${u.id})">Alterar</button></td></tr>`).join('');
  } catch (e) { fail(e); }
}
function openAcessoForm(id) {
  const u = usuariosCache.find(x => x.id === id);
  if (!u) return;
  const proprio = id === S.user.id;
  openModal(`Login e senha — ${u.nome}`, `<div class="form-grid">
    <div class="full"><label for="aLogin">Login</label><input class="field" id="aLogin" name="usuario" maxlength="40" autocapitalize="none" autocomplete="off" value="${esc(u.usuario)}"><p class="note">Letras minúsculas, números, ponto, hífen ou sublinhado (3 a 40 caracteres).</p></div>
    <div><label for="aSenha">Nova senha (opcional)</label><input class="field" id="aSenha" name="senha" type="password" minlength="8" autocomplete="new-password" placeholder="Em branco = manter a atual"></div>
    <div><label for="aConf">Confirmar nova senha</label><input class="field" id="aConf" name="confirmar_senha" type="password" autocomplete="new-password"></div>
    <div class="full"><p class="note">${proprio ? 'Este é o seu acesso: você continuará conectado neste aparelho.' : 'O usuário será desconectado dos aparelhos em que estiver logado.'}</p></div></div>`
    + actions('Salvar alterações', `saveAcesso(${id})`));
}
function saveAcesso(id) {
  saveForm(async () => {
    const u = usuariosCache.find(x => x.id === id);
    const login = val('aLogin').toLowerCase(), senha = $('aSenha').value, conf = $('aConf').value;
    if (login === u.usuario && !senha) throw Object.assign(new Error('Nada foi alterado. Mude o login ou informe uma nova senha.'), { campos: ['usuario', 'senha'] });
    const r = await api('PUT', `/api/admin/usuarios/${id}/acesso`, { usuario: login, senha, confirmar_senha: conf });
    closeModal();
    const partes = [];
    if (r.usuario !== u.usuario) partes.push(`login alterado para “${r.usuario}”`);
    if (senha) partes.push('senha alterada');
    toast(`${u.nome}: ${partes.join(' e ')}.`);
    loadAcessos();
  });
}
function saveConfig() {
  const btn = document.querySelector('#configuracoes .btn.primary');
  busy(btn, async () => {
    try {
      await api('PUT', '/api/admin/config', { nome_condominio: val('cNome'), descricao_condominio: val('cDesc'), exigir_qr: $('cQr').checked, url_base_qr: val('cUrl'), dias_alerta_documentos: val('cDias') });
      $('cfgMsg').style.display = 'none';
      toast('Configurações salvas.');
      const me = await api('GET', '/api/auth/me');
      $('condoName').textContent = me.condominio.nome_condominio;
      $('condoInfo').textContent = me.condominio.descricao_condominio || '';
    } catch (e) { formError($('cfgMsg'), e); }
  });
}
function openSenhaForm() {
  openModal('Alterar minha senha', `<div class="form-grid">
    <div class="full"><label for="sAtual">Senha atual</label><input class="field" id="sAtual" name="senha_atual" type="password" autocomplete="current-password"></div>
    <div><label for="sNova">Nova senha</label><input class="field" id="sNova" name="nova_senha" type="password" minlength="8" autocomplete="new-password"></div>
    <div><label for="sConf">Confirmar nova senha</label><input class="field" id="sConf" type="password" autocomplete="new-password"></div></div>`
    + actions('Alterar senha', 'saveSenha()'));
}
function saveSenha() {
  saveForm(async () => {
    if ($('sNova').value !== $('sConf').value) throw Object.assign(new Error('A confirmação não confere com a nova senha.'), { campos: ['nova_senha'] });
    await api('POST', '/api/auth/senha', { senha_atual: $('sAtual').value, nova_senha: $('sNova').value });
    closeModal(); toast('Senha alterada.');
  });
}

/* ============================================================== CONDOIA */
async function sendChat() {
  const input = $('chatInput'), text = input.value.trim();
  if (!text) return;
  const box = $('messages');
  box.insertAdjacentHTML('beforeend', `<div class="msg me">${esc(text)}</div>`);
  input.value = '';
  const id = 'm' + Date.now();
  box.insertAdjacentHTML('beforeend', `<div class="msg bot" id="${id}"><b>🤖 CondoIA</b><br>Consultando os dados…</div>`);
  box.scrollTop = box.scrollHeight;
  try {
    const r = await api('POST', '/api/ia/perguntar', { pergunta: text });
    $(id).innerHTML = `<b>🤖 CondoIA</b><br>${esc(r.texto)}${r.itens.length ? '<ul>' + r.itens.map(i => `<li>${esc(i)}</li>`).join('') + '</ul>' : ''}${r.fonte ? `<div class="source">Fonte: ${esc(r.fonte)}</div>` : ''}`;
  } catch (e) {
    $(id).innerHTML = `<b>🤖 CondoIA</b><br>${esc(e.message)}`;
  }
  box.scrollTop = box.scrollHeight;
}
