# CondoIA — Gestão Inteligente de Condomínios

Sistema web desenvolvido em **Python + Flask + SQLite** para apoiar a operação de condomínios, reunindo manutenção, rondas, ocorrências, documentos e indicadores em um único sistema.

> **Projeto de portfólio / demonstração.** Os dados de demonstração são fictícios. Não publique banco de produção, uploads reais, credenciais ou informações de clientes neste repositório.

## Funcionalidades

- 🔐 Autenticação e controle de acesso por perfil
- 🛠️ Ordens de serviço com prioridades, responsáveis, andamento e conclusão
- 🧾 Histórico imutável das alterações das OS
- 🚨 Registro e acompanhamento de ocorrências
- 📱 Rondas operacionais
- 🔳 QR Codes por bloco para validação da ronda
- 📸 Evidências fotográficas antes/depois
- 📄 Cadastro e controle de documentos e empresas terceirizadas
- 📊 Dashboard e relatórios operacionais
- 🤖 Módulo de assistência por IA
- 📝 Auditoria de ações do sistema
- 🛡️ Validação de uploads, sessões e permissões

## Tecnologias

- Python 3.10+
- Flask 3
- SQLite
- HTML5 / CSS3 / JavaScript
- Pillow
- QR Code implementado no próprio projeto, sem biblioteca externa

## Arquitetura

```text
CondoIA/
├── app.py                 # Rotas HTTP, API e regras de negócio
├── database.py            # Conexão e inicialização do banco
├── schema.sql             # Estrutura SQLite
├── seguranca.py           # Sessões, autorização, auditoria e uploads
├── qrcode_svg.py          # Geração de QR Codes
├── ia.py                  # Módulo de assistência por IA
├── demo.py                # Geração de dados fictícios para apresentação
├── manage.py              # Comandos administrativos
├── static/
│   ├── index.html
│   ├── css/
│   ├── js/
│   └── img/
└── tests/
    └── test_api.py
```

## Instalação

```bash
python -m venv .venv
```

### Windows

```powershell
.venv\Scripts\activate
pip install -r requirements.txt
```

### Linux/macOS

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

## Banco local

Crie um banco novo para desenvolvimento:

```bash
python manage.py init-db --senha-padrao "umaSenhaDeTeste"
```

Depois:

```bash
python app.py
```

Acesse:

```text
http://localhost:5000
```

O banco local fica em `instance/condoia.db` e está ignorado pelo Git.

## Modo demonstração

O projeto possui um modo separado para apresentações. Ele gera um banco fictício próprio e não altera o banco principal.

```bash
python manage.py demo
python app.py --demo
```

Credenciais da demonstração:

```text
Usuário: admin
Senha: demo12345
```

Também existem usuários de demonstração para os perfis de Ronda e Manutenção.

> Recomenda-se executar `python manage.py demo` antes da apresentação para gerar dados com datas atuais.

## Testes

```bash
python -m unittest discover -s tests -v
```

A suíte existente cobre fluxos como autenticação, sessões, permissões, rondas, QR Codes, ordens de serviço, uploads, auditoria e IA.

## Segurança

O projeto possui uma camada dedicada de segurança para:

- hash de senhas;
- sessões com token armazenado como hash;
- controle de acesso por perfil;
- bloqueio temporário após tentativas de login;
- auditoria de ações;
- validação de arquivos pelo conteúdo/MIME;
- limites de tamanho para uploads;
- nomes aleatórios para arquivos enviados;
- proteção contra acesso fora do diretório de uploads.

## Variáveis de ambiente

Algumas configurações podem ser ajustadas sem alterar o código:

```text
CONDOIA_PORTA
CONDOIA_HOST
CONDOIA_DB
CONDOIA_UPLOADS
CONDOIA_TZ
CONDOIA_HTTPS
CONDOIA_DEBUG
```

Use `.env.example` apenas como referência. **Nunca coloque segredos reais no GitHub.**

## Objetivo do projeto

O CondoIA foi desenvolvido como uma aplicação prática para centralizar processos operacionais de um condomínio, transformando atividades como rondas, manutenção e registro de ocorrências em fluxos digitais rastreáveis.

Além da implementação das funcionalidades, o projeto demonstra conceitos de:

- desenvolvimento backend;
- APIs REST;
- banco de dados relacional;
- autenticação e autorização;
- validação de dados;
- upload seguro de arquivos;
- auditoria;
- automação com QR Code;
- testes automatizados;
- integração de IA;
- organização de uma aplicação web.

## Portfólio

Para uma descrição mais curta do projeto, consulte [`PORTFOLIO.md`](PORTFOLIO.md).

## Aviso

Este repositório é uma versão pública/demonstrativa do projeto. Não contém o banco de produção nem uploads reais.
