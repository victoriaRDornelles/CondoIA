import os
import re
import secrets
from datetime import date, datetime, timedelta

from flask import Flask, Response, g, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash

import database
import ia
from database import agora, fechar_db, get_db, hoje
from qrcode_svg import gerar_svg
from seguranca import (COOKIE, ErroApi, auditar, booleano, caminho_upload, carregar_usuario, criar_sessao,
                       dados_requisicao, data, encerrar_sessao, encerrar_sessoes_do_usuario, escolha, inteiro,
                       limpar_falhas_login, login_bloqueado, registrar_falha_login, requer_login, salvar_arquivo,
                       texto)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PRIORIDADES = ("Crítica", "Alta", "Média", "Baixa")
CATEGORIAS_OS = ("Portões", "Elétrica", "Hidráulica", "Iluminação", "CFTV", "Jardinagem", "Limpeza", "Civil", "Outros")
STATUS_RONDA_PONTO = ("ok", "atencao", "problema")
MSG_FOTO_PROBLEMA = "Adicione uma foto para registrar este problema."
MAX_FOTOS_POR_ENVIO = 5


def num_os(i):
    return f"#{i:05d}"


def num_oc(i):
    return f"#{i:06d}"


def create_app(config=None):
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config.update(
        DATABASE=os.environ.get("CONDOIA_DB", os.path.join(BASE_DIR, "instance", "condoia.db")),
        UPLOAD_DIR=os.environ.get("CONDOIA_UPLOADS", os.path.join(BASE_DIR, "uploads")),
        MAX_FOTO_BYTES=10 * 1024 * 1024,
        MAX_DOC_BYTES=20 * 1024 * 1024,
        MAX_CONTENT_LENGTH=60 * 1024 * 1024,
        SESSAO_HORAS=12,
        SESSAO_LEMBRAR_HORAS=24 * 30,
        COOKIE_SEGURO=os.environ.get("CONDOIA_HTTPS", "0") == "1",
        LOGIN_MAX_TENTATIVAS=5,
        LOGIN_BLOQUEIO_SEGUNDOS=300,
    )
    if config:
        app.config.update(config)
    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)

    app.teardown_appcontext(fechar_db)
    registrar_hooks(app)
    registrar_rotas(app)
    return app


# ======================================================================= hooks
def registrar_hooks(app):
    @app.before_request
    def antes():
        g.arquivos_salvos = []
        carregar_usuario()
        # Proteção CSRF: requisições que alteram dados precisam do cabeçalho enviado pelo app.
        if request.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("X-CondoIA") != "1":
                return jsonify(erro="Requisição recusada."), 403

    @app.after_request
    def depois(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Permissions-Policy"] = "camera=(self), geolocation=()"
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def descartar_arquivos():
        for caminho in g.get("arquivos_salvos", []):
            try:
                os.remove(caminho_upload(caminho))
            except Exception:
                pass
        g.arquivos_salvos = []
        if "db" in g:
            g.db.rollback()

    @app.errorhandler(ErroApi)
    def erro_api(e):
        descartar_arquivos()
        corpo = {"erro": e.mensagem}
        if e.campos:
            corpo["campos"] = e.campos
        return jsonify(corpo), e.status

    @app.errorhandler(RequestEntityTooLarge)
    def muito_grande(_e):
        descartar_arquivos()
        return jsonify(erro="Envio muito grande. Cada foto pode ter até 10 MB."), 413

    @app.errorhandler(HTTPException)
    def http_erro(e):
        if request.path.startswith("/api/"):
            descartar_arquivos()
            return jsonify(erro=e.description or "Erro na requisição."), e.code
        return e

    @app.errorhandler(Exception)
    def erro_interno(e):
        descartar_arquivos()
        app.logger.exception("Erro não tratado: %s", e)
        return jsonify(erro="Erro interno no servidor. Tente novamente."), 500


# ================================================================== auxiliares
def config_valor(chave, padrao=None):
    row = get_db().execute("SELECT valor FROM configuracoes WHERE chave=?", (chave,)).fetchone()
    return row["valor"] if row and row["valor"] is not None else padrao


def fotos_da_requisicao(obrigatoria=False, msg=None):
    arquivos = [f for f in request.files.getlist("fotos") if f and f.filename]
    if obrigatoria and not arquivos:
        raise ErroApi(msg or "Adicione pelo menos uma foto.", campos=["fotos"])
    if len(arquivos) > MAX_FOTOS_POR_ENVIO:
        raise ErroApi(f"Envie no máximo {MAX_FOTOS_POR_ENVIO} fotos por vez.", campos=["fotos"])
    return arquivos


def gravar_fotos(arquivos, tipo, **vinculos):
    db = get_db()
    ids = []
    for arq in arquivos:
        info = salvar_arquivo(arq, "fotos", "imagem")
        g.arquivos_salvos.append(info["arquivo"])
        colunas = ["arquivo", "nome_original", "mime", "tamanho", "user_id", "tipo", "criado_em"] + list(vinculos)
        valores = [info["arquivo"], info["nome_original"], info["mime"], info["tamanho"], g.user["id"], tipo,
                   agora()] + list(vinculos.values())
        cur = db.execute(
            f"INSERT INTO fotos ({','.join(colunas)}) VALUES ({','.join('?' * len(colunas))})", valores)
        ids.append(cur.lastrowid)
        auditar("foto_enviada", "foto", cur.lastrowid, f"Tipo: {tipo}")
    return ids


def os_visivel(os_row):
    u = g.user
    if u["perfil"] == "admin":
        return True
    if u["perfil"] == "manutencao":
        return os_row["responsavel_id"] == u["id"] or (
            os_row["status"] == "aberta" and os_row["responsavel_id"] is None)
    return os_row["aberta_por"] == u["id"]


def ocorrencia_visivel(oc):
    return g.user["perfil"] in ("admin", "manutencao") or oc["user_id"] == g.user["id"]


def ronda_visivel(r):
    return g.user["perfil"] == "admin" or r["user_id"] == g.user["id"]


def buscar_os(os_id):
    row = get_db().execute("SELECT * FROM ordens_servico WHERE id=?", (os_id,)).fetchone()
    if not row or not os_visivel(row):
        raise ErroApi("Ordem de serviço não encontrada.", 404)
    return row


def historico_os(os_id, user_id, acao, anterior, novo, detalhe=None):
    get_db().execute(
        "INSERT INTO os_historico (os_id, user_id, acao, status_anterior, status_novo, detalhe, criado_em) "
        "VALUES (?,?,?,?,?,?,?)", (os_id, user_id, acao, anterior, novo, detalhe, agora()))


def extrair_token_qr(codigo):
    codigo = (codigo or "").strip()
    m = re.search(r"[?&]qr=([A-Za-z0-9_\-]+)", codigo)
    token = m.group(1) if m else codigo
    return token if re.fullmatch(r"[A-Za-z0-9_\-]{8,64}", token or "") else None


def url_qr(token):
    base = (config_valor("url_base_qr") or request.host_url).rstrip("/")
    return f"{base}/?qr={token}"


def linhas(rows):
    return [dict(r) for r in rows]


# ===================================================================== rotas
def registrar_rotas(app):

    @app.get("/")
    def index():
        return send_from_directory(os.path.join(BASE_DIR, "static"), "index.html")

    # ------------------------------------------------------------- autenticação
    @app.post("/api/auth/login")
    def login():
        d = dados_requisicao()
        usuario = (d.get("usuario") or "").strip().lower()[:120]
        senha = d.get("senha") or ""
        chave = f"{usuario}|{request.remote_addr}"
        if not usuario or not senha:
            raise ErroApi("Informe usuário e senha.")
        if login_bloqueado(chave):
            raise ErroApi("Muitas tentativas incorretas. Aguarde 5 minutos e tente novamente.", 429)
        db = get_db()
        u = db.execute(
            "SELECT u.*, r.codigo AS perfil FROM users u JOIN roles r ON r.id=u.role_id "
            "WHERE u.usuario=? OR u.email=?", (usuario, usuario)).fetchone()
        if not u or not check_password_hash(u["senha_hash"], senha):
            registrar_falha_login(chave)
            auditar("login_falhou", "user", u["id"] if u else None, f"Usuário informado: {usuario}",
                    user_id=u["id"] if u else None, commit=True)
            raise ErroApi("Usuário ou senha inválidos.", 401)
        if not u["ativo"]:
            auditar("login_bloqueado_inativo", "user", u["id"], user_id=u["id"], commit=True)
            raise ErroApi("Usuário inativo. Procure a Administração.", 403)
        limpar_falhas_login(chave)
        token, max_age = criar_sessao(u["id"], booleano(d, "lembrar"))
        db.execute("UPDATE users SET ultimo_acesso=? WHERE id=?", (agora(), u["id"]))
        auditar("login", "user", u["id"], user_id=u["id"])
        db.commit()
        resp = jsonify(ok=True, perfil=u["perfil"])
        resp.set_cookie(COOKIE, token, max_age=max_age, httponly=True, samesite="Lax",
                        secure=app.config["COOKIE_SEGURO"], path="/")
        return resp

    @app.post("/api/auth/logout")
    def logout():
        if g.user:
            auditar("logout", "user", g.user["id"])
        encerrar_sessao()
        resp = jsonify(ok=True)
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @app.get("/api/auth/me")
    def me():
        db = get_db()
        cfg = {r["chave"]: r["valor"] for r in db.execute("SELECT * FROM configuracoes")}
        info = {"nome_condominio": cfg.get("nome_condominio"), "descricao_condominio": cfg.get("descricao_condominio"),
                "exigir_qr": cfg.get("exigir_qr") == "1"}
        if not g.user:
            return jsonify(autenticado=False, condominio=info)
        u = g.user
        return jsonify(autenticado=True, condominio=info, usuario={
            "id": u["id"], "nome": u["nome"], "usuario": u["usuario"], "perfil": u["perfil"],
            "perfil_nome": u["perfil_nome"]})

    @app.post("/api/auth/senha")
    @requer_login()
    def trocar_propria_senha():
        d = dados_requisicao()
        atual = d.get("senha_atual") or ""
        nova = d.get("nova_senha") or ""
        db = get_db()
        u = db.execute("SELECT senha_hash FROM users WHERE id=?", (g.user["id"],)).fetchone()
        if not check_password_hash(u["senha_hash"], atual):
            raise ErroApi("Senha atual incorreta.", campos=["senha_atual"])
        if len(nova) < 8:
            raise ErroApi("A nova senha deve ter pelo menos 8 caracteres.", campos=["nova_senha"])
        db.execute("UPDATE users SET senha_hash=? WHERE id=?", (generate_password_hash(nova), g.user["id"]))
        db.execute("DELETE FROM sessoes WHERE user_id=? AND token_hash<>?",
                   (g.user["id"], __import__("hashlib").sha256(request.cookies.get(COOKIE, "").encode()).hexdigest()))
        auditar("senha_alterada", "user", g.user["id"])
        db.commit()
        return jsonify(ok=True)

    # ---------------------------------------------------------------- fotos
    @app.get("/api/fotos/<int:foto_id>")
    @requer_login()
    def ver_foto(foto_id):
        db = get_db()
        f = db.execute("SELECT * FROM fotos WHERE id=?", (foto_id,)).fetchone()
        permitido = False
        if f:
            if g.user["perfil"] == "admin" or f["user_id"] == g.user["id"]:
                permitido = True
            elif f["os_id"]:
                o = db.execute("SELECT * FROM ordens_servico WHERE id=?", (f["os_id"],)).fetchone()
                permitido = bool(o and os_visivel(o))
            elif f["ocorrencia_id"]:
                o = db.execute("SELECT * FROM ocorrencias WHERE id=?", (f["ocorrencia_id"],)).fetchone()
                permitido = bool(o and ocorrencia_visivel(o))
            elif f["ronda_id"]:
                r = db.execute("SELECT * FROM rondas WHERE id=?", (f["ronda_id"],)).fetchone()
                permitido = bool(r and ronda_visivel(r))
        if not permitido:
            raise ErroApi("Foto não encontrada.", 404)
        caminho = caminho_upload(f["arquivo"])
        if not os.path.exists(caminho):
            raise ErroApi("Arquivo da foto não encontrado no servidor.", 404)
        resp = send_file(caminho, mimetype=f["mime"], max_age=0)
        resp.headers["Cache-Control"] = "private, max-age=3600"
        return resp

    # ======================================================= ORDENS DE SERVIÇO
    def os_serializar(o):
        d = dict(o)
        d["numero"] = num_os(o["id"])
        return d

    SQL_OS = """SELECT o.*, ab.nome AS aberta_por_nome, rp.nome AS responsavel_nome
                  FROM ordens_servico o JOIN users ab ON ab.id=o.aberta_por
                  LEFT JOIN users rp ON rp.id=o.responsavel_id"""

    @app.get("/api/os")
    @requer_login()
    def listar_os():
        u = g.user
        where, params = [], []
        if u["perfil"] == "manutencao":
            escopo = request.args.get("escopo", "")
            if escopo == "disponiveis":
                where.append("o.status='aberta' AND o.responsavel_id IS NULL")
            elif escopo == "minhas":
                where.append("o.responsavel_id=?"); params.append(u["id"])
            else:
                where.append("(o.responsavel_id=? OR (o.status='aberta' AND o.responsavel_id IS NULL))")
                params.append(u["id"])
        elif u["perfil"] == "ronda":
            where.append("o.aberta_por=?"); params.append(u["id"])
        status = request.args.get("status")
        if status in ("aberta", "em_andamento", "concluida"):
            where.append("o.status=?"); params.append(status)
        busca = (request.args.get("busca") or "").strip()[:100]
        if busca:
            where.append("(o.descricao LIKE ? OR o.local LIKE ? OR o.equipamento LIKE ? OR CAST(o.id AS TEXT) LIKE ?)")
            params += [f"%{busca}%"] * 3 + [f"%{busca.lstrip('#').lstrip('0')}%"]
        sql = SQL_OS + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY o.id DESC LIMIT 300"
        return jsonify([os_serializar(r) for r in get_db().execute(sql, params)])

    @app.post("/api/os")
    @requer_login("admin", "ronda")
    def abrir_os():
        d = request.form
        local = texto(d, "local", "Local", True, 150)
        equipamento = texto(d, "equipamento", "Equipamento", False, 150)
        categoria = escolha(d, "categoria", "Categoria", CATEGORIAS_OS)
        descricao = texto(d, "descricao", "Qual o problema?", True, 2000,
                          msg="Descreva o problema (“Qual o problema?”).")
        prioridade = escolha(d, "prioridade", "Prioridade", PRIORIDADES)
        fotos = fotos_da_requisicao(True, "A foto do problema é obrigatória para abrir a OS.")
        db = get_db()
        ts = agora()
        cur = db.execute(
            "INSERT INTO ordens_servico (local, equipamento, categoria, descricao, prioridade, status, aberta_por, "
            "criado_em, atualizado_em) VALUES (?,?,?,?,?,'aberta',?,?,?)",
            (local, equipamento, categoria, descricao, prioridade, g.user["id"], ts, ts))
        os_id = cur.lastrowid
        gravar_fotos(fotos, "os_antes", os_id=os_id)
        historico_os(os_id, g.user["id"], "abertura", None, "aberta", descricao)
        auditar("os_aberta", "ordem_servico", os_id, f"{num_os(os_id)} — {local}")
        db.commit()
        return jsonify(id=os_id, numero=num_os(os_id)), 201

    @app.get("/api/os/<int:os_id>")
    @requer_login()
    def detalhe_os(os_id):
        buscar_os(os_id)
        db = get_db()
        o = db.execute(SQL_OS + " WHERE o.id=?", (os_id,)).fetchone()
        hist = db.execute(
            "SELECT h.*, u.nome AS usuario_nome FROM os_historico h JOIN users u ON u.id=h.user_id "
            "WHERE h.os_id=? ORDER BY h.id", (os_id,)).fetchall()
        fotos = db.execute("SELECT id, tipo, criado_em FROM fotos WHERE os_id=? ORDER BY id", (os_id,)).fetchall()
        dados = os_serializar(o)
        if o["ocorrencia_id"]:
            dados["ocorrencia_numero"] = num_oc(o["ocorrencia_id"])
        dados.update(historico=linhas(hist), fotos=linhas(fotos))
        return jsonify(dados)

    @app.post("/api/os/<int:os_id>/assumir")
    @requer_login("manutencao")
    def assumir_os(os_id):
        o = buscar_os(os_id)
        if o["status"] != "aberta" or o["responsavel_id"] is not None:
            raise ErroApi("Esta OS não está disponível para assumir.", 409)
        db = get_db()
        cur = db.execute("UPDATE ordens_servico SET responsavel_id=?, atualizado_em=? "
                         "WHERE id=? AND responsavel_id IS NULL AND status='aberta'", (g.user["id"], agora(), os_id))
        if cur.rowcount == 0:
            raise ErroApi("Outra pessoa assumiu esta OS agora há pouco.", 409)
        historico_os(os_id, g.user["id"], "responsavel", "aberta", "aberta", f"Responsável: {g.user['nome']}")
        auditar("os_assumida", "ordem_servico", os_id, num_os(os_id))
        db.commit()
        return jsonify(ok=True)

    @app.post("/api/os/<int:os_id>/atribuir")
    @requer_login("admin")
    def atribuir_os(os_id):
        o = buscar_os(os_id)
        if o["status"] == "concluida":
            raise ErroApi("A OS já foi concluída.", 409)
        rid = inteiro(dados_requisicao(), "responsavel_id", "Responsável", True)
        db = get_db()
        resp = db.execute("SELECT u.id, u.nome FROM users u JOIN roles r ON r.id=u.role_id "
                          "WHERE u.id=? AND r.codigo='manutencao' AND u.ativo=1", (rid,)).fetchone()
        if not resp:
            raise ErroApi("Selecione um usuário de Manutenção ativo.")
        db.execute("UPDATE ordens_servico SET responsavel_id=?, atualizado_em=? WHERE id=?", (rid, agora(), os_id))
        historico_os(os_id, g.user["id"], "responsavel", o["status"], o["status"], f"Responsável: {resp['nome']}")
        auditar("os_atribuida", "ordem_servico", os_id, f"{num_os(os_id)} → {resp['nome']}")
        db.commit()
        return jsonify(ok=True)

    @app.post("/api/os/<int:os_id>/iniciar")
    @requer_login("manutencao", "admin")
    def iniciar_os(os_id):
        o = buscar_os(os_id)
        if o["status"] != "aberta":
            raise ErroApi("Somente OS abertas podem ser colocadas em andamento.", 409)
        if o["responsavel_id"] is None:
            raise ErroApi("Assuma a OS (ou atribua um responsável) antes de iniciar.", 409)
        if g.user["perfil"] == "manutencao" and o["responsavel_id"] != g.user["id"]:
            raise ErroApi("Esta OS está atribuída a outro responsável.", 403)
        db = get_db()
        ts = agora()
        db.execute("UPDATE ordens_servico SET status='em_andamento', iniciada_em=?, atualizado_em=? WHERE id=?",
                   (ts, ts, os_id))
        historico_os(os_id, g.user["id"], "status", "aberta", "em_andamento")
        if o["ocorrencia_id"]:
            db.execute("UPDATE ocorrencias SET status='em_atendimento', atualizado_em=? WHERE id=? AND status='aberta'",
                       (ts, o["ocorrencia_id"]))
        auditar("os_status", "ordem_servico", os_id, f"{num_os(os_id)}: aberta → em andamento")
        db.commit()
        return jsonify(ok=True)

    @app.post("/api/os/<int:os_id>/concluir")
    @requer_login("manutencao", "admin")
    def concluir_os(os_id):
        o = buscar_os(os_id)
        if o["status"] == "concluida":
            raise ErroApi("Esta OS já está concluída.", 409)
        if o["status"] != "em_andamento":
            raise ErroApi("Coloque a OS em andamento antes de concluir.", 409)
        if g.user["perfil"] == "manutencao" and o["responsavel_id"] != g.user["id"]:
            raise ErroApi("Somente o responsável pode concluir esta OS.", 403)
        d = request.form
        servico = texto(d, "servico_realizado", "O que foi feito?", False, 3000)
        fotos = fotos_da_requisicao(False)
        faltando = []
        if not servico:
            faltando.append("preencha “O que foi feito?”")
        if not fotos:
            faltando.append("adicione a foto depois de feito")
        if faltando:
            raise ErroApi("Não é possível concluir a OS: " + " e ".join(faltando) + ".",
                          campos=(["servico_realizado"] if not servico else []) + (["fotos"] if not fotos else []))
        db = get_db()
        ts = agora()
        gravar_fotos(fotos, "os_depois", os_id=os_id)
        db.execute("UPDATE ordens_servico SET status='concluida', servico_realizado=?, concluida_em=?, "
                   "atualizado_em=? WHERE id=?", (servico, ts, ts, os_id))
        historico_os(os_id, g.user["id"], "servico", "em_andamento", "em_andamento", servico)
        historico_os(os_id, g.user["id"], "status", "em_andamento", "concluida")
        if o["ocorrencia_id"]:
            db.execute("UPDATE ocorrencias SET status='concluida', atualizado_em=? WHERE id=?", (ts, o["ocorrencia_id"]))
        auditar("os_concluida", "ordem_servico", os_id, num_os(os_id))
        db.commit()
        return jsonify(ok=True)

    # ================================================================== RONDA
    def estado_ronda(ronda):
        db = get_db()
        rid = ronda["id"]
        registros = db.execute("SELECT * FROM ronda_pontos WHERE ronda_id=?", (rid,)).fetchall()
        fotos = db.execute("SELECT id, ronda_ponto_id FROM fotos WHERE ronda_id=?", (rid,)).fetchall()
        fotos_por_rp = {}
        for f in fotos:
            fotos_por_rp.setdefault(f["ronda_ponto_id"], []).append(f["id"])
        ocs = {r["ronda_ponto_id"]: r["id"] for r in
               db.execute("SELECT id, ronda_ponto_id FROM ocorrencias WHERE ronda_id=?", (rid,))}

        def reg(r):
            if not r:
                return None
            return {"id": r["id"], "status": r["status"], "observacao": r["observacao"],
                    "registrado_em": r["registrado_em"], "fotos": fotos_por_rp.get(r["id"], []),
                    "ocorrencia": num_oc(ocs[r["id"]]) if r["id"] in ocs else None,
                    "ocorrencia_id": ocs.get(r["id"])}

        por_ponto = {r["ponto_id"]: r for r in registros if r["ponto_id"]}
        por_andar = {r["andar_id"]: r for r in registros if r["andar_id"]}
        pontos = [dict(p, registro=reg(por_ponto.get(p["id"]))) for p in
                  db.execute("SELECT * FROM pontos WHERE ativo=1 ORDER BY ordem, id")]
        validacoes = {r["bloco_id"]: r for r in db.execute("SELECT * FROM ronda_blocos WHERE ronda_id=?", (rid,))}
        blocos = []
        for b in db.execute("SELECT * FROM blocos WHERE ativo=1 ORDER BY numero"):
            andares = [dict(a, registro=reg(por_andar.get(a["id"]))) for a in db.execute(
                "SELECT id, numero, nome FROM andares WHERE bloco_id=? AND ativo=1 ORDER BY numero", (b["id"],))]
            v = validacoes.get(b["id"])
            concluido = bool(v and andares and all(a["registro"] for a in andares))
            blocos.append({"id": b["id"], "numero": b["numero"], "nome": b["nome"], "andares": andares,
                           "validado": bool(v), "validado_em": v["validado_em"] if v else None,
                           "via_qr": bool(v and v["qr_code_id"]), "concluido": concluido,
                           "concluido_em": v["concluido_em"] if v else None})
        usuario = db.execute("SELECT nome FROM users WHERE id=?", (ronda["user_id"],)).fetchone()
        return {
            "id": rid, "status": ronda["status"], "iniciada_em": ronda["iniciada_em"],
            "finalizada_em": ronda["finalizada_em"], "observacao": ronda["observacao"],
            "usuario": usuario["nome"], "user_id": ronda["user_id"], "pontos": pontos, "blocos": blocos,
            "exigir_qr": config_valor("exigir_qr", "1") == "1",
            "progresso": {"pontos_total": len(pontos), "pontos_ok": sum(1 for p in pontos if p["registro"]),
                          "blocos_total": len(blocos), "blocos_ok": sum(1 for b in blocos if b["concluido"])},
        }

    def ronda_em_andamento_do_usuario(ronda_id):
        r = get_db().execute("SELECT * FROM rondas WHERE id=?", (ronda_id,)).fetchone()
        if not r or r["user_id"] != g.user["id"]:
            raise ErroApi("Ronda não encontrada.", 404)
        if r["status"] != "em_andamento":
            raise ErroApi("Esta ronda já foi finalizada.", 409)
        return r

    def validar_status_ronda(d):
        status = escolha(d, "status", "Status", STATUS_RONDA_PONTO)
        obs = texto(d, "observacao", "Observação", False, 1000)
        fotos = fotos_da_requisicao(False)
        if status == "problema":
            if not obs:
                raise ErroApi("Descreva o problema encontrado.", campos=["observacao"])
            if not fotos:
                raise ErroApi(MSG_FOTO_PROBLEMA, campos=["fotos"])
        if status == "ok":
            fotos = []
        return status, obs, fotos

    def registrar_na_ronda(ronda, status, obs, fotos, local, ponto_id=None, bloco_id=None, andar_id=None,
                           qr_code_id=None):
        db = get_db()
        ts = agora()
        try:
            cur = db.execute(
                "INSERT INTO ronda_pontos (ronda_id, user_id, ponto_id, bloco_id, andar_id, qr_code_id, status, "
                "observacao, registrado_em) VALUES (?,?,?,?,?,?,?,?,?)",
                (ronda["id"], g.user["id"], ponto_id, bloco_id, andar_id, qr_code_id, status, obs, ts))
        except __import__("sqlite3").IntegrityError:
            raise ErroApi(f"“{local}” já foi registrado nesta ronda.", 409)
        rp_id = cur.lastrowid
        oc_id = None
        if status == "problema":
            cur = db.execute(
                "INSERT INTO ocorrencias (user_id, ronda_id, ronda_ponto_id, local, ponto_id, bloco_id, andar_id, "
                "descricao, status, criado_em, atualizado_em) VALUES (?,?,?,?,?,?,?,?,'aberta',?,?)",
                (g.user["id"], ronda["id"], rp_id, local, ponto_id, bloco_id, andar_id, obs, ts, ts))
            oc_id = cur.lastrowid
            auditar("ronda_problema", "ocorrencia", oc_id, f"{local}: {obs}")
        if fotos:
            gravar_fotos(fotos, "ronda_problema" if status == "problema" else "ronda_atencao",
                         ronda_id=ronda["id"], ronda_ponto_id=rp_id, ponto_id=ponto_id, bloco_id=bloco_id,
                         andar_id=andar_id, ocorrencia_id=oc_id)
        return rp_id, oc_id

    @app.get("/api/rondas/atual")
    @requer_login("ronda")
    def ronda_atual():
        r = get_db().execute("SELECT * FROM rondas WHERE user_id=? AND status='em_andamento' ORDER BY id DESC",
                             (g.user["id"],)).fetchone()
        return jsonify(ronda=estado_ronda(r) if r else None)

    @app.post("/api/rondas")
    @requer_login("ronda")
    def iniciar_ronda():
        db = get_db()
        r = db.execute("SELECT * FROM rondas WHERE user_id=? AND status='em_andamento'", (g.user["id"],)).fetchone()
        if r:
            return jsonify(ronda=estado_ronda(r))
        cur = db.execute("INSERT INTO rondas (user_id, status, iniciada_em) VALUES (?,'em_andamento',?)",
                         (g.user["id"], agora()))
        auditar("ronda_iniciada", "ronda", cur.lastrowid)
        db.commit()
        r = db.execute("SELECT * FROM rondas WHERE id=?", (cur.lastrowid,)).fetchone()
        return jsonify(ronda=estado_ronda(r)), 201

    @app.get("/api/rondas")
    @requer_login("admin", "ronda")
    def listar_rondas():
        where, params = [], []
        if g.user["perfil"] == "ronda":
            where.append("r.user_id=?"); params.append(g.user["id"])
        elif request.args.get("usuario"):
            where.append("r.user_id=?"); params.append(inteiro(request.args, "usuario", "Usuário"))
        de, ate = data(request.args, "de", "De"), data(request.args, "ate", "Até")
        if de:
            where.append("substr(r.iniciada_em,1,10)>=?"); params.append(de)
        if ate:
            where.append("substr(r.iniciada_em,1,10)<=?"); params.append(ate)
        sql = """SELECT r.*, u.nome AS usuario,
                   (SELECT COUNT(*) FROM ronda_pontos p WHERE p.ronda_id=r.id) AS registros,
                   (SELECT COUNT(*) FROM ronda_pontos p WHERE p.ronda_id=r.id AND p.status='problema') AS problemas,
                   (SELECT COUNT(*) FROM ronda_pontos p WHERE p.ronda_id=r.id AND p.status='atencao') AS atencoes
                 FROM rondas r JOIN users u ON u.id=r.user_id"""
        sql += (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY r.id DESC LIMIT 300"
        return jsonify(linhas(get_db().execute(sql, params)))

    @app.get("/api/rondas/<int:ronda_id>")
    @requer_login("admin", "ronda")
    def detalhe_ronda(ronda_id):
        r = get_db().execute("SELECT * FROM rondas WHERE id=?", (ronda_id,)).fetchone()
        if not r or not ronda_visivel(r):
            raise ErroApi("Ronda não encontrada.", 404)
        return jsonify(ronda=estado_ronda(r))

    @app.post("/api/rondas/<int:ronda_id>/pontos")
    @requer_login("ronda")
    def registrar_ponto(ronda_id):
        r = ronda_em_andamento_do_usuario(ronda_id)
        d = request.form
        pid = inteiro(d, "ponto_id", "Ponto", True)
        ponto = get_db().execute("SELECT * FROM pontos WHERE id=? AND ativo=1", (pid,)).fetchone()
        if not ponto:
            raise ErroApi("Ponto de ronda inválido.", 404)
        status, obs, fotos = validar_status_ronda(d)
        registrar_na_ronda(r, status, obs, fotos, ponto["nome"], ponto_id=pid)
        get_db().commit()
        return jsonify(ronda=estado_ronda(r))

    @app.post("/api/rondas/<int:ronda_id>/blocos/validar")
    @requer_login("ronda")
    def validar_qr_bloco(ronda_id):
        r = ronda_em_andamento_do_usuario(ronda_id)
        token = extrair_token_qr(dados_requisicao().get("codigo"))
        db = get_db()
        qr = db.execute("SELECT q.*, b.nome AS bloco_nome FROM qr_codes q JOIN blocos b ON b.id=q.bloco_id "
                        "WHERE q.token=? AND b.ativo=1", (token,)).fetchone() if token else None
        if not qr:
            auditar("qr_invalido", "ronda", ronda_id, "QR Code não reconhecido", commit=True)
            raise ErroApi("QR Code não reconhecido. Confira se é o QR Code de um bloco do condomínio.", 404)
        if not qr["ativo"]:
            auditar("qr_desativado", "ronda", ronda_id, qr["bloco_nome"], commit=True)
            raise ErroApi("Este QR Code foi substituído e não vale mais. Procure a Administração.", 409)
        existe = db.execute("SELECT 1 FROM ronda_blocos WHERE ronda_id=? AND bloco_id=?",
                            (ronda_id, qr["bloco_id"])).fetchone()
        if not existe:
            db.execute("INSERT INTO ronda_blocos (ronda_id, bloco_id, qr_code_id, validado_em) VALUES (?,?,?,?)",
                       (ronda_id, qr["bloco_id"], qr["id"], agora()))
            auditar("qr_validado", "ronda", ronda_id, qr["bloco_nome"])
            db.commit()
        return jsonify(bloco_id=qr["bloco_id"], ronda=estado_ronda(r))

    @app.post("/api/rondas/<int:ronda_id>/blocos/<int:bloco_id>/manual")
    @requer_login("ronda")
    def validar_bloco_manual(ronda_id, bloco_id):
        r = ronda_em_andamento_do_usuario(ronda_id)
        if config_valor("exigir_qr", "1") == "1":
            raise ErroApi("Escaneie o QR Code do bloco para iniciar a verificação.", 403)
        db = get_db()
        b = db.execute("SELECT * FROM blocos WHERE id=? AND ativo=1", (bloco_id,)).fetchone()
        if not b:
            raise ErroApi("Bloco não encontrado.", 404)
        db.execute("INSERT OR IGNORE INTO ronda_blocos (ronda_id, bloco_id, qr_code_id, validado_em) "
                   "VALUES (?,?,NULL,?)", (ronda_id, bloco_id, agora()))
        auditar("bloco_sem_qr", "ronda", ronda_id, b["nome"])
        db.commit()
        return jsonify(bloco_id=bloco_id, ronda=estado_ronda(r))

    @app.post("/api/rondas/<int:ronda_id>/andares")
    @requer_login("ronda")
    def registrar_andar(ronda_id):
        r = ronda_em_andamento_do_usuario(ronda_id)
        d = request.form
        aid = inteiro(d, "andar_id", "Andar", True)
        db = get_db()
        andar = db.execute("SELECT a.*, b.nome AS bloco_nome FROM andares a JOIN blocos b ON b.id=a.bloco_id "
                           "WHERE a.id=? AND a.ativo=1 AND b.ativo=1", (aid,)).fetchone()
        if not andar:
            raise ErroApi("Andar inválido.", 404)
        validacao = db.execute("SELECT * FROM ronda_blocos WHERE ronda_id=? AND bloco_id=?",
                               (ronda_id, andar["bloco_id"])).fetchone()
        if not validacao:
            raise ErroApi(f"Escaneie o QR Code do {andar['bloco_nome']} antes de verificar os andares.", 403)
        status, obs, fotos = validar_status_ronda(d)
        local = f"{andar['bloco_nome']} — {andar['nome']}"
        registrar_na_ronda(r, status, obs, fotos, local, bloco_id=andar["bloco_id"], andar_id=aid,
                           qr_code_id=validacao["qr_code_id"])
        faltam = db.execute(
            "SELECT COUNT(*) FROM andares a WHERE a.bloco_id=? AND a.ativo=1 AND NOT EXISTS "
            "(SELECT 1 FROM ronda_pontos p WHERE p.ronda_id=? AND p.andar_id=a.id)",
            (andar["bloco_id"], ronda_id)).fetchone()[0]
        if faltam == 0 and not validacao["concluido_em"]:
            db.execute("UPDATE ronda_blocos SET concluido_em=? WHERE id=?", (agora(), validacao["id"]))
            auditar("bloco_concluido", "ronda", ronda_id, andar["bloco_nome"])
        db.commit()
        return jsonify(ronda=estado_ronda(r))

    @app.post("/api/rondas/<int:ronda_id>/finalizar")
    @requer_login("ronda")
    def finalizar_ronda(ronda_id):
        r = ronda_em_andamento_do_usuario(ronda_id)
        obs = texto(dados_requisicao(), "observacao", "Observação", False, 1000)
        est = estado_ronda(r)
        pendentes = [p["nome"] for p in est["pontos"] if not p["registro"]]
        pendentes += [b["nome"] for b in est["blocos"] if not b["concluido"]]
        if pendentes and not obs:
            raise ErroApi("Ainda há pontos pendentes: " + ", ".join(pendentes) +
                          ". Para finalizar assim mesmo, informe o motivo na observação.", 409,
                          campos=["observacao"])
        status = "incompleta" if pendentes else "concluida"
        db = get_db()
        db.execute("UPDATE rondas SET status=?, finalizada_em=?, observacao=? WHERE id=?",
                   (status, agora(), obs, ronda_id))
        auditar("ronda_finalizada", "ronda", ronda_id,
                "Concluída" if status == "concluida" else f"Incompleta — pendentes: {', '.join(pendentes)}")
        db.commit()
        r = db.execute("SELECT * FROM rondas WHERE id=?", (ronda_id,)).fetchone()
        return jsonify(ronda=estado_ronda(r))

    # ============================================================ OCORRÊNCIAS
    SQL_OC = """SELECT c.*, u.nome AS usuario_nome, b.nome AS bloco_nome, a.nome AS andar_nome,
                       (SELECT COUNT(*) FROM fotos f WHERE f.ocorrencia_id=c.id) AS total_fotos
                  FROM ocorrencias c JOIN users u ON u.id=c.user_id
                  LEFT JOIN blocos b ON b.id=c.bloco_id LEFT JOIN andares a ON a.id=c.andar_id"""

    def oc_serializar(c):
        d = dict(c)
        d["numero"] = num_oc(c["id"])
        d["os_numero"] = num_os(c["os_id"]) if c["os_id"] else None
        return d

    @app.get("/api/ocorrencias")
    @requer_login()
    def listar_ocorrencias():
        where, params = [], []
        if g.user["perfil"] == "ronda":
            where.append("c.user_id=?"); params.append(g.user["id"])
        st = request.args.get("status")
        if st in ("aberta", "em_atendimento", "concluida"):
            where.append("c.status=?"); params.append(st)
        busca = (request.args.get("busca") or "").strip()[:100]
        if busca:
            where.append("(c.descricao LIKE ? OR c.local LIKE ? OR CAST(c.id AS TEXT) LIKE ?)")
            params += [f"%{busca}%", f"%{busca}%", f"%{busca.lstrip('#').lstrip('0')}%"]
        sql = SQL_OC + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY c.id DESC LIMIT 300"
        return jsonify([oc_serializar(c) for c in get_db().execute(sql, params)])

    @app.post("/api/ocorrencias")
    @requer_login("admin", "ronda")
    def registrar_ocorrencia():
        d = request.form
        db = get_db()
        local = texto(d, "local", "Local", True, 150)
        descricao = texto(d, "descricao", "Descrição", True, 2000)
        bloco_id = inteiro(d, "bloco_id", "Bloco")
        andar_id = inteiro(d, "andar_id", "Andar")
        if bloco_id and not db.execute("SELECT 1 FROM blocos WHERE id=?", (bloco_id,)).fetchone():
            raise ErroApi("Bloco inválido.")
        if andar_id and not db.execute("SELECT 1 FROM andares WHERE id=? AND bloco_id=?",
                                       (andar_id, bloco_id)).fetchone():
            raise ErroApi("Andar inválido para o bloco selecionado.")
        fotos = fotos_da_requisicao(False)
        ronda = db.execute("SELECT id FROM rondas WHERE user_id=? AND status='em_andamento'",
                           (g.user["id"],)).fetchone()
        ts = agora()
        cur = db.execute(
            "INSERT INTO ocorrencias (user_id, ronda_id, local, bloco_id, andar_id, descricao, status, criado_em, "
            "atualizado_em) VALUES (?,?,?,?,?,?,'aberta',?,?)",
            (g.user["id"], ronda["id"] if ronda else None, local, bloco_id, andar_id, descricao, ts, ts))
        oc_id = cur.lastrowid
        if fotos:
            gravar_fotos(fotos, "ocorrencia", ocorrencia_id=oc_id, bloco_id=bloco_id, andar_id=andar_id)
        auditar("ocorrencia_registrada", "ocorrencia", oc_id, f"{num_oc(oc_id)} — {local}")
        db.commit()
        return jsonify(id=oc_id, numero=num_oc(oc_id)), 201

    def buscar_oc(oc_id):
        c = get_db().execute(SQL_OC + " WHERE c.id=?", (oc_id,)).fetchone()
        if not c or not ocorrencia_visivel(c):
            raise ErroApi("Ocorrência não encontrada.", 404)
        return c

    @app.get("/api/ocorrencias/<int:oc_id>")
    @requer_login()
    def detalhe_ocorrencia(oc_id):
        c = buscar_oc(oc_id)
        d = oc_serializar(c)
        d["fotos"] = linhas(get_db().execute("SELECT id, tipo, criado_em FROM fotos WHERE ocorrencia_id=?", (oc_id,)))
        return jsonify(d)

    @app.post("/api/ocorrencias/<int:oc_id>/status")
    @requer_login("admin")
    def status_ocorrencia(oc_id):
        c = buscar_oc(oc_id)
        novo = escolha(dados_requisicao(), "status", "Status", ("aberta", "em_atendimento", "concluida"))
        db = get_db()
        db.execute("UPDATE ocorrencias SET status=?, atualizado_em=? WHERE id=?", (novo, agora(), oc_id))
        auditar("ocorrencia_status", "ocorrencia", oc_id, f"{c['status']} → {novo}")
        db.commit()
        return jsonify(ok=True)

    @app.post("/api/ocorrencias/<int:oc_id>/gerar-os")
    @requer_login("admin")
    def gerar_os_da_ocorrencia(oc_id):
        c = buscar_oc(oc_id)
        if c["os_id"]:
            raise ErroApi(f"Esta ocorrência já está vinculada à OS {num_os(c['os_id'])}.", 409)
        d = request.form if request.form else dados_requisicao()
        categoria = escolha(d, "categoria", "Categoria", CATEGORIAS_OS)
        prioridade = escolha(d, "prioridade", "Prioridade", PRIORIDADES)
        equipamento = texto(d, "equipamento", "Equipamento", False, 150)
        db = get_db()
        fotos_oc = db.execute("SELECT * FROM fotos WHERE ocorrencia_id=?", (oc_id,)).fetchall()
        novas = fotos_da_requisicao(not fotos_oc, "A foto do problema é obrigatória para abrir a OS.")
        ts = agora()
        cur = db.execute(
            "INSERT INTO ordens_servico (local, equipamento, categoria, descricao, prioridade, status, aberta_por, "
            "ocorrencia_id, criado_em, atualizado_em) VALUES (?,?,?,?,?,'aberta',?,?,?,?)",
            (c["local"], equipamento, categoria, c["descricao"], prioridade, g.user["id"], oc_id, ts, ts))
        os_id = cur.lastrowid
        for f in fotos_oc:  # reaproveita o mesmo arquivo, com novo vínculo
            db.execute("INSERT INTO fotos (arquivo, nome_original, mime, tamanho, user_id, tipo, bloco_id, andar_id, "
                       "os_id, criado_em) VALUES (?,?,?,?,?,'os_antes',?,?,?,?)",
                       (f["arquivo"], f["nome_original"], f["mime"], f["tamanho"], f["user_id"], f["bloco_id"],
                        f["andar_id"], os_id, ts))
        if novas:
            gravar_fotos(novas, "os_antes", os_id=os_id)
        historico_os(os_id, g.user["id"], "abertura", None, "aberta",
                     f"Gerada a partir da ocorrência {num_oc(oc_id)}: {c['descricao']}")
        db.execute("UPDATE ocorrencias SET os_id=?, status='em_atendimento', atualizado_em=? WHERE id=?",
                   (os_id, ts, oc_id))
        auditar("os_aberta", "ordem_servico", os_id, f"{num_os(os_id)} gerada da ocorrência {num_oc(oc_id)}")
        db.commit()
        return jsonify(id=os_id, numero=num_os(os_id)), 201

    # ================================================================== DADOS
    @app.get("/api/estrutura")
    @requer_login()
    def estrutura():
        db = get_db()
        blocos = []
        for b in db.execute("SELECT * FROM blocos WHERE ativo=1 ORDER BY numero"):
            andares = linhas(db.execute("SELECT id, numero, nome FROM andares WHERE bloco_id=? AND ativo=1 "
                                        "ORDER BY numero", (b["id"],)))
            blocos.append({"id": b["id"], "numero": b["numero"], "nome": b["nome"], "andares": andares})
        manut = []
        if g.user["perfil"] == "admin":
            manut = linhas(db.execute("SELECT u.id, u.nome FROM users u JOIN roles r ON r.id=u.role_id "
                                      "WHERE r.codigo='manutencao' AND u.ativo=1 ORDER BY u.nome"))
        return jsonify(blocos=blocos, categorias=CATEGORIAS_OS, prioridades=PRIORIDADES, manutencao=manut)

    # ============================================================ DASHBOARD
    @app.get("/api/dashboard")
    @requer_login("admin")
    def dashboard():
        db = get_db()
        um = lambda sql, *p: db.execute(sql, p).fetchone()[0]
        d_hoje = hoje()
        mes = d_hoje[:7]
        dias = int(config_valor("dias_alerta_documentos", "30") or 30)
        limite = (date.fromisoformat(d_hoje) + timedelta(days=dias)).isoformat()
        blocos_total = um("SELECT COUNT(*) FROM blocos WHERE ativo=1")
        ultima = db.execute("SELECT * FROM rondas ORDER BY id DESC LIMIT 1").fetchone()
        ultima_registros = []
        if ultima:
            ultima_registros = linhas(db.execute(
                """SELECT p.status, p.registrado_em, COALESCE(pt.nome, b.nome || ' — ' || a.nome) AS local
                     FROM ronda_pontos p LEFT JOIN pontos pt ON pt.id=p.ponto_id
                     LEFT JOIN blocos b ON b.id=p.bloco_id LEFT JOIN andares a ON a.id=p.andar_id
                    WHERE p.ronda_id=? ORDER BY p.id DESC LIMIT 6""", (ultima["id"],)))
        return jsonify(
            unidades=um("SELECT COUNT(*) FROM unidades"),
            unidades_ocupadas=um("SELECT COUNT(*) FROM unidades WHERE status='ocupada'"),
            os_abertas=um("SELECT COUNT(*) FROM ordens_servico WHERE status='aberta'"),
            os_criticas=um("SELECT COUNT(*) FROM ordens_servico WHERE status<>'concluida' AND prioridade='Crítica'"),
            os_andamento=um("SELECT COUNT(*) FROM ordens_servico WHERE status='em_andamento'"),
            os_concluidas_mes=um("SELECT COUNT(*) FROM ordens_servico WHERE status='concluida' "
                                 "AND substr(concluida_em,1,7)=?", mes),
            rondas_mes=um("SELECT COUNT(*) FROM rondas WHERE status<>'em_andamento' AND substr(iniciada_em,1,7)=?", mes),
            rondas_hoje=um("SELECT COUNT(*) FROM rondas WHERE status<>'em_andamento' AND substr(iniciada_em,1,10)=?",
                           d_hoje),
            rondas_andamento=um("SELECT COUNT(*) FROM rondas WHERE status='em_andamento'"),
            rondas_incompletas_mes=um("SELECT COUNT(*) FROM rondas WHERE status='incompleta' "
                                      "AND substr(iniciada_em,1,7)=?", mes),
            problemas_mes=um("SELECT COUNT(*) FROM ronda_pontos WHERE status='problema' "
                             "AND substr(registrado_em,1,7)=?", mes),
            blocos_verificados_hoje=um("SELECT COUNT(DISTINCT bloco_id) FROM ronda_blocos "
                                       "WHERE substr(concluido_em,1,10)=?", d_hoje),
            blocos_total=blocos_total,
            blocos_sem_andares=[r["nome"] for r in db.execute(
                "SELECT nome FROM blocos b WHERE ativo=1 AND NOT EXISTS "
                "(SELECT 1 FROM andares a WHERE a.bloco_id=b.id AND a.ativo=1) ORDER BY numero")],
            empresas_ativas=um("SELECT COUNT(*) FROM empresas_terceirizadas WHERE ativo=1"),
            documentos_vencendo=um("SELECT COUNT(*) FROM documentos WHERE validade BETWEEN ? AND ?", d_hoje, limite),
            documentos_vencidos=um("SELECT COUNT(*) FROM documentos WHERE validade < ?", d_hoje),
            dias_alerta=dias,
            os_recentes=[os_serializar(r) for r in db.execute(SQL_OS + " ORDER BY o.id DESC LIMIT 5")],
            ocorrencias_recentes=[oc_serializar(r) for r in db.execute(SQL_OC + " ORDER BY c.id DESC LIMIT 5")],
            documentos_alerta=linhas(db.execute(
                "SELECT id, nome, categoria, validade FROM documentos WHERE validade IS NOT NULL AND validade <= ? "
                "ORDER BY validade LIMIT 5", (limite,))),
            ultima_ronda=({"id": ultima["id"], "status": ultima["status"], "iniciada_em": ultima["iniciada_em"],
                           "finalizada_em": ultima["finalizada_em"],
                           "usuario": db.execute("SELECT nome FROM users WHERE id=?",
                                                 (ultima["user_id"],)).fetchone()[0],
                           "registros": ultima_registros} if ultima else None),
        )

    @app.get("/api/relatorios")
    @requer_login("admin")
    def relatorios():
        db = get_db()
        de = data(request.args, "de", "De") or hoje()[:8] + "01"
        ate = data(request.args, "ate", "Até") or hoje()
        if de > ate:
            raise ErroApi("A data inicial deve ser anterior à final.")
        p = (de, ate)
        um = lambda sql, *prm: db.execute(sql, prm).fetchone()[0]
        filtro_os = "substr(criado_em,1,10) BETWEEN ? AND ?"
        rondas_total = um("SELECT COUNT(*) FROM rondas WHERE status<>'em_andamento' "
                          "AND substr(iniciada_em,1,10) BETWEEN ? AND ?", *p)
        rondas_ok = um("SELECT COUNT(*) FROM rondas WHERE status='concluida' "
                       "AND substr(iniciada_em,1,10) BETWEEN ? AND ?", *p)
        tempo = db.execute("SELECT AVG((julianday(concluida_em)-julianday(criado_em))*24) FROM ordens_servico "
                           "WHERE status='concluida' AND substr(concluida_em,1,10) BETWEEN ? AND ?", p).fetchone()[0]
        return jsonify(
            de=de, ate=ate,
            os_abertas_periodo=um(f"SELECT COUNT(*) FROM ordens_servico WHERE {filtro_os}", *p),
            os_concluidas_periodo=um("SELECT COUNT(*) FROM ordens_servico WHERE status='concluida' "
                                     "AND substr(concluida_em,1,10) BETWEEN ? AND ?", *p),
            tempo_medio_horas=round(tempo, 1) if tempo is not None else None,
            rondas_finalizadas=rondas_total, rondas_concluidas=rondas_ok,
            percentual_rondas=round(100 * rondas_ok / rondas_total) if rondas_total else None,
            problemas=um("SELECT COUNT(*) FROM ronda_pontos WHERE status='problema' "
                         "AND substr(registrado_em,1,10) BETWEEN ? AND ?", *p),
            os_por_categoria=linhas(db.execute(
                f"SELECT categoria AS nome, COUNT(*) AS total FROM ordens_servico WHERE {filtro_os} "
                "GROUP BY categoria ORDER BY total DESC", p)),
            ocorrencias_por_local=linhas(db.execute(
                "SELECT COALESCE(b.nome, c.local) AS nome, COUNT(*) AS total FROM ocorrencias c "
                "LEFT JOIN blocos b ON b.id=c.bloco_id WHERE substr(c.criado_em,1,10) BETWEEN ? AND ? "
                "GROUP BY 1 ORDER BY total DESC LIMIT 10", p)),
            rondas_por_usuario=linhas(db.execute(
                "SELECT u.nome, COUNT(*) AS total, SUM(r.status='concluida') AS concluidas FROM rondas r "
                "JOIN users u ON u.id=r.user_id WHERE r.status<>'em_andamento' "
                "AND substr(r.iniciada_em,1,10) BETWEEN ? AND ? GROUP BY u.id ORDER BY u.nome", p)),
        )

    # ============================================================== IA
    @app.post("/api/ia/perguntar")
    @requer_login()
    def perguntar_ia():
        pergunta = texto(dados_requisicao(), "pergunta", "Pergunta", True, 500)
        return jsonify(ia.responder(get_db(), g.user, pergunta))

    # ======================================================= ADMINISTRAÇÃO
    registrar_rotas_admin(app)


def registrar_rotas_admin(app):
    # ------------------------------------------------------------- usuários
    @app.get("/api/admin/usuarios")
    @requer_login("admin")
    def admin_usuarios():
        return jsonify(linhas(get_db().execute(
            "SELECT u.id, u.nome, u.usuario, u.email, u.ativo, u.criado_em, u.ultimo_acesso, r.codigo AS perfil, "
            "r.nome AS perfil_nome FROM users u JOIN roles r ON r.id=u.role_id ORDER BY r.id, u.nome")))

    def validar_usuario(d, novo):
        nome = texto(d, "nome", "Nome", True, 120)
        email = texto(d, "email", "E-mail", False, 150)
        if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ErroApi("Informe um e-mail válido.", campos=["email"])
        perfil = escolha(d, "perfil", "Perfil", ("admin", "ronda", "manutencao"))
        usuario = None
        if novo:
            usuario = (texto(d, "usuario", "Usuário", True, 40) or "").lower()
            if not re.fullmatch(r"[a-z0-9._-]{3,40}", usuario):
                raise ErroApi("Usuário deve ter 3 a 40 caracteres: letras minúsculas, números, ponto, hífen.",
                              campos=["usuario"])
        return nome, email.lower() if email else None, perfil, usuario

    @app.post("/api/admin/usuarios")
    @requer_login("admin")
    def admin_criar_usuario():
        d = dados_requisicao()
        nome, email, perfil, usuario = validar_usuario(d, True)
        senha = d.get("senha") or ""
        if len(senha) < 8:
            raise ErroApi("A senha deve ter pelo menos 8 caracteres.", campos=["senha"])
        db = get_db()
        if db.execute("SELECT 1 FROM users WHERE usuario=? OR (email IS NOT NULL AND email=?)",
                      (usuario, email)).fetchone():
            raise ErroApi("Já existe um usuário com esse login ou e-mail.", 409)
        role = db.execute("SELECT id FROM roles WHERE codigo=?", (perfil,)).fetchone()[0]
        cur = db.execute("INSERT INTO users (nome, usuario, email, senha_hash, role_id, ativo, criado_em) "
                         "VALUES (?,?,?,?,?,1,?)", (nome, usuario, email, generate_password_hash(senha), role, agora()))
        auditar("usuario_criado", "user", cur.lastrowid, f"{usuario} ({perfil})")
        db.commit()
        return jsonify(id=cur.lastrowid), 201

    @app.put("/api/admin/usuarios/<int:uid>")
    @requer_login("admin")
    def admin_editar_usuario(uid):
        d = dados_requisicao()
        db = get_db()
        atual = db.execute("SELECT u.*, r.codigo AS perfil FROM users u JOIN roles r ON r.id=u.role_id WHERE u.id=?",
                           (uid,)).fetchone()
        if not atual:
            raise ErroApi("Usuário não encontrado.", 404)
        nome, email, perfil, _ = validar_usuario(d, False)
        ativo = booleano(d, "ativo")
        if uid == g.user["id"] and (not ativo or perfil != "admin"):
            raise ErroApi("Você não pode desativar nem retirar o perfil de Administração do seu próprio acesso.")
        if email and db.execute("SELECT 1 FROM users WHERE email=? AND id<>?", (email, uid)).fetchone():
            raise ErroApi("Esse e-mail já está em uso.", 409)
        role = db.execute("SELECT id FROM roles WHERE codigo=?", (perfil,)).fetchone()[0]
        db.execute("UPDATE users SET nome=?, email=?, role_id=?, ativo=? WHERE id=?", (nome, email, role, ativo, uid))
        if not ativo or perfil != atual["perfil"]:
            encerrar_sessoes_do_usuario(uid)
        mud = []
        if nome != atual["nome"]: mud.append("nome")
        if (email or None) != (atual["email"] or None): mud.append("e-mail")
        if perfil != atual["perfil"]: mud.append(f"perfil {atual['perfil']}→{perfil}")
        if ativo != atual["ativo"]: mud.append("ativado" if ativo else "desativado")
        auditar("usuario_alterado", "user", uid, f"{atual['usuario']}: {', '.join(mud) or 'sem mudanças'}")
        db.commit()
        return jsonify(ok=True)

    @app.put("/api/admin/usuarios/<int:uid>/acesso")
    @requer_login("admin")
    def admin_alterar_acesso(uid):
        """Altera o login e/ou a senha. Campo vazio = mantém o atual."""
        d = dados_requisicao()
        db = get_db()
        atual = db.execute("SELECT id, usuario FROM users WHERE id=?", (uid,)).fetchone()
        if not atual:
            raise ErroApi("Usuário não encontrado.", 404)
        novo_login = (d.get("usuario") or "").strip().lower()
        nova_senha = d.get("senha") or ""
        mudar_login = bool(novo_login) and novo_login != atual["usuario"]
        if not mudar_login and not nova_senha:
            raise ErroApi("Informe um novo login ou uma nova senha.", campos=["usuario", "senha"])
        if mudar_login:
            if not re.fullmatch(r"[a-z0-9._-]{3,40}", novo_login):
                raise ErroApi("O login deve ter de 3 a 40 caracteres: letras minúsculas, números, ponto, hífen "
                              "ou sublinhado.", campos=["usuario"])
            if db.execute("SELECT 1 FROM users WHERE (usuario=? OR email=?) AND id<>?",
                          (novo_login, novo_login, uid)).fetchone():
                raise ErroApi("Esse login já está em uso por outro usuário.", 409, campos=["usuario"])
        if nova_senha:
            if len(nova_senha) < 8:
                raise ErroApi("A senha deve ter pelo menos 8 caracteres.", campos=["senha"])
            if nova_senha != (d.get("confirmar_senha") or ""):
                raise ErroApi("A confirmação não confere com a nova senha.", campos=["confirmar_senha"])
        mudancas = []
        if mudar_login:
            db.execute("UPDATE users SET usuario=? WHERE id=?", (novo_login, uid))
            mudancas.append(f"login {atual['usuario']} → {novo_login}")
        if nova_senha:
            db.execute("UPDATE users SET senha_hash=? WHERE id=?", (generate_password_hash(nova_senha), uid))
            mudancas.append("senha alterada")
        if uid != g.user["id"]:  # desconecta o usuário alterado; quem está alterando continua logado
            encerrar_sessoes_do_usuario(uid)
        auditar("acesso_alterado", "user", uid, "; ".join(mudancas))
        db.commit()
        return jsonify(ok=True, usuario=novo_login if mudar_login else atual["usuario"])

    @app.post("/api/admin/usuarios/<int:uid>/senha")
    @requer_login("admin")
    def admin_redefinir_senha(uid):
        senha = dados_requisicao().get("senha") or ""
        if len(senha) < 8:
            raise ErroApi("A senha deve ter pelo menos 8 caracteres.", campos=["senha"])
        db = get_db()
        u = db.execute("SELECT usuario FROM users WHERE id=?", (uid,)).fetchone()
        if not u:
            raise ErroApi("Usuário não encontrado.", 404)
        db.execute("UPDATE users SET senha_hash=? WHERE id=?", (generate_password_hash(senha), uid))
        if uid != g.user["id"]:
            encerrar_sessoes_do_usuario(uid)
        auditar("senha_redefinida", "user", uid, u["usuario"])
        db.commit()
        return jsonify(ok=True)

    # ----------------------------------------------------- configurações
    CHAVES_CONFIG = ("nome_condominio", "descricao_condominio", "exigir_qr", "url_base_qr", "dias_alerta_documentos")

    @app.get("/api/admin/config")
    @requer_login("admin")
    def admin_config():
        cfg = {r["chave"]: r["valor"] for r in get_db().execute("SELECT * FROM configuracoes")}
        return jsonify({k: cfg.get(k) for k in CHAVES_CONFIG})

    @app.put("/api/admin/config")
    @requer_login("admin")
    def admin_salvar_config():
        d = dados_requisicao()
        url = texto(d, "url_base_qr", "Endereço do sistema", False, 200) or ""
        if url and not re.fullmatch(r"https?://[^\s/?#]+(:\d+)?(/[^\s?#]*)?", url):
            raise ErroApi("Endereço do sistema inválido. Exemplo: http://192.168.0.10:5000", campos=["url_base_qr"])
        valores = {
            "nome_condominio": texto(d, "nome_condominio", "Nome do condomínio", True, 120),
            "descricao_condominio": texto(d, "descricao_condominio", "Descrição", False, 120) or "",
            "exigir_qr": str(booleano(d, "exigir_qr")),
            "url_base_qr": url.rstrip("/"),
            "dias_alerta_documentos": str(inteiro(d, "dias_alerta_documentos", "Dias de alerta", True, 1, 365)),
        }
        db = get_db()
        for k, v in valores.items():
            db.execute("INSERT INTO configuracoes (chave, valor) VALUES (?,?) "
                       "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor", (k, v))
        auditar("config_alterada", "configuracoes", None,
                f"QR obrigatório: {'sim' if valores['exigir_qr'] == '1' else 'não'}")
        db.commit()
        return jsonify(ok=True)

    # ---------------------------------------------------- blocos e QR Codes
    @app.get("/api/admin/blocos")
    @requer_login("admin")
    def admin_blocos():
        db = get_db()
        res = []
        for b in db.execute("SELECT * FROM blocos ORDER BY numero"):
            qr = db.execute("SELECT * FROM qr_codes WHERE bloco_id=? AND ativo=1 ORDER BY id DESC",
                            (b["id"],)).fetchone()
            res.append({"id": b["id"], "numero": b["numero"], "nome": b["nome"], "ativo": b["ativo"],
                        "andares": db.execute("SELECT COUNT(*) FROM andares WHERE bloco_id=? AND ativo=1",
                                              (b["id"],)).fetchone()[0],
                        "qr_token": qr["token"] if qr else None, "qr_criado_em": qr["criado_em"] if qr else None,
                        "qr_url": url_qr(qr["token"]) if qr else None})
        return jsonify(res)

    @app.put("/api/admin/blocos/<int:bloco_id>")
    @requer_login("admin")
    def admin_editar_bloco(bloco_id):
        d = dados_requisicao()
        db = get_db()
        b = db.execute("SELECT * FROM blocos WHERE id=?", (bloco_id,)).fetchone()
        if not b:
            raise ErroApi("Bloco não encontrado.", 404)
        nome = texto(d, "nome", "Nome", True, 60)
        qtd = inteiro(d, "andares", "Quantidade de andares", True, 0, 60)
        for n in range(1, qtd + 1):
            db.execute("INSERT INTO andares (bloco_id, numero, nome, ativo) VALUES (?,?,?,1) "
                       "ON CONFLICT(bloco_id, numero) DO UPDATE SET ativo=1", (bloco_id, n, f"{n}º andar"))
        db.execute("UPDATE andares SET ativo=0 WHERE bloco_id=? AND numero>?", (bloco_id, qtd))
        db.execute("UPDATE blocos SET nome=? WHERE id=?", (nome, bloco_id))
        auditar("bloco_alterado", "bloco", bloco_id, f"{nome}: {qtd} andar(es)")
        db.commit()
        return jsonify(ok=True)

    @app.post("/api/admin/blocos/<int:bloco_id>/qr/regenerar")
    @requer_login("admin")
    def admin_regenerar_qr(bloco_id):
        db = get_db()
        b = db.execute("SELECT * FROM blocos WHERE id=?", (bloco_id,)).fetchone()
        if not b:
            raise ErroApi("Bloco não encontrado.", 404)
        db.execute("UPDATE qr_codes SET ativo=0 WHERE bloco_id=?", (bloco_id,))
        db.execute("INSERT INTO qr_codes (bloco_id, token, ativo, criado_em) VALUES (?,?,1,?)",
                   (bloco_id, secrets.token_urlsafe(12), agora()))
        auditar("qr_regenerado", "bloco", bloco_id, f"{b['nome']}: QR Code anterior desativado")
        db.commit()
        return jsonify(ok=True)

    @app.get("/api/admin/blocos/<int:bloco_id>/qr.svg")
    @requer_login("admin")
    def admin_qr_svg(bloco_id):
        qr = get_db().execute("SELECT token FROM qr_codes WHERE bloco_id=? AND ativo=1 ORDER BY id DESC",
                              (bloco_id,)).fetchone()
        if not qr:
            raise ErroApi("QR Code não encontrado.", 404)
        return Response(gerar_svg(url_qr(qr["token"]), 300), mimetype="image/svg+xml")

    @app.get("/admin/qrcodes/imprimir")
    def admin_qr_imprimir():
        if not g.user or g.user["perfil"] != "admin":
            return Response("Acesso restrito à Administração.", 403, mimetype="text/plain; charset=utf-8")
        db = get_db()
        nome_cond = config_valor("nome_condominio", "CondoIA")
        cartoes = []
        for b in db.execute("SELECT * FROM blocos WHERE ativo=1 ORDER BY numero"):
            qr = db.execute("SELECT token FROM qr_codes WHERE bloco_id=? AND ativo=1 ORDER BY id DESC",
                            (b["id"],)).fetchone()
            if qr:
                from html import escape
                cartoes.append(f'<div class="c">{gerar_svg(url_qr(qr["token"]), 230)}<h2>{escape(b["nome"])}</h2>'
                               f'<p>Ronda · {escape(nome_cond)}</p><small>Código: {escape(qr["token"])}</small></div>')
        html = ("<!doctype html><html lang='pt-BR'><meta charset='utf-8'><title>QR Codes dos blocos</title>"
                "<style>body{font-family:Inter,Segoe UI,Arial,sans-serif;color:#172b3a;margin:24px}"
                ".g{display:grid;grid-template-columns:repeat(2,1fr);gap:18px}.c{border:2px solid #102a43;"
                "border-radius:14px;padding:18px;text-align:center;break-inside:avoid}h2{margin:8px 0 2px;"
                "font-size:26px;color:#102a43}p{margin:0;color:#6b7c8f}small{color:#6b7c8f;font-size:11px}"
                "button{margin-bottom:16px;padding:10px 16px;border:0;border-radius:9px;background:#1677e8;"
                "color:#fff;font-weight:700}@media print{button{display:none}}</style>"
                "<button onclick='print()'>Imprimir</button><div class='g'>" + "".join(cartoes) + "</div></html>")
        return Response(html, mimetype="text/html")

    # ------------------------------------------------------------- unidades
    @app.get("/api/admin/unidades")
    @requer_login("admin")
    def admin_unidades():
        return jsonify(linhas(get_db().execute(
            "SELECT un.*, b.nome AS bloco_nome, a.nome AS andar_nome FROM unidades un JOIN blocos b ON b.id=un.bloco_id "
            "LEFT JOIN andares a ON a.id=un.andar_id ORDER BY b.numero, un.numero")))

    def dados_unidade(d):
        db = get_db()
        bloco_id = inteiro(d, "bloco_id", "Bloco", True)
        if not db.execute("SELECT 1 FROM blocos WHERE id=?", (bloco_id,)).fetchone():
            raise ErroApi("Bloco inválido.")
        andar_id = inteiro(d, "andar_id", "Andar")
        if andar_id and not db.execute("SELECT 1 FROM andares WHERE id=? AND bloco_id=?", (andar_id, bloco_id)).fetchone():
            raise ErroApi("Andar inválido para o bloco.")
        return (bloco_id, andar_id, texto(d, "numero", "Unidade", True, 20),
                escolha(d, "status", "Status", ("ocupada", "desocupada")),
                texto(d, "observacao", "Observação", False, 500))

    @app.post("/api/admin/unidades")
    @requer_login("admin")
    def admin_criar_unidade():
        v = dados_unidade(dados_requisicao())
        db = get_db()
        try:
            cur = db.execute("INSERT INTO unidades (bloco_id, andar_id, numero, status, observacao) VALUES (?,?,?,?,?)", v)
        except __import__("sqlite3").IntegrityError:
            raise ErroApi("Essa unidade já existe neste bloco.", 409)
        auditar("unidade_criada", "unidade", cur.lastrowid, v[2])
        db.commit()
        return jsonify(id=cur.lastrowid), 201

    @app.put("/api/admin/unidades/<int:uid>")
    @requer_login("admin")
    def admin_editar_unidade(uid):
        v = dados_unidade(dados_requisicao())
        db = get_db()
        if not db.execute("SELECT 1 FROM unidades WHERE id=?", (uid,)).fetchone():
            raise ErroApi("Unidade não encontrada.", 404)
        try:
            db.execute("UPDATE unidades SET bloco_id=?, andar_id=?, numero=?, status=?, observacao=? WHERE id=?",
                       (*v, uid))
        except __import__("sqlite3").IntegrityError:
            raise ErroApi("Essa unidade já existe neste bloco.", 409)
        auditar("unidade_alterada", "unidade", uid, v[2])
        db.commit()
        return jsonify(ok=True)

    @app.delete("/api/admin/unidades/<int:uid>")
    @requer_login("admin")
    def admin_excluir_unidade(uid):
        db = get_db()
        u = db.execute("SELECT numero FROM unidades WHERE id=?", (uid,)).fetchone()
        if not u:
            raise ErroApi("Unidade não encontrada.", 404)
        db.execute("DELETE FROM unidades WHERE id=?", (uid,))
        auditar("unidade_excluida", "unidade", uid, u["numero"])
        db.commit()
        return jsonify(ok=True)

    # ------------------------------------------------ empresas terceirizadas
    SERVICOS = ("Limpeza", "Jardinagem", "Elevadores", "Elétrica", "Hidráulica", "Piscina", "Segurança",
                "Manutenção", "Outros")

    @app.get("/api/admin/empresas")
    @requer_login("admin")
    def admin_empresas():
        return jsonify(linhas(get_db().execute(
            "SELECT e.*, (SELECT COUNT(*) FROM documentos d WHERE d.empresa_id=e.id) AS documentos "
            "FROM empresas_terceirizadas e ORDER BY e.ativo DESC, e.nome")))

    def dados_empresa(d):
        email = texto(d, "email", "E-mail", False, 150)
        if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ErroApi("Informe um e-mail válido.", campos=["email"])
        inicio, fim = data(d, "data_inicio", "Data de início"), data(d, "data_termino", "Término/validade")
        if inicio and fim and fim < inicio:
            raise ErroApi("O término deve ser depois do início.", campos=["data_termino"])
        return (texto(d, "nome", "Empresa", True, 150), escolha(d, "servico", "Serviço prestado", SERVICOS),
                texto(d, "responsavel", "Responsável", False, 120), texto(d, "telefone", "Telefone", False, 40),
                email, texto(d, "contrato", "Contrato", False, 120), inicio, fim,
                texto(d, "observacoes", "Observações", False, 2000))

    @app.post("/api/admin/empresas")
    @requer_login("admin")
    def admin_criar_empresa():
        v = dados_empresa(dados_requisicao())
        db = get_db()
        cur = db.execute("INSERT INTO empresas_terceirizadas (nome, servico, responsavel, telefone, email, contrato, "
                         "data_inicio, data_termino, observacoes, ativo, criado_em) VALUES (?,?,?,?,?,?,?,?,?,1,?)",
                         (*v, agora()))
        auditar("empresa_criada", "empresa", cur.lastrowid, v[0])
        db.commit()
        return jsonify(id=cur.lastrowid), 201

    @app.put("/api/admin/empresas/<int:eid>")
    @requer_login("admin")
    def admin_editar_empresa(eid):
        d = dados_requisicao()
        v = dados_empresa(d)
        db = get_db()
        if not db.execute("SELECT 1 FROM empresas_terceirizadas WHERE id=?", (eid,)).fetchone():
            raise ErroApi("Empresa não encontrada.", 404)
        db.execute("UPDATE empresas_terceirizadas SET nome=?, servico=?, responsavel=?, telefone=?, email=?, "
                   "contrato=?, data_inicio=?, data_termino=?, observacoes=?, ativo=? WHERE id=?",
                   (*v, booleano(d, "ativo"), eid))
        auditar("empresa_alterada", "empresa", eid, v[0])
        db.commit()
        return jsonify(ok=True)

    # ------------------------------------------------------------ documentos
    CATEGORIAS_DOC = ("Normas", "Contratos", "Laudos", "Certificados", "Terceirizados", "Administrativo", "Outros")

    @app.get("/api/admin/documentos")
    @requer_login("admin")
    def admin_documentos():
        return jsonify(linhas(get_db().execute(
            "SELECT d.id, d.nome, d.categoria, d.nome_original, d.tamanho, d.data_documento, d.validade, "
            "d.responsavel, d.observacao, d.empresa_id, e.nome AS empresa_nome, d.criado_em, u.nome AS criado_por_nome "
            "FROM documentos d JOIN users u ON u.id=d.criado_por "
            "LEFT JOIN empresas_terceirizadas e ON e.id=d.empresa_id ORDER BY d.id DESC")))

    def dados_documento(d):
        db = get_db()
        empresa_id = inteiro(d, "empresa_id", "Empresa")
        if empresa_id and not db.execute("SELECT 1 FROM empresas_terceirizadas WHERE id=?", (empresa_id,)).fetchone():
            raise ErroApi("Empresa inválida.")
        return (texto(d, "nome", "Nome", True, 150), escolha(d, "categoria", "Categoria", CATEGORIAS_DOC),
                data(d, "data_documento", "Data"), data(d, "validade", "Validade"),
                texto(d, "responsavel", "Responsável", False, 120), texto(d, "observacao", "Observação", False, 2000),
                empresa_id)

    @app.post("/api/admin/documentos")
    @requer_login("admin")
    def admin_criar_documento():
        v = dados_documento(request.form)
        arq = request.files.get("arquivo")
        if not arq or not arq.filename:
            raise ErroApi("Selecione o arquivo do documento.", campos=["arquivo"])
        info = salvar_arquivo(arq, "documentos", "documento")
        g.arquivos_salvos.append(info["arquivo"])
        db = get_db()
        cur = db.execute(
            "INSERT INTO documentos (nome, categoria, data_documento, validade, responsavel, observacao, empresa_id, "
            "arquivo, nome_original, mime, tamanho, criado_por, criado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (*v, info["arquivo"], info["nome_original"], info["mime"], info["tamanho"], g.user["id"], agora()))
        auditar("documento_criado", "documento", cur.lastrowid, v[0])
        db.commit()
        return jsonify(id=cur.lastrowid), 201

    @app.put("/api/admin/documentos/<int:doc_id>")
    @requer_login("admin")
    def admin_editar_documento(doc_id):
        db = get_db()
        atual = db.execute("SELECT * FROM documentos WHERE id=?", (doc_id,)).fetchone()
        if not atual:
            raise ErroApi("Documento não encontrado.", 404)
        v = dados_documento(request.form)
        db.execute("UPDATE documentos SET nome=?, categoria=?, data_documento=?, validade=?, responsavel=?, "
                   "observacao=?, empresa_id=? WHERE id=?", (*v, doc_id))
        arq = request.files.get("arquivo")
        if arq and arq.filename:
            info = salvar_arquivo(arq, "documentos", "documento")
            g.arquivos_salvos.append(info["arquivo"])
            db.execute("UPDATE documentos SET arquivo=?, nome_original=?, mime=?, tamanho=? WHERE id=?",
                       (info["arquivo"], info["nome_original"], info["mime"], info["tamanho"], doc_id))
        auditar("documento_alterado", "documento", doc_id, v[0])
        db.commit()
        if arq and arq.filename and atual["arquivo"]:
            try:
                os.remove(caminho_upload(atual["arquivo"]))
            except Exception:
                pass
        return jsonify(ok=True)

    @app.delete("/api/admin/documentos/<int:doc_id>")
    @requer_login("admin")
    def admin_excluir_documento(doc_id):
        db = get_db()
        atual = db.execute("SELECT * FROM documentos WHERE id=?", (doc_id,)).fetchone()
        if not atual:
            raise ErroApi("Documento não encontrado.", 404)
        db.execute("DELETE FROM documentos WHERE id=?", (doc_id,))
        auditar("documento_excluido", "documento", doc_id, atual["nome"])
        db.commit()
        if atual["arquivo"]:
            try:
                os.remove(caminho_upload(atual["arquivo"]))
            except Exception:
                pass
        return jsonify(ok=True)

    @app.get("/api/admin/documentos/<int:doc_id>/arquivo")
    @requer_login("admin")
    def admin_baixar_documento(doc_id):
        doc = get_db().execute("SELECT * FROM documentos WHERE id=?", (doc_id,)).fetchone()
        if not doc or not doc["arquivo"]:
            raise ErroApi("Documento não encontrado.", 404)
        caminho = caminho_upload(doc["arquivo"])
        if not os.path.exists(caminho):
            raise ErroApi("Arquivo não encontrado no servidor.", 404)
        return send_file(caminho, mimetype=doc["mime"], as_attachment=True, download_name=doc["nome_original"])

    # ------------------------------------------------------------- auditoria
    @app.get("/api/admin/auditoria")
    @requer_login("admin")
    def admin_auditoria():
        where, params = [], []
        if request.args.get("usuario"):
            where.append("a.user_id=?"); params.append(inteiro(request.args, "usuario", "Usuário"))
        acao = (request.args.get("acao") or "").strip()[:50]
        if acao:
            where.append("a.acao LIKE ?"); params.append(f"{acao}%")
        de, ate = data(request.args, "de", "De"), data(request.args, "ate", "Até")
        if de:
            where.append("substr(a.criado_em,1,10)>=?"); params.append(de)
        if ate:
            where.append("substr(a.criado_em,1,10)<=?"); params.append(ate)
        sql = ("SELECT a.*, u.nome AS usuario_nome FROM auditoria a LEFT JOIN users u ON u.id=a.user_id" +
               (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY a.id DESC LIMIT 500")
        return jsonify(linhas(get_db().execute(sql, params)))


MODO_DEMO = __name__ == "__main__" and "--demo" in __import__("sys").argv
if MODO_DEMO:
    os.environ["CONDOIA_DB"] = os.path.join(BASE_DIR, "instance", "demo.db")
    os.environ["CONDOIA_UPLOADS"] = os.path.join(BASE_DIR, "uploads_demo")

app = create_app()

if __name__ == "__main__":
    if not os.path.exists(app.config["DATABASE"]):
        if MODO_DEMO:
            print("Demonstração não encontrada. Rode primeiro: python manage.py demo")
        else:
            print("Banco de dados não encontrado. Rode primeiro: python manage.py init-db")
        raise SystemExit(1)
    if MODO_DEMO:
        print("*** MODO DEMONSTRAÇÃO — usando instance/demo.db (dados fictícios) ***")
    host = os.environ.get("CONDOIA_HOST", "0.0.0.0")
    porta = int(os.environ.get("CONDOIA_PORTA", "5000"))
    print(f"CondoIA rodando em http://localhost:{porta}")
    app.run(host=host, port=porta, debug=os.environ.get("CONDOIA_DEBUG") == "1")
