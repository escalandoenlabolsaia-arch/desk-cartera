# -*- coding: utf-8 -*-
"""
perfiles.py — Los 3 perfiles del board de analistas (el nieto).

Cada perfil es una filosofia de inversion con numeros concretos:
- techo_posicion:      maximo % de una sola accion
- top5_max:            maximo % acumulado de las 5 mayores posiciones
- sector_default_max:  maximo % por sector
- colchon_min:         minimo % en renta fija + cash (FCIs + bonos + cash)
- renta_fija_ar_max:   maximo % en bonos argentinos + ONs (riesgo pais)
- opciones_max:        maximo % en el bucket de opciones (bucket_manual)
- fragil_accion:       cuando el veredicto 'fragil' del hijo obliga a REVISAR
                       ("siempre" o "peso>X": solo si la posicion pesa > X%)

Vocabulario cerrado de veredictos: ACCIONAR / ESPERAR / REVISAR.
Regla de arquitectura: la aritmetica la hace Python (expediente con las
cuentas ya hechas); la opinion, los agentes (toro/oso/juez via Groq).

Tus numeros (calibrados el dia del diseno, con tu cartera real sobre la
mesa): el conservador vivia preocupado (VST, OPTIONS y top-5 en borde),
el moderado casi tranquilo (solo OPTIONS cerca), el agresivo en verde.
"""

PERFILES = {
    "conservador": {
        "emoji": "🛡️",
        "techo_posicion": 8,
        "top5_max": 45,
        "sector_default_max": 25,
        "colchon_min": 30,
        "renta_fija_ar_max": 15,
        "opciones_max": 10,
        "fragil_accion": "siempre",
    },
    "moderado": {
        "emoji": "⚖️",
        "techo_posicion": 12,
        "top5_max": 55,
        "sector_default_max": 35,
        "colchon_min": 20,
        "renta_fija_ar_max": 25,
        "opciones_max": 15,
        "fragil_accion": "peso>5",
    },
    "agresivo": {
        "emoji": "🚀",
        "techo_posicion": 20,
        "top5_max": 70,
        "sector_default_max": 50,
        "colchon_min": 10,
        "renta_fija_ar_max": 35,
        "opciones_max": 25,
        "fragil_accion": "peso>10",
    },
}

ORDEN = ["conservador", "moderado", "agresivo"]


def obtener_perfil(nombre):
    """Devuelve el dict del perfil. KeyError visible si el nombre es malo
    (fail-fast: mejor explotar en el arranque que deliberar mal)."""
    return PERFILES[nombre]
