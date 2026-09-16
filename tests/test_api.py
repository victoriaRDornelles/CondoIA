"""Testes da API do CondoIA.  Rodar:  python -m unittest discover -s tests -v"""
import io
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database  # noqa: E402

SENHA = "senha-teste-123"
H = {"X-CondoIA": "1"}


def jpeg(nome="foto.jpg"):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 80, 40)).save(buf, "JPEG")
    buf.seek(0)
    return (buf, nome)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        db = os.path.join(cls.tmp, "t.db")
        database.inicializar(db, SENHA)
        from app import create_app
        cls.app = create_app({"DATABASE": db, "UPLOAD_DIR": os.path.join(cls.tmp, "up"), "TESTING": True})
        cls.db_path = db

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def cliente(self, usuario=None, senha=SENHA):
        c = self.app.test_client()
        if usuario:
            r = c.post("/api/auth/login", json={"usuario": usuario, "senha": senha}, headers=H)
            self.assertEqual(r.status_code, 200, r.json)
        return c

    def sql(self, q, *p):
        con = sqlite3.connect(self.db_path)
        try:
            cur = con.execute(q, p)
            con.commit()
            return cur.fetchall()
        finally:
            con.close()

    def abrir_os(self, c, fotos=True, **extra):
        dados = {"local": "Garagem", "equipamento": "Portão de saída", "categoria": "Portões",
                 "descricao": "Portão do subsolo não fecha", "prioridade": "Alta"}
        dados.update(extra)
        if fotos:
            dados["fotos"] = [jpeg()]
        return c.post("/api/os", data=dados, headers=H, content_type="multipart/form-data")


class TestLogin(Base):
    def test_perfis_entram(self):
        for usuario, perfil in (("admin", "admin"), ("ronda01", "ronda"), ("manutencao02", "manutencao")):
            c = self.app.test_client()
            r = c.post("/api/auth/login", json={"usuario": usuario, "senha": SENHA}, headers=H)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json["perfil"], perfil)
            self.assertEqual(c.get("/api/auth/me").json["usuario"]["perfil"], perfil)
            self.assertIsNotNone(self.sql("SELECT ultimo_acesso FROM users WHERE usuario=?", usuario)[0][0])

    def test_invalido_nao_entra(self):
        c = self.app.test_client()
        self.assertEqual(c.post("/api/auth/login", json={"usuario": "admin", "senha": "errada"}, headers=H).status_code, 401)
        self.assertEqual(c.post("/api/auth/login", json={"usuario": "ninguem", "senha": SENHA}, headers=H).status_code, 401)
        self.assertFalse(c.get("/api/auth/me").json["autenticado"])

    def test_inativo_nao_entra_e_perde_sessao(self):
        c = self.cliente("ronda04")
        self.sql("UPDATE users SET ativo=0 WHERE usuario='ronda04'")
        self.assertEqual(c.get("/api/rondas/atual").status_code, 401)
        r = self.app.test_client().post("/api/auth/login", json={"usuario": "ronda04", "senha": SENHA}, headers=H)
        self.assertEqual(r.status_code, 403)
        self.sql("UPDATE users SET ativo=1 WHERE usuario='ronda04'")

    def test_senha_com_hash(self):
        for (h,) in self.sql("SELECT senha_hash FROM users"):
            self.assertNotIn(SENHA, h)
            self.assertTrue(h.startswith(("scrypt:", "pbkdf2:")))

    def test_logout_invalida_sessao(self):
        c = self.cliente("manutencao03")
        c.post("/api/auth/logout", headers=H)
        self.assertEqual(c.get("/api/os").status_code, 401)

    def test_sem_cabecalho_csrf_recusa(self):
        r = self.app.test_client().post("/api/auth/login", json={"usuario": "admin", "senha": SENHA})
        self.assertEqual(r.status_code, 403)

    def test_bloqueio_por_tentativas(self):
        c = self.app.test_client()
        for _ in range(5):
            c.post("/api/auth/login", json={"usuario": "ronda03", "senha": "x"}, headers=H)
        r = c.post("/api/auth/login", json={"usuario": "ronda03", "senha": SENHA}, headers=H)
        self.assertEqual(r.status_code, 429)


class TestPermissoes(Base):
    ADMIN_GET = ["/api/dashboard", "/api/relatorios", "/api/admin/usuarios", "/api/admin/config",
                 "/api/admin/blocos", "/api/admin/unidades", "/api/admin/empresas", "/api/admin/documentos",
                 "/api/admin/auditoria", "/api/admin/blocos/1/qr.svg"]

    def test_ronda_e_manutencao_bloqueados_no_admin(self):
        for u in ("ronda01", "manutencao01"):
            c = self.cliente(u)
            for url in self.ADMIN_GET:
                self.assertEqual(c.get(url).status_code, 403, f"{u} {url}")
            self.assertEqual(c.post("/api/admin/usuarios", json={}, headers=H).status_code, 403)
            self.assertEqual(c.get("/admin/qrcodes/imprimir").status_code, 403)

    def test_admin_acessa_tudo(self):
        c = self.cliente("admin")
        for url in self.ADMIN_GET:
            self.assertEqual(c.get(url).status_code, 200, url)
        self.assertEqual(c.get("/admin/qrcodes/imprimir").status_code, 200)

    def test_sem_login(self):
        c = self.app.test_client()
        for url in self.ADMIN_GET + ["/api/os", "/api/ocorrencias", "/api/fotos/1"]:
            self.assertEqual(c.get(url).status_code, 401, url)

    def test_perfis_restritos_por_acao(self):
        m = self.cliente("manutencao01")
        self.assertEqual(self.abrir_os(m).status_code, 403)
        self.assertEqual(m.post("/api/rondas", headers=H).status_code, 403)
        a = self.cliente("admin")
        self.assertEqual(a.post("/api/rondas", headers=H).status_code, 403)
        r = self.cliente("ronda01")
        self.assertEqual(r.post("/api/os/1/assumir", headers=H).status_code, 403)

    def test_manipulacao_de_ids(self):
        r1, r2 = self.cliente("ronda01"), self.cliente("ronda02")
        os_id = self.abrir_os(r1).json["id"]
        self.assertEqual(r2.get(f"/api/os/{os_id}").status_code, 404)
        foto = self.sql("SELECT id FROM fotos WHERE os_id=?", os_id)[0][0]
        self.assertEqual(r2.get(f"/api/fotos/{foto}").status_code, 404)
        self.assertEqual(r1.get(f"/api/fotos/{foto}").status_code, 200)
        ronda = r1.post("/api/rondas", headers=H).json["ronda"]["id"]
        self.assertEqual(r2.get(f"/api/rondas/{ronda}").status_code, 404)
        self.assertEqual(r2.post(f"/api/rondas/{ronda}/pontos", data={"ponto_id": 1, "status": "ok"},
                                 headers=H).status_code, 404)
        # manutenção não vê OS atribuída a outro
        m1, m2 = self.cliente("manutencao01"), self.cliente("manutencao02")
        m1.post(f"/api/os/{os_id}/assumir", headers=H)
        self.assertEqual(m2.get(f"/api/os/{os_id}").status_code, 404)
        self.assertEqual(m2.post(f"/api/os/{os_id}/iniciar", headers=H).status_code, 404)


class TestRonda(Base):
    def setUp(self):
        self.c = self.cliente("ronda02")
        self.sql("UPDATE rondas SET status='concluida' WHERE status='em_andamento'")
        self.ronda = self.c.post("/api/rondas", headers=H).json["ronda"]
        self.rid = self.ronda["id"]

    def token_bloco(self, numero):
        return self.sql("SELECT q.token, b.id FROM qr_codes q JOIN blocos b ON b.id=q.bloco_id "
                        "WHERE b.numero=? AND q.ativo=1", numero)[0]

    def test_estrutura_inicial(self):
        self.assertEqual(len(self.ronda["pontos"]), 12)
        self.assertEqual(len(self.ronda["blocos"]), 7)
        for b in self.ronda["blocos"]:
            self.assertEqual([a["nome"] for a in b["andares"]], ["1º andar", "2º andar", "3º andar"], b["nome"])

    def test_qr_identifica_bloco(self):
        token, bid = self.token_bloco(7)
        r = self.c.post(f"/api/rondas/{self.rid}/blocos/validar",
                        json={"codigo": f"http://qualquer:5000/?qr={token}"}, headers=H)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json["bloco_id"], bid)
        self.assertEqual(self.c.post(f"/api/rondas/{self.rid}/blocos/validar", json={"codigo": "inexistente123"},
                                     headers=H).status_code, 404)

    def test_andar_exige_qr_e_bloco_so_conclui_com_todos(self):
        token, bid = self.token_bloco(7)
        andares = self.sql("SELECT id FROM andares WHERE bloco_id=? AND ativo=1 ORDER BY numero", bid)
        r = self.c.post(f"/api/rondas/{self.rid}/andares", data={"andar_id": andares[0][0], "status": "ok"}, headers=H)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.c.post(f"/api/rondas/{self.rid}/blocos/{bid}/manual", headers=H).status_code, 403)
        self.c.post(f"/api/rondas/{self.rid}/blocos/validar", json={"codigo": token}, headers=H)
        for i, (aid,) in enumerate(andares):
            r = self.c.post(f"/api/rondas/{self.rid}/andares", data={"andar_id": aid, "status": "ok"}, headers=H)
            self.assertEqual(r.status_code, 200)
            b = [x for x in r.json["ronda"]["blocos"] if x["id"] == bid][0]
            self.assertEqual(b["concluido"], i == len(andares) - 1)
        # mesmo andar não pode ser registrado duas vezes
        r = self.c.post(f"/api/rondas/{self.rid}/andares", data={"andar_id": andares[0][0], "status": "ok"}, headers=H)
        self.assertEqual(r.status_code, 409)

    def test_qr_regenerado_invalida_antigo(self):
        token, bid = self.token_bloco(3)
        self.cliente("admin").post(f"/api/admin/blocos/{bid}/qr/regenerar", headers=H)
        r = self.c.post(f"/api/rondas/{self.rid}/blocos/validar", json={"codigo": token}, headers=H)
        self.assertEqual(r.status_code, 409)

    def test_problema_exige_descricao_e_foto(self):
        url = f"/api/rondas/{self.rid}/pontos"
        r = self.c.post(url, data={"ponto_id": 2, "status": "problema", "observacao": "Portão aberto"}, headers=H)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json["erro"], "Adicione uma foto para registrar este problema.")
        r = self.c.post(url, data={"ponto_id": 2, "status": "problema", "fotos": [jpeg()]}, headers=H,
                        content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        r = self.c.post(url, data={"ponto_id": 2, "status": "problema", "observacao": "Portão aberto",
                                   "fotos": [jpeg()]}, headers=H, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200)
        reg = [p for p in r.json["ronda"]["pontos"] if p["id"] == 2][0]["registro"]
        self.assertEqual(reg["status"], "problema")
        self.assertEqual(len(reg["fotos"]), 1)
        self.assertIsNotNone(reg["ocorrencia_id"])
        f = self.sql("SELECT tipo, user_id, ronda_id, ponto_id, ocorrencia_id FROM fotos WHERE id=?", reg["fotos"][0])[0]
        self.assertEqual(f[0], "ronda_problema")
        self.assertEqual((f[2], f[3], f[4]), (self.rid, 2, reg["ocorrencia_id"]))

    def test_atencao_com_observacao_e_finalizacao(self):
        url = f"/api/rondas/{self.rid}/pontos"
        r = self.c.post(url, data={"ponto_id": 1, "status": "atencao", "observacao": "Lâmpada fraca"}, headers=H)
        self.assertEqual(r.status_code, 200)
        r = self.c.post(f"/api/rondas/{self.rid}/finalizar", json={}, headers=H)
        self.assertEqual(r.status_code, 409)
        r = self.c.post(f"/api/rondas/{self.rid}/finalizar", json={"observacao": "Chuva forte"}, headers=H)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json["ronda"]["status"], "incompleta")
        self.assertIsNotNone(r.json["ronda"]["finalizada_em"])
        self.assertEqual(self.c.post(url, data={"ponto_id": 3, "status": "ok"}, headers=H).status_code, 409)


class TestOS(Base):
    def test_fluxo_completo_e_historico(self):
        ronda, adm = self.cliente("ronda03"), self.cliente("admin")
        m = self.cliente("manutencao02")
        self.assertEqual(self.abrir_os(ronda, fotos=False).status_code, 400)
        r = self.abrir_os(ronda, descricao="")
        self.assertEqual(r.status_code, 400)
        r = self.abrir_os(ronda)
        self.assertEqual(r.status_code, 201)
        os_id, numero = r.json["id"], r.json["numero"]
        self.assertRegex(numero, r"^#\d{5}$")
        n2 = self.abrir_os(ronda).json["numero"]
        self.assertNotEqual(numero, n2)

        self.assertIn(os_id, [o["id"] for o in m.get("/api/os?escopo=disponiveis").json])
        self.assertEqual(m.post(f"/api/os/{os_id}/concluir", data={"servico_realizado": "x"}, headers=H).status_code, 409)
        self.assertEqual(m.post(f"/api/os/{os_id}/assumir", headers=H).status_code, 200)
        self.assertEqual(self.cliente("manutencao01").post(f"/api/os/{os_id}/assumir", headers=H).status_code, 404)
        self.assertEqual(m.post(f"/api/os/{os_id}/iniciar", headers=H).status_code, 200)
        self.assertEqual(m.get(f"/api/os/{os_id}").json["status"], "em_andamento")

        r = m.post(f"/api/os/{os_id}/concluir", data={"fotos": [jpeg()]}, headers=H, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        self.assertIn("O que foi feito", r.json["erro"])
        r = m.post(f"/api/os/{os_id}/concluir", data={"servico_realizado": "Ajuste do mecanismo"}, headers=H)
        self.assertEqual(r.status_code, 400)
        self.assertIn("foto depois de feito", r.json["erro"])
        self.assertEqual(m.get(f"/api/os/{os_id}").json["status"], "em_andamento")

        r = m.post(f"/api/os/{os_id}/concluir", data={"servico_realizado": "Ajuste do mecanismo e teste de fechamento",
                                                     "fotos": [jpeg()]}, headers=H, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200)
        d = adm.get(f"/api/os/{os_id}").json
        self.assertEqual(d["status"], "concluida")
        self.assertEqual([h["acao"] for h in d["historico"]], ["abertura", "responsavel", "status", "servico", "status"])
        self.assertEqual({f["tipo"] for f in d["fotos"]}, {"os_antes", "os_depois"})
        self.assertTrue(all(h["criado_em"] for h in d["historico"]))
        self.assertEqual(m.post(f"/api/os/{os_id}/concluir", data={"servico_realizado": "x", "fotos": [jpeg()]},
                                headers=H, content_type="multipart/form-data").status_code, 409)
        with self.assertRaises(sqlite3.DatabaseError):
            self.sql("DELETE FROM os_historico WHERE os_id=?", os_id)
        self.assertEqual(len(adm.get(f"/api/os/{os_id}").json["historico"]), 5)

    def test_ocorrencia_gera_os_vinculada(self):
        ronda, adm = self.cliente("ronda01"), self.cliente("admin")
        oc = ronda.post("/api/ocorrencias", data={"local": "Deck", "descricao": "Tábua solta", "fotos": [jpeg()]},
                        headers=H, content_type="multipart/form-data").json
        r = adm.post(f"/api/ocorrencias/{oc['id']}/gerar-os", data={"categoria": "Civil", "prioridade": "Média"}, headers=H,
                     content_type="multipart/form-data")
        self.assertEqual(r.status_code, 201)
        d = adm.get(f"/api/ocorrencias/{oc['id']}").json
        self.assertEqual(d["os_id"], r.json["id"])
        self.assertEqual(len(adm.get(f"/api/os/{r.json['id']}").json["fotos"]), 1)


class TestUploadsEAdmin(Base):
    def test_upload_invalido(self):
        c = self.cliente("ronda04")
        falso = (io.BytesIO(b"isso nao e imagem"), "foto.jpg")
        r = c.post("/api/os", data={"local": "X", "categoria": "Outros", "descricao": "Y", "prioridade": "Baixa",
                                    "fotos": [falso]}, headers=H, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 415)
        exe = (io.BytesIO(b"MZ\x90\x00"), "virus.exe")
        r = c.post("/api/os", data={"local": "X", "categoria": "Outros", "descricao": "Y", "prioridade": "Baixa",
                                    "fotos": [exe]}, headers=H, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 415)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM ordens_servico WHERE local='X'")[0][0], 0)

    def test_upload_grande(self):
        c = self.cliente("ronda04")
        from PIL import Image  # noqa: F401
        grande = (io.BytesIO(b"\xff\xd8\xff" + b"0" * (11 * 1024 * 1024)), "g.jpg")
        r = c.post("/api/os", data={"local": "Z", "categoria": "Outros", "descricao": "Y", "prioridade": "Baixa",
                                    "fotos": [grande]}, headers=H, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 413)

    def test_blocos_andares_configuraveis(self):
        a = self.cliente("admin")
        bid = self.sql("SELECT id FROM blocos WHERE numero=1")[0][0]
        self.assertEqual(a.put(f"/api/admin/blocos/{bid}", json={"nome": "Bloco 1", "andares": 5}, headers=H).status_code, 200)
        est = a.get("/api/estrutura").json
        self.assertEqual(len([b for b in est["blocos"] if b["id"] == bid][0]["andares"]), 5)
        a.put(f"/api/admin/blocos/{bid}", json={"nome": "Bloco 1", "andares": 2}, headers=H)
        est = a.get("/api/estrutura").json
        self.assertEqual(len([b for b in est["blocos"] if b["id"] == bid][0]["andares"]), 2)

    def test_qr_svg_decodificavel(self):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("OpenCV não instalado")
        from qrcode_svg import gerar_matriz
        a = self.cliente("admin")
        bloco = a.get("/api/admin/blocos").json[6]
        m = gerar_matriz(bloco["qr_url"])
        n, s = len(m), 8
        img = np.full(((n + 8) * s, (n + 8) * s), 255, np.uint8)
        for y in range(n):
            for x in range(n):
                if m[y][x]:
                    img[(y + 4) * s:(y + 5) * s, (x + 4) * s:(x + 5) * s] = 0
        leitores = [cv2.QRCodeDetector()] + ([cv2.QRCodeDetectorAruco()] if hasattr(cv2, "QRCodeDetectorAruco") else [])
        self.assertIn(bloco["qr_url"], [l.detectAndDecode(img)[0] for l in leitores])

    def test_empresa_documento_usuario_auditoria(self):
        a = self.cliente("admin")
        e = a.post("/api/admin/empresas", json={"nome": "Elevadores XYZ", "servico": "Elevadores",
                                                "data_termino": "2026-10-01"}, headers=H)
        self.assertEqual(e.status_code, 201)
        pdf = (io.BytesIO(b"%PDF-1.4\n%fim"), "contrato.pdf")
        d = a.post("/api/admin/documentos", data={"nome": "Contrato elevador", "categoria": "Contratos",
                                                  "empresa_id": e.json["id"], "validade": "2026-09-20",
                                                  "arquivo": pdf}, headers=H, content_type="multipart/form-data")
        self.assertEqual(d.status_code, 201)
        self.assertEqual(a.get(f"/api/admin/documentos/{d.json['id']}/arquivo").status_code, 200)
        u = a.post("/api/admin/usuarios", json={"nome": "Ronda 05", "usuario": "ronda05", "perfil": "ronda",
                                                "senha": "curta"}, headers=H)
        self.assertEqual(u.status_code, 400)
        u = a.post("/api/admin/usuarios", json={"nome": "Ronda 05", "usuario": "ronda05", "perfil": "ronda",
                                                "senha": "senhaforte1"}, headers=H)
        self.assertEqual(u.status_code, 201)
        eu = self.sql("SELECT id FROM users WHERE usuario='admin'")[0][0]
        r = a.put(f"/api/admin/usuarios/{eu}", json={"nome": "Adm", "perfil": "admin", "ativo": False}, headers=H)
        self.assertEqual(r.status_code, 400)
        acoes = {x["acao"] for x in a.get("/api/admin/auditoria").json}
        for esperado in ("login", "empresa_criada", "documento_criado", "usuario_criado"):
            self.assertIn(esperado, acoes)
        self.assertIsInstance(a.get("/api/dashboard").json["documentos_vencendo"], int)

    def test_ia_usa_dados_reais_e_respeita_perfil(self):
        r = self.cliente("ronda01").post("/api/ia/perguntar", json={"pergunta": "Quais documentos estão próximos do vencimento?"}, headers=H)
        self.assertIn("restrita", r.json["texto"])
        r = self.cliente("admin").post("/api/ia/perguntar", json={"pergunta": "Qual a cor do céu?"}, headers=H)
        self.assertIsNone(r.json["fonte"])


class TestAndaresEAcesso(Base):
    def test_banco_existente_recebe_andares_sem_mexer_no_configurado(self):
        caminho = os.path.join(self.tmp, "antigo.db")
        database.inicializar(caminho, SENHA)
        con = sqlite3.connect(caminho)
        # simula banco antigo: blocos 1-6 sem andares; bloco 2 ajustado pela Administração para 5
        con.execute("DELETE FROM andares WHERE bloco_id IN (SELECT id FROM blocos WHERE numero<=6)")
        b2 = con.execute("SELECT id FROM blocos WHERE numero=2").fetchone()[0]
        for n in range(1, 6):
            con.execute("INSERT INTO andares (bloco_id, numero, nome) VALUES (?,?,?)", (b2, n, f"{n}º andar"))
        con.commit(); con.close()
        self.assertEqual(database.inicializar(caminho, SENHA), {})  # não recria usuários
        con = sqlite3.connect(caminho)
        qtd = dict(con.execute("SELECT b.numero, COUNT(a.id) FROM blocos b LEFT JOIN andares a "
                               "ON a.bloco_id=b.id AND a.ativo=1 GROUP BY b.numero").fetchall())
        con.close()
        self.assertEqual(qtd, {1: 3, 2: 5, 3: 3, 4: 3, 5: 3, 6: 3, 7: 3})

    def test_alterar_login_e_senha(self):
        a = self.cliente("admin")
        alvo = self.cliente("manutencao03")
        uid = self.sql("SELECT id FROM users WHERE usuario='manutencao03'")[0][0]
        url = f"/api/admin/usuarios/{uid}/acesso"
        # nada informado
        self.assertEqual(a.put(url, json={"usuario": "manutencao03", "senha": ""}, headers=H).status_code, 400)
        # login inválido / já em uso
        self.assertEqual(a.put(url, json={"usuario": "Com Espaço"}, headers=H).status_code, 400)
        self.assertEqual(a.put(url, json={"usuario": "ronda01"}, headers=H).status_code, 409)
        # senha curta / confirmação diferente
        self.assertEqual(a.put(url, json={"senha": "curta", "confirmar_senha": "curta"}, headers=H).status_code, 400)
        self.assertEqual(a.put(url, json={"senha": "novasenha1", "confirmar_senha": "outra"}, headers=H).status_code, 400)
        # só o login (senha continua a mesma)
        r = a.put(url, json={"usuario": "joao.manutencao"}, headers=H)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(alvo.get("/api/os").status_code, 401)  # foi desconectado
        c = self.app.test_client()
        self.assertEqual(c.post("/api/auth/login", json={"usuario": "manutencao03", "senha": SENHA}, headers=H).status_code, 401)
        self.assertEqual(c.post("/api/auth/login", json={"usuario": "joao.manutencao", "senha": SENHA}, headers=H).status_code, 200)
        # só a senha (login continua)
        r = a.put(url, json={"usuario": "joao.manutencao", "senha": "novasenha1", "confirmar_senha": "novasenha1"}, headers=H)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c.get("/api/os").status_code, 401)
        self.assertEqual(c.post("/api/auth/login", json={"usuario": "joao.manutencao", "senha": SENHA}, headers=H).status_code, 401)
        self.assertEqual(c.post("/api/auth/login", json={"usuario": "joao.manutencao", "senha": "novasenha1"}, headers=H).status_code, 200)
        self.assertIn("acesso_alterado", {x["acao"] for x in a.get("/api/admin/auditoria").json})
        # outros perfis não podem
        self.assertEqual(self.cliente("ronda02").put(url, json={"usuario": "hack1"}, headers=H).status_code, 403)
        # admin altera o próprio acesso e continua conectado
        aid = self.sql("SELECT id FROM users WHERE usuario='admin'")[0][0]
        self.assertEqual(a.put(f"/api/admin/usuarios/{aid}/acesso", json={"senha": "adminnova1", "confirmar_senha": "adminnova1"},
                               headers=H).status_code, 200)
        self.assertEqual(a.get("/api/dashboard").status_code, 200)
        self.sql("UPDATE users SET senha_hash=(SELECT senha_hash FROM users WHERE usuario='ronda01') WHERE id=?", aid)


class TestDemonstracao(Base):
    def test_gera_demo_coerente_sem_afetar_relogio(self):
        import demo
        import app as appmod
        import database as dbmod
        caminho = os.path.join(self.tmp, "demo.db")
        resumo = demo.criar(caminho, os.path.join(self.tmp, "up_demo"), "demo12345")
        self.assertEqual(resumo["Rondas"], 13)
        self.assertEqual(resumo["Ordens de serviço"], 9)
        self.assertEqual(appmod.agora.__module__, "database")  # relógio real restaurado
        con = sqlite3.connect(caminho)
        agora = dbmod.agora()
        self.assertEqual(con.execute("SELECT COUNT(*) FROM auditoria WHERE criado_em > ?", (agora,)).fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM os_historico h JOIN ordens_servico o ON o.id=h.os_id "
                                     "WHERE h.criado_em < o.criado_em").fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM ordens_servico WHERE status='concluida' AND "
                                     "(servico_realizado IS NULL OR id NOT IN (SELECT os_id FROM fotos "
                                     "WHERE tipo='os_depois'))").fetchone()[0], 0)
        con.close()

    def test_ia_informa_empate(self):
        import ia
        con = database.conectar(os.path.join(self.tmp, "t.db"))
        uid = self.sql("SELECT id FROM users WHERE usuario='admin'")[0][0]
        b = dict(self.sql("SELECT numero, id FROM blocos"))
        for n in (4, 6):
            con.execute("INSERT INTO ocorrencias (user_id, local, bloco_id, descricao, criado_em, atualizado_em) "
                        "VALUES (?,?,?,?,?,?)", (uid, f"Bloco {n}", b[n], "teste empate", "2026-01-01T10:00:00",
                                                 "2026-01-01T10:00:00"))
        con.commit()
        r = ia.responder(con, {"id": uid, "perfil": "admin"}, "Qual bloco teve mais ocorrências?")
        con.execute("DELETE FROM ocorrencias WHERE descricao='teste empate'"); con.commit(); con.close()
        self.assertIn("empate", r["texto"])


if __name__ == "__main__":
    unittest.main()
