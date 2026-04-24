import os
from collections import Counter
import re

def deve_ignorar(nome_item):
    ignorar = {
        'venv', 'env', '.venv', '.env', '__pycache__', '.git', '.svn', 
        '.hg', '.vscode', '.idea', '.vs', '.DS_Store', 'Thumbs.db', 
        'node_modules', 'build', 'dist', 'target', 'logs', 'log', 'tmp', 'temp'
    }
    return nome_item in ignorar or nome_item.endswith(('.pyc', '.pyo'))

def agrupar_arquivos(arquivos):
    """Agrupa arquivos por extensão ou padrões de hash (a_, d_, js_)."""
    if not arquivos:
        return []

    extensoes = Counter()
    prefixos_hash = ['a_', 'd_', 'js_', 'l_', 'p_']
    detectados_hash = set()
    vistos_unicos = []

    for f in arquivos:
        # Verifica se começa com padrões de hash conhecidos
        is_hash = False
        for p in prefixos_hash:
            if f.startswith(p):
                detectados_hash.add(f"{p}*")
                is_hash = True
                break
        
        if is_hash:
            continue

        # Separa arquivos únicos de arquivos repetitivos por extensão
        nome, ext = os.path.splitext(f)
        if ext:
            extensoes[ext] += 1
            vistos_unicos.append(f)
        else:
            vistos_unicos.append(f)

    # Regra: Se houver mais de 3 arquivos da mesma extensão, agrupa
    agrupados_ext = {ext for ext, count in extensoes.items() if count > 3}
    
    resultado = []
    # Adiciona os grupos de hash
    for h in sorted(detectados_hash):
        resultado.append(h)

    # Adiciona os grupos de extensão
    for ext in sorted(agrupados_ext):
        resultado.append(f"*{ext}")

    # Adiciona arquivos únicos (que não foram agrupados)
    for f in vistos_unicos:
        _, ext = os.path.splitext(f)
        if ext not in agrupados_ext:
            resultado.append(f)

    return sorted(list(set(resultado)))

def gerar_arvore_otimizada(caminho, prefixo="", linhas=None):
    if linhas is None:
        linhas = []

    try:
        itens_todos = sorted(os.listdir(caminho))
        itens_filtrados = [i for i in itens_todos if not deve_ignorar(i)]
    except PermissionError:
        return linhas

    # Lógica especial para Clean vs Raw
    if os.path.basename(caminho).lower() == "clean":
        parent = os.path.dirname(caminho)
        if "raw" in os.listdir(parent):
            linhas[-1] = linhas[-1] + " (Igual a raw)"
            return linhas

    subpastas = [i for i in itens_filtrados if os.path.isdir(os.path.join(caminho, i))]
    arquivos = [i for i in itens_filtrados if os.path.isfile(os.path.join(caminho, i))]

    # Processa arquivos com a nova lógica de agrupamento
    arquivos_processados = agrupar_arquivos(arquivos)
    
    # Lista final para exibir (pastas primeiro, depois arquivos agrupados)
    todos_itens = [(p, True) for p in subpastas] + [(f, False) for f in arquivos_processados]
    
    total = len(todos_itens)
    for i, (item, is_dir) in enumerate(todos_itens):
        ultimo = i == total - 1
        marcador = "└──" if ultimo else "├──"
        
        caminho_completo = os.path.join(caminho, item) if is_dir else ""
        
        if is_dir:
            linhas.append(f"{prefixo}{marcador} {item}/")
            novo_prefixo = prefixo + ("    " if ultimo else "│   ")
            gerar_arvore_otimizada(caminho_completo, novo_prefixo, linhas)
        else:
            linhas.append(f"{prefixo}{marcador} {item}")

    return linhas

def main():
    caminho = "downloads"
    
    if os.path.isdir(caminho):
        abs_path = os.path.abspath(caminho)
        print(f"\nGerando estrutura otimizada para: {abs_path}")
        
        linhas = [abs_path]
        linhas = gerar_arvore_otimizada(caminho, linhas=linhas)

        print("\n".join(linhas))
    else:
        print("Caminho inválido.")

if __name__ == "__main__":
    main()
