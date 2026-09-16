"""Gerador de QR Code sem dependências externas.

Suporta modo byte (UTF-8), nível de correção M, versões 1 a 10
(até 213 bytes — suficiente para os links dos blocos).
Baseado na especificação ISO/IEC 18004.
"""

# (ec por bloco, [(qtd_blocos, dados_por_bloco), ...]) para nível M
_BLOCOS_M = {
    1: (10, [(1, 16)]), 2: (16, [(1, 28)]), 3: (26, [(1, 44)]),
    4: (18, [(2, 32)]), 5: (24, [(2, 43)]), 6: (16, [(4, 27)]),
    7: (18, [(4, 31)]), 8: (22, [(2, 38), (2, 39)]),
    9: (22, [(3, 36), (2, 37)]), 10: (26, [(4, 43), (1, 44)]),
}
_ALINHAMENTO = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}
_FORMATO_M = 0  # bits do nível M


def _gf_mul(x, y):
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(grau):
    res = [0] * (grau - 1) + [1]
    raiz = 1
    for _ in range(grau):
        for j in range(len(res)):
            res[j] = _gf_mul(res[j], raiz)
            if j + 1 < len(res):
                res[j] ^= res[j + 1]
        raiz = _gf_mul(raiz, 0x02)
    return res


def _rs_resto(dados, divisor):
    res = [0] * len(divisor)
    for b in dados:
        fator = b ^ res.pop(0)
        res.append(0)
        for i, coef in enumerate(divisor):
            res[i] ^= _gf_mul(coef, fator)
    return res


def _codewords(texto):
    dados = texto.encode("utf-8")
    for versao in range(1, 11):
        ec, grupos = _BLOCOS_M[versao]
        cap = sum(q * d for q, d in grupos)
        bits_contagem = 8 if versao < 10 else 16
        if 4 + bits_contagem + 8 * len(dados) <= cap * 8:
            break
    else:
        raise ValueError("Texto longo demais para o QR Code (máx. ~200 bytes).")

    bits = []

    def add(valor, n):
        bits.extend((valor >> i) & 1 for i in range(n - 1, -1, -1))

    add(0b0100, 4)
    add(len(dados), bits_contagem)
    for b in dados:
        add(b, 8)
    add(0, min(4, cap * 8 - len(bits)))
    add(0, (-len(bits)) % 8)
    pad = 0xEC
    while len(bits) < cap * 8:
        add(pad, 8)
        pad = 0x11 if pad == 0xEC else 0xEC
    bytes_dados = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]

    divisor = _rs_divisor(ec)
    blocos, k = [], 0
    for qtd, tam in grupos:
        for _ in range(qtd):
            blocos.append(bytes_dados[k:k + tam])
            k += tam
    ecs = [_rs_resto(b, divisor) for b in blocos]
    final = []
    for i in range(max(len(b) for b in blocos)):
        for b in blocos:
            if i < len(b):
                final.append(b[i])
    for i in range(ec):
        for e in ecs:
            final.append(e[i])
    return versao, final


_MASCARAS = [
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
]


def gerar_matriz(texto):
    versao, dados = _codewords(texto)
    n = versao * 4 + 17
    mod = [[False] * n for _ in range(n)]
    func = [[False] * n for _ in range(n)]

    def setf(x, y, escuro):
        mod[y][x] = escuro
        func[y][x] = True

    for i in range(n):
        setf(6, i, i % 2 == 0)
        setf(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                xx, yy = cx + dx, cy + dy
                if 0 <= xx < n and 0 <= yy < n:
                    setf(xx, yy, max(abs(dx), abs(dy)) not in (2, 4))
    pos = _ALINHAMENTO[versao]
    for i, px in enumerate(pos):
        for j, py in enumerate(pos):
            if (i == 0 and j == 0) or (i == 0 and j == len(pos) - 1) or (i == len(pos) - 1 and j == 0):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    setf(px + dx, py + dy, max(abs(dx), abs(dy)) != 1)

    def formato(mascara):
        d = (_FORMATO_M << 3) | mascara
        r = d
        for _ in range(10):
            r = (r << 1) ^ ((r >> 9) * 0x537)
        b = ((d << 10) | r) ^ 0x5412
        bit = lambda i: (b >> i) & 1 == 1
        for i in range(6):
            setf(8, i, bit(i))
        setf(8, 7, bit(6)); setf(8, 8, bit(7)); setf(7, 8, bit(8))
        for i in range(9, 15):
            setf(14 - i, 8, bit(i))
        for i in range(8):
            setf(n - 1 - i, 8, bit(i))
        for i in range(8, 15):
            setf(8, n - 15 + i, bit(i))
        setf(8, n - 8, True)

    formato(0)
    if versao >= 7:
        r = versao
        for _ in range(12):
            r = (r << 1) ^ ((r >> 11) * 0x1F25)
        b = (versao << 12) | r
        for i in range(18):
            bt = (b >> i) & 1 == 1
            a, c = n - 11 + i % 3, i // 3
            setf(a, c, bt)
            setf(c, a, bt)

    i = 0
    total = len(dados) * 8
    direita = n - 1
    while direita >= 1:
        if direita == 6:
            direita = 5
        for vert in range(n):
            for j in range(2):
                x = direita - j
                subindo = ((direita + 1) & 2) == 0
                y = n - 1 - vert if subindo else vert
                if not func[y][x] and i < total:
                    mod[y][x] = (dados[i >> 3] >> (7 - (i & 7))) & 1 == 1
                    i += 1
        direita -= 2

    def aplicar(mascara):
        f = _MASCARAS[mascara]
        for y in range(n):
            for x in range(n):
                if not func[y][x] and f(x, y):
                    mod[y][x] = not mod[y][x]

    def penalidade():
        """Pontuação oficial (ISO/IEC 18004, regras N1–N4): quanto menor, mais fácil de ler."""
        p = 0
        colunas = [list(c) for c in zip(*mod)]
        padrao_a = [True, False, True, True, True, False, True, False, False, False, False]
        padrao_b = padrao_a[::-1]
        for linhas in (mod, colunas):
            for linha in linhas:
                # N1: sequências de 5 ou mais módulos da mesma cor
                seq = 1
                for k in range(1, n):
                    if linha[k] == linha[k - 1]:
                        seq += 1
                    else:
                        if seq >= 5:
                            p += 3 + (seq - 5)
                        seq = 1
                if seq >= 5:
                    p += 3 + (seq - 5)
                # N3: padrões parecidos com os quadrados de canto (1:1:3:1:1 com área clara)
                ext = [False] * 4 + linha + [False] * 4
                for k in range(len(ext) - 10):
                    trecho = ext[k:k + 11]
                    if trecho == padrao_a or trecho == padrao_b:
                        p += 40
        # N2: blocos 2x2 da mesma cor
        for y in range(n - 1):
            for x in range(n - 1):
                if mod[y][x] == mod[y][x + 1] == mod[y + 1][x] == mod[y + 1][x + 1]:
                    p += 3
        # N4: equilíbrio entre claros e escuros
        escuros = sum(sum(l) for l in mod)
        p += (abs(escuros * 20 - n * n * 10) // (n * n)) * 10
        return p

    melhor, melhor_p = 0, None
    for m in range(8):
        aplicar(m); formato(m)
        pm = penalidade()
        if melhor_p is None or pm < melhor_p:
            melhor, melhor_p = m, pm
        aplicar(m)
    aplicar(melhor); formato(melhor)
    return mod


def gerar_svg(texto, tamanho_px=260, margem=4):
    mod = gerar_matriz(texto)
    n = len(mod)
    total = n + margem * 2
    caminho = []
    for y in range(n):
        for x in range(n):
            if mod[y][x]:
                caminho.append(f"M{x + margem},{y + margem}h1v1h-1z")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" '
        f'width="{tamanho_px}" height="{tamanho_px}" shape-rendering="crispEdges">'
        f'<rect width="100%" height="100%" fill="#fff"/>'
        f'<path fill="#000" d="{"".join(caminho)}"/></svg>'
    )
