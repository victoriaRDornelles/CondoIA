-- CondoIA — esquema do banco de dados (SQLite)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS roles (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  codigo    TEXT NOT NULL UNIQUE CHECK (codigo IN ('admin','ronda','manutencao')),
  nome      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  nome           TEXT NOT NULL,
  usuario        TEXT NOT NULL UNIQUE COLLATE NOCASE,
  email          TEXT UNIQUE COLLATE NOCASE,
  senha_hash     TEXT NOT NULL,
  role_id        INTEGER NOT NULL REFERENCES roles(id),
  ativo          INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
  criado_em      TEXT NOT NULL,
  ultimo_acesso  TEXT
);

CREATE TABLE IF NOT EXISTS sessoes (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  token_hash  TEXT NOT NULL UNIQUE,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  criado_em   TEXT NOT NULL,
  expira_em   TEXT NOT NULL,
  ip          TEXT
);
CREATE INDEX IF NOT EXISTS ix_sessoes_user ON sessoes(user_id);

CREATE TABLE IF NOT EXISTS configuracoes (
  chave  TEXT PRIMARY KEY,
  valor  TEXT
);

-- Estrutura física do condomínio
CREATE TABLE IF NOT EXISTS blocos (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  numero  INTEGER NOT NULL UNIQUE,
  nome    TEXT NOT NULL,
  ativo   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS andares (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  bloco_id  INTEGER NOT NULL REFERENCES blocos(id),
  numero    INTEGER NOT NULL,
  nome      TEXT NOT NULL,
  ativo     INTEGER NOT NULL DEFAULT 1,
  UNIQUE (bloco_id, numero)
);

CREATE TABLE IF NOT EXISTS qr_codes (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  bloco_id   INTEGER NOT NULL REFERENCES blocos(id),
  token      TEXT NOT NULL UNIQUE,
  ativo      INTEGER NOT NULL DEFAULT 1,
  criado_em  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_qr_bloco ON qr_codes(bloco_id);

CREATE TABLE IF NOT EXISTS unidades (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  bloco_id    INTEGER NOT NULL REFERENCES blocos(id),
  andar_id    INTEGER REFERENCES andares(id),
  numero      TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'ocupada' CHECK (status IN ('ocupada','desocupada')),
  observacao  TEXT,
  UNIQUE (bloco_id, numero)
);

-- Pontos fixos da ronda (guaritas e áreas comuns)
CREATE TABLE IF NOT EXISTS pontos (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  nome        TEXT NOT NULL,
  grupo       TEXT NOT NULL CHECK (grupo IN ('guarita_norte','guarita_sul','area_comum')),
  observacao  TEXT,
  ordem       INTEGER NOT NULL DEFAULT 0,
  ativo       INTEGER NOT NULL DEFAULT 1
);

-- Rondas
CREATE TABLE IF NOT EXISTS rondas (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id        INTEGER NOT NULL REFERENCES users(id),
  status         TEXT NOT NULL DEFAULT 'em_andamento'
                 CHECK (status IN ('em_andamento','concluida','incompleta')),
  iniciada_em    TEXT NOT NULL,
  finalizada_em  TEXT,
  observacao     TEXT
);
CREATE INDEX IF NOT EXISTS ix_rondas_user ON rondas(user_id, status);

-- Validação do QR Code de cada bloco dentro de uma ronda
CREATE TABLE IF NOT EXISTS ronda_blocos (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  ronda_id      INTEGER NOT NULL REFERENCES rondas(id),
  bloco_id      INTEGER NOT NULL REFERENCES blocos(id),
  qr_code_id    INTEGER REFERENCES qr_codes(id),
  validado_em   TEXT NOT NULL,
  concluido_em  TEXT,
  UNIQUE (ronda_id, bloco_id)
);

-- Cada ponto fixo ou andar verificado na ronda
CREATE TABLE IF NOT EXISTS ronda_pontos (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  ronda_id       INTEGER NOT NULL REFERENCES rondas(id),
  user_id        INTEGER NOT NULL REFERENCES users(id),
  ponto_id       INTEGER REFERENCES pontos(id),
  bloco_id       INTEGER REFERENCES blocos(id),
  andar_id       INTEGER REFERENCES andares(id),
  qr_code_id     INTEGER REFERENCES qr_codes(id),
  status         TEXT NOT NULL CHECK (status IN ('ok','atencao','problema')),
  observacao     TEXT,
  registrado_em  TEXT NOT NULL,
  CHECK ((ponto_id IS NOT NULL AND andar_id IS NULL) OR (ponto_id IS NULL AND andar_id IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_rp_ponto ON ronda_pontos(ronda_id, ponto_id) WHERE ponto_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_rp_andar ON ronda_pontos(ronda_id, andar_id) WHERE andar_id IS NOT NULL;

-- Ordens de serviço (o número exibido é o id com zeros à esquerda: #00001)
CREATE TABLE IF NOT EXISTS ordens_servico (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  local              TEXT NOT NULL,
  equipamento        TEXT,
  categoria          TEXT NOT NULL,
  descricao          TEXT NOT NULL,
  prioridade         TEXT NOT NULL CHECK (prioridade IN ('Crítica','Alta','Média','Baixa')),
  status             TEXT NOT NULL DEFAULT 'aberta' CHECK (status IN ('aberta','em_andamento','concluida')),
  aberta_por         INTEGER NOT NULL REFERENCES users(id),
  responsavel_id     INTEGER REFERENCES users(id),
  ocorrencia_id      INTEGER REFERENCES ocorrencias(id),
  servico_realizado  TEXT,
  criado_em          TEXT NOT NULL,
  iniciada_em        TEXT,
  concluida_em       TEXT,
  atualizado_em      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_os_status ON ordens_servico(status);
CREATE INDEX IF NOT EXISTS ix_os_resp ON ordens_servico(responsavel_id);

-- Histórico da OS (somente inserção; não há rota de exclusão)
CREATE TABLE IF NOT EXISTS os_historico (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  os_id            INTEGER NOT NULL REFERENCES ordens_servico(id),
  user_id          INTEGER NOT NULL REFERENCES users(id),
  acao             TEXT NOT NULL,
  status_anterior  TEXT,
  status_novo      TEXT,
  detalhe          TEXT,
  criado_em        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_osh_os ON os_historico(os_id);
CREATE TRIGGER IF NOT EXISTS tg_os_historico_sem_update BEFORE UPDATE ON os_historico
BEGIN SELECT RAISE(ABORT, 'O histórico da OS não pode ser alterado.'); END;
CREATE TRIGGER IF NOT EXISTS tg_os_historico_sem_delete BEFORE DELETE ON os_historico
BEGIN SELECT RAISE(ABORT, 'O histórico da OS não pode ser apagado.'); END;

-- Ocorrências (número exibido: #000001)
CREATE TABLE IF NOT EXISTS ocorrencias (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id         INTEGER NOT NULL REFERENCES users(id),
  ronda_id        INTEGER REFERENCES rondas(id),
  ronda_ponto_id  INTEGER REFERENCES ronda_pontos(id),
  local           TEXT NOT NULL,
  ponto_id        INTEGER REFERENCES pontos(id),
  bloco_id        INTEGER REFERENCES blocos(id),
  andar_id        INTEGER REFERENCES andares(id),
  descricao       TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'aberta' CHECK (status IN ('aberta','em_atendimento','concluida')),
  os_id           INTEGER REFERENCES ordens_servico(id),
  criado_em       TEXT NOT NULL,
  atualizado_em   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_oc_status ON ocorrencias(status);

-- Fotos (arquivos ficam em /uploads/fotos; aqui fica o vínculo)
CREATE TABLE IF NOT EXISTS fotos (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  arquivo         TEXT NOT NULL,
  nome_original   TEXT,
  mime            TEXT NOT NULL,
  tamanho         INTEGER NOT NULL,
  user_id         INTEGER NOT NULL REFERENCES users(id),
  tipo            TEXT NOT NULL CHECK (tipo IN ('ronda_problema','ronda_atencao','ocorrencia','os_antes','os_depois')),
  ronda_id        INTEGER REFERENCES rondas(id),
  ronda_ponto_id  INTEGER REFERENCES ronda_pontos(id),
  ponto_id        INTEGER REFERENCES pontos(id),
  bloco_id        INTEGER REFERENCES blocos(id),
  andar_id        INTEGER REFERENCES andares(id),
  ocorrencia_id   INTEGER REFERENCES ocorrencias(id),
  os_id           INTEGER REFERENCES ordens_servico(id),
  criado_em       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fotos_os ON fotos(os_id);
CREATE INDEX IF NOT EXISTS ix_fotos_oc ON fotos(ocorrencia_id);
CREATE INDEX IF NOT EXISTS ix_fotos_rp ON fotos(ronda_ponto_id);

CREATE TABLE IF NOT EXISTS empresas_terceirizadas (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  nome           TEXT NOT NULL,
  servico        TEXT NOT NULL,
  responsavel    TEXT,
  telefone       TEXT,
  email          TEXT,
  contrato       TEXT,
  data_inicio    TEXT,
  data_termino   TEXT,
  observacoes    TEXT,
  ativo          INTEGER NOT NULL DEFAULT 1,
  criado_em      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documentos (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  nome            TEXT NOT NULL,
  categoria       TEXT NOT NULL,
  arquivo         TEXT,
  nome_original   TEXT,
  mime            TEXT,
  tamanho         INTEGER,
  data_documento  TEXT,
  validade        TEXT,
  responsavel     TEXT,
  observacao      TEXT,
  empresa_id      INTEGER REFERENCES empresas_terceirizadas(id),
  criado_por      INTEGER NOT NULL REFERENCES users(id),
  criado_em       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auditoria (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id      INTEGER REFERENCES users(id),
  acao         TEXT NOT NULL,
  entidade     TEXT,
  entidade_id  INTEGER,
  detalhe      TEXT,
  ip           TEXT,
  criado_em    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_aud_data ON auditoria(criado_em);
