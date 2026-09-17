# -*- coding: utf-8 -*-
"""
expediente.py — El expediente del board: aritmetica hecha por Python.

v3 (post-calibracion): la EVALUACION del perfil se pre-redacta en lenguaje
llano, regla por regla, con el ALCANCE de cada limite explicito en cada
linea (leccion del estreno v2: el agresivo aplico el techo por ACCION de
8% a SECTORES y recomendo 'vender hasta que cada sector quede bajo 8%').
Los agentes NO calculan ni deciden que techo aplica a que dato: leen la
evaluacion lista y debaten que hacer.

Formato de cada linea de evaluacion:
- 'no cumple el techo/piso/tope/maximo de X%' cuando no se cumple
- 'cerca del...' en borde (>= 90% del limite)
- 'dentro de...' / 'por encima del piso...' cuando cumple

Sectores: reales, en espanol, en RAM (gratis del hijo + yfinance para el
resto). Solo acciones individuales cuentan para sectores; ETFs son
multi-sector y se listan aparte; lo sin-clasificar NUNCA se suma.

Privacidad: todo vive SOLO en RAM. Jamas se persiste en el repo publico.
"""

import time

import yfinance as yf

TIPOS_COLCHON = {"fci", "cash"}
TIPOS_RENTA_AR = {"bono_soberano", "bono_subsoberano", "on"}
TIPOS_ACCIONES = {"accion", "etf"}
TIPOS_OPCIONES = {"bucket_manual"}

SECTOR_ES = {
    "Technology": "Tecnologia",
    "Communication Services": "Comunicacion",
    "Consumer Cyclical": "Consumo ciclico",
    "Consumer Defensive": "Consumo defensivo",
    "Energy": "Energia",
    "Financial Services": "Finanzas",
    "Healthcare": "Salud",
    "Industrials": "Industria",
    "Basic Materials": "Materiales",
    "Utilities": "Servicios publicos",
    "Real Estate": "Real Estate",
}


def _sector_yf(ticker):
    """Sector GICS de yfinance, o None (con reintento corto)."""
    for intento in range(2):
        try:
            info = yf.Ticker(ticker).info or {}
            s = info.get("sector")
            if s:
                return s
            return None
        except Exception:
            if intento == 0:
                time.sleep(5)
    return None


def obtener_sectores(lineas, hijos_estado):
    """Mapa ticker->sector (espanol) de las acciones de la cartera.
    Primero el estado del hijo (gratis), despues yfinance (RAM)."""
    out = {}
    acc = [l["ticker"] for l in lineas if l["tipo"] in TIPOS_ACCIONES]
    mapa_hijo = {}
    for e in (hijos_estado or {}).get("watchlist", []):
        if e.get("sector"):
            mapa_hijo[(e.get("ticker") or "").upper()] = e["sector"]
    faltan = []
    for t in acc:
        if t in mapa_hijo:
            out[t] = SECTOR_ES.get(mapa_hijo[t], mapa_hijo[t])
        else:
            faltan.append(t)
    for i, t in enumerate(sorted(faltan), start=1):
        s = _sector_yf(t)
        if s:
            out[t] = SECTOR_ES.get(s, s)
        print(f"  sectores: {i}/{len(faltan)} resueltos")
        time.sleep(0.5)
    return out


def _por_sector(lineas, sectores):
    """Agrupa SOLO acciones individuales por sector real.
    Devuelve (dict sector -> [lineas], lista sin clasificar). ETFs fuera."""
    por, sin = {}, []
    for l in lineas:
        if l["tipo"] == "etf":
            continue
        if l["tipo"] not in TIPOS_ACCIONES:
            continue
        s = sectores.get(l["ticker"])
        if s:
            por.setdefault(s, []).append(l)
        else:
            sin.append(l)
    return por, sin


def _fmt(x, suf=""):
    return "n/d" if x is None else f"{x}{suf}"


def _top_n(lineas, n=5):
    acc = sorted((l for l in lineas if l["tipo"] in TIPOS_ACCIONES),
                 key=lambda l: -l["peso"])
    return acc[:n], round(sum(l["peso"] for l in acc[:n]), 2)


def _bloque_sectores(lineas, sectores):
    """Mapa de sectores legible: nombre, peso y tickers."""
    por, sin = _por_sector(lineas, sectores)
    lineas_txt = []
    for s, ls in sorted(por.items(),
                        key=lambda kv: -sum(x["peso"] for x in kv[1])):
        total = round(sum(x["peso"] for x in ls), 2)
        det = ", ".join(f"{x['ticker']} {x['peso']}%"
                        for x in sorted(ls, key=lambda x: -x["peso"]))
        lineas_txt.append(f"- {s}: {total}% ({det})")
    if sin:
        det = ", ".join(f"{x['ticker']} {x['peso']}%" for x in sin)
        lineas_txt.append(f"- (sin clasificar, NO suman a sectores: {det})")
    etf = [l for l in lineas if l["tipo"] == "etf"]
    if etf:
        det = ", ".join(f"{x['ticker']} {x['peso']}%" for x in etf)
        lineas_txt.append(f"- (ETFs multi-sector, NO suman a sectores: {det})")
    return "\n".join(lineas_txt) if lineas_txt else "- (sin acciones)"


# ------------------------------------------------------- lectura en RAM
def leer_cartera_ram(sheet, pestana="cartera", tol=3.0):
    """Lee la foto de cartera (Lector). Todo queda en RAM del proceso."""
    try:
        ws = sheet.worksheet(pestana)
        valores = ws.get_all_values()
    except Exception as e:
        return [], None, f"fallo lectura de hoja ({type(e).__name__})"
    if len(valores) < 2:
        return [], None, "hoja sin filas de datos"
    headers = [str(h).strip().lower() for h in valores[0]]
    try:
        i_t = headers.index("ticker")
        i_p = headers.index("peso_%")
        i_tipo = headers.index("tipo")
    except ValueError:
        return [], None, "headers esperados no encontrados (ticker/peso_%/tipo)"
    fecha = None
    if len(valores[0]) > 4:
        fecha = str(valores[0][4]).strip() or None
    lineas = []
    for fila in valores[1:]:
        if len(fila) <= max(i_t, i_p, i_tipo):
            continue
        t = str(fila[i_t]).strip().upper()
        if not t or t in ("TOTAL", "SUMA"):
            continue
        try:
            s = str(fila[i_p]).strip().replace("%", "").replace(",", ".")
            peso = float(s)
        except ValueError:
            continue
        lineas.append({"ticker": t, "peso": peso,
                       "tipo": str(fila[i_tipo]).strip().lower()})
    if not lineas:
        return [], fecha, "0 lineas utiles"
    suma = round(sum(l["peso"] for l in lineas), 2)
    ok = abs(suma - 100) <= tol
    return lineas, fecha, f"{len(lineas)} lineas, suma {suma}% ({'ok' if ok else 'FUERA'})"


def cargar_politica(sheet):
    """Pestana 'politica' (texto del usuario). None si falta."""
    try:
        ws = sheet.worksheet("politica")
        valores = ws.get_all_values()
        lineas = []
        for fila in valores:
            for celda in fila:
                if celda and str(celda).strip():
                    lineas.append(str(celda).strip())
        return "\n".join(lineas) if lineas else None
    except Exception:
        return None


# ------------------------------------------------------- evaluacion llano
def evaluar_perfil(lineas, perfil, sectores, fragil_flags=None):
    """La evaluacion del perfil, PRE-REDACTADA en lenguaje llano por Python.
    Devuelve (texto, viol_count). Esta es la unica fuente de verdad para
    los agentes: ellos no recalculan ni interpretan alcances."""
    u = perfil
    ev, viol = [], 0
    acc = sorted((l for l in lineas if l["tipo"] in TIPOS_ACCIONES),
                 key=lambda l: -l["peso"])

    # 1. Techo por ACCION (solo quienes no cumplen o estan en borde)
    for l in acc:
        p = l["peso"]
        if p > u["techo_posicion"]:
            ev.append(f"- {l['ticker']} {_fmt(p, '%')}: no cumple el techo "
                      f"por accion de {u['techo_posicion']}%")
            viol += 1
        elif p >= 0.9 * u["techo_posicion"]:
            ev.append(f"- {l['ticker']} {_fmt(p, '%')}: cerca del techo por "
                      f"accion de {u['techo_posicion']}%")

    # 2. Top-5 acumulado
    _, top5 = _top_n(lineas)
    if top5 > u["top5_max"]:
        ev.append(f"- Top-5 acumulado {_fmt(top5, '%')}: no cumple el maximo "
                  f"acumulado de {u['top5_max']}%")
        viol += 1
    elif top5 >= 0.9 * u["top5_max"]:
        ev.append(f"- Top-5 acumulado {_fmt(top5, '%')}: cerca del maximo "
                  f"acumulado de {u['top5_max']}%")
    else:
        ev.append(f"- Top-5 acumulado {_fmt(top5, '%')}: dentro del maximo "
                  f"de {u['top5_max']}%")

    # 3. Sectores: los 3 mayores, con el alcance EXPLICITO en cada linea
    #    (el maximo por sector es una regla DISTINTA del techo por accion)
    por_sec, _ = _por_sector(lineas, sectores)
    max_sec = u.get("sector_default_max", 1000)
    mayores = sorted(por_sec.items(),
                     key=lambda kv: -sum(x["peso"] for x in kv[1]))[:3]
    for s, ls in mayores:
        peso = round(sum(x["peso"] for x in ls), 2)
        if peso > max_sec:
            ev.append(f"- Sector {s} {_fmt(peso, '%')}: no cumple el maximo "
                      f"por sector de {max_sec}%")
            viol += 1
        elif peso >= 0.9 * max_sec:
            ev.append(f"- Sector {s} {_fmt(peso, '%')}: cerca del maximo por "
                      f"sector de {max_sec}%")
        else:
            ev.append(f"- Sector {s} {_fmt(peso, '%')}: dentro del maximo por "
                      f"sector de {max_sec}%")

    # 4. Colchon (fci + cash): es un PISO, no un tope
    col = round(sum(l["peso"] for l in lineas if l["tipo"] in TIPOS_COLCHON), 2)
    if col < u["colchon_min"]:
        ev.append(f"- Colchon fci+cash {_fmt(col, '%')}: no cumple el piso "
                  f"de {u['colchon_min']}%")
        viol += 1
    elif col < u["colchon_min"] * 1.1:
        ev.append(f"- Colchon fci+cash {_fmt(col, '%')}: cerca del piso "
                  f"de {u['colchon_min']}%")
    else:
        ev.append(f"- Colchon fci+cash {_fmt(col, '%')}: por encima del piso "
                  f"de {u['colchon_min']}%")

    # 5. Renta fija AR
    rf = round(sum(l["peso"] for l in lineas if l["tipo"] in TIPOS_RENTA_AR), 2)
    if rf > u["renta_fija_ar_max"]:
        ev.append(f"- Renta fija AR {_fmt(rf, '%')}: no cumple el maximo "
                  f"de {u['renta_fija_ar_max']}%")
        viol += 1

    # 6. Opciones (bucket_manual)
    op = round(sum(l["peso"] for l in lineas if l["tipo"] in TIPOS_OPCIONES), 2)
    if op > u["opciones_max"]:
        ev.append(f"- Opciones {_fmt(op, '%')}: no cumple el tope "
                  f"de {u['opciones_max']}%")
        viol += 1
    elif op >= 0.9 * u["opciones_max"]:
        ev.append(f"- Opciones {_fmt(op, '%')}: cerca del tope "
                  f"de {u['opciones_max']}%")
    else:
        ev.append(f"- Opciones {_fmt(op, '%')}: dentro del tope "
                  f"de {u['opciones_max']}%")

    # 7. Veredictos fragil del hijo sobre acciones de la cartera
    for f in (fragil_flags or []):
        ev.append(f"- {f}: revisar con prioridad")

    ev.append("(el resto de la cartera: sin observaciones)")
    return "\n".join(ev), viol


def _bloque_hijo(hijos_estado, tickers_cartera):
    """Lineas por accion de la cartera que el hijo tambien sigue."""
    out = []
    for e in (hijos_estado or {}).get("watchlist", []):
        t = (e.get("ticker") or "").upper()
        if t and t in tickers_cartera:
            out.append(f"{t}: precio {_fmt(e.get('precio'))}, "
                       f"veredicto {e.get('veredicto') or 'n/d'}, "
                       f"desde {e.get('desde', 'n/d')} "
                       f"({e.get('dias_seguimiento', '?')} dias), "
                       f"senales recientes {', '.join(e.get('senales_hoy') or []) or 'ninguna'}, "
                       f"earnings {e.get('proximo_earnings') or 'n/d'}")
    return "\n".join("- " + l for l in out) or "(el hijo no sigue ninguna accion de la cartera)"


def armar_expediente(lineas, fecha_foto, perfil_nombre, perfil, hijos_estado,
                     politica, propuesta, sectores=None, fragil_flags=None):
    """Arma el dict-expediente que leen los 3 agentes de UN perfil."""
    acc, top5 = _top_n(lineas)
    tickers = {l["ticker"] for l in lineas}
    eval_txt, viol = evaluar_perfil(lineas, perfil, sectores or {},
                                    fragil_flags)

    datos = [
        f"Foto de cartera: {fecha_foto or 'sin fecha'} - {len(lineas)} lineas",
        "Acciones por peso (las primeras 10): "
        + ", ".join(f"{l['ticker']} {l['peso']}%" for l in acc[:10]),
        "Cripto (reportado, sin regla): "
        + f"{round(sum(l['peso'] for l in lineas if l['tipo'] == 'cripto'), 2)}%",
        "",
        "MAPA DE SECTORES (solo referencia; los maximos por sector ya estan "
        "evaluados en la evaluacion de tu perfil, con su alcance dicho):",
        _bloque_sectores(lineas, sectores or {}),
        "",
        "SEGUIMIENTO DEL HIJO (empresas de tu cartera que el hijo sigue):",
        _bloque_hijo(hijos_estado, tickers),
    ]
    return {
        "propuesta": propuesta,
        "perfil": perfil_nombre,
        "evaluacion": eval_txt,
        "datos": "\n".join(datos),
        "violaciones": viol,
        "politica": politica,
    }
