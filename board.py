# -*- coding: utf-8 -*-
"""
board.py — El motor de deliberacion: 3 perfiles (toro/oso/juez) + el
FUND MANAGER (mirada libre, sin reglas del usuario).

v4: dos novedades
1) El FM: cuarto miembro del board. Un solo agente (sin toro/oso: su
   valor es la mirada unica) que ademas puede recibir un bloque de
   OPORTUNIDADES RECIENTES del detector (senales de la madre que viven en
   el estado del hijo) para ideas de rotacion o cobertura.
2) Mensaje ntfy SEPARADO por voz (conservador / moderado / agresivo / FM /
   consenso): mensajes cortos y autocontenidos — fin de las partes
   cortadas. Cada titulo identifica la voz.

El consenso cuenta 4 veredictos (3 jueces + FM). Si coinciden los cuatro,
el mensaje lo celebra explicitamente: senal fuerte.

Privacidad: los textos citan datos de la cartera -> JAMAS al log publico.
linea_log: conteo abstracto sin tickers ni perfiles asociados.

Contrato con main.py: deliberar_board devuelve (mensajes, linea_log,
ok_count, total_voces). main.py SOLO registra el trigger si
ok_count == total_voces.
"""

import json
import os
import time

import requests

from prompts import (prompt_sistema, prompt_usuario_toro, prompt_usuario_oso,
                     prompt_usuario_juez, prompt_usuario_fm,
                     extraer_veredicto)
from perfiles import PERFILES, ORDEN

DEFAULT_MODELO = "openai/gpt-oss-120b"
FM_EMOJI = "👨‍💼"


def cargar_modelo():
    """Modelo Groq desde config.json del nieto (misma filosofia que la
    madre y el hijo: el modelo se cambia SOLO tocando config)."""
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            return (json.load(f).get("ia") or {}).get("modelo") or DEFAULT_MODELO
    except Exception:
        return DEFAULT_MODELO


# --------------------------------------------------------------- groq
def _llamar_groq(sys_prompt, user_prompt, key, modelo, max_tokens):
    """Una llamada al modelo con reintentos paciente ante 429 (limite de
    velocidad). Devuelve texto o None (falla definitiva -> None)."""
    esperas = [10, 20, 30, 30]
    for intento in range(1, len(esperas) + 2):
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": modelo,
                    "messages": [
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "reasoning_effort": "low",
                    "max_tokens": max_tokens,
                    "temperature": 0.4,
                },
                timeout=40,
            )
            if r.status_code == 429:
                espera = esperas[min(intento - 1, len(esperas) - 1)]
                print(f"  Groq 429 (limite de velocidad), espero {espera}s "
                      f"(intento {intento}/{len(esperas) + 1})")
                time.sleep(espera)
                continue
            r.raise_for_status()
            return (r.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception as e:
            print(f"  Groq fallo: {e}")
            return None
    print("  Groq 429 persistente tras todos los reintentos")
    return None


def _recortar(texto, max_lineas):
    lineas = [l.strip() for l in (texto or "").splitlines() if l.strip()]
    return "\n".join(lineas[:max_lineas])


def _quitar_veredicto(texto):
    partes = (texto or "").split("VEREDICTO:")
    return partes[0].strip()


# --------------------------------------------------------------- perfil (toro/oso/juez)
def deliberar_perfil(expediente, perfil_nombre, key, modelo):
    """Toro -> Oso (lee al toro) -> Juez (lee ambos)."""
    res = {"perfil": perfil_nombre, "emoji": PERFILES[perfil_nombre]["emoji"],
           "toro": None, "oso": None, "juez": None, "veredicto": None}

    texto_toro = _llamar_groq(prompt_sistema("toro", perfil_nombre),
                              prompt_usuario_toro(expediente),
                              key, modelo, max_tokens=500)
    if not texto_toro:
        res["fallo"] = "toro no respondio"
        return res
    res["toro"] = _recortar(texto_toro, 4)

    texto_oso = _llamar_groq(prompt_sistema("oso", perfil_nombre),
                             prompt_usuario_oso(expediente, res["toro"]),
                             key, modelo, max_tokens=500)
    if not texto_oso:
        res["fallo"] = "oso no respondio"
        return res
    res["oso"] = _recortar(texto_oso, 4)

    sys_juez = prompt_sistema("juez", perfil_nombre)
    texto_juez = _llamar_groq(sys_juez,
                              prompt_usuario_juez(expediente, res["toro"],
                                                  res["oso"]),
                              key, modelo, max_tokens=800)
    veredicto = extraer_veredicto(texto_juez)
    if veredicto is None:
        texto_juez = _llamar_groq(
            sys_juez,
            prompt_usuario_juez(expediente, res["toro"], res["oso"])
            + "\n\nRECORDATORIO: tu respuesta DEBE incluir el veredicto "
              "escrito como 'VEREDICTO: ACCIONAR' o 'VEREDICTO: ESPERAR' o "
              "'VEREDICTO: REVISAR'.",
            key, modelo, max_tokens=800)
        veredicto = extraer_veredicto(texto_juez)

    res["juez"] = _recortar(texto_juez, 8) if texto_juez else None
    res["veredicto"] = veredicto
    return res


# --------------------------------------------------------------- FM (1 llamada)
def deliberar_fm(expediente, key, modelo):
    """El Fund Manager: UNA llamada, sin toro/oso (su valor es la mirada
    unica y libre)."""
    res = {"perfil": "fm", "emoji": FM_EMOJI, "texto": None, "veredicto": None}
    sys_fm = prompt_sistema("fm", None)
    texto = _llamar_groq(sys_fm, prompt_usuario_fm(expediente),
                         key, modelo, max_tokens=600)
    veredicto = extraer_veredicto(texto)
    if veredicto is None:
        texto = _llamar_groq(
            sys_fm,
            prompt_usuario_fm(expediente)
            + "\n\nRECORDATORIO: tu respuesta DEBE incluir el veredicto "
              "escrito como 'VEREDICTO: ACCIONAR' o 'VEREDICTO: ESPERAR' o "
              "'VEREDICTO: REVISAR'.",
            key, modelo, max_tokens=600)
        veredicto = extraer_veredicto(texto)
    res["texto"] = _recortar(texto, 10) if texto else None
    res["veredicto"] = veredicto
    if not texto:
        res["fallo"] = "FM no respondio"
    return res


# --------------------------------------------------------------- board completo
def deliberar_board(expedientes, expediente_fm, key, modelo,
                    trigger_log="deliberacion"):
    """Corre 3 perfiles + FM. Devuelve (mensajes, linea_log, ok_count,
    total_voces). mensajes: LISTA de mensajes ntfy cortos (uno por voz +
    consenso). linea_log: conteo abstracto (publico)."""
    resultados = []
    for nombre in ORDEN:
        exp = expedientes.get(nombre)
        if exp is None:
            resultados.append({"perfil": nombre, "emoji": PERFILES[nombre]["emoji"],
                               "veredicto": None, "fallo": "sin expediente"})
            continue
        r = deliberar_perfil(exp, nombre, key, modelo)
        resultados.append(r)
        time.sleep(5)

    res_fm = None
    if expediente_fm is not None:
        res_fm = deliberar_fm(expediente_fm, key, modelo)
        time.sleep(5)

    voces = resultados + ([res_fm] if res_fm is not None else [])
    veredictos = [v.get("veredicto") for v in voces]
    validos = [v for v in veredictos if v]
    total = len(voces)

    if len(validos) == total and len(set(validos)) == 1 and total >= 3:
        consenso = f"UNANIMIDAD en {validos[0]}"
    elif len(validos) >= 2 and len(set(validos)) == 1:
        consenso = f"mayoria {len(validos)}/{total} en {validos[0]}"
    elif validos:
        consenso = "sin coincidencias (" + ", ".join(
            f"{v['emoji']}{x or '?'}" for v, x in zip(voces, veredictos)) + ")"
    else:
        consenso = "sin sentencias validas"

    # ---- mensajes privados: UNO por voz, cortos y autocontenidos ----
    mensajes = []
    for r in resultados:
        e, nombre = r["emoji"], r["perfil"].upper()
        v = r.get("veredicto")
        etiqueta = v if v else ("SIN SENTENCIA" if not r.get("fallo") else "FALLO TECNICO")
        l = [f"{e} {nombre} -> {etiqueta}", ""]
        if r.get("fallo"):
            l.append(f"(sin deliberacion: {r['fallo']})")
        else:
            if r.get("juez"):
                l.append(_quitar_veredicto(r["juez"]))
                l.append("")
            if r.get("toro") or r.get("oso"):
                l.append("El debate de atras:")
            if r.get("toro"):
                l.append(f'  Toro: "{r["toro"]}"')
            if r.get("oso"):
                l.append(f'  Oso: "{r["oso"]}"')
        mensajes.append("\n".join(l))

    if res_fm is not None:
        v = res_fm.get("veredicto")
        etiqueta = v if v else ("SIN SENTENCIA" if not res_fm.get("fallo")
                                else "FALLO TECNICO")
        l = [f"{FM_EMOJI} FUND MANAGER -> {etiqueta}", ""]
        if res_fm.get("fallo"):
            l.append(f"(sin deliberacion: {res_fm['fallo']})")
        elif res_fm.get("texto"):
            l.append(_quitar_veredicto(res_fm["texto"]))
        mensajes.append("\n".join(l))

    # ---- mensaje final: consenso de las 4 voces ----
    l = ["CONSENSO DEL BOARD",
         " | ".join(f"{v['emoji']}{x or '?'}" for v, x in zip(voces, veredictos)),
         ""]
    if len(validos) == total and len(set(validos)) == 1 and total >= 3:
        l.append(f"Los {total} coinciden en {validos[0]}: señal fuerte — "
                 "cuando el board entero y la mirada libre apuntan al mismo "
                 "lado, vale la pena sentarse a leerlo con calma.")
    elif len(validos) >= 2 and len(set(validos)) == 1:
        l.append(f"Mayoria ({len(validos)} de {total}) en {validos[0]}. "
                 "La divergencia del resto tambien es informacion: mirala "
                 "antes de decidir.")
    elif validos:
        l.append("Sin coincidencias: cada lente ve una cartera distinta. "
                 "Esa divergencia es tu decision puesta sobre la mesa.")
    else:
        l.append("Sin sentencias validas esta corrida: se reintenta sola.")
    mensajes.append("\n".join(l))

    # ---- linea de log PUBLICO: abstracta ----
    ok_count = len(validos)
    linea_log = (f"board: {ok_count}/{total} voces deliberadas | "
                 f"consenso: {consenso} (detalle por ntfy)")
    return mensajes, linea_log, ok_count, total
