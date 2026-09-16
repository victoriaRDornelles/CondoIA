import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from flask import current_app, g
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo(os.environ.get("CONDOIA_TZ", "America/Sao_Paulo"))
except Exception:  # Windows sem o pacote tzdata
    _TZ = timezone(timedelta(hours=-3))


def agora():
    """Data/hora local do condomínio, formato ISO sem fuso (AAAA-MM-DDTHH:MM:SS)."""
    return datetime.now(_TZ).replace(tzinfo=None, microsecond=0).isoformat()


def hoje():
    return agora()[:10]


def conectar(caminho):
    con = sqlite3.connect(caminho, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def get_db():
    if "db" not in g:
        g.db = conectar(current_app.config["DATABASE"])
    return g.db


def fechar_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def criar_tabelas(con):
    with open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8") as f:
        con.executescript(f.read())


PERFIS = [("admin", "Administração"), ("ronda", "Ronda"), ("manutencao", "Manutenção")]

USUARIOS_INICIAIS = [
    ("Administração Geral", "admin", "admin"),
    ("Ronda 01", "ronda01", "ronda"), ("Ronda 02", "ronda02", "ronda"),
    ("Ronda 03", "ronda03", "ronda"), ("Ronda 04", "ronda04", "ronda"),
    ("Manutenção 01", "manutencao01", "manutencao"),
    ("Manutenção 02", "manutencao02", "manutencao"),
    ("Manutenção 03", "manutencao03", "manutencao"),
]

ANDARES_POR_BLOCO = 3

PONTOS_INICIAIS = [
    ("Guarita Norte", "guarita_norte", None, 1),
    ("Portão de entrada", "guarita_norte", None, 2),
    ("Portão de saída — próximo à rua", "guarita_norte", None, 3),
    ("Portão de saída — subsolo", "guarita_norte", None, 4),
    ("Guarita Sul", "guarita_sul", "Funciona com somente 1 porteiro", 5),
    ("Deck", "guarita_sul", "Área aberta", 6),
    ("Náutica — lado direito", "guarita_sul", None, 7),
    ("Deck flutuante — lado esquerdo", "guarita_sul", None, 8),
    ("Espaço Gourmet", "area_comum", None, 9),
    ("Sala de Jogos", "area_comum", None, 10),
    ("Casa do Pirata", "area_comum", None, 11),
    ("Banheiros", "area_comum", None, 12),
]

CONFIG_PADRAO = {
    "nome_condominio": "Edifício Solar das Flores",
    "descricao_condominio": "7 blocos",
    "exigir_qr": "1",
    "url_base_qr": "",
    "dias_alerta_documentos": "30",
}


def inicializar(caminho, senha_padrao=None):
    """Cria as tabelas e a estrutura inicial. Retorna {usuario: senha} dos usuários criados agora."""
    con = conectar(caminho)
    criar_tabelas(con)
    ts = agora()
    for codigo, nome in PERFIS:
        con.execute("INSERT OR IGNORE INTO roles (codigo, nome) VALUES (?,?)", (codigo, nome))
    for chave, valor in CONFIG_PADRAO.items():
        con.execute("INSERT OR IGNORE INTO configuracoes (chave, valor) VALUES (?,?)", (chave, valor))

    criados = {}
    for nome, usuario, perfil in USUARIOS_INICIAIS:
        if con.execute("SELECT 1 FROM users WHERE usuario=?", (usuario,)).fetchone():
            continue
        senha = senha_padrao or secrets.token_urlsafe(8)
        role_id = con.execute("SELECT id FROM roles WHERE codigo=?", (perfil,)).fetchone()[0]
        con.execute(
            "INSERT INTO users (nome, usuario, senha_hash, role_id, ativo, criado_em) VALUES (?,?,?,?,1,?)",
            (nome, usuario, generate_password_hash(senha), role_id, ts),
        )
        criados[usuario] = senha

    if not con.execute("SELECT 1 FROM pontos").fetchone():
        con.executemany("INSERT INTO pontos (nome, grupo, observacao, ordem) VALUES (?,?,?,?)", PONTOS_INICIAIS)

    if not con.execute("SELECT 1 FROM blocos").fetchone():
        for n in range(1, 8):
            cur = con.execute("INSERT INTO blocos (numero, nome) VALUES (?,?)", (n, f"Bloco {n}"))
            con.execute(
                "INSERT INTO qr_codes (bloco_id, token, ativo, criado_em) VALUES (?,?,1,?)",
                (cur.lastrowid, secrets.token_urlsafe(12), ts),
            )
    # Cada bloco tem 3 andares (1º, 2º e 3º). Só recebe andares o bloco que nunca teve
    # nenhum cadastrado: um bloco já ajustado pela Administração não é alterado.
    for (bloco_id,) in con.execute(
            "SELECT id FROM blocos b WHERE NOT EXISTS (SELECT 1 FROM andares a WHERE a.bloco_id=b.id)").fetchall():
        for a in range(1, ANDARES_POR_BLOCO + 1):
            con.execute("INSERT INTO andares (bloco_id, numero, nome) VALUES (?,?,?)", (bloco_id, a, f"{a}º andar"))
    con.commit()
    con.close()
    return criados
