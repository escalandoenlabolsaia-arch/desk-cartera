# -*- coding: utf-8 -*-
"""
main.py — Orquestador del nieto (desk-cartera): el board de analistas.

v5: el FUND MANAGER entra al board como cuarta voz. Un agente que opina
SIN las reglas del usuario (ni siquiera las recibe) y que ademas se nutre
de las OPORTUNIDADES RECIENTES del detector (senales de la madre que viven
en el estado del hijo y NO estan en la cartera): ahi nacen sus ideas de
rotacion o cobertura. Consenso final de 4 voces.

Envio: un mensaje ntfy por voz (cortos y autocontenidos, fin de las
partes cortadas), titulos que identifican cada voz.

Triggers de deliberacion (si no hay ninguno: corrida liviana, sin LLM):
  A. FOTO NUEVA: la fecha E1 de la pestana 'cartera' cambia -> ESTRUCTURA.
  B. SENAL DEL HIJO SOBRE EL NUCLEO -> board sobre ESA empresa.
  C. EVENTO: earnings en <= 7 dias de una accion del nucleo -> ESA empresa.

Prioridad: A > B > C. Una deliberacion por corrida (simplicidad v1).
REGLA DE REGISTRO: el trigger solo se marca atendido si el board delibero
COMPLETO (todas las voces). Incompleto = la proxima corrida reintenta sola.

Privacidad (reglas de la familia):
- La cartera vive SOLO en RAM (incluido el mapa de sectores y el bloque
  de oportunidades: guardarlo seria publicar la cartera). Al repo jamas.
- Los mensajes completos viajan por ntfy PRIVADO. Titulos solo latinos.
- ultima_deliberacion.json y salidas/estado.json: solo fecha/tipo/conteos.
- Flujo unidireccional: madre -> hijo -> nieto. Service account Lector.
"""

import json
import os
import time
from datetime import date

import gspread
import requests

from perfiles import PERFILES, ORDEN
from expediente import (leer_cartera_ram, cargar_politica, armar_expediente,
                        obtener_sectores)
from board import deliberar_board, cargar_modelo, FM_EMOJI

REGISTRO_TRIGGER = "ultima_deliberacion.json"


def cargar_config():
    with open("config.json", "r", encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------- hijo
def descargar_estado_hijo(cfg):
    """Descarga el estado publico del hijo (contrato v1). 3 reintentos."""
    hcfg = cfg.get("hijo", {})
    url = (hcfg.get("estado_url") or "").strip()
    max_atraso = int(hcfg.get("max_atraso_dias", 2))
    if not url or "USUARIO" in url:
        return None, "hijo.estado_url sin configurar (reemplazá USUARIO)"
    resultado = None
    for intento in range(1, 4):
        try:
            r = requests.get(url, timeout=30,
                             headers={"User-Agent": "desk-cartera/1.0"})
            if r.status_code == 200:
                resultado = r.json()
                break
            resultado = f"HTTP {r.status_code}"
        except Exception as e:
            resultado = type(e).__name__
        if intento < 3:
            time.sleep(5 * intento)
    if not isinstance(resultado, dict):
        pista = (" (¿existe salidas/estado.json en el repo hijo? ¿URL del "
                 "boton Raw?)" if "404" in str(resultado) else "")
        return None, f"fallo descarga ({resultado}){pista}"
    if resultado.get("version") != 1:
        return None, f"contrato inesperado: version {resultado.get('version')}"
    try:
        fecha = date.fromisoformat(str(resultado.get("fecha"))[:10])
    except ValueError:
        return None, "estado del hijo sin fecha valida"
    atraso = (date.today() - fecha).days
    if atraso > max_atraso:
        print(f"  AVISO: estado del hijo con {atraso} dias de atraso "
              f"({fecha.isoformat()}); sigo con el ultimo valido")
    return resultado, "ok"


# --------------------------------------------------------------- hoja
def conectar_hoja(cfg):
    """Service account del nieto (Lector). Jamas escribe."""
    cred = json.loads(os.environ["GSA_JSON_NIETO"])
    sheet_id = os.environ["SHEET_ID_NIETO"].strip()
    gc = gspread.service_account_from_dict(cred)
    return gc.open_by_key(sheet_id)


# --------------------------------------------------------------- triggers
def cargar_ultimo():
    if os.path.exists(REGISTRO_TRIGGER):
        try:
            with open(REGISTRO_TRIGGER, "r", encoding="utf-8") as f:
                d = json.load(f)
            if "fecha_foto" in d or "tipo" in d:
                return d
        except (json.JSONDecodeError, OSError):
            pass
    return {"fecha_foto": None, "tipo": None, "fecha": None}


def guardar_ultimo(tipo, fecha_foto):
    """Registro MINIMO: fecha y tipo del trigger. JAMAS contenido."""
    with open(REGISTRO_TRIGGER, "w", encoding="utf-8") as f:
        json.dump({"tipo": tipo, "fecha_foto": fecha_foto,
                   "fecha": date.today().isoformat()}, f,
                  ensure_ascii=False, indent=2)


def _nucleo(lineas):
    return [l["ticker"] for l in lineas if l["tipo"] == "accion"]


def detectar_trigger(lineas, fecha_foto, estado_hijo, ultimo):
    """Prioridad: foto nueva > senal sobre nucleo > earnings <= 7 dias.
    El detalle de B/C empieza SIEMPRE con el ticker (main lo parsea)."""
    nucleo = set(_nucleo(lineas))
    watch = (estado_hijo or {}).get("watchlist") or []

    if fecha_foto and fecha_foto != ultimo.get("fecha_foto"):
        return "estructura", "foto nueva de cartera"

    for e in watch:
        t = (e.get("ticker") or "").upper()
        if t in nucleo and (e.get("senales_hoy") or []):
            return "senal", f"{t} senal del hijo (nucleo)"

    for e in watch:
        t = (e.get("ticker") or "").upper()
        if t not in nucleo or not e.get("proximo_earnings"):
            continue
        try:
            dias = (date.fromisoformat(str(e["proximo_earnings"])[:10])
                    - date.today()).days
        except ValueError:
            continue
        if 0 <= dias <= 7:
            return "evento", f"{t} earnings en {dias} dias (nucleo)"
    return None, None


# --------------------------------------------------------------- oportunidades
def bloque_oportunidades(estado_hijo, lineas, max_nombres=5):
    """Bloque para el FM: senales recientes del detector (via estado del
    hijo) que NO estan en la cartera. Devuelve (texto, count). Con 0
    oportunidades, el FM opina igual: el bloque se lo explica."""
    en_cartera = {l["ticker"] for l in lineas}
    oportunidades = []
    for e in (estado_hijo or {}).get("watchlist", []):
        t = (e.get("ticker") or "").upper()
        if not t or t in en_cartera:
            continue
        origenes = ", ".join(e.get("origen") or []) or "senal"
        oportunidades.append(
            f"{t} ({e.get('sector') or 'sector n/d'}): via {origenes}, "
            f"veredicto del hijo {e.get('veredicto') or 'n/d'}, "
            f"seguida desde {e.get('desde', 'n/d')}")
    if not oportunidades:
        return ("(El detector de la madre no trae oportunidades fuera de "
                "tu cartera en este momento.)", 0)
    texto = ("\n".join(f"- {o}" for o in oportunidades[:max_nombres])
             + (f" (y {max(0, len(oportunidades) - max_nombres)} mas)"
                if len(oportunidades) > max_nombres else ""))
    return texto, min(len(oportunidades), max_nombres)


# --------------------------------------------------------------- expedientes
def _propuesta_estructura(fecha_foto):
    return ("Deliberar la ESTRUCTURA de la cartera segun la foto mas "
            f"reciente ({fecha_foto}): concentraciones (nombrando sector), "
            "colchon, sectores, y las acciones del nucleo que el hijo "
            "sigue. Proponé movimientos solo si hay reglas que no se "
            "cumplen o están en borde; si todo OK, sentencia ESPERAR con "
            "el punto que mas importe.")


def _propuesta_empresa(ticker, detalle, e_hijo):
    return (f"Deliberar la posicion de {ticker} en la cartera. Motivo: "
            f"{detalle}. Dato del hijo: veredicto "
            f"{(e_hijo or {}).get('veredicto') or 'n/d'}, "
            f"earnings {(e_hijo or {}).get('proximo_earnings') or 'n/d'}.")


def _e_hijo_de(estado_hijo, ticker):
    for e in (estado_hijo or {}).get("watchlist", []):
        if (e.get("ticker") or "").upper() == ticker.upper():
            return e
    return {}


def _fragil_flags(estado_hijo, lineas):
    tickers_acc = {l["ticker"] for l in lineas if l["tipo"] == "accion"}
    flags = []
    for e in (estado_hijo or {}).get("watchlist", []):
        t = (e.get("ticker") or "").upper()
        if t in tickers_acc and e.get("veredicto") == "fragil":
            flags.append(f"{t} score fragil en el hijo")
    return flags


def armar_expedientes(lineas, fecha_foto, estado_hijo, politica,
                      tipo, detalle, sectores):
    """Expedientes de los 3 perfiles + el expediente del FM (que recibe
    el bloque de oportunidades del detector). Devuelve (perfiles, fm,
    ticker_objetivo)."""
    if tipo == "estructura":
        prop = _propuesta_estructura(fecha_foto)
        ticker_obj = None
    else:
        ticker = detalle.split()[0].upper()
        e_h = _e_hijo_de(estado_hijo, ticker)
        prop = _propuesta_empresa(ticker, detalle, e_h)
        ticker_obj = ticker
    fragil = _fragil_flags(estado_hijo, lineas)

    perfiles = {}
    for nombre in ORDEN:
        perfiles[nombre] = armar_expediente(lineas, fecha_foto, nombre,
                                            PERFILES[nombre], estado_hijo,
                                            politica, prop,
                                            sectores=sectores,
                                            fragil_flags=fragil)

    # El expediente del FM: mismo base + bloque de oportunidades
    fm = dict(perfiles["conservador"])   # copia con mismos datos/politica
    oport_texto, oport_n = bloque_oportunidades(estado_hijo, lineas)
    fm["propuesta"] = prop + (
        "\n\nOPORTUNIDADES RECIENTES DEL DETECTOR (fuera de tu cartera; "
        "usallas si sirven para ideas de rotacion o cobertura; si no, "
        "ignoralas):\n" + oport_texto)
    fm["oportunidades_n"] = oport_n
    return perfiles, fm, ticker_obj


# --------------------------------------------------------------- ntfy
def enviar_ntfy(topic, texto, titulo="Board de Cartera"):
    """Un mensaje corto por voz. Corte que prefiere fin de linea y luego
    fin de oracion. Titulo solo caracteres latinos basicos."""
    MAX = 2500
    partes, resto = [], texto
    while len(resto) > MAX:
        corte = resto.rfind("\n", 0, MAX)
        if corte == -1:
            corte = resto.rfind(". ", 0, MAX)
            if corte != -1:
                corte += 1
        if corte == -1:
            corte = MAX
        partes.append(resto[:corte])
        resto = resto[corte:].lstrip()
    if resto:
        partes.append(resto)
    for i, parte in enumerate(partes, start=1):
        sufijo = f" ({i}/{len(partes)})" if len(partes) > 1 else ""
        ok = False
        for intento in range(3):
            try:
                r = requests.post(
                    f"https://ntfy.sh/{topic}",
                    data=parte.encode("utf-8"),
                    headers={"Title": f"{titulo}{sufijo}",
                             "Priority": "high",
                             "Tags": "chart", "Markdown": "yes"},
                    timeout=30,
                )
                r.raise_for_status()
                ok = True
                break
            except Exception as e:
                print(f"  ntfy intento {intento + 1} fallo: {e}")
                time.sleep(5)
        if not ok:
            raise RuntimeError(f"No se pudo enviar la parte {i} a ntfy")
        time.sleep(2)


# --------------------------------------------------------------- estado publico
def publicar_estado(tipo, linea_log, n_empresas_hijo):
    """Estado publico del nieto: SOLO conteos abstractos. JAMAS cartera."""
    estado = {
        "version": 1,
        "fecha": date.today().isoformat(),
        "corrida_ok": True,
        "ultima_deliberacion": {"tipo": tipo, "linea_log": linea_log},
        "resumen": {"empresas_en_estado_hijo": n_empresas_hijo},
    }
    os.makedirs("salidas", exist_ok=True)
    with open(os.path.join("salidas", "estado.json"), "w",
              encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


# --------------------------------------------------------------- orquestacion
def main():
    cfg = cargar_config()
    print("board: arranque")

    # 1. estado del hijo
    estado_hijo, aviso = descargar_estado_hijo(cfg)
    if estado_hijo is None:
        raise RuntimeError(f"sin estado del hijo: {aviso}")
    print(f"estado hijo ok (fecha {estado_hijo.get('fecha')})")

    # 2. hoja (Lector) + politica — todo en RAM
    sheet = conectar_hoja(cfg)
    lineas, fecha_foto, resumen_lectura = leer_cartera_ram(
        sheet, cfg.get("cartera", {}).get("pestana", "cartera"))
    if not lineas:
        raise RuntimeError(f"cartera ilegible: {resumen_lectura}")
    print(f"cartera: {resumen_lectura} (solo RAM)")
    politica = cargar_politica(sheet)
    print(f"politica: {'leida' if politica else 'no encontrada (sigo sin ella)'}")

    # 3. trigger
    ultimo = cargar_ultimo()
    tipo, detalle = detectar_trigger(lineas, fecha_foto, estado_hijo, ultimo)
    if tipo is None:
        print("board: sin triggers hoy (silencio = todo bien)")
        publicar_estado(None, "sin deliberacion",
                        len(estado_hijo.get("watchlist", [])))
        return

    # 4. sectores reales en RAM (gratis del hijo, yfinance para el resto)
    sectores = obtener_sectores(lineas, estado_hijo)
    resueltos = sum(1 for l in lineas
                    if l["tipo"] == "accion" and l["ticker"] in sectores)
    total_acc = sum(1 for l in lineas if l["tipo"] == "accion")
    print(f"sectores: {resueltos}/{total_acc} acciones clasificadas (RAM)")

    # 5. expedientes: 3 perfiles + FM (con oportunidades del detector)
    perfiles_exp, fm_exp, ticker_objetivo = armar_expedientes(
        lineas, fecha_foto, estado_hijo, politica, tipo, detalle, sectores)
    oport = fm_exp.get("oportunidades_n") or 0
    print(f"trigger: {tipo} | expedientes: 3 perfiles + FM "
          f"(oportunidades del detector: {oport})")

    # 6. board (3 perfiles + fund manager)
    key = os.environ.get("GROQ_API_KEY", "").strip()
    modelo = cargar_modelo()
    mensajes, linea_log, ok_count, total_voces = deliberar_board(
        perfiles_exp, fm_exp, key, modelo,
        trigger_log=f"{tipo} - {detalle}")
    print(linea_log)

    # 7. ntfy privado: un mensaje por voz, titulos que identifican
    topic = os.environ.get("NTFY_TOPIC_NIETO", "").strip()
    if topic:
        try:
            titulos = [f"Board - {t.upper()}"
                       for t in list(ORDEN) + ["FM", "consenso"]]
            for titulo, mensaje in zip(titulos, mensajes):
                enviar_ntfy(topic, mensaje, titulo=titulo)
            print(f"ntfy: {len(mensajes)} mensajes enviados")
        except Exception as e:
            print(f"  AVISO: ntfy fallo ({type(e).__name__}); la corrida sigue")
    else:
        print("  AVISO: sin NTFY_TOPIC_NIETO: deliberacion NO enviada")

    # 8. registro: SOLO con board completo (todas las voces). Incompleto =
    # el trigger queda vivo y la proxima corrida reintenta sola.
    if ok_count == total_voces:
        guardar_ultimo(tipo, fecha_foto if tipo == "estructura" else None)
    else:
        print(f"  AVISO: board incompleto ({ok_count}/{total_voces}): NO "
              f"registro el trigger -> la proxima corrida reintenta")

    # 9. estado publico
    publicar_estado(tipo, linea_log, len(estado_hijo.get("watchlist", [])))
    print("estado.json del nieto publicado")


# --------------------------------------------------------------- arranque
if __name__ == "__main__":
    main()
