import hashlib
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta
from functools import wraps

from flask import current_app, g, jsonify, request

from database import agora, get_db

COOKIE = "condoia_sessao"


class ErroApi(Exception):
    def __init__(self, mensagem, status=400, campos=None):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = status
        self.campos = campos


# ---------------------------------------------------------------- sessões
def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def criar_sessao(user_id, lembrar):
    token = secrets.token_urlsafe(32)
    horas = current_app.config["SESSAO_LEMBRAR_HORAS"] if lembrar else current_app.config["SESSAO_HORAS"]
    expira = (datetime.fromisoformat(agora()) + timedelta(hours=horas)).isoformat()
    db = get_db()
    db.execute(
        "INSERT INTO sessoes (token_hash, user_id, criado_em, expira_em, ip) VALUES (?,?,?,?,?)",
        (_hash_token(token), user_id, agora(), expira, ip_cliente()),
    )
    db.commit()
    return token, (horas * 3600 if lembrar else None)


def encerrar_sessao():
    token = request.cookies.get(COOKIE)
    if token:
        db = get_db()
        db.execute("DELETE FROM sessoes WHERE token_hash=?", (_hash_token(token),))
        db.commit()


def encerrar_sessoes_do_usuario(user_id):
    get_db().execute("DELETE FROM sessoes WHERE user_id=?", (user_id,))


def carregar_usuario():
    """Carrega o usuário da sessão. Usuário inativo ou sessão expirada = sem acesso."""
    g.user = None
    token = request.cookies.get(COOKIE)
    if not token:
        return
    db = get_db()
    row = db.execute(
        """SELECT u.id, u.nome, u.usuario, u.email, u.ativo, r.codigo AS perfil, r.nome AS perfil_nome,
                  s.expira_em
             FROM sessoes s JOIN users u ON u.id = s.user_id JOIN roles r ON r.id = u.role_id
            WHERE s.token_hash = ?""",
        (_hash_token(token),),
    ).fetchone()
    if not row:
        return
    if row["expira_em"] < agora() or not row["ativo"]:
        db.execute("DELETE FROM sessoes WHERE token_hash=?", (_hash_token(token),))
        db.commit()
        return
    g.user = dict(row)


def ip_cliente():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()[:60]


# ------------------------------------------------------- limite de tentativas
def _tentativas():
    return current_app.extensions.setdefault("condoia_tentativas_login", {})


def login_bloqueado(chave):
    reg = _tentativas().get(chave)
    return bool(reg and reg["bloqueado_ate"] > time.time())


def registrar_falha_login(chave):
    reg = _tentativas().setdefault(chave, {"falhas": 0, "bloqueado_ate": 0})
    reg["falhas"] += 1
    if reg["falhas"] >= current_app.config["LOGIN_MAX_TENTATIVAS"]:
        reg["bloqueado_ate"] = time.time() + current_app.config["LOGIN_BLOQUEIO_SEGUNDOS"]
        reg["falhas"] = 0


def limpar_falhas_login(chave):
    _tentativas().pop(chave, None)


# ------------------------------------------------------------ autorização
def requer_login(*perfis):
    """Exige usuário autenticado; se perfis forem informados, exige um deles."""

    def decorador(fn):
        @wraps(fn)
        def interno(*args, **kwargs):
            if not g.get("user"):
                return jsonify(erro="Sessão expirada. Entre novamente."), 401
            if perfis and g.user["perfil"] not in perfis:
                return jsonify(erro="Você não tem permissão para acessar este recurso."), 403
            return fn(*args, **kwargs)

        return interno

    return decorador


def auditar(acao, entidade=None, entidade_id=None, detalhe=None, user_id=None, commit=False):
    uid = user_id if user_id is not None else (g.user["id"] if g.get("user") else None)
    db = get_db()
    db.execute(
        "INSERT INTO auditoria (user_id, acao, entidade, entidade_id, detalhe, ip, criado_em) VALUES (?,?,?,?,?,?,?)",
        (uid, acao, entidade, entidade_id, (detalhe or "")[:500] or None, ip_cliente(), agora()),
    )
    if commit:
        db.commit()


# -------------------------------------------------------------- validação
def dados_requisicao():
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form


def texto(dados, campo, rotulo, obrigatorio=False, maximo=2000, msg=None):
    valor = dados.get(campo)
    valor = "" if valor is None else str(valor).strip()
    if obrigatorio and not valor:
        raise ErroApi(msg or f"Preencha o campo “{rotulo}”.", campos=[campo])
    if len(valor) > maximo:
        raise ErroApi(f"“{rotulo}” deve ter no máximo {maximo} caracteres.", campos=[campo])
    return valor or None


def escolha(dados, campo, rotulo, opcoes, obrigatorio=True):
    valor = dados.get(campo)
    valor = "" if valor is None else str(valor).strip()
    if not valor and not obrigatorio:
        return None
    if valor not in opcoes:
        raise ErroApi(f"Selecione um valor válido para “{rotulo}”.", campos=[campo])
    return valor


def inteiro(dados, campo, rotulo, obrigatorio=False, minimo=None, maximo=None):
    valor = dados.get(campo)
    if valor in (None, ""):
        if obrigatorio:
            raise ErroApi(f"Informe “{rotulo}”.", campos=[campo])
        return None
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise ErroApi(f"“{rotulo}” deve ser um número inteiro.", campos=[campo])
    if (minimo is not None and n < minimo) or (maximo is not None and n > maximo):
        raise ErroApi(f"“{rotulo}” fora do intervalo permitido.", campos=[campo])
    return n


def data(dados, campo, rotulo, obrigatorio=False):
    valor = texto(dados, campo, rotulo, obrigatorio, maximo=10)
    if valor is None:
        return None
    try:
        datetime.strptime(valor, "%Y-%m-%d")
    except ValueError:
        raise ErroApi(f"“{rotulo}” deve ser uma data válida.", campos=[campo])
    return valor


def booleano(dados, campo):
    return 1 if str(dados.get(campo, "")).lower() in ("1", "true", "on", "sim") else 0


# ---------------------------------------------------------------- uploads
_ASSINATURAS_IMAGEM = {
    "image/jpeg": ([b"\xff\xd8\xff"], {".jpg", ".jpeg"}),
    "image/png": ([b"\x89PNG\r\n\x1a\n"], {".png"}),
    "image/webp": ([b"RIFF"], {".webp"}),
}
_ASSINATURAS_DOC = {
    "application/pdf": ([b"%PDF-"], {".pdf"}),
    "image/jpeg": ([b"\xff\xd8\xff"], {".jpg", ".jpeg"}),
    "image/png": ([b"\x89PNG\r\n\x1a\n"], {".png"}),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ([b"PK\x03\x04"], {".docx"}),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ([b"PK\x03\x04"], {".xlsx"}),
}


def _detectar(conteudo, ext, tabela):
    for mime, (assinaturas, exts) in tabela.items():
        if ext in exts and any(conteudo.startswith(a) for a in assinaturas):
            if mime == "image/webp" and conteudo[8:12] != b"WEBP":
                continue
            return mime
    return None


def salvar_arquivo(arquivo, pasta, tipo="imagem"):
    """Valida extensão, assinatura (MIME real) e tamanho; grava com nome aleatório."""
    if not arquivo or not arquivo.filename:
        raise ErroApi("Nenhum arquivo enviado.")
    nome_original = os.path.basename(arquivo.filename)[:200]
    ext = os.path.splitext(nome_original)[1].lower()
    limite = current_app.config["MAX_FOTO_BYTES"] if tipo == "imagem" else current_app.config["MAX_DOC_BYTES"]
    conteudo = arquivo.read(limite + 1)
    if len(conteudo) > limite:
        raise ErroApi(f"O arquivo “{nome_original}” ultrapassa o limite de {limite // (1024 * 1024)} MB.", 413)
    if not conteudo:
        raise ErroApi(f"O arquivo “{nome_original}” está vazio.")
    tabela = _ASSINATURAS_IMAGEM if tipo == "imagem" else _ASSINATURAS_DOC
    mime = _detectar(conteudo, ext, tabela)
    if not mime:
        permitidos = "JPG, PNG ou WEBP" if tipo == "imagem" else "PDF, JPG, PNG, DOCX ou XLSX"
        raise ErroApi(f"Arquivo “{nome_original}” inválido. Envie {permitidos}.", 415)
    if mime.startswith("image/"):
        try:
            from io import BytesIO
            from PIL import Image
            with Image.open(BytesIO(conteudo)) as im:
                im.verify()
        except ImportError:
            pass
        except Exception:
            raise ErroApi(f"A imagem “{nome_original}” está corrompida ou não é uma imagem válida.", 415)

    sub = os.path.join(pasta, agora()[:7].replace("-", "/"))
    destino_dir = os.path.join(current_app.config["UPLOAD_DIR"], sub)
    os.makedirs(destino_dir, exist_ok=True)
    nome = uuid.uuid4().hex + (".jpg" if ext == ".jpeg" else ext)
    with open(os.path.join(destino_dir, nome), "wb") as f:
        f.write(conteudo)
    return {"arquivo": os.path.join(sub, nome).replace("\\", "/"), "nome_original": nome_original,
            "mime": mime, "tamanho": len(conteudo)}


def caminho_upload(relativo):
    base = os.path.realpath(current_app.config["UPLOAD_DIR"])
    caminho = os.path.realpath(os.path.join(base, relativo))
    if not caminho.startswith(base + os.sep):
        raise ErroApi("Arquivo não encontrado.", 404)
    return caminho
