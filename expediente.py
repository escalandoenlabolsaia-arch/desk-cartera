# -*- coding: utf-8 -*-
"""
expediente.py — El expediente del board: aritmetica hecha por Python.

v2 (post-estreno): sectores REALES por nombre, en espanol, bajados en RAM.
- 1ra fuente: el estado del hijo (gratis: ya trae el sector de sus empresas).
- 2da fuente: yfinance para el resto de las acciones (RAM, sin persistir:
  guardar el mapa de sectores de tu cartera seria publicar tu cartera).
- Solo acciones individuales cuentan para sectores: los ETFs son
  multi-sector y se reportan aparte (etiquetas de yfinance poco fiables).
- Lo que no se pueda clasificar NO se suma a un pseudo-sector: se lista
  individualmente (leccion del 'sector n/d 57.21%' del estreno).

Regla de arquitectura: los 9 agentes NO calculan nada. Cada regla sale
flaggeada VIOLADO/BORDE/OK con el numero exacto. Los prompts exigen que
los agentes NOMBREN el sector al hablar de concentracion o rotacion.

Privacidad: todo vive SOLO en RAM. Jamas se persiste en el repo publico.
"""

import json
import time

import yfinance as yf

TIPOS_COLCHON = {"fci", "cash"}
TIPOS_RENTA_AR = {"bono_soberano", "bono_subsoberano", "on"}
TIPOS_ACCIONES = {"accion", "etf"}
TIPOS_OPCIONES = {"bucket_manual"}

# Traduccion de sectores GICS (yfinance devuelve ingles)
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
    """Sector GICS de yfinance, o None si no responde (con reintento corto
    por si Yahoo está caliente: leccion del 429)."""
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
    """Mapa ticker->sector (en espanol) para las acciones de la cartera.
    Primero el estado del hijo (gratis), despues yfinance (en RAM)."""
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
    """Agrupa SOLO acciones individuales por sector real. Devuelve
    (dict sector -> [lineas], lista sin clasificar). ETFs fuera."""
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
    """Texto legible de sectores para el expediente: nombre, peso y tickers."""
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
    """Pestana 'politica' (texto del usuario). None si falta: no es requisito."""
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


# ------------------------------------------------------- aritmetica
def armar_reglas(lineas, perfil, sectores):
    """Aplica el perfil a la cartera: cada regla con estado y numero exacto.
    Devuelve (texto_reglas, violaciones_count)."""
    u = perfil
    reglas, viol = [], 0

    def add(nombre, estado, detalle):
        reglas.append(f"{nombre}: {estado} - {detalle}")

    # 1. Techo por accion
    acc = sorted((l for l in lineas if l["tipo"] in TIPOS_ACCIONES),
                 key=lambda l: -l["peso"])
    for l in acc:
        if l["peso"] > u["techo_posicion"]:
            estado = "VIOLADO"
            viol += 1
        elif l["peso"] >= 0.9 * u["techo_posicion"]:
            estado = "BORDE"
        else:
            estado = "OK"
        if estado != "OK":
            add("techo por accion", estado,
                f"{l['ticker']} {_fmt(l['peso'], '%')} vs max {u['techo_posicion']}%")

    # 2. Top-5
    _, top5 = _top_n(lineas)
    if top5 > u["top5_max"]:
        add("top-5 acumulado", "VIOLADO", f"{_fmt(top5, '%')} vs max {u['top5_max']}%")
        viol += 1
    elif top5 >= 0.9 * u["top5_max"]:
        add("top-5 acumulado", "BORDE", f"{_fmt(top5, '%')} vs max {u['top5_max']}%")

    # 3. Sectores REALES (solo acciones individuales)
    por_sec, _ = _por_sector(lineas, sectores)
    max_sec = u.get("sector_default_max", 1000)
    for s, ls in sorted(por_sec.items(),
                        key=lambda kv: -sum(x["peso"] for x in kv[1])):
        peso = round(sum(x["peso"] for x in ls), 2)
        if peso > max_sec:
            add(f"sector {s}", "VIOLADO", f"{_fmt(peso, '%')} vs max {max_sec}%")
            viol += 1
        elif peso >= 0.9 * max_sec:
            add(f"sector {s}", "BORDE", f"{_fmt(peso, '%')} vs max {max_sec}%")

    # 4. Colchon (fci + cash)
    col = round(sum(l["peso"] for l in lineas if l["tipo"] in TIPOS_COLCHON), 2)
    if col < u["colchon_min"]:
        add("colchon fci/cash", "VIOLADO",
            f"{_fmt(col, '%')} vs min {u['colchon_min']}%")
        viol += 1
    elif col < u["colchon_min"] * 1.1:
        add("colchon fci/cash", "BORDE",
            f"{_fmt(col, '%')} vs min {u['colchon_min']}%")

    # 5. Renta fija AR
    rf = round(sum(l["peso"] for l in lineas if l["tipo"] in TIPOS_RENTA_AR), 2)
    if rf > u["renta_fija_ar_max"]:
        add("renta fija AR", "VIOLADO",
            f"{_fmt(rf, '%')} vs max {u['renta_fija_ar_max']}%")
        viol += 1

    # 6. Opciones
    op = round(sum(l["peso"] for l in lineas if l["tipo"] in TIPOS_OPCIONES), 2)
    if op > u["opciones_max"]:
        add("opciones", "VIOLADO", f"{_fmt(op, '%')} vs max {u['opciones_max']}%")
        viol += 1
    elif op >= 0.9 * u["opciones_max"]:
        add("opciones", "BORDE", f"{_fmt(op, '%')} vs max {u['opciones_max']}%")

    # 7. Veredictos fragil del hijo sobre acciones de la cartera
    tickers_acc = {l["ticker"] for l in lineas if l["tipo"] == "accion"}
    for e in []:  # se completa abajo con hijos_estado
        pass
    return "\n".join("- " + r for r in reglas), viol


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
    reglas_txt, viol = armar_reglas(lineas, perfil, sectores)

    # fragil del hijo como regla textual (en armar_reglas no hay acceso al estado)
    if fragil_flags:
        for f in fragil_flags:
            reglas_txt += f"\n- veredicto fragil (hijo): REVISAR - {f}"

    datos = [
        f"Foto de cartera: {fecha_foto or 'sin fecha'} - {len(lineas)} lineas",
        "Acciones por peso (las primeras 10): "
        + ", ".join(f"{l['ticker']} {l['peso']}%" for l in acc[:10]),
        f"Top-5 acumulado: {top5}%",
        "Colchon (fci+cash): "
        + f"{round(sum(l['peso'] for l in lineas if l['tipo'] in TIPOS_COLCHON), 2)}%",
        "Renta fija AR (soberanos+subsoberanos+ONs): "
        + f"{round(sum(l['peso'] for l in lineas if l['tipo'] in TIPOS_RENTA_AR), 2)}%",
        "Opciones (bucket_manual): "
        + f"{round(sum(l['peso'] for l in lineas if l['tipo'] in TIPOS_OPCIONES), 2)}%",
        "Cripto (reportado, sin regla): "
        + f"{round(sum(l['peso'] for l in lineas if l['tipo'] == 'cripto'), 2)}%",
        "",
        "SECTORES DE TUS ACCIONES (solo acciones individuales; aca es donde "
        "hay que NOMBRAR sectores si hablas de concentracion o rotacion):",
        _bloque_sectores(lineas, sectores or {}),
        "",
        "SEGUIMIENTO DEL HIJO (empresas de tu cartera que el hijo sigue):",
        _bloque_hijo(hijos_estado, tickers),
    ]
    return {
        "propuesta": propuesta,
        "perfil": perfil_nombre,
        "datos": "\n".join(datos),
        "reglas": reglas_txt,
        "violaciones": viol,
        "politica": politica,
    }
