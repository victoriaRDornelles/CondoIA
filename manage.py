"""Uso:
  python manage.py init-db [--senha-padrao SENHA]   cria o banco, a estrutura e os 8 usuários iniciais
  python manage.py redefinir-senha USUARIO SENHA    redefine a senha de um usuário
  python manage.py demo [--senha SENHA] [--sim]     cria o banco de DEMONSTRAÇÃO (instance/demo.db)
                                                    depois abra com: python app.py --demo
"""
import os
import sys

from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAMINHO_DB = os.environ.get("CONDOIA_DB", os.path.join(BASE_DIR, "instance", "condoia.db"))


def main(args):
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    import database

    if args[0] == "init-db":
        senha = None
        if "--senha-padrao" in args:
            i = args.index("--senha-padrao")
            senha = args[i + 1] if i + 1 < len(args) else None
            if not senha:
                print("Informe a senha após --senha-padrao.")
                return 1
        os.makedirs(os.path.dirname(CAMINHO_DB), exist_ok=True)
        criados = database.inicializar(CAMINHO_DB, senha)
        print(f"Banco pronto em: {CAMINHO_DB}")
        if criados:
            print("\nUsuários criados agora (anote as senhas — elas não serão exibidas novamente):")
            for u, s in criados.items():
                print(f"  {u:<14} {s}")
        else:
            print("Nenhum usuário novo: os usuários iniciais já existiam.")
        return 0

    if args[0] == "demo":
        import demo
        senha = "demo12345"
        if "--senha" in args:
            i = args.index("--senha")
            senha = args[i + 1] if i + 1 < len(args) else ""
            if len(senha) < 8:
                print("A senha da demonstração deve ter pelo menos 8 caracteres.")
                return 1
        try:
            import PIL  # noqa: F401
        except ImportError:
            print("A demonstração precisa do Pillow para gerar as fotos: pip install Pillow")
            return 1
        print("Este comando cria um banco SEPARADO só para demonstração (instance/demo.db).")
        print("O banco real (instance/condoia.db) não é alterado.")
        if os.path.exists(demo.DB_DEMO) and "--sim" not in args:
            if input("Já existe uma demonstração. Apagar e criar de novo? (s/N) ").strip().lower() != "s":
                print("Nada foi alterado.")
                return 0
        print("Gerando dados de demonstração… (leva alguns segundos)")
        resumo = demo.criar(senha=senha)
        print("\nDemonstração pronta:")
        for nome, total in resumo.items():
            print(f"  {nome:<24} {total}")
        print(f"\nUsuários: admin, ronda01–ronda04, manutencao01–manutencao03 · senha: {senha}")
        print("Para abrir:  python app.py --demo")
        return 0

    if args[0] == "redefinir-senha" and len(args) == 3:
        usuario, senha = args[1].lower(), args[2]
        if len(senha) < 8:
            print("A senha deve ter pelo menos 8 caracteres.")
            return 1
        con = database.conectar(CAMINHO_DB)
        cur = con.execute("UPDATE users SET senha_hash=? WHERE usuario=?", (generate_password_hash(senha), usuario))
        uid = con.execute("SELECT id FROM users WHERE usuario=?", (usuario,)).fetchone()
        if uid:
            con.execute("DELETE FROM sessoes WHERE user_id=?", (uid[0],))
        con.commit()
        print("Senha redefinida." if cur.rowcount else "Usuário não encontrado.")
        return 0 if cur.rowcount else 1

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
