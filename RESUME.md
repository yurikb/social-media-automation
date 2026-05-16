# Social Media Automation — Resumo Completo

**Localização:** `C:\Users\yurik\Code\social-media-automation`

## Stack
- Python 3.11+, httpx, whisper, ffmpeg, Pillow, rich
- CLI entry point: `python -m src.cli` ou `sma`

## Fluxo do Pipeline (`sma run`)

**Research → Curate → Clip → Enhance → Publish/Queue → Analytics**

1. **Research** — Escaneia Twitch ao vivo, cria clips via API (`POST /helix/clips`)
2. **Curate** — Pontua clips por energia de áudio + transcrição
3. **Clip** — Extrai, reframe vertical (1080x1920), remove silêncio
4. **Enhance** — Legendas (Whisper → ASS karaoke), thumbnails com texto, hook overlay (drawtext)
5. **Publish** — Publica nas plataformas habilitadas (ou enfileira pra review)
6. **Analytics** — Métricas, relatórios, detecção viral

## CLI Commands

| Comando | Descrição |
|---------|-----------|
| `sma scan` | Lista streamers ao vivo |
| `sma list-streamers` | Lista todos os streamers configurados |
| `sma run` | Executa pipeline completo |
| `sma run --dry-run` | Processa sem publicar |
| `sma run --once` | Roda um ciclo e sai (sem scheduling loop) |
| `sma preview` | Lista vídeos pendentes de aprovação |
| `sma preview <id>` | Detalhes completos de 1 vídeo |
| `sma approve <id>` | Aprova e publica 1 |
| `sma approve --all` | Aprova e publica todos |
| `sma reject <id>` | Rejeita da fila |
| `sma report` | Relatório de analytics |
| `sma auth login` | Auth Twitch (✅ OK — token salvo) |
| `sma auth youtube` | Auth YouTube (✅ OK — token salvo) |
| `sma auth instagram` | Auth Instagram (implementado, mas criação de Meta App bloqueada) |
| `sma auth test` | Testa se tokens ainda são válidos |
| `sma auth status` | Status de todas as auths |

## Streamers Monitorados

| Streamer | Prio | Estilo |
|----------|------|--------|
| alanzoka | 1 | gaming/variety |
| cellbit | 1 | gaming/RP |
| felps | 2 | gaming/variety |
| brino/brinoplay | 2 | gaming/comedy |

## Plataformas

| Plataforma | Status | Precisa de |
|------------|--------|------------|
| TikTok | `enabled: true` | TIKTOK_API_KEY, TIKTOK_API_SECRET |
| YouTube Shorts | `enabled: false` | OAuth **já autorizado** (`data/youtube_token.json`) |
| Instagram Reels | `enabled: false` | Meta Business App (criação bloqueada pelo usuário) |
| X/Twitter | `enabled: false` | X_API_KEY, X_API_SECRET |
| Threads | `enabled: false` | THREADS_ACCESS_TOKEN |

## Bug Fixes (nesta sessão)

1. **`clipping.py` start_time**: Passava Unix timestamp (`1747350436`) como `-ss` do ffmpeg em vez de `0`. Consertado — `start_time=0`, timestamp local só pro filename.
2. **`enhancement.py` ASS path (Windows)**: Paths com `C:\Users\...` quebravam filtro `ass=` porque `:` é interpretado como separador de opção. Consertado — copia `.ass` pro diretório do vídeo + usa caminho relativo + `cwd=` no subprocess.
3. **`enhancement.py` drawtext crash**: ffmpeg crashava com `drawtext=text='...'` contendo `!` (STATUS_ACCESS_VIOLATION 3221225477). Consertado — usa `textfile=_hook.txt` + `fontfile=_arial.ttf` + commas escapados (`\,`) no enable + `cwd=`.

## Progresso Atual

- **Pipeline end-to-end**: ✅ Rodou completo (2 clips: cellbit + felps) — clip → captions → hook overlay → thumbnail → queue
- **YouTube OAuth**: ✅ Autorizado, token em `data/youtube_token.json`
- **Instagram upload**: Código implementado (OAuth + Graph API Reels), mas usuário não conseguiu criar Meta Business App
- **Tests**: 65 passando
- **Dados**: `data/enhanced/` populado com vídeos legendados + hooked + thumbnails
- **Scheduled Task (Windows)**: `SMA-Pipeline` a cada 4h, roda `scripts/run_sma.ps1`

## Setup Pendente (pra publicação real)

1. Criar app TikTok Developer → TIKTOK_API_KEY + TIKTOK_API_SECRET
2. Criar Meta Business App → INSTAGRAM_APP_ID + INSTAGRAM_APP_SECRET
3. Criar app X/Twitter → X_API_KEY + X_API_SECRET
4. Supabase (opcional) → storage/logs remotos

## Estrutura de Arquivos

```
social-media-automation/
├── .env                          # Credenciais (TWITCH + YOUTUBE preenchidos)
├── .env.example                  # Template com todas as chaves
├── RESUME.md                     # Este arquivo
├── pyproject.toml                # Dependências e config
├── config/
│   ├── pipeline.json             # Config do pipeline
│   ├── platforms.json            # Plataformas (enable/disable)
│   ├── streamers.json            # Streamers monitorados
│   └── ngrok.yml                 # legal-suite
├── scripts/
│   └── run_sma.ps1               # Scheduled Task script
├── src/
│   ├── cli.py                    # CLI principal
│   ├── models/                   # Pydantic/dataclass models
│   ├── services/
│   │   ├── pipeline.py           # Orquestrador principal
│   │   ├── research.py           # Twitch scan + clip creation
│   │   ├── clip_creator.py       # Cria clips via Twitch API
│   │   ├── clipping.py           # Processamento de vídeo
│   │   ├── curation.py           # Pontuação de clips
│   │   ├── enhancement.py        # Legendas + thumbnails + hook
│   │   ├── publishing.py         # Publicação multiplataforma
│   │   ├── review.py             # Fila de aprovação
│   │   ├── analytics.py          # Métricas e relatórios
│   │   ├── twitch_auth.py        # OAuth Twitch
│   │   ├── youtube_upload.py     # Upload YouTube OAuth
│   │   └── instagram_upload.py   # Upload Instagram OAuth
│   └── utils/
│       ├── audio.py              # Análise de áudio
│       └── video.py              # Processamento de vídeo
├── data/
│   ├── clips/                    # Clips baixados
│   ├── enhanced/                 # Vídeos com legendas + hook
│   ├── pending/                  # Fila de aprovação
│   ├── raw/                      # Downloads brutos
│   ├── twitch_user_token.json    # Token Twitch
│   ├── youtube_token.json        # Token YouTube ✅
│   └── logs/                     # Logs do pipeline
└── tests/                        # 65 testes pytest
```
