"""Monta um banco de DEMONSTRAÇÃO do CondoIA (separado do banco real).

Todos os registros passam pela própria API do sistema — com as mesmas regras de foto
obrigatória, histórico da OS e auditoria. Um relógio simulado espalha as datas pelos
últimos 12 dias até o momento em que o comando é executado.

Uso:  python manage.py demo            (cria instance/demo.db e uploads_demo/)
      python app.py --demo             (abre o sistema com esse banco)
"""
import io
import os
import random
import shutil
import sqlite3
import textwrap
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DEMO = os.path.join(BASE_DIR, "instance", "demo.db")
UPLOADS_DEMO = os.path.join(BASE_DIR, "uploads_demo")
H = {"X-CondoIA": "1"}


# ------------------------------------------------------------------ imagens
def _fonte(tamanho):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=tamanho)
    except TypeError:  # Pillow antigo
        return ImageFont.load_default()


def foto(titulo, tipo="antes"):
    """Imagem JPG identificada como foto de demonstração."""
    from PIL import Image, ImageDraw
    cores = {"antes": ((62, 84, 104), (214, 226, 236)), "depois": ((25, 110, 75), (222, 244, 232)),
             "ronda": ((130, 52, 60), (246, 226, 229))}
    escura, clara = cores.get(tipo, cores["antes"])
    im = Image.new("RGB", (1024, 768), clara)
    d = ImageDraw.Draw(im)
    for y in range(0, 768, 48):
        d.line([(0, y), (1024, y + 180)], fill=tuple(max(c - 12, 0) for c in clara), width=18)
    d.rounded_rectangle([60, 180, 964, 600], radius=36, fill=(255, 255, 255), outline=escura, width=6)
    rotulo = {"antes": "FOTO DO PROBLEMA", "depois": "FOTO DEPOIS DE FEITO", "ronda": "FOTO DA RONDA"}[tipo]
    d.text((100, 215), rotulo, font=_fonte(34), fill=escura)
    y = 285
    for linha in textwrap.wrap(titulo, 30)[:4]:
        d.text((100, y), linha, font=_fonte(54), fill=(23, 43, 58))
        y += 72
    d.text((100, 545), "Imagem ilustrativa · demonstração CondoIA", font=_fonte(26), fill=(107, 124, 143))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82)
    buf.seek(0)
    return buf


def pdf(titulo, linhas):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 1240, 170], fill=(16, 42, 67))
    d.text((80, 55), "CondoIA · documento de demonstração", font=_fonte(40), fill="white")
    d.text((80, 260), titulo, font=_fonte(60), fill=(16, 42, 67))
    y = 380
    for linha in linhas:
        for parte in textwrap.wrap(linha, 52):
            d.text((80, y), parte, font=_fonte(34), fill=(23, 43, 58))
            y += 52
        y += 20
    buf = io.BytesIO()
    im.save(buf, "PDF")
    buf.seek(0)
    return buf


# ------------------------------------------------------------------- gerador
class Demo:
    def __init__(self, caminho_db, pasta_uploads, senha):
        import app as appmod
        import database
        import seguranca
        self.db_path, self.senha = caminho_db, senha
        self.agora_real = datetime.fromisoformat(database.agora())
        self.hoje = self.agora_real.replace(hour=0, minute=0, second=0)
        self.t = self.hoje - timedelta(days=13)
        self.rng = random.Random(2026)

        relogio = lambda: self.t.replace(microsecond=0).isoformat()
        self._originais = [(appmod, "agora", appmod.agora), (appmod, "hoje", appmod.hoje),
                           (seguranca, "agora", seguranca.agora), (database, "agora", database.agora)]
        for mod in (appmod, seguranca, database):
            mod.agora = relogio
        appmod.hoje = lambda: relogio()[:10]

        database.inicializar(caminho_db, senha)
        self.app = appmod.create_app({"DATABASE": caminho_db, "UPLOAD_DIR": pasta_uploads})
        self.ids = {u: i for i, u in self.sql("SELECT id, usuario FROM users")}

    def restaurar_relogio(self):
        for mod, nome, funcao in self._originais:
            setattr(mod, nome, funcao)

    # utilidades
    def sql(self, q, *p):
        con = sqlite3.connect(self.db_path)
        try:
            cur = con.execute(q, p)
            con.commit()
            return [tuple(r) for r in cur.fetchall()]
        finally:
            con.close()

    def quando(self, dias_atras, hora, minuto=0):
        self.t = (self.hoje - timedelta(days=dias_atras)).replace(hour=hora, minute=minuto)

    def passo(self, minimo=2, maximo=4):
        self.t += timedelta(minutes=self.rng.randint(minimo, maximo), seconds=self.rng.randint(0, 59))

    def login(self, usuario):
        c = self.app.test_client()
        self.chamar(c, "post", "/api/auth/login", json={"usuario": usuario, "senha": self.senha})
        return c

    def chamar(self, c, metodo, url, arquivos=False, **kw):
        if arquivos:
            kw["content_type"] = "multipart/form-data"
        r = getattr(c, metodo)(url, headers=H, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{metodo.upper()} {url} → {r.status_code}: {r.get_json()}")
        return r.get_json()

    # cadastros
    def cadastros(self):
        self.quando(12, 8, 10)
        c = self.login("admin")
        blocos = {n: i for i, n in self.sql("SELECT id, numero FROM blocos")}
        andares = {(b, n): i for i, b, n in self.sql("SELECT a.id, b.numero, a.numero FROM andares a "
                                                      "JOIN blocos b ON b.id=a.bloco_id")}
        desocupadas = {(2, 302), (4, 101), (5, 202), (7, 301)}
        for b in range(1, 8):
            for andar in range(1, 4):
                for final in (1, 2):
                    numero = andar * 100 + final
                    self.chamar(c, "post", "/api/admin/unidades", json={
                        "bloco_id": blocos[b], "andar_id": andares[(b, andar)], "numero": str(numero),
                        "status": "desocupada" if (b, numero) in desocupadas else "ocupada"})
        self.passo(10, 15)

        empresas = [
            ("Vertical Elevadores Manutenção", "Elevadores", "Ricardo Menezes", "(21) 3456-7801", "contato@verticalelevadores.com.br", "CT-2025/014", -300, 20),
            ("Verde Vivo Jardinagem", "Jardinagem", "Paula Rocha", "(21) 99812-4410", "paula@verdevivo.com.br", "CT-2025/021", -200, 165),
            ("Limpa Bem Serviços", "Limpeza", "Anderson Lima", "(21) 3322-1908", "operacao@limpabem.com.br", "CT-2024/033", -400, 330),
            ("Aqua Clara Piscinas", "Piscina", "Marcos Vieira", "(21) 98877-1203", "marcos@aquaclara.com.br", "CT-2025/008", -150, 45),
            ("Sentinela Segurança Patrimonial", "Segurança", "Cláudia Freitas", "(21) 3030-4545", "comercial@sentinela.com.br", "CT-2024/040", -500, -6),
            ("EletroForte Instalações", "Elétrica", "Jorge Almeida", "(21) 99655-7788", "jorge@eletroforte.com.br", None, None, None),
        ]
        ids_emp = {}
        for nome, serv, resp, tel, email, contrato, ini, fim in empresas:
            r = self.chamar(c, "post", "/api/admin/empresas", json={
                "nome": nome, "servico": serv, "responsavel": resp, "telefone": tel, "email": email, "contrato": contrato,
                "data_inicio": (self.hoje + timedelta(days=ini)).date().isoformat() if ini is not None else "",
                "data_termino": (self.hoje + timedelta(days=fim)).date().isoformat() if fim is not None else "",
                "observacoes": "Empresa fictícia para demonstração."})
            ids_emp[serv] = r["id"]
            self.passo(3, 6)

        documentos = [
            ("Regulamento Interno", "Normas", None, None, "Síndico", None,
             ["Normas de convivência, uso das áreas comuns e horários de silêncio."]),
            ("Contrato de manutenção dos elevadores", "Contratos", -300, 20, "Administração", "Elevadores",
             ["Manutenção preventiva mensal e corretiva dos elevadores dos blocos."]),
            ("AVCB — Auto de Vistoria do Corpo de Bombeiros", "Laudos", -350, 12, "Administração", None,
             ["Vistoria de prevenção e combate a incêndio das áreas comuns."]),
            ("Certificado de limpeza das caixas d'água", "Certificados", -185, -5, "Administração", "Limpeza",
             ["Higienização semestral dos reservatórios de água."]),
            ("Contrato de jardinagem", "Terceirizados", -200, 165, "Administração", "Jardinagem",
             ["Poda, adubação e manutenção dos jardins e palmeiras."]),
            ("Apólice de seguro do condomínio", "Administrativo", -275, 90, "Síndico", None,
             ["Cobertura de incêndio, danos elétricos e responsabilidade civil."]),
        ]
        for nome, cat, data, validade, resp, emp, texto in documentos:
            arquivo = pdf(nome, texto + ["Documento fictício gerado para demonstração."])
            dados = {"nome": nome, "categoria": cat, "responsavel": resp,
                     "data_documento": (self.hoje + timedelta(days=data)).date().isoformat() if data else "",
                     "validade": (self.hoje + timedelta(days=validade)).date().isoformat() if validade is not None else "",
                     "empresa_id": ids_emp.get(emp, ""), "observacao": "",
                     "arquivo": (arquivo, nome.lower().split(" —")[0].replace(" ", "-").replace("'", "") + ".pdf")}
            self.chamar(c, "post", "/api/admin/documentos", arquivos=True, data=dados)
            self.passo(3, 6)
        self.chamar(c, "post", "/api/auth/logout")

    # ronda
    def ronda(self, usuario, eventos=None, pular_blocos=(), obs_final=None, limite=None):
        """eventos: {nome_do_ponto | (bloco, andar): (status, observação)}. Retorna {chave: ocorrencia_id}."""
        eventos = eventos or {}
        c = self.login(usuario)
        self.passo(1, 2)
        estado = self.chamar(c, "post", "/api/rondas")["ronda"]
        rid, feitos, ocorrencias = estado["id"], 0, {}
        tokens = {n: t for t, n in self.sql("SELECT q.token, b.numero FROM qr_codes q JOIN blocos b "
                                            "ON b.id=q.bloco_id WHERE q.ativo=1")}

        def registrar(url, campo, item_id, chave, local):
            nonlocal estado, feitos
            status, obs = eventos.get(chave, ("ok", ""))
            dados = {campo: item_id, "status": status, "observacao": obs}
            if status == "problema":
                dados["fotos"] = [(foto(f"{local}: {obs}", "ronda"), "ronda.jpg")]
            self.passo()
            estado = self.chamar(c, "post", url, arquivos=True, data=dados)["ronda"]
            feitos += 1
            if status == "problema":
                lista = estado["pontos"] if campo == "ponto_id" else [a for b in estado["blocos"] for a in b["andares"]]
                reg = [x for x in lista if x["id"] == item_id][0]["registro"]
                ocorrencias[chave] = reg["ocorrencia_id"]

        for p in list(estado["pontos"]):
            if limite is not None and feitos >= limite:
                return ocorrencias
            registrar(f"/api/rondas/{rid}/pontos", "ponto_id", p["id"], p["nome"], p["nome"])
        for b in list(estado["blocos"]):
            if b["numero"] in pular_blocos:
                continue
            if limite is not None and feitos >= limite:
                return ocorrencias
            self.passo(2, 5)
            estado = self.chamar(c, "post", f"/api/rondas/{rid}/blocos/validar",
                                 json={"codigo": tokens[b["numero"]]})["ronda"]
            for a in b["andares"]:
                if limite is not None and feitos >= limite:
                    return ocorrencias
                registrar(f"/api/rondas/{rid}/andares", "andar_id", a["id"], (b["numero"], a["numero"]),
                          f"{b['nome']} — {a['nome']}")
        self.passo(2, 4)
        self.chamar(c, "post", f"/api/rondas/{rid}/finalizar", json={"observacao": obs_final or ""})
        self.chamar(c, "post", "/api/auth/logout")
        return ocorrencias

    # ordens de serviço
    def abrir_os(self, usuario, local, equipamento, categoria, descricao, prioridade):
        c = self.login(usuario)
        self.passo(1, 3)
        return self.chamar(c, "post", "/api/os", arquivos=True, data={
            "local": local, "equipamento": equipamento or "", "categoria": categoria, "descricao": descricao,
            "prioridade": prioridade, "fotos": [(foto(descricao, "antes"), "problema.jpg")]})["id"]

    def gerar_os(self, oc_id, categoria, prioridade, equipamento=""):
        c = self.login("admin")
        self.passo(5, 20)
        return self.chamar(c, "post", f"/api/ocorrencias/{oc_id}/gerar-os", arquivos=True,
                           data={"categoria": categoria, "prioridade": prioridade, "equipamento": equipamento})["id"]

    def assumir(self, usuario, os_id):
        self.passo(10, 50)
        self.chamar(self.login(usuario), "post", f"/api/os/{os_id}/assumir")

    def atribuir(self, os_id, usuario):
        self.passo(5, 20)
        self.chamar(self.login("admin"), "post", f"/api/os/{os_id}/atribuir", json={"responsavel_id": self.ids[usuario]})

    def iniciar(self, usuario, os_id):
        self.passo(10, 40)
        self.chamar(self.login(usuario), "post", f"/api/os/{os_id}/iniciar")

    def concluir(self, usuario, os_id, servico, titulo):
        self.passo(30, 120)
        self.chamar(self.login(usuario), "post", f"/api/os/{os_id}/concluir", arquivos=True, data={
            "servico_realizado": servico, "fotos": [(foto(titulo, "depois"), "depois.jpg")]})

    # roteiro
    def executar(self):
        self.cadastros()

        self.quando(12, 10, 20)
        os1 = self.abrir_os("admin", "Portaria Norte", "Cancela de veículos", "Portões",
                            "Cancela de veículos travando na abertura", "Crítica")
        self.assumir("manutencao01", os1); self.iniciar("manutencao01", os1)
        self.quando(11, 9, 15)
        self.concluir("manutencao01", os1, "Lubrificação do braço da cancela e ajuste do sensor de presença. "
                                           "Testada 20 vezes sem travar.", "Cancela funcionando normalmente")

        self.quando(11, 22, 0)
        self.ronda("ronda01", {"Guarita Sul": ("atencao", "Porteiro sozinho e fila de veículos na entrada")})

        self.quando(10, 6, 0)
        oc = self.ronda("ronda02", {"Portão de saída — subsolo": (
            "problema", "Portão do subsolo não está fechando corretamente, fica aberto cerca de 30 cm")})
        self.quando(10, 8, 30)
        os2 = self.gerar_os(oc["Portão de saída — subsolo"], "Portões", "Alta", "Portão de saída")
        self.assumir("manutencao02", os2); self.iniciar("manutencao02", os2)
        self.quando(9, 10, 40)
        self.concluir("manutencao02", os2, "Ajuste do mecanismo e teste de fechamento.", "Portão do subsolo fechando corretamente")

        self.quando(9, 14, 5)
        os3 = self.abrir_os("ronda01", "Portaria Sul", "Interfone", "Elétrica", "Interfone da Portaria Sul sem áudio", "Média")
        self.quando(9, 22, 0)
        self.ronda("ronda03")
        self.quando(8, 9, 0)
        self.assumir("manutencao02", os3); self.iniciar("manutencao02", os3)
        self.concluir("manutencao02", os3, "Substituição do cabo do monofone e teste de chamada com os blocos.",
                      "Interfone da Portaria Sul com áudio")

        self.quando(8, 6, 0)
        oc = self.ronda("ronda04", {(3, 2): ("problema", "Lâmpada do corredor queimada")})
        self.quando(8, 9, 30)
        os4 = self.gerar_os(oc[(3, 2)], "Iluminação", "Média", "Iluminação")
        self.quando(7, 8, 20)
        self.assumir("manutencao01", os4); self.iniciar("manutencao01", os4)
        self.concluir("manutencao01", os4, "Troca da lâmpada por modelo LED e teste do sensor de presença.",
                      "Corredor do Bloco 3 iluminado")

        self.quando(7, 22, 0)
        self.ronda("ronda01", pular_blocos=(5, 6, 7),
                   obs_final="Chuva forte: blocos 5, 6 e 7 não verificados. Retomado na ronda seguinte.")

        self.quando(6, 6, 0)
        oc = self.ronda("ronda02", {"Deck": ("atencao", "Piso molhado próximo à escada"),
                                    "Banheiros": ("problema", "Vazamento na descarga do banheiro masculino")})
        self.quando(6, 9, 10)
        os5 = self.abrir_os("admin", "Garagem", "CFTV — Câmeras", "CFTV", "Câmera 4 da garagem sem imagem", "Alta")
        self.atribuir(os5, "manutencao01")
        self.quando(6, 9, 40)
        os6 = self.gerar_os(oc["Banheiros"], "Hidráulica", "Alta")
        self.quando(5, 8, 0)
        self.assumir("manutencao03", os6); self.iniciar("manutencao03", os6)
        self.iniciar("manutencao01", os5)

        self.quando(5, 22, 0)
        self.ronda("ronda03")
        self.quando(4, 6, 0)
        self.ronda("ronda04", {"Náutica — lado direito": ("problema", "Refletor apagado, área escura à noite")})
        self.quando(3, 16, 0)
        self.abrir_os("ronda04", "Área de lazer", None, "Jardinagem", "Poda das palmeiras próximas à entrada", "Baixa")
        self.quando(3, 22, 0)
        self.ronda("ronda01", {(6, 1): ("atencao", "Porta corta-fogo não fecha sozinha")})

        self.quando(2, 6, 0)
        self.ronda("ronda02")
        self.quando(2, 15, 20)
        c = self.login("ronda01")
        blocos = {n: i for i, n in self.sql("SELECT id, numero FROM blocos")}
        andar = self.sql("SELECT a.id FROM andares a JOIN blocos b ON b.id=a.bloco_id WHERE b.numero=5 AND a.numero=2")[0][0]
        self.chamar(c, "post", "/api/ocorrencias", arquivos=True, data={
            "local": "Bloco 5 — 2º andar", "bloco_id": blocos[5], "andar_id": andar,
            "descricao": "Barulho de obra fora do horário permitido"})

        self.quando(1, 11, 0)
        os8 = self.abrir_os("admin", "Casa de máquinas", None, "Hidráulica", "Bomba da piscina fazendo ruído alto", "Alta")
        self.atribuir(os8, "manutencao03")
        self.quando(1, 22, 0)
        self.ronda("ronda03", {(2, 3): ("problema", "Infiltração no teto do corredor"),
                               "Espaço Gourmet": ("atencao", "Churrasqueira sem limpeza após evento")})

        # hoje (sempre antes do horário em que o comando está rodando)
        self.t = self.agora_real - timedelta(hours=4)
        self.ronda("ronda04", {(2, 1): ("problema", "Luz de emergência do corredor não acende")})
        self.t = self.agora_real - timedelta(hours=2)
        self.abrir_os("ronda01", "Portaria Norte", "Portão de entrada", "Portões",
                      "Portão de entrada abrindo sozinho", "Crítica")
        self.t = self.agora_real - timedelta(minutes=50)
        self.ronda("ronda02", limite=6)

        self.sql("DELETE FROM sessoes")
        self.sql("UPDATE configuracoes SET valor='7 blocos · demonstração' WHERE chave='descricao_condominio'")


def criar(caminho_db=DB_DEMO, pasta_uploads=UPLOADS_DEMO, senha="demo12345"):
    for sufixo in ("", "-wal", "-shm"):
        if os.path.exists(caminho_db + sufixo):
            os.remove(caminho_db + sufixo)
    shutil.rmtree(pasta_uploads, ignore_errors=True)
    os.makedirs(os.path.dirname(caminho_db), exist_ok=True)
    gerador = Demo(caminho_db, pasta_uploads, senha)
    try:
        gerador.executar()
    finally:
        gerador.restaurar_relogio()
    con = sqlite3.connect(caminho_db)
    resumo = {nome: con.execute(q).fetchone()[0] for nome, q in [
        ("Unidades", "SELECT COUNT(*) FROM unidades"),
        ("Empresas terceirizadas", "SELECT COUNT(*) FROM empresas_terceirizadas"),
        ("Documentos", "SELECT COUNT(*) FROM documentos"),
        ("Rondas", "SELECT COUNT(*) FROM rondas"),
        ("Ocorrências", "SELECT COUNT(*) FROM ocorrencias"),
        ("Ordens de serviço", "SELECT COUNT(*) FROM ordens_servico"),
        ("Fotos", "SELECT COUNT(*) FROM fotos"),
    ]}
    con.close()
    return resumo
