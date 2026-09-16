"""CondoIA — assistente baseado nos dados reais do sistema.

Arquitetura:
  • FERRAMENTAS: cada consulta é uma função que lê o banco respeitando o perfil do usuário.
    Nenhuma resposta é inventada: se não houver ferramenta para a pergunta, o assistente diz isso.
  • responder(): hoje escolhe a ferramenta por palavras-chave.
  • Integração futura com um modelo de IA (LLM): basta expor FERRAMENTAS como "tools"
    (nome + descrição + perfis) e deixar o modelo escolher qual chamar; a resposta final
    deve ser montada somente com o retorno dessas funções.
"""
import unicodedata
from datetime import date, timedelta

from database import agora, hoje


def _norm(t):
    t = unicodedata.normalize("NFD", t.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _filtro_os(user):
    if user["perfil"] == "manutencao":
        return "(o.responsavel_id=? OR (o.status='aberta' AND o.responsavel_id IS NULL))", [user["id"]]
    if user["perfil"] == "ronda":
        return "o.aberta_por=?", [user["id"]]
    return "1=1", []


ROTULO_OS = {"aberta": "Aberta", "em_andamento": "Em andamento", "concluida": "Concluída"}


def os_abertas(db, user):
    f, p = _filtro_os(user)
    rows = db.execute(f"SELECT o.id, o.local, o.descricao, o.prioridade, o.status FROM ordens_servico o "
                      f"WHERE o.status<>'concluida' AND {f} ORDER BY o.id DESC LIMIT 20", p).fetchall()
    if not rows:
        return "Não há ordens de serviço abertas ou em andamento.", []
    itens = [f"#{r['id']:05d} · {r['local']} · {r['prioridade']} · {ROTULO_OS[r['status']]}" for r in rows]
    return f"Há {len(rows)} ordem(ns) de serviço não concluída(s):", itens


def os_mais_antiga(db, user):
    f, p = _filtro_os(user)
    r = db.execute(f"SELECT o.id, o.local, o.descricao, o.criado_em, o.status FROM ordens_servico o "
                   f"WHERE o.status<>'concluida' AND {f} ORDER BY o.criado_em LIMIT 1", p).fetchone()
    if not r:
        return "Não há ordens de serviço pendentes de conclusão.", []
    dias = (date.fromisoformat(hoje()) - date.fromisoformat(r["criado_em"][:10])).days
    return (f"A OS mais antiga sem conclusão é a #{r['id']:05d} ({r['local']}), aberta em "
            f"{r['criado_em'][8:10]}/{r['criado_em'][5:7]}/{r['criado_em'][:4]} — há {dias} dia(s). "
            f"Status: {ROTULO_OS[r['status']]}."), [r["descricao"]]


def problemas_rondas_hoje(db, user):
    extra, p = ("AND r.user_id=?", [user["id"]]) if user["perfil"] == "ronda" else ("", [])
    rows = db.execute(
        f"""SELECT COALESCE(pt.nome, b.nome || ' — ' || a.nome) AS local, rp.observacao, rp.registrado_em, u.nome
              FROM ronda_pontos rp JOIN rondas r ON r.id=rp.ronda_id JOIN users u ON u.id=rp.user_id
              LEFT JOIN pontos pt ON pt.id=rp.ponto_id LEFT JOIN blocos b ON b.id=rp.bloco_id
              LEFT JOIN andares a ON a.id=rp.andar_id
             WHERE rp.status='problema' AND substr(rp.registrado_em,1,10)=? {extra} ORDER BY rp.id""",
        [hoje()] + p).fetchall()
    if not rows:
        return "Nenhum problema foi registrado nas rondas de hoje.", []
    return (f"{len(rows)} problema(s) registrado(s) nas rondas de hoje:",
            [f"{r['registrado_em'][11:16]} · {r['local']}: {r['observacao']} ({r['nome']})" for r in rows])


def bloco_mais_ocorrencias(db, user):
    rows = db.execute("SELECT 1 FROM ocorrencias WHERE bloco_id IS NOT NULL LIMIT 1").fetchall()
    if not rows:
        return "Ainda não há ocorrências registradas em blocos.", []
    todos = db.execute("SELECT b.nome, COUNT(*) AS total FROM ocorrencias c JOIN blocos b ON b.id=c.bloco_id "
                       "GROUP BY b.id ORDER BY total DESC, b.numero").fetchall()
    maximo = todos[0]["total"]
    lideres = [r["nome"] for r in todos if r["total"] == maximo]
    itens = [f"{r['nome']}: {r['total']}" for r in todos[:5]]
    if len(lideres) > 1:
        return (f"Há empate entre {', '.join(lideres[:-1])} e {lideres[-1]}, com {maximo} ocorrência(s) cada.", itens)
    return f"O bloco com mais ocorrências é o {lideres[0]}, com {maximo}.", itens


def documentos_vencendo(db, user):
    limite = (date.fromisoformat(hoje()) + timedelta(days=30)).isoformat()
    rows = db.execute("SELECT nome, validade FROM documentos WHERE validade IS NOT NULL AND validade<=? "
                      "ORDER BY validade", (limite,)).fetchall()
    if not rows:
        return "Nenhum documento vence nos próximos 30 dias.", []
    h = hoje()
    return ("Documentos vencidos ou que vencem nos próximos 30 dias:",
            [f"{r['nome']} — {r['validade'][8:10]}/{r['validade'][5:7]}/{r['validade'][:4]}"
             f"{' (vencido)' if r['validade'] < h else ''}" for r in rows])


def ocorrencias_abertas(db, user):
    extra, p = ("AND user_id=?", [user["id"]]) if user["perfil"] == "ronda" else ("", [])
    rows = db.execute(f"SELECT id, local, descricao FROM ocorrencias WHERE status<>'concluida' {extra} "
                      f"ORDER BY id DESC LIMIT 20", p).fetchall()
    if not rows:
        return "Não há ocorrências em aberto.", []
    return f"Há {len(rows)} ocorrência(s) em aberto:", [f"#{r['id']:06d} · {r['local']}: {r['descricao']}" for r in rows]


def rondas_hoje(db, user):
    extra, p = ("AND r.user_id=?", [user["id"]]) if user["perfil"] == "ronda" else ("", [])
    rows = db.execute(f"SELECT r.id, r.status, r.iniciada_em, u.nome FROM rondas r JOIN users u ON u.id=r.user_id "
                      f"WHERE substr(r.iniciada_em,1,10)=? {extra} ORDER BY r.id", [hoje()] + p).fetchall()
    if not rows:
        return "Nenhuma ronda foi iniciada hoje.", []
    rot = {"em_andamento": "em andamento", "concluida": "concluída", "incompleta": "finalizada incompleta"}
    return (f"{len(rows)} ronda(s) hoje:", [f"{r['iniciada_em'][11:16]} · {r['nome']} · {rot[r['status']]}"
                                            for r in rows])


# nome: (descrição para o futuro modelo, perfis permitidos, função, palavras-chave [todas de um grupo])
FERRAMENTAS = {
    "os_mais_antiga": ("OS há mais tempo sem conclusão", ("admin", "manutencao", "ronda"), os_mais_antiga,
                       [["mais tempo"], ["mais antiga"], ["mais velha"], ["mais atrasada"]]),
    "problemas_rondas_hoje": ("Problemas encontrados nas rondas de hoje", ("admin", "ronda"), problemas_rondas_hoje,
                              [["problema", "ronda"]]),
    "bloco_mais_ocorrencias": ("Bloco com mais ocorrências", ("admin", "manutencao"), bloco_mais_ocorrencias,
                               [["bloco", "ocorrenc"]]),
    "documentos_vencendo": ("Documentos próximos do vencimento", ("admin",), documentos_vencendo,
                            [["document"], ["vencim"], ["vencend"]]),
    "os_abertas": ("Ordens de serviço abertas", ("admin", "manutencao", "ronda"), os_abertas,
                   [["os"], ["ordem"], ["ordens"]]),
    "ocorrencias_abertas": ("Ocorrências em aberto", ("admin", "manutencao", "ronda"), ocorrencias_abertas,
                            [["ocorrenc"]]),
    "rondas_hoje": ("Rondas de hoje", ("admin", "ronda"), rondas_hoje, [["ronda"]]),
}

EXEMPLOS = ["Quais OS estão abertas?", "Qual OS está há mais tempo sem conclusão?",
            "Quais problemas foram encontrados nas rondas de hoje?", "Qual bloco teve mais ocorrências?",
            "Quais documentos estão próximos do vencimento?"]


def responder(db, user, pergunta):
    q = " " + _norm(pergunta) + " "
    for q_sub in ("?", ",", ".", "!"):
        q = q.replace(q_sub, " ")
    for nome, (_desc, perfis, fn, grupos) in FERRAMENTAS.items():
        if any(all((f" {p} " in q) if p in ("os",) else (p in q) for p in grupo) for grupo in grupos):
            if user["perfil"] not in perfis:
                return {"texto": "Essa informação é restrita à Administração.", "itens": [], "fonte": None}
            txt, itens = fn(db, user)
            return {"texto": txt, "itens": itens, "fonte": f"Banco de dados CondoIA · {agora()[11:16]}",
                    "ferramenta": nome}
    return {"texto": "Ainda não sei responder essa pergunta com os dados do sistema. Experimente perguntar:",
            "itens": EXEMPLOS, "fonte": None}
