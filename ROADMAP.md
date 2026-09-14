> **Superseded.** This was the original 4-5 week plan. The MVP was built to
> `PLAN.md` instead, in three days. Kept for the reasoning about scope and
> risk — in particular risk R1, source availability, which is exactly what
> went on to reshape the project. See `SOURCES.md` for what actually happened.

# Music Research Agent — MVP Roadmap

**Owner:** Alejandro Trujillo · **Doc status:** draft v0.1 · **Fecha:** 2026-09-12

---

## 1. Problema y usuario

**Usuario primario:** A&R / equipo de fichaje (sello o publisher).

**Decisión que toma con el reporte:** *¿este artista merece una conversación de firma, y bajo qué tesis?*

**Dolor actual:** un screening serio de un artista toma 2-4 horas de tabs abiertas (Spotify, YouTube, prensa, Bandsintown, Reddit) y el resultado vive en la cabeza del analista. No es comparable entre artistas ni auditable por un comité.

**Promesa del MVP:** el mismo screening en <3 minutos, con cada número trazable a su fuente, y en un formato idéntico artista tras artista.

> **Implicación de diseño:** para A&R el reporte no gana por ser bonito, gana por ser **confiable y comparable**. Un número sin fuente vale menos que un hueco honesto. Esto ordena todas las decisiones técnicas de abajo.

---

## 2. Qué es y qué NO es el MVP

| Es | No es |
|---|---|
| Un CLI que toma un nombre de artista y emite `report.json` + `report.md` | Un dashboard, un SaaS, o un frontend |
| Un agregador de **datos públicos** con análisis encima | Una fuente de verdad de datos de industria (eso es Chartmetric) |
| Un screening de primera pasada | Un due diligence financiero de catálogo |
| Determinista y reproducible | Un chat conversacional sobre artistas |
| 1 artista por corrida | Batch scoring de 200 artistas (v1.1) |

**Anti-goal explícito:** el agente nunca inventa una métrica. Si no la puede citar, la reporta como `null` con un motivo.

---

## 3. Criterios de éxito del MVP

El MVP está listo cuando, sobre un *golden set* de 10 artistas (4 emergentes, 3 mid-tier, 2 establecidos, 1 con nombre ambiguo):

1. **Cero fabricación:** 100% de los datos cuantitativos del reporte se resuelven a una URL/fuente verificable en auditoría manual. Sin excepciones.
2. **Cobertura:** ≥80% de los campos del schema poblados en artistas mid-tier; ≥50% en emergentes (el resto explícitamente `null` + motivo).
3. **Identidad correcta:** 10/10 artistas resueltos a la entidad correcta (el caso ambiguo puede pedir desambiguación, no adivinar mal en silencio).
4. **Utilidad:** un A&R real califica ≥7/10 la pregunta *"¿esto te ahorró trabajo?"* en al menos 8 de 10 reportes.
5. **Operación:** p95 < 3 min por reporte, costo < $0.50 USD por reporte.
6. **Reproducibilidad:** dos corridas del mismo artista el mismo día producen el mismo JSON en los campos duros.

---

## 4. Decisiones de producto

### Confirmadas

| # | Decisión | Elección |
|---|---|---|
| D1 | Usuario primario | A&R / fichaje |
| D2 | Fuentes | APIs oficiales gratuitas + web search |
| D3 | Entrega | CLI → `report.json` + `report.md` |
| D4 | Arquitectura | Híbrida: pipeline determinista + sub-agente libre solo para lo cualitativo |

### Defaults que asumo (reversibles — dime si alguno no te cuadra)

| # | Tema | Default asumido | Por qué |
|---|---|---|---|
| A1 | Alcance de artista | Emergente → mid-tier | Es donde vive la decisión de A&R. Data escasa es el caso normal, no la excepción → el sistema debe manejar huecos con elegancia |
| A2 | Desambiguación | Resolver contra Spotify + MusicBrainz; si hay >1 candidato fuerte, el CLI **pregunta**. Flag `--spotify-id` para saltarlo. El reporte siempre abre con la identidad resuelta | Un reporte del artista equivocado es peor que ningún reporte |
| A3 | Mercados | Geografía de audiencia + huella de gira. Con APIs gratuitas esto es **proxy**, no dato duro (ver §7 Riesgos) | Para A&R importa dónde puede girar y dónde crece |
| A4 | Comparables | Dos listas separadas: **peers de nivel** (misma banda de popularidad) y **análogos de trayectoria** (dónde estaba X hace 2-3 años) | La segunda es la que arma la tesis de inversión |
| A5 | Actividad reciente | Ventana rodante 12 meses, con highlight de 90 días. Releases, shows, prensa, señales sociales | |
| A6 | Trazabilidad | Cada dato cuantitativo carga `source`, `url`, `retrieved_at`, `confidence`. El LLM **solo ve el evidence bundle**, nunca recuerda números de memoria | Es el criterio de éxito #1 |
| A7 | Idioma | Reporte en EN (lingua franca de industria), `--lang es` disponible | |
| A8 | Persistencia | Stateless, pero cada corrida se guarda en `runs/<artist_id>/<timestamp>/`. Sin BD | Te regala series de tiempo gratis para v1.1 |
| A9 | Volumen | 1 artista/corrida; el core es una función pura → batch es un loop después | |
| A10 | Contrato | El JSON es el producto. Pydantic + `schema_version` | Un downstream futuro (dashboard, scoring) no debe forzar refactor |
| A11 | Equipo/tiempo | Solo dev, part-time, ~4-5 semanas | Ajustar si hay más manos |
| A12 | Costo LLM | Claude para análisis; presupuesto duro por corrida con corte | |

---

## 5. El contrato de salida (el corazón del producto)

Diseñar el schema **antes** que el código. Todo lo demás existe para llenarlo.

```
ArtistReport
├── schema_version, generated_at, run_id, cost_usd, duration_s
├── identity            # quién es exactamente
│   ├── resolved_name, spotify_id, musicbrainz_id, isni
│   ├── disambiguation_confidence, alternates_considered[]
│   └── origin_country, active_since, label_status, members[]
├── snapshot            # los números duros, cada uno con fuente
│   └── metric[]  { name, value, unit, source, url, retrieved_at, confidence }
├── positioning         # cualitativo, anclado a evidencia
│   ├── genre_primary, genre_secondary[], sonic_descriptors[]
│   ├── narrative          # la historia que el artista cuenta
│   ├── audience_profile   # quién escucha y por qué
│   └── differentiation    # white space vs. sus peers
├── comparables
│   ├── tier_peers[]       { artist, why, shared_signals[], popularity_delta }
│   └── trajectory_analogs[] { artist, stage_matched, what_happened_next }
├── markets
│   ├── strongholds[]      { market, evidence_type, strength, caveat }
│   ├── emerging[]
│   └── touring_footprint  { cities[], venue_tier, last_12mo_shows }
├── recent_activity       # 12 meses, ordenado
│   └── event[] { date, type, title, significance, url }
├── signals
│   ├── momentum          # acelerando / estable / enfriando + por qué
│   ├── green_flags[]
│   └── risks[]           # lo que un A&R debe preguntar antes de firmar
├── ar_summary            # 5-8 bullets: la tesis, para el comité
└── data_quality
    ├── coverage_score, fields_null[]
    ├── sources_used[], sources_failed[]
    └── caveats[]         # "monthly listeners por país no disponible vía API pública"
```

**Regla de oro:** `data_quality` no es metadata de debug, es una **sección visible del reporte**. Un A&R necesita saber qué tan sólido es el piso antes de pisarlo.

---

## 6. Arquitectura (híbrida)

```
  CLI  ──►  ┌──────────────────────────────────────────────┐
            │ 0. RESOLVE   identidad canónica              │  determinista
            │              (Spotify + MusicBrainz)         │
            ├──────────────────────────────────────────────┤
            │ 1. COLLECT   fan-out paralelo a N fuentes    │  determinista
            │              → EvidenceBundle (crudo+citado) │
            ├──────────────────────────────────────────────┤
            │ 2. NORMALIZE dedupe, unidades, timestamps,   │  determinista
            │              scoring de confianza            │
            ├──────────────────────────────────────────────┤
            │ 3. ANALYZE   positioning · comparables ·     │  LLM, 1 llamada
            │              markets · momentum              │  por sección,
            │              (input = SOLO el bundle)        │  output tipado
            ├──────────────────────────────────────────────┤
            │ 3b. DEEP DIVE  sub-agente libre: prensa,     │  agente c/ tools
            │               narrativa, contexto cultural   │  (presupuestado)
            ├──────────────────────────────────────────────┤
            │ 4. ASSEMBLE  validar Pydantic → JSON + MD    │  determinista
            └──────────────────────────────────────────────┘
```

**Por qué híbrido gana aquí:** los pasos 0-2 y 4 no deben tener creatividad — son los que dan reproducibilidad y trazabilidad. El paso 3b sí la necesita, porque "¿qué está diciendo la prensa de este artista?" no tiene una API. Lo encapsulamos con presupuesto de tokens y tiempo, y su output entra al reporte **marcado como cualitativo**, nunca como métrica.

**Capa de fuentes:** interfaz `SourceAdapter` común (`fetch(artist_identity) -> list[Evidence]`). Cada fuente es un adapter aislado que puede fallar sin tumbar la corrida. Esto es lo que te permite enchufar Chartmetric en v1.1 sin tocar el resto.

---

## 7. Riesgos y restricciones (leer antes de codear)

| # | Riesgo | Impacto | Mitigación |
|---|---|---|---|
| R1 | **Las APIs gratuitas dan menos de lo que crees.** Spotify restringió endpoints para apps nuevas (related-artists, audio-features, recommendations) y nunca expuso *monthly listeners por país* | Alto — golpea directo a "comparables" y "mercados" | **Phase 0 es un spike de feasibility.** Validar con credenciales reales qué responde hoy cada endpoint, antes de diseñar encima |
| R2 | Alucinación de métricas | Fatal para la confianza del A&R | Evidence-first: el LLM recibe solo el bundle; validación post-hoc que rechaza todo número sin `source` |
| R3 | Artistas emergentes con data casi nula | El reporte queda vacío y parece roto | `coverage_score` visible + el reporte se degrada con gracia, no falla. Un "no hay data" fundamentado **también es señal de A&R** |
| R4 | Nombres ambiguos / homónimos | Reporte del artista equivocado | A2: desambiguación explícita + identidad al tope del reporte |
| R5 | Rate limits (MusicBrainz 1 req/s, YouTube 10k unidades/día) | Batch inviable, corridas lentas | Cache en disco por `artist_id`, backoff, fan-out paralelo respetando límites |
| R6 | Fuentes de terceros cambian sin aviso | Rompe en producción silenciosamente | Tests de contrato por adapter + `sources_failed[]` visible en el reporte |
| R7 | ToS de scraping | Legal | Solo APIs oficiales y web search. Nada de scraping de Spotify/Instagram |

> **R1 es el riesgo que puede redefinir el producto.** Si resulta que la data geográfica gratuita es demasiado pobre, la decisión de producto es: (a) reportar mercados solo como proxy honesto, o (b) mover Chartmetric de v1.1 a MVP. Esa decisión se toma con datos al cerrar Phase 0, no antes.

---

## 8. Roadmap por fases

Fases, no fechas. Cada una tiene criterio de salida binario.

### Phase 0 — Feasibility spike + contrato *(3-4 días)*
Lo más importante del roadmap. Nada de arquitectura hasta saber qué data existe.

- [ ] Dar de alta credenciales: Spotify, YouTube Data, Last.fm, MusicBrainz, Genius, Bandsintown, Deezer
- [ ] Script crudo que pega a cada endpoint con 3 artistas de prueba (1 emergente, 1 mid, 1 grande)
- [ ] **Matriz de disponibilidad de data:** fuente × campo × ¿existe? × ¿confiable? × rate limit
- [ ] Congelar `schema.py` (Pydantic) contra lo que realmente existe
- [ ] Definir el golden set de 10 artistas

**Salida:** matriz de data + schema v1 congelado + decisión documentada sobre R1.

### Phase 1 — Resolve + Collect *(1 semana)*
- [ ] `SourceAdapter` base + registry
- [ ] Resolución de identidad con desambiguación (A2)
- [ ] Adapters: Spotify, MusicBrainz, Last.fm, YouTube, Wikipedia/Wikidata, Bandsintown, Deezer
- [ ] Fan-out paralelo con timeout y aislamiento de fallos por adapter
- [ ] `EvidenceBundle` + cache en disco
- [ ] Normalización: unidades, fechas, dedupe, `confidence`

**Salida:** `collect("Artista") -> EvidenceBundle` con citas, corriendo sobre los 10 del golden set.

### Phase 2 — Capa de análisis *(1-1.5 semanas)*
- [ ] Positioning (LLM, output tipado, solo sobre bundle)
- [ ] Comparables: seed desde tags/similares → filtro por banda de popularidad → LLM rankea y **justifica con señales compartidas**
- [ ] Markets: agregación de proxies + caveats explícitos
- [ ] Recent activity: timeline ordenado + scoring de relevancia
- [ ] Momentum + green flags + risks
- [ ] Sub-agente de deep dive (prensa/narrativa) con presupuesto duro
- [ ] **Validador anti-alucinación:** rechaza cualquier número sin fuente en el bundle

**Salida:** todas las secciones pobladas y validadas para el golden set.

### Phase 3 — Ensamblado, CLI y renderer *(3-4 días)*
- [ ] Validación Pydantic del reporte completo
- [ ] Renderer Markdown (el MD se deriva del JSON, nunca se escribe aparte)
- [ ] CLI: `--spotify-id`, `--lang`, `--out`, `--no-cache`, `--budget`
- [ ] Persistencia en `runs/`
- [ ] Degradación con gracia + `data_quality` visible

**Salida:** `python -m music_research_agent "Artista"` end-to-end.

### Phase 4 — Harness de calidad *(3-4 días)* — no saltar
- [ ] Suite de eval sobre el golden set: coverage, trazabilidad, latencia, costo
- [ ] Auditoría manual de fabricación (criterio #1)
- [ ] Sesión de review con un A&R real → criterio #4
- [ ] Tests de contrato por adapter
- [ ] README + setup de credenciales

**Salida:** los 6 criterios de §3 medidos y pasando. **Esto es el MVP.**

---

## 9. Backlog post-MVP (no ahora)

- Chartmetric/Soundcharts detrás del `SourceAdapter` existente → mercados dejan de ser proxy
- Batch screening + ranking de N artistas
- Diffs temporales ("qué cambió vs. hace 30 días") — la data ya está en `runs/`
- Señales sociales: TikTok, Instagram, Reddit sentiment
- Scoring de fit contra el roster del sello
- API FastAPI + frontend
- Export a PDF/deck para comité

---

## 10. Preguntas abiertas para ti

1. ¿Los defaults A1-A12 te funcionan, o hay alguno que quieras cambiar?
2. ¿Tienes acceso a un A&R real para el review del criterio #4? Sin ese loop el MVP se valida solo técnicamente.
3. ¿Presupuesto para APIs de pago existe o está descartado de entrada? Cambia cómo resolvemos R1.
4. ¿Timeline objetivo? El plan asume ~4-5 semanas part-time en solitario.
