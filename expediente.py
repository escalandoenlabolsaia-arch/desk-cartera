# -*- coding: utf-8 -*-
"""
expediente.py — El expediente del board: aritmetica hecha por Python.

Regla de arquitectura del diseno: los 9 agentes NO calculan nada. Este
modulo lee la cartera (en RAM), el estado publico del hijo y los perfiles,
hace TODAS las cuentas (techos, top-5, sectores, colchon, renta fija AR,
opciones) y arma un paquete de datos con cada regla flaggeada
VIOLADO / BORDE / OK y el numero exacto. Los agentes debaten que hacer
sobre hechos verificables.

Tipos de activo (vocabulario de la hoja):
- accion/etf        -> cuentan para techos, top-5 y sector
- fci/cash          -> colchon
- bono_soberano/bono_subsoberano/on -> colchon + renta fija AR
- bucket_manual     -> opciones (se mide contra opciones_max; no en top-5)
- cripto            -> se REPORTA, no se flaggea (sin regla en v1)

Privacidad: todo lo que este modulo produce vive SOLO en RAM y viaja al
chat de Groq (topic privado). Jamas se persiste en el repo publico.
"""

import json
import os
from datetime import date

TIPOS_COLCHON = {"fci", "cash"}
TIPOS_RENTA_AR = {"bono_soberano", "bono_subsoberano", "on"}
TIPOS_ACCIONES = {"accion", "etf"}
TIPOS_OPCIONES = {"bucket_manual"}


def cargar_politica(sheet):
    """Lee la pestana 'politica' de la hoja (texto libre del usuario).
    Devuelve el texto plano o None. Si falla: None y el board sigue
    (la politica es municon extra, no requisito)."""
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


def _fmt(x, suf=""):
    return "n/d" if x is None else f"{x}{suf}"


# ------------------------------------------------------- lectura en RAM
def leer_cartera_ram(sheet, pestana="cartera", tol=3.0):
    """Lee la foto de cartera desde la service account del nieto (Lector).
    Devuelve (lineas, fecha_foto, ok). Todo queda en RAM del proceso."""
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


# ------------------------------------------------------- aritmetica
def _top_n(lineas, n=5):
    acc = sorted((l for l in lineas if l["tipo"] in TIPOS_ACCIONES),
                 key=lambda l: -l["peso"])
    return acc[:n], round(sum(l["peso"] for l in acc[:n]), 2)


def _sectores(lineas, hijos_estado):
    """Agrega pesos por sector usando el sector del estado del hijo
    (solo acciones/ETFs). Lo que no tiene sector en el hijo queda 'n/d'."""
    out = {}
    for l in lineas:
        if l["tipo"] not in TIPOS_ACCIONES:
            continue
        sec = None
        for e in (hijos_estado or {}).get("watchlist", []):
            if e.get("ticker") == l["ticker"]:
                sec = e.get("sector")
                break
        key = sec or "n/d"
        out[key] = round(out.get(key, 0) + l["peso"], 2)
    return out


def armar_reglas(lineas, perfil, hijos_estado):
    """Aplica el perfil a la cartera: cada regla con estado y numero exacto.
    Devuelve (texto_reglas, violaciones_count)."""
    u = perfil
    reglas, viol = [], 0

    def add(nombre, estado, detalle):
        reglas.append(f"{nombre}: {estado} — {detalle}")

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
        estado = "VIOLADO"; viol += 1
    elif top5 >= 0.9 * u["top5_max"]:
        estado = "BORDE"
    else:
        estado = "OK"
    if estado != "OK":
        add("top-5 acumulado", estado,
            f"{_fmt(top5, '%')} vs max {u['top5_max']}%")

    # 3. Sectores (solo si algo viola/bordea el default del perfil)
    for sec, peso in sorted(_sectores(lineas, hijos_estado).items(),
                            key=lambda kv: -kv[1]):
        max_sec = u.get("sector_default_max", 1000)
        if peso > max_sec:
            add("sector " + sec, "VIOLADO",
                f"{_fmt(peso, '%')} vs max {max_sec}%")
            viol += 1
        elif peso >= 0.9 * max_sec:
            add("sector " + sec, "BORDE",
                f"{_fmt(peso, '%')} vs max {max_sec}%")

    # 4. Colchon (fci + cash)
    col = round(sum(l["peso"] for l in lineas if l["tipo"] in TIPOS_COLCHON), 2)
    if col < u["colchon_min"]:
        add("colchon fijo/cash", "VIOLADO",
            f"{_fmt(col, '%')} vs min {u['colchon_min']}%")
        viol += 1
    elif col < u["colchon_min"] * 1.1:
        add("colchon fijo/cash", "BORDE",
            f"{_fmt(col, '%')} vs min {u['colchon_min']}%")

    # 5. Renta fija AR
    rf = round(sum(l["peso"] for l in lineas if l["tipo"] in TIPOS_RENTA_AR), 2)
    if rf > u["renta_fija_ar_max"]:
        add("renta fija AR", "VIOLADO",
            f"{_fmt(rf, '%')} vs max {u['renta_fija_ar_max']}%")
        viol += 1

    # 6. Opciones (bucket_manual)
    op = round(sum(l["peso"] for l in lineas if l["tipo"] in TIPOS_OPCIONES), 2)
    if op > u["opciones_max"]:
        add("opciones", "VIOLADO",
            f"{_fmt(op, '%')} vs max {u['opciones_max']}%")
        viol += 1
    elif op >= 0.9 * u["opciones_max"]:
        add("opciones", "BORDE", f"{_fmt(op, '%')} vs max {u['opciones_max']}%")

    # 7. Veredictos 'fragil' del hijo sobre acciones de la cartera
    for e in (hijos_estado or {}).get("watchlist", []):
        if e.get("veredicto") == "fragil" and e.get("ticker") in {
                l["ticker"] for l in lineas if l["tipo"] == "accion"}:
            add("veredicto fragil (hijo)", "REVISAR",
                f"{e['ticker']} score fragil en el hijo")

    if not reglas:
        reglas.append("(sin violaciones ni bordes: todas las reglas OK)")
    return "\n".join("- " + r for r in reglas), viol


def _bloque_hijo(hijos_estado, tickers_cartera):
    """Lineas por accion de la cartera que el hijo tambien sigue."""
    out = []
    for e in (hijos_estado or {}).get("watchlist", []):
        t = e.get("ticker")
        if t and t in tickers_cartera:
            out.append(f"{t}: peso {_fmt(e.get('precio') and round(e['precio'],2))}, "
                       f"veredicto {e.get('veredicto') or 'n/d'}, "
                       f"desde {e.get('desde', 'n/d')} "
                       f"({e.get('dias_seguimiento', '?')} dias), "
                       f"senales recientes {', '.join(e.get('senales_hoy') or []) or 'ninguna'}, "
                       f"earnings {e.get('proximo_earnings') or 'n/d'}")
    return "\n".join("- " + l for l in out) or "(el hijo no sigue ninguna accion de la cartera)"


def armar_expediente(lineas, fecha_foto, perfil_nombre, perfil, hijos_estado,
                     politica, propuesta):
    """Arma el dict-expediente que leen los 3 agentes de UN perfil."""
    acc, top5 = _top_n(lineas)
    tickers = {l["ticker"] for l in lineas}
    reglas_txt, viol = armar_reglas(lineas, perfil, hijos_estado)
    datos = [
        f"Foto de cartera: {fecha_foto or 'sin fecha'} — {len(lineas)} lineas",
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
