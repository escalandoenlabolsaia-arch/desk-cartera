# -*- coding: utf-8 -*-
"""
board.py — El motor de deliberacion: 9 agentes (toro/oso/juez x 3 perfiles).

Flujo por perfil: TORO argumenta -> OSO responde (lee al toro) -> JUEZ
sentencia con linea 'VEREDICTO: X'. La unanimidad la calcula Python
contando veredictos parseados: jamas a ojo del LLM.

Privacidad (regla de la familia): los textos de los agentes CITAN datos de
la cartera -> JAMAS van al log publico. Al log sale solo un conteo
abstracto (sin tickers ni perfiles asociados). El contenido completo viaja
unicamente por ntfy privado.

Resiliencia ante 429 (limite de velocidad de Groq, tipico del plan gratis
en horas calientes): hasta 4 reintentos con espera creciente (10s/20s/30s/
30s). Nunca se inventa un veredicto: si todo falla, ese perfil queda 'sin
deliberacion' y el resto sigue.
"""

import json
import os
import time

import requests

from prompts import (prompt_sistema, prompt_usuario_toro, prompt_usuario_oso,
                     prompt_usuario_juez, extraer_veredicto)
from perfiles import PERFILES, ORDEN

DEFAULT_MODELO = "openai/gpt-oss-120b"


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
    velocidad). Devuelve texto o None (falla definitiva -> None: la
    deliberacion degrada, jamas se inventa contenido)."""
    esperas = [10, 20, 30, 30]   # reintentos ante 429: total hasta 90s
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
    """Seguro local de concision (los prompts ya limitan palabras)."""
    lineas = [l.strip() for l in (texto or "").splitlines() if l.strip()]
    return "\n".join(lineas[:max_lineas])


# --------------------------------------------------------------- deliberacion x perfil
def deliberar_perfil(expediente, perfil_nombre, key, modelo):
    """Toro -> Oso (lee al toro) -> Juez (lee ambos). Devuelve dict del
    perfil con textos y veredicto (o None en los pasos que fallen)."""
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
        # reintento unico con recordatorio de formato (no inventamos: si
        # tampoco cumple, el perfil queda sin sentencia)
        texto_juez = _llamar_groq(
            sys_juez,
            prompt_usuario_juez(expediente, res["toro"], res["oso"])
            + "\n\nRECORDATORIO: tu respuesta DEBE terminar con la linea "
              "exacta 'VEREDICTO: ACCIONAR' o 'VEREDICTO: ESPERAR' o "
              "'VEREDICTO: REVISAR'.",
            key, modelo, max_tokens=800)
        veredicto = extraer_veredicto(texto_juez)

    res["juez"] = _recortar(texto_juez, 5) if texto_juez else None
    res["veredicto"] = veredicto   # None = juez no cumplio formato
    return res


# --------------------------------------------------------------- board completo
def deliberar_board(expedientes, key, modelo, trigger_log="deliberacion"):
    """Corre los 3 perfiles. Devuelve (mensaje_ntfy, linea_log).
    mensaje_ntfy: contenido COMPLETO (privado). linea_log: conteo abstracto
    (publico, sin tickers ni datos de cartera)."""
    resultados = []
    for nombre in ORDEN:
        exp = expedientes.get(nombre)
        if exp is None:
            resultados.append({"perfil": nombre, "emoji": PERFILES[nombre]["emoji"],
                               "veredicto": None, "fallo": "sin expediente"})
            continue
        r = deliberar_perfil(exp, nombre, key, modelo)
        resultados.append(r)
        time.sleep(5)   # pausa entre perfiles (cortesia con el limite)

    veredictos = [r.get("veredicto") for r in resultados]
    validos = [v for v in veredictos if v]
    if len(validos) == 3 and len(set(validos)) == 1:
        consenso = f"UNANIMIDAD en {validos[0]}"
    elif len(validos) >= 2 and len(set(validos)) == 1:
        consenso = f"mayoria {len(validos)}/3 en {validos[0]}"
    elif validos:
        consenso = "sin coincidencias (" + ", ".join(
            f"{r['emoji']}{v or '?'}" for r, v in zip(resultados, veredictos)) + ")"
    else:
        consenso = "sin sentencias validas"

    # ---- mensaje privado (contenido completo, con datos de cartera) ----
    l = [f"BOARD - {trigger_log}", "-----------------------------"]
    for r in resultados:
        e, nombre = r["emoji"], r["perfil"].upper()
        v = r.get("veredicto")
        titulo = v if v else ("SIN SENTENCIA" if not r.get("fallo") else "FALLO TECNICO")
        l.append(f"{e} {nombre} - {titulo}")
        if r.get("fallo"):
            l.append(f"(sin deliberacion: {r['fallo']})")
        else:
            if r.get("juez"):
                cuerpo = "\n".join(x for x in r["juez"].splitlines()
                                   if not x.strip().upper().startswith("VEREDICTO:"))
                l.append(cuerpo)
            if r.get("toro"):
                l.append(f"  -> toro: {r['toro']}")
            if r.get("oso"):
                l.append(f"  -> oso: {r['oso']}")
        l.append("")
    l.append(f"CONSENSO: {consenso}")
    mensaje = "\n".join(l)

    # ---- linea de log PUBLICO: conteo abstracto, sin tickers ni perfiles ----
    ok = sum(1 for r in resultados if r.get("veredicto"))
    linea_log = (f"board: {ok}/3 perfiles deliberados | consenso: {consenso} "
                 f"(detalle por ntfy)")
    return mensaje, linea_log
