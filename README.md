# dsplay — monorepo de desenvolvimento

Monorepo privado de desenvolvimento da plataforma DSPlay Analytics. Consolida todos os repositórios da organização [DSPlayAnalytics](https://github.com/DSPlayAnalytics) e o portfolio pessoal em um único workspace via **git subtree**.

---

## Estrutura

```
dsplay/
├── sdk/          # SDK browser — cliente WebSocket para ingestão de eventos
├── landing/      # Site comercial e portal do cliente (Astro 6 + Tailwind 4)
├── backend/      # API Flask — auth, ingestão, billing, exportação
├── ark/          # Infra — Nginx, Ansible, CrowdSec, Prometheus, Grafana
└── portifolio/   # Portfolio pessoal (React + Vite + Three.js) + monorepo legado
```

---

## Repositórios upstream

| Diretório | Repositório upstream | Visibilidade |
|---|---|---|
| `sdk/` | [DSPlayAnalytics/SDK](https://github.com/DSPlayAnalytics/SDK) | Público |
| `landing/` | [DSPlayAnalytics/landing](https://github.com/DSPlayAnalytics/landing) | Público |
| `backend/` | [DSPlayAnalytics/backend](https://github.com/DSPlayAnalytics/backend) | Privado |
| `ark/` | [DSPlayAnalytics/ark](https://github.com/DSPlayAnalytics/ark) | Privado |
| `portifolio/` | [danpqdan/portifolio](https://github.com/danpqdan/portifolio) | Público |

---

## Configuração inicial

Clone o monorepo e configure os remotes upstream:

```bash
git clone https://github.com/danpqdan/dsplay.git
cd dsplay

git remote add sdk      https://github.com/DSPlayAnalytics/SDK.git
git remote add landing  https://github.com/DSPlayAnalytics/landing.git
git remote add backend  https://github.com/DSPlayAnalytics/backend.git
git remote add ark      https://github.com/DSPlayAnalytics/ark.git
git remote add portifolio https://github.com/danpqdan/portifolio.git
```

---

## Fluxo de trabalho

### Buscar atualizações do upstream

Puxa as últimas mudanças de um repositório upstream para o subdiretório correspondente:

```bash
git subtree pull --prefix=sdk        sdk        main --squash
git subtree pull --prefix=landing    landing    main --squash
git subtree pull --prefix=backend    backend    main --squash
git subtree pull --prefix=ark        ark        main --squash
git subtree pull --prefix=portifolio portifolio main --squash
```

### Publicar mudanças de volta ao upstream

Após fazer commits neste monorepo, envia as mudanças de um subdiretório para o respectivo repositório upstream:

```bash
git subtree push --prefix=sdk        sdk        main
git subtree push --prefix=landing    landing    main
git subtree push --prefix=backend    backend    main
git subtree push --prefix=ark        ark        main
git subtree push --prefix=portifolio portifolio main
```

### Fluxo recomendado

```bash
# 1. Sincronizar antes de começar
git subtree pull --prefix=backend backend main --squash

# 2. Trabalhar normalmente — commits no monorepo
git add backend/arquivo.py
git commit -m "feat(backend): descrição da mudança"

# 3. Publicar de volta ao repo da org
git subtree push --prefix=backend backend main

# 4. Manter o monorepo atualizado no GitHub
git push origin main
```

> `--squash` comprime o histórico do upstream em um único commit ao importar,
> mantendo o log do monorepo limpo. Ao publicar com `push`, o histórico completo
> dos commits locais é preservado no upstream.

---

## Sobre git subtree

Diferente de submódulos (`git submodule`), subtrees copiam o código do repositório
upstream diretamente na árvore do monorepo. Não há arquivos `.gitmodules` nem
dependências de inicialização — um `git clone` simples já traz tudo pronto para uso.

A desvantagem é que `git subtree push` pode ser lento em repositórios com histórico
extenso, pois o git precisa filtrar os commits relevantes ao subdiretório.

---

## Desenvolvimento local por projeto

Cada subdiretório é um projeto independente com suas próprias dependências e comandos:

| Projeto | Runtime | Comando principal |
|---|---|---|
| `sdk/` | Node.js 20+ | `npm run dev` |
| `landing/` | Node.js 20+ | `npm run dev` |
| `backend/` | Python 3.12+ | `SECRET_KEY=test pytest` / `python app.py` |
| `ark/` | Ansible + Docker | `make -f Makefile ansible-check` |
| `portifolio/` | Node.js 20+ / Python 3.12+ | ver `portifolio/README.md` |

Consulte o `README.md` de cada subdiretório para instruções detalhadas de setup.

---

## Repositórios relacionados

- Organização: [github.com/DSPlayAnalytics](https://github.com/DSPlayAnalytics)
- Site: [dsplayground.com.br](https://dsplayground.com.br)
