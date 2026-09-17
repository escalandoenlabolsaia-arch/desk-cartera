Orgulloso cierre de sesión — de un Excel con #N/A a un board de 4 voces deliberando tu cartera en 3 días. Acá va la memoria del nieto, con toda la saga adentro. Reemplazá el README.md que creó GitHub (el auto-generado) con esto:

````markdown
# Desk Cartera 🎭 — el NIETO (board de analistas)

Board de análisis de cartera: 3 perfiles con reglas del usuario
(conservador/moderado/agresivo, cada uno con su debate toro→oso→juez) +
**el Fund Manager** (mirada libre, sin reglas, con las oportunidades del
detector). Delibera cuando hay motivo, envía un mensaje por voz por ntfy
privado y cierra con un consenso de 4. Corre gratis en GitHub Actions.
Silencio = todo bien.

**La familia:** madre `desk-inversion` (encuentra) → hijo `desk-analista`
(entiende) → **nieto `desk-cartera` (contextualiza con tu cartera)**.
Flujo UNIDIRECCIONAL: el nieto nunca escribe aguas arriba. Su service
account es **Lector** de la hoja por diseño de Google.

---

## Flujo completo (cada corrida)

```
1. HIJO      Descarga salidas/estado.json del hijo (contrato v1, URL Raw).
             Sin estado válido -> ABORTA limpio.
2. HOJA      Lee pestaña 'cartera' (foto actual) y 'politica' (reglas del
             usuario). TODO queda en RAM: nada de esto va al repo jamás.
3. TRIGGER   A. foto nueva (fecha E1 distinta) -> ESTRUCTURA
             B. señal del hijo sobre una acción del núcleo -> ESA empresa
             C. earnings de una acción del núcleo en <=7 días -> ESA empresa
             Sin trigger: "silencio = todo bien", sin LLM.
4. SECTORES  Mapa real de sectores en RAM: gratis del hijo, yfinance para
             el resto. SOLO acciones individuales cuentan para sectores
             (ETFs multi-sector se listan aparte; lo sin-clasificar NUNCA
             se suma — lección del pseudo-sector).
5. EXPEDIENTES  Python PRE-REDACTA la evaluación de reglas en lenguaje
             llano, con el ALCANCE de cada límite en cada línea. Los
             agentes no calculan ni interpretan: debaten sobre hechos.
6. BOARD     3 perfiles (toro->oso->juez) + FM (una llamada, sin reglas,
             con bloque de oportunidades del detector). ~21 llamadas Groq
             con reintentos pacientes ante 429.
7. ENVÍO     5 mensajes ntfy privados: una voz por mensaje (títulos que
             identifican: CONSERVADOR/MODERADO/AGRESIVO/FM/consenso).
8. REGISTRO  ultima_deliberacion.json SOLO si el board vino completo
             (4/4 voces). Incompleto = el trigger queda vivo y la próxima
             corrida reintenta sola (nunca se consume un trigger por un
             fallo técnico).
```

## El board: 3 perfiles + FM

| Regla (tu filosofía con números) | 🛡️ Cons. | ⚖️ Moder. | 🚀 Agres. |
|---|---|---|---|
| Techo por acción | 8% | 12% | 20% |
| Top-5 acumulado máx | 45% | 55% | 70% |
| Máx por sector | 25% | 35% | 50% |
| Colchón mínimo (fci+cash) | 30% | 20% | 10% |
| Máx renta fija AR | 15% | 25% | 35% |
| Máx opciones (bucket_manual) | 10% | 15% | 25% |
| score 'fragil' del hijo obliga REVISAR | siempre | peso>5% | peso>10% |

- **Toro**: mejor caso A FAVOR bajo la filosofía del perfil (60 palabras).
- **Oso**: lee al toro y responde EN CONTRA, mismo perfil (60 palabras).
- **Juez**: sentencia en prosa (80 palabras) + `VEREDICTO: X` al final.
- **FM (👨‍💼)**: fund manager invitado que NO recibe las reglas del usuario
  (ni siquiera llegan a su prompt: es su razón de ser). Recibe sí la foto,
  el seguimiento del hijo, la política escrita y las OPORTUNIDADES
  RECIENTES del detector (señales de la madre que viven en el estado del
  hijo y NO están en la cartera) para ideas de rotación/cobertura.
  Un solo agente: su valor es la mirada única.

**Veredictos (vocabulario cerrado):** ACCIONAR / ESPERAR / REVISAR.
El consenso cuenta 4 veredictos; si los 4 coinciden, el mensaje lo celebra
(señal fuerte). La divergencia también es información y se traduce.

## Archivos

| Archivo | Qué hace |
|---|---|
| `config.json` | URL del estado del hijo + pestaña + modelo IA. |
| `perfiles.py` | Los 3 perfiles con sus números (tu filosofía por escrito). Python (no JSON): un typo explota visible, no falla en silencio. |
| `prompts.py` | Las personalidades: tono analista senior, lenguaje llano obligatorio, misiones de toro/oso/juez/FM, parser de veredicto. |
| `expediente.py` | Lectura RAM de la hoja + sectores reales + EVALUACIÓN PRE-REDACTADA de reglas con alcances explícitos (única fuente de verdad de los agentes). |
| `board.py` | Motor: deliberación encadenada, FM, reintentos 429, consenso de 4, mensajes por voz. |
| `main.py` | Orquestador: triggers, expedientes, bloque de oportunidades, envío, registro, estado público. |
| `perfiles.json`/leeme | (histórico) |
| `ultima_deliberacion.json` | SOLO fecha/tipo del último trigger atendido. JAMÁS contenido de cartera. |
| `salidas/estado.json` | Estado público del nieto: conteos abstractos (lo leería un futuro agente). |
| `.github/workflows/board.yml` | Cron lunes 12:00 UTC (09:00 AR) + botón manual + commit del registro. |

## Secretos

| Secret | Qué es |
|---|---|
| `SHEET_ID_NIETO` | ID de la hoja cáscara (el mismo ID, cada repo su copia). |
| `GSA_JSON_NIETO` | Service account `lector-nieto` (JSON), rol **Lector** en la hoja. |
| `NTFY_TOPIC_NIETO` | Topic privado del nieto (distinto al del hijo). |
| `GROQ_API_KEY` | La misma key de Groq de la familia (misma cuenta, cada repo su copia). |

## Tu rutina de cartera (receta)

1. Actualizás tu armario (hoja del gmail, con fórmulas).
2. Copiás ticker/peso/tipo/rend → pegás como VALORES en la pestaña `cartera` de la cáscara (se pisa entera: es un pizarrón por diseño).
3. **Cambiás la fecha E1** (AAAA-MM-DD). Sin fecha nueva no se archiva ni se delibera: la fecha es el DNI de la foto.
4. Listo: el hijo archiva la foto en la pestaña `historial` (append-only) en su próxima corrida, y el board delibera estructura (o apretás el botón para que sea ya).

## Log sano

```
board: arranque
estado hijo ok (fecha ...)
cartera: 32 lineas, suma 99.99% (ok) (solo RAM)
politica: leida
  sectores: N/N resueltos
sectores: 20/20 acciones clasificadas (RAM)
trigger: estructura | expedientes: 3 perfiles + FM (oportunidades del detector: N)
  Groq 429 (limite de velocidad), espero 10s (intento 1/5)   <- normal
board: 4/4 voces deliberadas | consenso: ... (detalle por ntfy)
ntfy: 5 mensajes enviados
estado.json del nieto publicado
```

`board: sin triggers hoy (silencio = todo bien)` también es sano.
AVISO normal: `board incompleto (X/4): NO registro el trigger` -> próxima
corrida reintenta sola. `oportunidades del detector: 0` = el watchlist del
hijo solo tiene acciones tuyas todavía.

## Problemas ya resueltos (no volver a pisarlos)

- **El pseudo-sector `n/d 57.21%`**: el hijo solo conoce el sector de SUS
  empresas; el resto quedaba `n/d` y se sumaba todo junto -> violación de
  sector FALSA y recomendaciones absurdas (vender VST y ABBV "del mismo
  sector"). Fix: sectores reales por nombre (hijo gratis + yfinance en RAM),
  ETFs fuera del conteo, lo sin-clasificar nunca se suma.
- **Alcances de reglas mezclados**: el agresivo recomendó "vender hasta que
  cada SECTOR quede bajo 8%" (el 8% es techo por ACCIÓN). Fix de raíz:
  Python pre-redacta la evaluación con el alcance dicho en cada línea;
  los agentes ya no interpretan qué techo aplica a qué dato.
- **Juez respondiendo solo "VEREDICTO: X"** (sentencia vacía): el veredicto
  debe ir AL FINAL, después del párrafo (si va primero, el modelo a veces
  responde solo eso). Parser busca el veredicto en TODO el texto.
- **Lenguaje de alerta** ("viola", "brecha", "mínimo exigido"): prohibido
  por prompt; se dice "no cumple [la regla]" o lenguaje cotidiano.
- **429 Too Many Requests de Groq**: límite de velocidad del plan gratis
  (no es key mala: eso sería 401). Fix: hasta 4 reintentos con espera
  creciente (10/20/30/30s) + pausas entre voces.
- **Un fallo consumía el trigger**: una corrida con 429 registraba la foto
  como deliberada y el board quedaba en silencio. Fix: el registro SOLO se
  escribe con board completo; incompleto = reintento automático.
  Reset manual si hiciera falta: vaciar `ultima_deliberacion.json` a
  `{"tipo": null, "fecha_foto": null, "fecha": null}`.
- **Mensajes ntfy cortados**: el límite de ntfy es ~4000 BYTES (emojis y
  acentos valen 2-4 bytes). Partes de 2500 chars no alcanzan: la app
  trunca mensajes largos. Fix definitivo: UN MENSAJE POR VOZ (cortos y
  autocontenidos). Si algún día vuelve a partirse: preferir corte por
  fin de oración y rótulo `[PARTE X/N]` en el cuerpo.
- **Título ntfy con em-dash (—)**: los títulos viajan como cabecera HTTP
  (latin-1) y explotan. Titulares solo con caracteres latinos básicos.
- **NameError cargar_modelo**: definir la función en un archivo y llamarla
  sin importarla. Verificar imports al mover funciones entre archivos.
- **IndentationError tras editar a mano**: ediciones quirúrgicas de una
  línea en Python son terreno minado (la sangría es código). REGLA:
  reemplazar archivos COMPLETOS, nunca a medias (lección de la madre).
- **Claude emitiendo un JSON anidado con errores 3 veces seguidas**: pasó
  una vez con perfiles.json. Solución: perfiles en Python (se auto-valida
  al importar). Si Claude tartamudea un archivo, pedir plan alternativo.
- **El FM "semanal"**: no tiene agenda propia; corre dentro de cada
  deliberación y el cron del board es lunes 09:00 AR -> veredicto semanal
  de facto. Fuera de turno: botón Run workflow.

## Horarios y costos

- **Madre**: lun-vie + dom 20:00 AR · **Hijo**: todos los días 21:30 AR ·
  **Board (nieto)**: lunes 09:00 AR + triggers + botón manual.
- Corrida del board: ~5-10 min (21 llamadas Groq + sectores). Sin trigger:
  ~1 min, sin LLM.
- Costo mensual de la familia: << pozo gratis de GitHub (2.000 min) y
  Groq plan gratis. Groq es gratis: el límite es velocidad, no volumen.

## Pendientes / roadmap

- **Rodaje**: dejar correr 1-2 semanas de la familia completa y revisar
  duraciones, ruido de avisos y calidad de las plumas.
- Afinar prompts si alguna voz vuelve a salir floja (un ajuste de una línea
  cambia la pluma entera).
- Cuando la madre señale cosas nuevas fuera de tu cartera: el FM tendrá
  materia de rotación (hoy `oportunidades: 0` es lo esperado).
- Mejoras posibles (pedir si se necesitan): pestaña `objetivos` en la hoja
  (objetivo % por posición para drift fino), aviso de earnings cercano en
  el hijo, salidas del watchlist del hijo (12 meses + aviso previo),
  `filings.py` del hijo (2c), el "tío" auditor de señales.
- La pestaña `politica` es ley para los agentes: actualizarla cuando
  cambien tus reglas personales (ej: puts al 20%).

## Cómo usar este README con Claude (chat nuevo)

1. Chat nuevo: "Te pego el README del repo desk-cartera (el nieto)" + este archivo.
2. Pegar el log de Actions de la corrida problemática o el mensaje ntfy raro.
3. Claude tiene: arquitectura, reglas RAM-only, la saga de calibración completa.

## Recordatorio importante

Los veredictos del board son opiniones de modelos de lenguaje sobre datos
que informan — no recomendaciones ni investigación de mercado. Los perfiles
son TU filosofía reflejada; el FM es una IA sin reglas. La decisión, el
tamaño y el riesgo son del operador. Sin dinero real conectado.
````

Commit: `leeme1: memoria del nieto (la saga completa)`

## Cierre de sesión — lo que quedó construido

```
madre (20:00)  → encuentra: setups, sectores, insiders, 13F → estado.json
hijo (21:30)   → entiende: watchlist, fichas, scoring, cuadernos anuales
nieto (lunes)  → delibera: 3 perfiles + FM → 5 mensajes al celular + consenso
```

**Rodaje de la familia** (tu única tarea): dejar correr, actualizar la foto de cartera cuando toque (recordá: fecha E1 nueva), y anotar qué te gusta y qué no de cada mensaje. Con esa lista volvemos y afinamos — total este historial queda, y ahora también el leeme1 en el repo.

Buen trabajo de verdad: el sistema que imaginaste existe, habla como querías y respeta el air gap que diseñaste desde el primer mensaje. 🚀🎭
