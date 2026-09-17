# -*- coding: utf-8 -*-
"""
main.py — Orquestador del nieto (desk-cartera): el board de analistas.

Triggers de deliberacion (si no hay ninguno: corrida liviana, sin LLM):
  A. FOTO NUEVA: la fecha E1 de la pestana 'cartera' cambia respecto de la
     ultima deliberacion -> board ESTRUCTURAL (todo el portafolio).
  B. SENAL DEL HIJO SOBRE EL NUCLEO: el estado del hijo tiene senales_hoy
     en una accion de la cartera -> board sobre ESA empresa.
  C. EVENTO: earnings en <= 7 dias de una accion del nucleo -> board sobre
     ESA empresa.

Prioridad: A > B > C. Una deliberacion por corrida (simplicidad v1).

Privacidad (reglas de la familia):
- La cartera vive SOLO en RAM. Al repo publico jamas: ni expedientes, ni
  textos de agentes, ni pesos. ultima_deliberacion.json guarda SOLO fecha
  y tipo de trigger (nada de contenido).
- El mensaje completo viaja por ntfy PRIVADO (topic del nieto). El titulo
  viaja como cabecera HTTP (solo caracteres latinos basicos: sin em-dash).
- El estado publico propio (salidas/estado.json) lleva conteos abstractos.

Reglas de la familia:
- Flujo unidireccional: madre -> hijo -> nieto. El nieto nunca escribe
  aguas arriba y su service account es Lector de la hoja.
- Cada capa con try/except propio: la corrida degrada, no muere.
"""

import json
import os
import time
from datetime import date

import gspread
import requests

from perfiles import PERFILES, ORDEN
from expediente import (leer_cartera_ram, cargar_politica, armar_expediente)
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
    """Service account del nieto (Lector). Devuelve spreadsheet. Jamas
    escribe: la cuenta no tiene permiso de escritura por diseno de Google."""
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
    """Registro MINIMO: fecha y tipo del trigger. JAMAS contenido de
    cartera (este archivo se commitea en el repo publico)."""
    with open(REGISTRO_TRIGGER, "w", encoding="utf-8") as f:
        json.dump({"tipo": tipo, "fecha_foto": fecha_foto,
                   "fecha": date.today().isoformat()}, f,
                  ensure_ascii=False, indent=2)


def _nucleo(lineas):
    return [l["ticker"] for l in lineas if l["tipo"] == "accion"]


def detectar_trigger(lineas, fecha_foto, estado_hijo, ultimo):
    """Prioridad: foto nueva > senal sobre nucleo > earnings <= 7 dias.
    Devuelve (tipo, detalle) o (None, None) = silencio. El detalle de los
    triggers B/C empieza SIEMPRE con el ticker (main lo parsea)."""
    nucleo = set(_nucleo(lineas))
    watch = (estado_hijo or {}).get("watchlist") or []

    # A. foto nueva de cartera
    if fecha_foto and fecha_foto != ultimo.get("fecha_foto"):
        return "estructura", "foto nueva de cartera"

    # B. senal del hijo sobre una accion del nucleo
    for e in watch:
        t = (e.get("ticker") or "").upper()
        if t in nucleo and (e.get("senales_hoy") or []):
            return "senal", f"{t} senal del hijo (nucleo)"

    # C. earnings de una accion del nucleo en <= 7 dias
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
            f"reciente ({fecha_foto}): concentraciones, colchon, sectores, "
            "y las acciones del nucleo que el hijo sigue. Proponé movimientos "
            "solo si hay violaciones o bordes; si todo OK, sentencia ESPERAR "
            "con el punto que mas importe.")


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


def armar_expedientes_perfiles(lineas, fecha_foto, estado_hijo, politica,
                               tipo, detalle):
    """Un expediente por perfil. Devuelve (expedientes, ticker_objetivo)."""
    out = {}
    if tipo == "estructura":
        prop = _propuesta_estructura(fecha_foto)
        for nombre in ORDEN:
            out[nombre] = armar_expediente(lineas, fecha_foto, nombre,
                                           PERFILES[nombre], estado_hijo,
                                           politica, prop)
        return out, None
    # senal o evento: el detalle empieza con el ticker
    ticker = detalle.split()[0].upper()
    e_h = _e_hijo_de(estado_hijo, ticker)
    prop = _propuesta_empresa(ticker, detalle, e_h)
    for nombre in ORDEN:
        out[nombre] = armar_expediente(lineas, fecha_foto, nombre,
                                       PERFILES[nombre], estado_hijo,
                                       politica, prop)
    return out, ticker


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

    # 4. expedientes (uno por perfil)
    expedientes, ticker_objetivo = armar_expedientes_perfiles(
        lineas, fecha_foto, estado_hijo, politica, tipo, detalle)
    print(f"trigger: {tipo} | expedientes armados: {len(expedientes)}")

    # 5. board (9 agentes)
    key = os.environ.get("GROQ_API_KEY", "").strip()
    modelo = cargar_modelo()
    mensaje, linea_log = deliberar_board(
        expedientes, key, modelo,
        trigger_log=f"{tipo} - {detalle}")
    print(linea_log)

    # 6. ntfy privado (contenido completo; titulo SOLO caracteres latinos)
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

    # 7. registro minimo (fecha/tipo, jamas contenido)
    guardar_ultimo(tipo, fecha_foto if tipo == "estructura" else None)

    # 8. estado publico
    publicar_estado(tipo, linea_log, len(estado_hijo.get("watchlist", [])))
    print("estado.json del nieto publicado")


# --------------------------------------------------------------- arranque
if __name__ == "__main__":
    main()
