# -*- coding: utf-8 -*-
"""
main.py — Orquestador del nieto (desk-cartera): el board de analistas.

v2 (post-estreno): sectores REALES por nombre (expediente.py los baja en
RAM), fragil-flags del hijo integrados a las reglas, y la regla de registro
aprendida: el trigger solo se marca atendido si el board delibero 3/3.

Triggers de deliberacion (si no hay ninguno: corrida liviana, sin LLM):
  A. FOTO NUEVA: la fecha E1 de la pestana 'cartera' cambia -> ESTRUCTURA.
  B. SENAL DEL HIJO SOBRE EL NUCLEO -> board sobre ESA empresa.
  C. EVENTO: earnings en <= 7 dias de una accion del nucleo -> ESA empresa.

Prioridad: A > B > C. Una deliberacion por corrida (simplicidad v1).

Privacidad (reglas de la familia):
- La cartera vive SOLO en RAM (incluido el mapa de sectores: guardarlo
  seria publicar la cartera). Al repo publico jamas.
- El mensaje completo viaja por ntfy PRIVADO. El titulo viaja como
  cabecera HTTP: solo caracteres latinos basicos.
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
from board import deliberar_board, cargar_modelo

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


# --------------------------------------------------------------- expedientes
def _propuesta_estructura(fecha_foto):
    return ("Deliberar la ESTRUCTURA de la cartera segun la foto mas "
            f"reciente ({fecha_foto}): concentraciones (nombrando sector), "
            "colchon, sectores, y las acciones del nucleo que el hijo "
            "sigue. Proponé movimientos solo si hay reglas incumplidas o "
            "en borde; si todo OK, sentencia ESPERAR con el punto que mas "
            "importe.")


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
    """Acciones de la cartera con veredicto 'fragil' del hijo."""
    tickers_acc = {l["ticker"] for l in lineas if l["tipo"] == "accion"}
    flags = []
    for e in (estado_hijo or {}).get("watchlist", []):
        t = (e.get("ticker") or "").upper()
        if t in tickers_acc and e.get("veredicto") == "fragil":
            flags.append(f"{t} score fragil en el hijo")
    return flags


def armar_expedientes_perfiles(lineas, fecha_foto, estado_hijo, politica,
                               tipo, detalle, sectores):
    """Un expediente por perfil. Devuelve (expedientes, ticker_objetivo)."""
    out = {}
    if tipo == "estructura":
        prop = _propuesta_estructura(fecha_foto)
        ticker_obj = None
    else:
        ticker = detalle.split()[0].upper()
        e_h = _e_hijo_de(estado_hijo, ticker)
        prop = _propuesta_empresa(ticker, detalle, e_h)
        ticker_obj = ticker
    fragil = _fragil_flags(estado_hijo, lineas)
    for nombre in ORDEN:
        out[nombre] = armar_expediente(lineas, fecha_foto, nombre,
                                       PERFILES[nombre], estado_hijo,
                                       politica, prop,
                                       sectores=sectores, fragil_flags=fragil)
    return out, ticker_obj


# --------------------------------------------------------------- ntfy
def enviar_ntfy(topic, texto, titulo="Board de Cartera"):
    MAX = 3800
    partes, resto = [], texto
    while len(resto) > MAX:
        corte = resto.rfind("\n", 0, MAX)
        if corte == -1:
            corte = MAX
        partes.append(resto[:corte])
        resto = resto[corte:].lstrip("\n")
    if resto:
        partes.append(resto)
    for i, parte in enumerate(partes, start=1):
        ok = False
        for intento in range(3):
            try:
                r = requests.post(
                    f"https://ntfy.sh/{topic}",
                    data=parte.encode("utf-8"),
                    headers={"Title": titulo, "Priority": "high",
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

    # 5. expedientes (uno por perfil)
    expedientes, ticker_objetivo = armar_expedientes_perfiles(
        lineas, fecha_foto, estado_hijo, politica, tipo, detalle, sectores)
    print(f"trigger: {tipo} | expedientes armados: {len(expedientes)}")

    # 6. board (9 agentes)
    key = os.environ.get("GROQ_API_KEY", "").strip()
    modelo = cargar_modelo()
    mensaje, linea_log, ok_count = deliberar_board(
        expedientes, key, modelo,
        trigger_log=f"{tipo} - {detalle}")
    print(linea_log)

    # 7. ntfy privado (titulo SOLO caracteres latinos)
    topic = os.environ.get("NTFY_TOPIC_NIETO", "").strip()
    if topic:
        try:
            enviar_ntfy(topic, mensaje,
                        titulo=f"Board - {tipo}: {ticker_objetivo or 'estructura'}")
            print("ntfy: deliberacion enviada")
        except Exception as e:
            print(f"  AVISO: ntfy fallo ({type(e).__name__}); la corrida sigue")
    else:
        print("  AVISO: sin NTFY_TOPIC_NIETO: deliberacion NO enviada")

    # 8. registro: SOLO con board completo (3/3). Incompleto = reintento
    # automatico en la proxima corrida.
    if ok_count == 3:
        guardar_ultimo(tipo, fecha_foto if tipo == "estructura" else None)
    else:
        print(f"  AVISO: board incompleto ({ok_count}/3): NO registro el "
              f"trigger -> la proxima corrida reintenta")

    # 9. estado publico
    publicar_estado(tipo, linea_log, len(estado_hijo.get("watchlist", [])))
    print("estado.json del nieto publicado")


# --------------------------------------------------------------- arranque
if __name__ == "__main__":
    main()
