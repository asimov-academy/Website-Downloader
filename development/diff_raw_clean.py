#!/usr/bin/env python3

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import tiktoken
    TIKTOKEN_DISPONIVEL = True
except ImportError:
    TIKTOKEN_DISPONIVEL = False


def formatar_tamanho(tamanho_bytes):
    if tamanho_bytes == 0:
        return "0 B"
    unidades = ['B', 'KB', 'MB']
    i = 0
    while tamanho_bytes >= 1024 and i < len(unidades) - 1:
        tamanho_bytes /= 1024
        i += 1
    return f"{tamanho_bytes:.2f} {unidades[i]}"


def formatar_diff_bytes(diff_bytes):
    sinal = "-" if diff_bytes > 0 else ("+" if diff_bytes < 0 else "")
    return f"{sinal}{formatar_tamanho(abs(diff_bytes))}"


def formatar_diff_tokens(diff):
    if diff == 0:
        return "±0"
    return f"{diff:+,}"


def detectar_tipo(caminho):
    ext = Path(caminho).suffix.lower()
    if ext:
        return ext
    try:
        with open(caminho, 'r', encoding='utf-8', errors='ignore') as f:
            head = f.read(500).strip().lower()
            if "<html" in head or "<!doctype" in head:
                return ".html"
            if "import " in head or "const " in head or "function" in head:
                return ".js"
            if "{" in head and ":" in head:
                return ".css"
    except OSError:
        pass
    return "unk"


def analisar_arquivo(caminho, encoding_tok=None):
    try:
        tamanho = os.path.getsize(caminho)
        with open(caminho, 'r', encoding='utf-8', errors='ignore') as f:
            conteudo = f.read()
            linhas = sum(1 for line in conteudo.splitlines() if line.strip())
            palavras = len(conteudo.split())
            tokens = len(encoding_tok.encode(conteudo)) if encoding_tok else None
        return linhas, tamanho, palavras, tokens
    except OSError:
        return 0, 0, 0, None


def emitir_resultado(status, summary, input_desc, output_lines=None):
    print("=== TOOL RESULT START ===")
    print("TOOL: diff_raw_clean")
    print(f"STATUS: {status}")
    print(f"SUMMARY: {summary}")
    if input_desc is not None:
        print("---")
        print(f"INPUT: {input_desc}")
    if output_lines is not None:
        print("---")
        print("OUTPUT:")
        for line in output_lines:
            print(line)
    print("=== TOOL RESULT END ===")


def progresso(msg, quiet):
    if not quiet:
        print(msg, file=sys.stderr)


def construir_output_texto(dados, args):
    linhas = []

    if not args.summary_only:
        if dados["usar_tokens"]:
            linhas.append(
                f"{'OP':<4} {'RAW':>10}  {'CLEAN':>10}  {'Δ BYTES':>11}  "
                f"{'TOK RAW':>9}  {'TOK CLEAN':>9}  {'Δ TOK':>8}  "
                f"{'MÉTRICA':<18}  ARQUIVO"
            )
            linhas.append("─" * 120)
        else:
            linhas.append(
                f"{'OP':<4} {'TAMANHO RAW':>12}  {'TAMANHO CLEAN':>13}  "
                f"{'Δ BYTES':>12}  {'MÉTRICA':<20}  ARQUIVO"
            )
            linhas.append("─" * 95)

        for r in dados["exibir"]:
            nome = r["rel"] if args.path_mode == 'full' else Path(r["rel"]).name
            diff_fmt = formatar_diff_bytes(r["diff_b"])

            if dados["usar_tokens"]:
                tok_r_fmt = f"{r['tok_r']:,}" if r['tok_r'] is not None else "—"
                tok_c_fmt = f"{r['tok_c']:,}" if r['tok_c'] is not None else "—"
                diff_t_fmt = formatar_diff_tokens(r['diff_tok']) if r['diff_tok'] is not None else "—"
                linhas.append(
                    f"{r['emoji']:<4}"
                    f"{formatar_tamanho(r['t_r']):>10}  "
                    f"{formatar_tamanho(r['t_c']):>10}  "
                    f"{diff_fmt:>11}  "
                    f"{tok_r_fmt:>9}  "
                    f"{tok_c_fmt:>9}  "
                    f"{diff_t_fmt:>8}  "
                    f"{r['metrica']:<18}  "
                    f"{nome}"
                )
            else:
                linhas.append(
                    f"{r['emoji']:<4}"
                    f"{formatar_tamanho(r['t_r']):>12}  "
                    f"{formatar_tamanho(r['t_c']):>13}  "
                    f"{diff_fmt:>12}  "
                    f"{r['metrica']:<20}  "
                    f"{nome}"
                )

    linhas.append("─" * 60)
    linhas.append(f"📦 Total RAW:            {formatar_tamanho(dados['total_bytes_raw']):>10}")
    linhas.append(f"📦 Total CLEAN:          {formatar_tamanho(dados['total_bytes_clean']):>10}")
    linhas.append(
        f"📉 Redução (bytes):      {formatar_diff_bytes(dados['total_diff_b']):>10}  ({dados['pct_b']:.1f}%)"
    )

    if dados["usar_tokens"] and dados["total_tokens_raw"] > 0:
        linhas.append(f"🔢 Tokens RAW:           {dados['total_tokens_raw']:>10,}")
        linhas.append(f"🔢 Tokens CLEAN:         {dados['total_tokens_clean']:>10,}")
        linhas.append(
            f"📉 Redução (tokens):     {formatar_diff_tokens(dados['total_diff_tok']):>10}  ({dados['pct_tok']:.1f}%)"
        )

    linhas.append(f"📄 Arquivos analisados:  {len(dados['resultados'])}")
    linhas.append(f"🔧 Com diferença:        {dados['com_diff']}")
    linhas.append(f"❌ Sem par em /clean:    {dados['total_sem_par']}")
    return linhas


def parse_extensoes(extensoes):
    resultado = set()
    for item in extensoes.split(','):
        ext = item.strip().lower()
        if not ext:
            continue
        if not ext.startswith('.'):
            ext = f".{ext}"
        resultado.add(ext)
    return resultado


def comparar(args):
    if args.tokens and not TIKTOKEN_DISPONIVEL:
        emitir_resultado(
            "error",
            "tiktoken não está instalado para usar --tokens",
            f"raw_dir={args.raw_dir} clean_dir={args.clean_dir} tokens={args.tokens}",
            [
                "Instale com UV antes de rodar com tokens:",
                "- uv add tiktoken",
                "ou",
                "- uv pip install tiktoken",
            ],
        )
        return 1

    encoding_tok = None
    if args.tokens:
        progresso(f"Carregando encoding tiktoken ({args.token_model})...", args.quiet)
        try:
            encoding_tok = tiktoken.encoding_for_model(args.token_model)
        except Exception as e:
            emitir_resultado(
                "error",
                f"Falha ao carregar encoding do modelo {args.token_model}",
                f"raw_dir={args.raw_dir} clean_dir={args.clean_dir} token_model={args.token_model}",
                [f"Detalhe: {e}"],
            )
            return 1

    extensoes_alvo = parse_extensoes(args.extensions)
    mapa_raw = {}

    for root, _, files in os.walk(args.raw_dir):
        for f in files:
            caminho = os.path.join(root, f)
            if detectar_tipo(caminho) in extensoes_alvo:
                rel = os.path.relpath(caminho, args.raw_dir)
                mapa_raw[rel] = analisar_arquivo(caminho, encoding_tok)

    if not mapa_raw:
        emitir_resultado(
            "success",
            f"Nenhum arquivo alvo encontrado em {args.raw_dir}",
            f"raw_dir={args.raw_dir} clean_dir={args.clean_dir} extensions={sorted(extensoes_alvo)}",
            ["Nada para comparar com os filtros de extensão informados."],
        )
        return 0

    resultados = []
    total_bytes_raw = 0
    total_bytes_clean = 0
    total_tokens_raw = 0
    total_tokens_clean = 0
    total_sem_par = 0

    for rel, (l_r, t_r, p_r, tok_r) in mapa_raw.items():
        caminho_clean = os.path.join(args.clean_dir, rel)
        if not os.path.exists(caminho_clean):
            total_sem_par += 1
            continue

        l_c, t_c, p_c, tok_c = analisar_arquivo(caminho_clean, encoding_tok)
        if t_c == 0:
            continue

        total_bytes_raw += t_r
        total_bytes_clean += t_c
        if args.tokens and tok_r is not None and tok_c is not None:
            total_tokens_raw += tok_r
            total_tokens_clean += tok_c

        diff_b = t_r - t_c
        diff_l = l_c - l_r
        diff_p = p_c - p_r
        diff_tok = (tok_r - tok_c) if (args.tokens and tok_r is not None and tok_c is not None) else None

        if diff_b == 0 and diff_l == 0:
            emoji = "✅"
            metrica = "sem mudança"
        elif diff_l == 0 and diff_b > 0:
            emoji = "💎"
            metrica = f"{diff_p:+d} palavras"
        elif diff_l < 0 and diff_b > 0 and (diff_b / abs(diff_l) > 1000 if diff_l != 0 else False):
            emoji = "⚡"
            metrica = f"{diff_p:+d} palavras"
        elif diff_l < 0:
            emoji = "🧹"
            metrica = f"{diff_l:+d} linhas"
        elif diff_b < 0:
            emoji = "⚠️ "
            metrica = f"{diff_l:+d} linhas"
        else:
            emoji = "✅"
            metrica = f"{diff_l:+d} linhas"

        if diff_p == 0 and diff_b > 0 and diff_l == 0:
            metrica = f"-{diff_b} bytes"

        tem_diferenca = not (diff_b == 0 and diff_l == 0 and diff_p == 0)

        resultados.append({
            "rel": rel,
            "emoji": emoji,
            "t_r": t_r,
            "t_c": t_c,
            "diff_b": diff_b,
            "metrica": metrica,
            "tem_diferenca": tem_diferenca,
            "tok_r": tok_r,
            "tok_c": tok_c,
            "diff_tok": diff_tok,
        })

    exibir = [r for r in resultados if r["tem_diferenca"]] if args.filter == 'diff' else resultados

    if args.sort == 'impact':
        exibir.sort(key=lambda r: r["diff_b"], reverse=True)
    else:
        exibir.sort(key=lambda r: Path(r["rel"]).name.lower())

    total_diff_b = total_bytes_raw - total_bytes_clean
    pct_b = (total_diff_b / total_bytes_raw * 100) if total_bytes_raw > 0 else 0
    com_diff = sum(1 for r in resultados if r["tem_diferenca"])
    total_diff_tok = total_tokens_raw - total_tokens_clean
    pct_tok = (total_diff_tok / total_tokens_raw * 100) if total_tokens_raw > 0 else 0

    dados = {
        "usar_tokens": args.tokens,
        "resultados": resultados,
        "exibir": exibir,
        "total_bytes_raw": total_bytes_raw,
        "total_bytes_clean": total_bytes_clean,
        "total_diff_b": total_diff_b,
        "pct_b": pct_b,
        "total_tokens_raw": total_tokens_raw,
        "total_tokens_clean": total_tokens_clean,
        "total_diff_tok": total_diff_tok,
        "pct_tok": pct_tok,
        "com_diff": com_diff,
        "total_sem_par": total_sem_par,
    }

    summary = (
        f"{len(resultados)} arquivos comparados | {com_diff} com diferença | "
        f"redução bytes: {formatar_diff_bytes(total_diff_b)} ({pct_b:.1f}%)"
    )

    input_desc = (
        f"raw_dir={args.raw_dir} clean_dir={args.clean_dir} path_mode={args.path_mode} "
        f"filter={args.filter} sort={args.sort} tokens={args.tokens} format={args.format} "
        f"extensions={sorted(extensoes_alvo)}"
    )

    if args.format == 'json':
        payload = {
            "summary": {
                "arquivos_analisados": len(resultados),
                "com_diferenca": com_diff,
                "sem_par_clean": total_sem_par,
                "total_bytes_raw": total_bytes_raw,
                "total_bytes_clean": total_bytes_clean,
                "total_diff_bytes": total_diff_b,
                "pct_bytes": round(pct_b, 3),
                "tokens_ativos": args.tokens,
                "total_tokens_raw": total_tokens_raw if args.tokens else None,
                "total_tokens_clean": total_tokens_clean if args.tokens else None,
                "total_diff_tokens": total_diff_tok if args.tokens else None,
                "pct_tokens": round(pct_tok, 3) if args.tokens else None,
            },
            "results": exibir,
        }
        output_lines = [json.dumps(payload, ensure_ascii=False, indent=2)]
    else:
        output_lines = construir_output_texto(dados, args)

    emitir_resultado("success", summary, input_desc, output_lines)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description='Compara diretórios raw/clean para arquivos de front-end, com métricas de redução.'
    )
    parser.add_argument('--raw-dir', default='raw', help='Diretório base RAW (padrão: raw)')
    parser.add_argument('--clean-dir', default='clean', help='Diretório base CLEAN (padrão: clean)')
    parser.add_argument(
        '--path-mode',
        choices=['name', 'full'],
        default='name',
        help='Exibir apenas nome do arquivo (name) ou caminho relativo completo (full)'
    )
    parser.add_argument(
        '--filter',
        choices=['diff', 'all'],
        default='diff',
        help='Mostrar só arquivos com diferença (diff) ou todos (all)'
    )
    parser.add_argument(
        '--sort',
        choices=['impact', 'name'],
        default='impact',
        help='Ordenar por maior impacto em bytes (impact) ou nome do arquivo (name)'
    )
    parser.add_argument(
        '--extensions',
        default='.js,.css,.html,.mjs',
        help='Lista de extensões separadas por vírgula (ex: .js,.css,.html,.mjs)'
    )
    parser.add_argument('--tokens', action='store_true', help='Ativa análise de tokens com tiktoken')
    parser.add_argument('--token-model', default='gpt-4o', help='Modelo usado no tiktoken (padrão: gpt-4o)')
    parser.add_argument('--format', choices=['text', 'json'], default='text', help='Formato de saída')
    parser.add_argument('--summary-only', action='store_true', help='Mostra só o resumo sem tabela detalhada')
    parser.add_argument('--quiet', '-q', action='store_true', help='Suprime progresso no stderr')

    args = parser.parse_args()

    if not os.path.isdir(args.raw_dir):
        emitir_resultado(
            "error",
            f"Diretório RAW inválido: {args.raw_dir}",
            f"raw_dir={args.raw_dir} clean_dir={args.clean_dir}",
            None,
        )
        sys.exit(1)

    if not os.path.isdir(args.clean_dir):
        emitir_resultado(
            "error",
            f"Diretório CLEAN inválido: {args.clean_dir}",
            f"raw_dir={args.raw_dir} clean_dir={args.clean_dir}",
            None,
        )
        sys.exit(1)

    sys.exit(comparar(args))


if __name__ == "__main__":
    main()