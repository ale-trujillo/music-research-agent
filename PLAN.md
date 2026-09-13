# MVP en 3 días — Music Research Agent

**Owner:** Alejandro Trujillo · **Fecha:** 2026-09-12 · `ROADMAP.md` queda parqueado (plan a 4-5 semanas)

---

## Spec confirmada

| Dimensión | Decisión |
|---|---|
| Usuario | A&R / fichaje |
| Artistas | **Emergentes en Colombia** |
| Fuentes | Solo APIs oficiales gratuitas (sin presupuesto) |
| Entrega | CLI → `report.json` + `report.md` |
| Arquitectura | Híbrida: pipeline determinista + sub-agente para lo cualitativo |
| Alcance | Las 6 funcionalidades, **con confianza marcada** por sección |
| Mercados | Colombia (dónde pega) + ruta de expansión |
| Trazabilidad | Citas + **validador anti-alucinación bloqueante** |
| Idioma | Inglés |
| Equipo | Solo dev, 3 días |

**El día extra compra la pieza que más importa:** con 2 días el validador salía en modo warning. Con 3 sale **bloqueante** — ninguna cifra sin fuente llega al reporte. Es justo el blindaje que pediste, y con artistas emergentes es donde más se nota.

---

## Golden set (criterio de aceptación)

El MVP está listo cuando corre limpio sobre 6 artistas emergentes colombianos reales.
La lista concreta vive en `GOLDEN_SET.md`, fuera de control de versiones.

Lo que importa del diseño de la prueba son los perfiles que cubre:

| Perfil | Qué pone a prueba |
|---|---|
| Presencia internacional | El caso "más fácil": data abundante en todas las fuentes |
| Singer-songwriter con prensa | Narrativa y contexto cualitativo |
| **Nombre común** | Prueba dura de desambiguación |
| Nombre atípico | Resolución exacta |
| **Nombre corto/ambiguo** | Colisión probable en búsqueda |
| **Baja huella digital** | Degradación con gracia |

> Los tres marcados son los valiosos. Un agente que solo funciona con perfiles de
> data abundante no sirve para A&R de emergentes.

---

## Aritmética

| Bloque | Est. |
|---|---|
| Setup + schema | 2h ✅ |
| Adapters (5 fuentes) | 4h |
| Evidence bundle + normalize | 2h |
| 6 secciones de análisis | 4h |
| Validador anti-alucinación | 3h |
| CLI + renderer | 2h |
| Pruebas sobre el golden set | 2h |
| **Total** | **~19h → ~6.5h/día** |

---

## La tensión honesta

**Emergentes colombianos + APIs gratuitas = reportes delgados.** Un artista con 3k oyentes tendrá Spotify y YouTube, casi nada en Last.fm, nada en Bandsintown. El validador va a dejar **muchos campos en `null`** — eso no es el sistema fallando, es el sistema siendo honesto. La alternativa (rellenar con estimaciones del LLM) es justo lo que decidimos evitar.

> **Reencuadre de producto:** para emergentes, la ausencia de data *es* la señal de A&R. Un artista sin prensa ni shows registrados es un perfil distinto al que sí los tiene. El reporte hace esa distinción legible en vez de esconderla.

**Sin loop de validación con un A&R real**, el MVP se valida técnicamente (¿corre? ¿cita bien?), no por utilidad. Deuda declarada.

---

## Día 1 — El espinazo (data citable, sin LLM)

**Meta: `python -m music_research_agent "<artista>" --raw` escupe JSON con evidencia citada.**

- [x] Scaffold + venv + `requirements.txt` + `.env.example`
- [x] `schema.py` — el contrato Pydantic (es el producto)
- [x] `SourceAdapter` base: falla aislada, timeout, retry
- [x] Adapters, en orden de valor para emergentes CO:
  1. **Spotify** — identidad, followers, popularity, releases *(el ancla)*
  2. **YouTube Data** — canal, views, uploads recientes
  3. **MusicBrainz** — ID canónico, relaciones, país
  4. **Last.fm** — tags, similares *(esperar huecos)*
  5. **Web search** — prensa, contexto de escena
- [x] Resolución de identidad + desambiguación + `--spotify-id` override
- [x] `EvidenceBundle` con `source`/`url`/`retrieved_at`/`confidence` por dato
- [ ] Cache en disco  *(no hecho: las cuotas se agotaron por probing, no por falta de cache)* (no quemar rate limits mientras iteras)

**Exit:** los 6 artistas resueltos a la entidad correcta + matriz de qué fuente respondió qué.

## Día 2 — El cerebro

**Meta: 6 secciones pobladas, cada una con confianza marcada.**

- [x] Capa de análisis (el LLM ve **solo** el bundle, nunca recuerda cifras):
  `positioning` · `comparables` · `markets` (CO + expansión) · `recent_activity` · `signals/momentum` · `ar_summary`
- [ ] Sub-agente de deep dive  *(no hecho: sin fuente de prensa en el MVP)*: prensa y escena (lo cualitativo sin API)
- [x] `confidence` + `evidence_basis` por sección

**Exit:** reporte completo en JSON para los 6.

## Día 3 — Blindaje y entrega

- [x] **Validador anti-alucinación** *(warning + exit code 2, no bloqueante)* — rechaza toda cifra ausente del bundle
- [x] Renderer Markdown derivado del JSON (nunca escrito aparte)
- [x] CLI completo + `data_quality` visible en el reporte
- [x] Auditoría manual de los 6 → `AUDIT.md`: cero cifras sin fuente
- [x] README + setup

**Exit:** MVP. Los 6 corren limpio, auditados a mano.

---

## Bloqueante: credenciales

Todas gratis, van en `.env` (plantilla en `.env.example`):

| Fuente | Dónde | Estado |
|---|---|---|
| **Spotify** *(crítico — ancla de identidad)* | developer.spotify.com/dashboard | ⬜ |
| **YouTube Data v3** | console.cloud.google.com | ⬜ |
| **Last.fm** | last.fm/api/account/create | ⬜ |
| Genius *(opcional)* | genius.com/api-clients | ⬜ |
| MusicBrainz | sin key, solo User-Agent | ✅ |

---

## Fuera de alcance (v2)

Chartmetric · batch screening · diffs temporales · TikTok/Instagram · API/frontend · PDF
