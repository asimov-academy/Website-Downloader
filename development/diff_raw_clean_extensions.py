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


DEFAULT_EXTENSIONS = '.js,.css,.html,.mjs,.json,.webmanifest'
JS_EXTENSIONS = {'.js', '.mjs', '.cjs'}
DATA_EXTENSIONS = {'.json', '.webmanifest'}
MARKUP_STYLE_EXTENSIONS = {'.html', '.css'}
VENDOR_MARKERS = (
    '/vendor/', '/vendors/', '/lib/', '/libs/', '/third_party/', '/third-party/',
    '/polyfill', '/polyfills', '/externals/', '/plugins/', '/chunks/vendor',
    'vendor.', 'vendors.', 'polyfill.', 'polyfills.', 'runtime.', 'webpack',
    'jquery', 'react', 'vue', 'svelte', 'gsap', 'lodash', 'draco', 'basis',
    'vosk', 'qrious',
)
SEMANTIC_BUCKET_LABELS = {
    'markup_style': 'markup_style',
    'data_structured': 'data_structured',
    'js_app_readable': 'js_app_readable',
    'js_app_minified': 'js_app_minified',
    'js_vendor_readable': 'js_vendor_readable',
    'js_vendor_minified': 'js_vendor_minified',
}
PRIORITY_BUCKETS = {'markup_style', 'data_structured', 'js_app_readable'}
SUPPORT_BUCKETS = {'js_app_minified', 'js_vendor_readable', 'js_vendor_minified'}


def formatar_tamanho(tamanho_bytes):
    if tamanho_bytes == 0:
        return '0 B'
    unidades = ['B', 'KB', 'MB', 'GB']
    i = 0
    valor = float(tamanho_bytes)
    while valor >= 1024 and i < len(unidades) - 1:
        valor /= 1024
        i += 1
    return f'{valor:.2f} {unidades[i]}'


def formatar_diff_bytes(diff_bytes):
    if diff_bytes == 0:
        return '±0 B'
    sinal = '-' if diff_bytes > 0 else '+'
    return f'{sinal}{formatar_tamanho(abs(diff_bytes))}'


def formatar_diff_num(diff):
    if diff == 0:
        return '±0'
    return f'{diff:+,}'


def progresso(msg, quiet):
    if not quiet:
        print(msg, file=sys.stderr)


def emitir_resultado(status, summary, input_desc, output_lines=None):
    print('=== TOOL RESULT START ===')
    print('TOOL: diff_raw_clean_extensions')
    print(f'STATUS: {status}')
    print(f'SUMMARY: {summary}')
    if input_desc is not None:
        print('---')
        print(f'INPUT: {input_desc}')
    if output_lines is not None:
        print('---')
        print('OUTPUT:')
        for line in output_lines:
            print(line)
    print('=== TOOL RESULT END ===')


def parse_extensoes(extensoes):
    resultado = set()
    for item in extensoes.split(','):
        ext = item.strip().lower()
        if not ext:
            continue
        if not ext.startswith('.'):
            ext = f'.{ext}'
        resultado.add(ext)
    return resultado


def detectar_tipo(caminho):
    ext = Path(caminho).suffix.lower()
    if ext:
        return ext
    try:
        with open(caminho, 'r', encoding='utf-8', errors='ignore') as f:
            head = f.read(500).strip().lower()
            if '<html' in head or '<!doctype' in head:
                return '.html'
            if 'import ' in head or 'const ' in head or 'function' in head:
                return '.js'
            if '{' in head and ':' in head:
                return '.json'
    except OSError:
        pass
    return 'unk'


def media_linhas_nao_vazias(linhas):
    if not linhas:
        return 0
    return sum(len(linha) for linha in linhas) / len(linhas)


def detectar_js_minificado(rel_path, conteudo):
    rel = rel_path.lower()
    nome = Path(rel_path).name.lower()
    if '.min.' in nome or nome.endswith('.min.js') or nome.endswith('.min.mjs'):
        return True

    linhas = [linha for linha in conteudo.splitlines() if linha.strip()]
    if not linhas:
        return False

    max_linha = max(len(linha) for linha in linhas)
    media_linha = media_linhas_nao_vazias(linhas)
    linhas_muito_longas = sum(1 for linha in linhas if len(linha) >= 200)
    proporcao_longas = linhas_muito_longas / len(linhas)

    if max_linha >= 1200:
        return True
    if media_linha >= 220 and len(linhas) >= 8:
        return True
    if proporcao_longas >= 0.35 and len(linhas) >= 8:
        return True
    if media_linha >= 120 and max_linha >= 600 and '/assets/js/' in rel:
        return True
    return False


def detectar_js_vendor(rel_path):
    rel = '/' + rel_path.replace('\\', '/').lower().lstrip('/')
    return any(marker in rel for marker in VENDOR_MARKERS)


def classificar_bucket(rel_path, ext, conteudo, view):
    if view == 'extensions':
        return ext

    if ext in MARKUP_STYLE_EXTENSIONS:
        return 'markup_style'
    if ext in DATA_EXTENSIONS:
        return 'data_structured'
    if ext in JS_EXTENSIONS:
        vendor = detectar_js_vendor(rel_path)
        minificado = detectar_js_minificado(rel_path, conteudo)
        if vendor and minificado:
            return 'js_vendor_minified'
        if vendor:
            return 'js_vendor_readable'
        if minificado:
            return 'js_app_minified'
        return 'js_app_readable'
    return ext


def analisar_arquivo(caminho, base_dir, view, encoding_tok=None):
    try:
        tamanho = os.path.getsize(caminho)
        with open(caminho, 'r', encoding='utf-8', errors='ignore') as f:
            conteudo = f.read()
    except OSError:
        return None

    rel_path = os.path.relpath(caminho, base_dir).replace(os.sep, '/')
    ext = detectar_tipo(caminho)
    linhas = sum(1 for line in conteudo.splitlines() if line.strip())
    palavras = len(conteudo.split())
    tokens = len(encoding_tok.encode(conteudo)) if encoding_tok else 0
    bucket = classificar_bucket(rel_path, ext, conteudo, view)

    return {
        'bucket': bucket,
        'rel_path': rel_path,
        'ext': ext,
        'arquivos': 1,
        'bytes': tamanho,
        'linhas': linhas,
        'palavras': palavras,
        'tokens': tokens,
    }


def somar_metricas(destino, origem):
    destino['arquivos'] += origem['arquivos']
    destino['bytes'] += origem['bytes']
    destino['linhas'] += origem['linhas']
    destino['palavras'] += origem['palavras']
    destino['tokens'] += origem['tokens']


def coletar_metricas(base_dir, extensoes_alvo, view, encoding_tok=None):
    agregados = {}
    for root, _, files in os.walk(base_dir):
        for nome in files:
            caminho = os.path.join(root, nome)
            ext = detectar_tipo(caminho)
            if ext not in extensoes_alvo:
                continue

            metricas = analisar_arquivo(caminho, base_dir, view, encoding_tok)
            if not metricas:
                continue

            bucket = metricas['bucket']
            item = agregados.setdefault(bucket, {
                'bucket': bucket,
                'arquivos': 0,
                'bytes': 0,
                'linhas': 0,
                'palavras': 0,
                'tokens': 0,
            })
            somar_metricas(item, metricas)

    return agregados


def build_empty_metrics():
    return {'arquivos': 0, 'bytes': 0, 'linhas': 0, 'palavras': 0, 'tokens': 0}


def montar_resultados(raw_agregado, clean_agregado):
    buckets = sorted(set(raw_agregado) | set(clean_agregado))
    resultados = []
    for bucket in buckets:
        raw = raw_agregado.get(bucket, build_empty_metrics())
        clean = clean_agregado.get(bucket, build_empty_metrics())
        resultados.append({
            'bucket': bucket,
            'label': SEMANTIC_BUCKET_LABELS.get(bucket, bucket),
            'arquivos_raw': raw['arquivos'],
            'arquivos_clean': clean['arquivos'],
            'bytes_raw': raw['bytes'],
            'bytes_clean': clean['bytes'],
            'diff_bytes': raw['bytes'] - clean['bytes'],
            'linhas_raw': raw['linhas'],
            'linhas_clean': clean['linhas'],
            'diff_linhas': raw['linhas'] - clean['linhas'],
            'palavras_raw': raw['palavras'],
            'palavras_clean': clean['palavras'],
            'diff_palavras': raw['palavras'] - clean['palavras'],
            'tokens_raw': raw['tokens'],
            'tokens_clean': clean['tokens'],
            'diff_tokens': raw['tokens'] - clean['tokens'],
        })
    return resultados


def filtrar_resultados(resultados, filtro):
    if filtro != 'diff':
        return resultados
    return [
        item for item in resultados
        if any((
            item['arquivos_raw'] != item['arquivos_clean'],
            item['bytes_raw'] != item['bytes_clean'],
            item['linhas_raw'] != item['linhas_clean'],
            item['tokens_raw'] != item['tokens_clean'],
        ))
    ]


def ordenar_resultados(resultados, sort_mode):
    if sort_mode == 'impact':
        resultados.sort(key=lambda item: item['diff_bytes'], reverse=True)
    else:
        resultados.sort(key=lambda item: item['label'])


def resumir_totais(resultados):
    total_raw = sum(item['bytes_raw'] for item in resultados)
    total_clean = sum(item['bytes_clean'] for item in resultados)
    total_diff = total_raw - total_clean
    pct_bytes = (total_diff / total_raw * 100) if total_raw else 0
    return total_raw, total_clean, total_diff, pct_bytes


def resumir_tokens(resultados):
    total_raw = sum(item['tokens_raw'] for item in resultados)
    total_clean = sum(item['tokens_clean'] for item in resultados)
    total_diff = total_raw - total_clean
    pct = (total_diff / total_raw * 100) if total_raw else 0
    return total_raw, total_clean, total_diff, pct


def construir_output_texto(resultados, usar_tokens, summary_only, view):
    linhas = []
    label_header = 'EXT' if view == 'extensions' else 'GRUPO'

    if not summary_only:
        if usar_tokens:
            linhas.append(
                f'{label_header:<20} {"ARQ RAW":>8}  {"ARQ CLEAN":>9}  {"BYTES RAW":>11}  '
                f'{"BYTES CLEAN":>12}  {"Δ BYTES":>11}  {"LIN RAW":>9}  {"LIN CLEAN":>10}  '
                f'{"Δ LIN":>8}  {"TOK RAW":>10}  {"TOK CLEAN":>11}  {"Δ TOK":>10}'
            )
            linhas.append('─' * 157)
        else:
            linhas.append(
                f'{label_header:<20} {"ARQ RAW":>8}  {"ARQ CLEAN":>9}  {"BYTES RAW":>11}  '
                f'{"BYTES CLEAN":>12}  {"Δ BYTES":>11}  {"LIN RAW":>9}  {"LIN CLEAN":>10}  {"Δ LIN":>8}'
            )
            linhas.append('─' * 117)

        for item in resultados:
            base = (
                f"{item['label']:<20} "
                f"{item['arquivos_raw']:>8,}  "
                f"{item['arquivos_clean']:>9,}  "
                f"{formatar_tamanho(item['bytes_raw']):>11}  "
                f"{formatar_tamanho(item['bytes_clean']):>12}  "
                f"{formatar_diff_bytes(item['diff_bytes']):>11}  "
                f"{item['linhas_raw']:>9,}  "
                f"{item['linhas_clean']:>10,}  "
                f"{formatar_diff_num(item['diff_linhas']):>8}"
            )
            if usar_tokens:
                base += (
                    f"  {item['tokens_raw']:>10,}  "
                    f"{item['tokens_clean']:>11,}  "
                    f"{formatar_diff_num(item['diff_tokens']):>10}"
                )
            linhas.append(base)

    linhas.append('─' * 60)
    total_raw, total_clean, total_diff, pct_bytes = resumir_totais(resultados)
    linhas.append(f'📦 Total RAW:            {formatar_tamanho(total_raw):>10}')
    linhas.append(f'📦 Total CLEAN:          {formatar_tamanho(total_clean):>10}')
    linhas.append(f'📉 Redução (bytes):      {formatar_diff_bytes(total_diff):>10}  ({pct_bytes:.1f}%)')
    linhas.append(f'🧩 Grupos analisados:    {len(resultados):>10}')
    linhas.append(f"📄 Arquivos RAW:         {sum(item['arquivos_raw'] for item in resultados):>10,}")
    linhas.append(f"📄 Arquivos CLEAN:       {sum(item['arquivos_clean'] for item in resultados):>10,}")
    linhas.append(f"📝 Linhas RAW:           {sum(item['linhas_raw'] for item in resultados):>10,}")
    linhas.append(f"📝 Linhas CLEAN:         {sum(item['linhas_clean'] for item in resultados):>10,}")

    if usar_tokens:
        total_tokens_raw, total_tokens_clean, total_tokens_diff, pct_tokens = resumir_tokens(resultados)
        linhas.append(f'🔢 Tokens RAW:           {total_tokens_raw:>10,}')
        linhas.append(f'🔢 Tokens CLEAN:         {total_tokens_clean:>10,}')
        linhas.append(f'📉 Redução (tokens):     {formatar_diff_num(total_tokens_diff):>10}  ({pct_tokens:.1f}%)')

    if view == 'semantic':
        priority_rows = [item for item in resultados if item['bucket'] in PRIORITY_BUCKETS]
        support_rows = [item for item in resultados if item['bucket'] in SUPPORT_BUCKETS]

        linhas.append('─' * 60)
        linhas.append('🎯 Leitura prioritária para AI')
        linhas.append(
            f"RAW: {sum(item['tokens_raw'] for item in priority_rows):,} tok | "
            f"CLEAN: {sum(item['tokens_clean'] for item in priority_rows):,} tok"
            if usar_tokens else
            f"RAW: {formatar_tamanho(sum(item['bytes_raw'] for item in priority_rows))} | "
            f"CLEAN: {formatar_tamanho(sum(item['bytes_clean'] for item in priority_rows))}"
        )
        linhas.append('🧱 Suporte / runtime / ruído')
        linhas.append(
            f"RAW: {sum(item['tokens_raw'] for item in support_rows):,} tok | "
            f"CLEAN: {sum(item['tokens_clean'] for item in support_rows):,} tok"
            if usar_tokens else
            f"RAW: {formatar_tamanho(sum(item['bytes_raw'] for item in support_rows))} | "
            f"CLEAN: {formatar_tamanho(sum(item['bytes_clean'] for item in support_rows))}"
        )

    return linhas


def comparar(args):
    if args.tokens and not TIKTOKEN_DISPONIVEL:
        emitir_resultado(
            'error',
            'tiktoken não está instalado para usar --tokens',
            f'raw_dir={args.raw_dir} clean_dir={args.clean_dir} tokens={args.tokens}',
            [
                'Instale com UV antes de rodar com tokens:',
                '- uv add tiktoken',
            ],
        )
        return 1

    encoding_tok = None
    if args.tokens:
        progresso(f'Carregando encoding tiktoken ({args.token_model})...', args.quiet)
        try:
            encoding_tok = tiktoken.encoding_for_model(args.token_model)
        except Exception as e:
            emitir_resultado(
                'error',
                f'Falha ao carregar encoding do modelo {args.token_model}',
                f'raw_dir={args.raw_dir} clean_dir={args.clean_dir} token_model={args.token_model}',
                [f'Detalhe: {e}'],
            )
            return 1

    extensoes_alvo = parse_extensoes(args.extensions)
    progresso('Coletando métricas agregadas do raw...', args.quiet)
    raw_agregado = coletar_metricas(args.raw_dir, extensoes_alvo, args.view, encoding_tok)
    progresso('Coletando métricas agregadas do clean...', args.quiet)
    clean_agregado = coletar_metricas(args.clean_dir, extensoes_alvo, args.view, encoding_tok)

    resultados = montar_resultados(raw_agregado, clean_agregado)
    if not resultados:
        emitir_resultado(
            'success',
            'Nenhuma extensão alvo encontrada',
            (
                f'raw_dir={args.raw_dir} clean_dir={args.clean_dir} '
                f'view={args.view} extensions={sorted(extensoes_alvo)}'
            ),
            ['Nada para comparar com os filtros de extensão informados.'],
        )
        return 0

    resultados = filtrar_resultados(resultados, args.filter)
    ordenar_resultados(resultados, args.sort)

    total_raw, total_clean, total_diff, pct_b = resumir_totais(resultados)
    summary = (
        f'{len(resultados)} grupos comparados | '
        f'redução bytes: {formatar_diff_bytes(total_diff)} ({pct_b:.1f}%)'
    )

    input_desc = (
        f'raw_dir={args.raw_dir} clean_dir={args.clean_dir} '
        f'view={args.view} filter={args.filter} sort={args.sort} '
        f'tokens={args.tokens} format={args.format} '
        f'extensions={sorted(extensoes_alvo)}'
    )

    if args.format == 'json':
        total_tokens_raw, total_tokens_clean, total_tokens_diff, pct_tokens = resumir_tokens(resultados)
        output_lines = [json.dumps({
            'summary': {
                'view': args.view,
                'grupos_analisados': len(resultados),
                'total_bytes_raw': total_raw,
                'total_bytes_clean': total_clean,
                'total_diff_bytes': total_diff,
                'pct_bytes': round(pct_b, 3),
                'tokens_ativos': args.tokens,
                'total_tokens_raw': total_tokens_raw,
                'total_tokens_clean': total_tokens_clean,
                'total_diff_tokens': total_tokens_diff,
                'pct_tokens': round(pct_tokens, 3),
            },
            'results': resultados,
        }, ensure_ascii=False, indent=2)]
    else:
        output_lines = construir_output_texto(resultados, args.tokens, args.summary_only, args.view)

    emitir_resultado('success', summary, input_desc, output_lines)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description=(
            'Compara raw/ e clean/ por extensão agregada ou por visão semântica, '
            'somando arquivos, linhas, bytes, palavras e tokens.'
        )
    )
    parser.add_argument('--raw-dir', default='raw', help='Diretório base RAW (padrão: raw)')
    parser.add_argument('--clean-dir', default='clean', help='Diretório base CLEAN (padrão: clean)')
    parser.add_argument(
        '--view',
        choices=['extensions', 'semantic'],
        default='extensions',
        help='Comparar por extensão agregada ou por buckets semânticos'
    )
    parser.add_argument(
        '--filter',
        choices=['diff', 'all'],
        default='diff',
        help='Mostrar só grupos com diferença (diff) ou todos (all)'
    )
    parser.add_argument(
        '--sort',
        choices=['impact', 'name'],
        default='impact',
        help='Ordenar por maior impacto em bytes (impact) ou nome do grupo/extensão (name)'
    )
    parser.add_argument(
        '--extensions',
        default=DEFAULT_EXTENSIONS,
        help='Lista de extensões separadas por vírgula (ex: .js,.css,.html,.json)'
    )
    parser.add_argument('--tokens', action='store_true', help='Ativa análise de tokens com tiktoken')
    parser.add_argument('--token-model', default='gpt-4o', help='Modelo usado no tiktoken (padrão: gpt-4o)')
    parser.add_argument('--format', choices=['text', 'json'], default='text', help='Formato de saída')
    parser.add_argument('--summary-only', action='store_true', help='Mostra só o resumo sem tabela detalhada')
    parser.add_argument('--quiet', '-q', action='store_true', help='Suprime progresso no stderr')
    args = parser.parse_args()

    if not os.path.isdir(args.raw_dir):
        emitir_resultado(
            'error',
            f'Diretório RAW inválido: {args.raw_dir}',
            f'raw_dir={args.raw_dir} clean_dir={args.clean_dir}',
            None,
        )
        sys.exit(1)

    if not os.path.isdir(args.clean_dir):
        emitir_resultado(
            'error',
            f'Diretório CLEAN inválido: {args.clean_dir}',
            f'raw_dir={args.raw_dir} clean_dir={args.clean_dir}',
            None,
        )
        sys.exit(1)

    sys.exit(comparar(args))


if __name__ == '__main__':
    main()
