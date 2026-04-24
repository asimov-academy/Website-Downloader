# Guia Prático de Engenharia de Prompts

Um manual direto para criar prompts eficazes, baseado em documentações oficial e análises de muitos prompts de ferramentas de IA autônomas.

## 1. Fundamentos e Hierarquia

### Sequência Recomendada

Temos que estabelecer uma ordem específica para aplicar técnicas de prompt engineering. Essa hierarquia funciona como uma escada - cada degrau constrói sobre o anterior.

**1º Estrutura** - Use tags XML para organizar informações complexas.
**2º Papel** - Defina um papel específico para a IA assumir colocando contextos relevântes para a tarefa que vai ser executada.
**3º Exemplos** - Escreva qual é o problema ou necessidade e o padrão desejado.  
**4º Clareza** - Seja direto e específico sobre o que você quer que o agente faça.
**5º Controle de saída** - As ordens devem ser diferetas, indicando uma ordem lógica e voltada para a programação com o resultado que queremos atingir, uma definição do que é sucesso para o problema proposto.
**6: Encadeamento** - Divida tarefas complexas em etapas mas não passe de 7, e sempre diga para ele fazer todas, essas tarefas devem resolver todos os problemas.

### Exemplo Avançado de Prompt

**Prompt estruturado (eficaz):**

```markdown

<role>

Você é um engenheiro software sênior que teve a experiência de começar trabalhado em uma empresa de software pequena de acompanhar o crescimento dela até o ponto mais alto que já era o foco. Uma empresa que desde o inicio, queria ser referência, pensando em consquistar clientes pela qualidade, exclusividade e método ágel. Você prioriza soluções que funcionam para qualquer outro sistema sobre abstrações que complicam e só funcionam em casos específicos. Sempre pensa em como deixar algo mais fácil para poder reutilizar, ser mais intuitivo e fácil não só para o usuário final, mas também para os desenvolvedores e gestores da empresa.

# TODO: Preencha essa parte com a função específica que ele vai exercer em cada caso.

</role>

<project_context>

# TODO: Referenciar arquivos e explicar de forma breve, colocando a estrutura de pastas simples usando o script "/opt/tools/paths/get_describe_paths.py" 

</project_context>

<architecture>

O sistema funciona em 3 pilares ...

1- ...
2- ...
3- ...

**Estrura de Pastas ...:**...
</architecture>

<status>

Estamos na fase de manutenção e correção de bugs que estão documentados em ...
Sempre que corrigirmos algo, devemos atualizar o ... NÃO MARQUE NADA COMO RESOLVIDO, em nenhum arquivo, a não ser que eu tiver dito que foi resolvido.
Atualmente o arquivo ... está muito grande, com mais de ..., e também temos funcões sem serem utilizadas no projeto.

</status>

<problem>

Ao listar os arquivos de ... na sessão, temos vários erros. Para ter mais conhecimento leia o arquivo ... na no tópico "## Bugs Conhecidos", o console e os logs do servidor mostram erros críticos e para um deles, nenhum arquivo foi baixado, todos os logs estão no arquivo ...

</problem>

<task>

Siga rigorosamente esta ordem de execução para resolver os problemas:

1- ...
2- ...
3- ...
4- Faça os testes, caso ainda não funcionar, volte o processo e só pare quando esgotar as possibilidades me trazendo um resumo do que não deu certo. Mas se tiver dado certo, me diga como analisar e confirmar se está funcionando.

</task>

<validation>

### Casos de Uso

...

### Corrigindo Problemas

...

### Escolha X ao invés de Y

...

</validation>

<constraints>

### Abordagem Técnica e Runtime

- NÃO faça x ...
- NÃO faça y ...
- NÃO faça z ...

### Estrutura de Arquivos e Organização

- NÃO altere a estrutura de pastas ou nomes de arquivos.
- NÃO crie arquivos auxiliares (scripts bash, arquivos de texto, configs extras, docs intermediários) sem eu pedir explicitamente.
- NÃO crie nenhum arquivo de texto ou algo no projeto que seja de documentação sem pedir para mim.

### Manipulação de Código e Estilos

- NÃO faça x ...
- NÃO faça y ...
- NÃO faça z ...

### Protocolo de Comunicação e Fluxo

- NÃO repita código que já foi mostrado antes.
- NÃO explique conceitos já discutidos.
- NÃO re-leia arquivos que já foram lidos.

</constraints>

<techniques>

Aqui está a lista de regras e técnicas que você DEVE usar para garantir que vai conseguir trabalhar bem com o projeto atual e ter resultados melhores:

- Utilize o UV para fazer os testes e mantenha o ambiente virtual, não instale nada no meu python do sistema.
- Utilize o Docker com Docker compose usando as regras do descritas no arquivo ...

### Comunicação

- Ao iniciar cada fase, diga o que vai fazer em 1-2 frases.
- Ao concluir, diga o que fez e qual o próximo passo.
- Se encontrar uma decisão arquitetural ambígua, informe o que escolheu e por quê.
- Economize contexto: não repita código que já foi mostrado, não explique conceitos já discutidos.

### Autonomia

- Rode TODOS os comandos necessários você mesmo (install, test, build). Não me peça para rodar manualmente, a não ser que só eu tenha permissão para fazer isso.
- Se um comando falhar, analise o erro e tente resolver. Só escale para o usuário quando esgotar alternativas.
- Ao concluir cada etapa, rode um teste para confirmar que funciona.

### Ambiente

- Sempre pergunte dando sugestão de commit (sem push).
- Limpe os "__pycache__" antes de rodar testes para evitar bugs de cache.
- Mantenha o "pyproject.toml" atualizado se adicionar dependências.

Comandos:deactivate
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
uv sync
### Estratégia de Navegação e Busca (Context Economy)

Você DEVE economizar tokens de contexto. Siga estas regras estritas para exploração:

1. **Exclusão Mandatória**:
   - Ao usar comandos como `grep`, `find` ou `ls -R`, você OBRIGATORIAMENTE deve excluir diretórios de infraestrutura e dados.
   - **Lista de Exclusão**: `.venv`, `.git`, `__pycache__`, `node_modules`, `downloads` (conteúdo baixado), `.pytest_cache`.

2. **Comandos Recomendados**:
   - Para listar estrutura: `find . -maxdepth 3 -not -path '*/.*' -not -path './downloads*'`
   - Para buscar texto/código: `grep -r "termo_busca" . --exclude-dir={.venv,.git,__pycache__,downloads,node_modules}`
   - Para listar apenas arquivos Python: `find . -name "*.py" -not -path "./.venv/*"`

3. **Leitura Inteligente**:
   - Nunca leia um arquivo inteiro se você só precisa de uma função.

4. **Ambiente Python**:
   - Utilize o gerenciador `uv` para rodar comandos: `uv run python script.py`.
   - Mantenha o ambiente virtual isolado e não instale pacotes no sistema global.

### Comandos e Estratégia de Busca (Context Economy)

Você DEVE economizar tokens e ser preciso. Não leia arquivos desnecessários.

1. **Investigação nos Logs**:
   - Para entender o erro sem ler o arquivo gigante:
     `grep -C 5 "SyntaxError" LOGS.md`
     `grep "404" LOGS.md | head -n 20`

2. **Navegação no Projeto (Ignorando Lixo)**:
   - A pasta `downloads/` contém milhares de arquivos que vão estourar seu contexto. **JAMAIS** liste ou dê grep nela sem filtros.
   - Para encontrar arquivos de código do projeto:
     `find . -maxdepth 2 -name "*.py" -not -path "*/.*"`
   - Para buscar onde uma função é definida:
     `grep -r "_global_url_rewrite" . --exclude-dir={downloads,.venv,.git,__pycache__}`

3. **Leitura de Arquivos**:
   - Use `read_file` apenas nos arquivos `.py` do sistema (`post_process.py`, `clean.py`).
   - Não tente ler os arquivos `.js` ou `.html` minificados que estão dentro de `downloads/` a menos que use `head -c 500` para ver apenas o cabeçalho.

</techniques>

```

### Modularização por função

Organize o prompt em blocos funcionais que podem ser reutilizados:

**Módulo de Contexto:**
```markdown
<context>

<company>

Startup de tecnologia financeira

</company>

<audience>

Investidores série A

</audience>

<goal>

Captação de R$ 5 milhões

</goal>

</context>
```

**Módulo de Restrições:**
```markdown
<constraints>

- **length**: Máximo 2 páginas.
- **tone**: Profissional, confiante, baseado em dados.
- **avoid**: Jargão técnico excessivo, promessas irrealistas.

</constraints>
```

**Módulo de Validação:**
```markdown
<validation>

Antes de finalizar, verifique se a resposta:
- Responde diretamente à pergunta principal
- Inclui dados quantitativos quando relevante
- Mantém o tom apropriado para o público

</validation>
```

## 2. Lógica Condicional e Gatilhos

### Sistema de palavras-chave revelado

Os agentes usam palavras específicas para ativar diferentes modos de processamento:

| Palavra-chave | Efeito ativado | Exemplo de uso |
|---------------|----------------|-----------------|
| "analyze" | Modo analítico profundo | "Analyze this financial report" |
| "comprehensive" | Pesquisa extensiva (5+ fontes) | "Comprehensive market analysis" |
| "deep dive" | Força mínimo 5 tool calls | "Deep dive into competitor strategies" |
| "step-by-step" | Chain of thought detalhado | "Step-by-step problem solving" |
| "compare" | Análise comparativa estruturada | "Compare these three solutions" |
| "evaluate" | Critérios de avaliação explícitos | "Evaluate the best approach" |

### Implementando lógica condicional

Use condicionais para criar prompts que se adaptam ao contexto:

```markdown
<conditional_logic>

SE o texto for menor que 500 palavras:
  - Forneça análise concisa em 3 pontos principais
  
SE o texto for entre 500-2000 palavras:
  - Crie resumo executivo + análise detalhada
  
SE o texto for maior que 2000 palavras:
  - Divida em seções temáticas + síntese final

</conditional_logic>
```

### Gatilhos para ferramentas específicas

```markdown

<tool_triggers>

SE pergunta sobre dados atuais: usar web_search que fica em ...;
SE precisa de documentos internos: usar google_drive_search usando a função x do arquivo y;
SE análise requer múltiplas fontes: encadear web_search + web_fetch;

</tool_triggers>
```

## 3. Técnicas Avançadas

### Chain of Thought estruturado

Guie o raciocínio com estrutura clara:

```markdown
<thinking_process>

1º Identificar o problema central;
2º Listar informações disponíveis;
3º Identificar lacunas de conhecimento;
4º Propor soluções alternativas;
5º Avaliar prós e contras de cada opção;
6º Recomendar melhor caminho;

</thinking_process>
```

### Prefilling estratégico

O prefilling orienta o formato e tom da resposta desde o início:

**Para análises técnicas:**
```
Com base na análise dos dados de x, identifique três padrões principais:

1. [IA continua automaticamente]
```

**Para relatórios executivos:**
```
**Sumário Executivo**

A análise de mercado revela oportunidades significativas, especificamente:
```

**Para código comentado:**
```
# Solução otimizada para o problema de classificação
# Estratégia: usar algoritmo híbrido para melhor performance

[IA completa o código]
```

### Multishot adaptativo

Crie exemplos que se adaptam ao contexto específico.

### Sistema de feedback interno

Implemente validação automática dentro do prompt:

```markdown
<self_validation>

Após gerar a resposta, verifique:
- Responde diretamente à pergunta principal?
- Inclui evidências ou dados de suporte?  
- Mantém tom apropriado para o público?
- Está dentro do limite de palavras especificado?
- Evita informações potencialmente desatualizadas?

Se qualquer item falhar, revise a resposta antes de enviá-la.

</self_validation>
```

## 4. Otimização e Melhores Práticas

### Princípios para prompts eficazes

**Especificidade vence generalidade:** "Crie 5 headlines para anúncio do Facebook vendendo curso de Excel para contadores" é melhor que "ajude com marketing";

**Contexto reduz ambiguidade:** Sempre inclua informações sobre público, objetivo e restrições relevantes;

**Exemplos aceleram compreensão:** Dois exemplos bem escolhidos valem mais que dez instruções abstratas;

**Validação previne erros:** Inclua critérios de qualidade dentro do próprio prompt;

### Checklist de revisão

Antes de usar um prompt complexo, verifique:

**Estrutura:**
- Papel do agente está claro?
- Tarefa principal está bem definida?
- Formato de saída está especificado?

**Conteúdo:**
- Exemplos são representativos e úteis?
- Instruções são acionáveis?
- Critérios de sucesso estão explícitos?

**Eficiência:**
- Prompt está conciso sem perder clareza?
- Tags XML estão organizadas logicamente?

### Troubleshooting comum

**Problema:** Respostas muito vagas ou genéricas;
**Solução:** Adicione mais contexto específico e exemplos concretos;

**Problema:** IA não segue o formato solicitado;
**Solução:** Use prefilling para começar a resposta no formato correto;

**Problema:** Informações irrelevantes na resposta;
**Solução:** Seja mais específico sobre o que deve ser incluído/excluído;

**Problema:** Respostas inconsistentes entre tentativas;
**Solução:** Adicione mais exemplos ou refine as instruções para reduzir ambiguidade;

## Conclusão

A engenharia de prompts eficaz combina estrutura clara, exemplos específicos e validação contínua. Use este guia como base de conhecimento modular: copie os templates relevantes, adapte para seu contexto específico e refine baseado nos resultados.

O objetivo é estabelecer um processo sistemático para iterar e melhorar continuamente a qualidade das interações com Agentes de IA.
