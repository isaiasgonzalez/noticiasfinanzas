from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import feedparser
import requests
import time
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────
# CACHE TTL  (evita martillar las APIs en cada request)
# ─────────────────────────────────────────────────────────────────
_cache: dict = {}

def cache_get(key: str):
    if key in _cache:
        data, ts, ttl = _cache[key]
        if time.time() - ts < ttl:
            return data
    return None

def cache_set(key: str, value, ttl: int = 180):
    _cache[key] = (value, time.time(), ttl)


# ─────────────────────────────────────────────────────────────────
# ANÁLISIS DE SENTIMIENTO POR KEYWORDS
# ─────────────────────────────────────────────────────────────────
BEARISH_KW = [
    'tariff', 'tariffs', 'arancel', 'aranceles', 'inflation', 'inflación',
    'hike', 'war', 'crash', 'cepo', 'default', 'sanction', 'ban', 'restrict',
    'recession', 'deuda', 'crisis', 'deficit', 'devalua', 'sell-off', 'selloff',
    'plunge', 'tumble', 'slump', 'tension', 'hawkish', 'tightening',
    'downgrade', 'warning', 'risk', 'uncertainty', 'fear', 'collapse'
]
BULLISH_KW = [
    'cut', 'cuts', 'baja', 'stimulus', 'rally', 'desregulación', 'superávit',
    'acuerdo', 'record', 'growth', 'deal', 'agreement', 'surplus', 'reserve',
    'imf', 'fmi', 'recovery', 'rebound', 'dovish', 'easing', 'boost',
    'surge', 'gain', 'upgrade', 'breakthrough', 'positive', 'strong'
]

def analizar_sentimiento_noticia(titulo: str):
    t = titulo.lower()
    b_score = sum(1 for k in BEARISH_KW if k in t)
    g_score = sum(1 for k in BULLISH_KW if k in t)
    diff = g_score - b_score
    if diff < 0:
        return "🔴 Bearish", "Keywords de restricción monetaria, riesgo geopolítico o stress financiero detectados."
    elif diff > 0:
        return "🟢 Bullish", "Drivers de liquidez, crecimiento o desregulación detectados."
    return "⚪ Neutral", "Sin direccionalidad técnica clara en el headline."


# ─────────────────────────────────────────────────────────────────
# DATOS DE MERCADO
# ─────────────────────────────────────────────────────────────────
def get_ticker_data(symbol: str):
    key = f"ticker_{symbol}"
    cached = cache_get(key)
    if cached:
        return cached
    try:
        data = yf.Ticker(symbol).history(period="2d")
        if len(data) < 2:
            result = (0.0, 0.0)
        else:
            c_hoy   = float(data['Close'].iloc[-1])
            c_ayer  = float(data['Close'].iloc[-2])
            vol     = float(data['Volume'].iloc[-1]) if 'Volume' in data.columns else 0.0
            var_pct = ((c_hoy - c_ayer) / c_ayer) * 100
            result  = (c_hoy, var_pct, vol)
    except Exception:
        result = (0.0, 0.0, 0.0)
    cache_set(key, result, ttl=180)
    return result


def safe_ticker(symbol: str):
    r = get_ticker_data(symbol)
    val = r[0] if len(r) > 0 else 0.0
    var = r[1] if len(r) > 1 else 0.0
    return val, var


# ─────────────────────────────────────────────────────────────────
# NOTICIAS RSS  (Google News – sin costo, sin API key)
# ─────────────────────────────────────────────────────────────────
def get_noticias(rss_url: str, cache_key: str, limit: int = 7):
    cached = cache_get(f"news_{cache_key}")
    if cached:
        return cached
    try:
        feed = feedparser.parse(rss_url)
        noticias = []
        for entry in feed.entries[:limit]:
            sent, just = analizar_sentimiento_noticia(entry.title)
            fuente = "Google News"
            if hasattr(entry, 'source') and hasattr(entry.source, 'title'):
                fuente = entry.source.title
            noticias.append({
                "titulo": entry.title,
                "fuente": fuente,
                "link":   getattr(entry, 'link', '#'),
                "impacto": sent,
                "justificacion": just,
                "fecha": getattr(entry, 'published', '')
            })
        cache_set(f"news_{cache_key}", noticias, ttl=300)
        return noticias
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────
# DÓLARES Y RIESGO PAÍS  (Ámbito Financiero – público/gratuito)
# ─────────────────────────────────────────────────────────────────
def _fetch_ambito(endpoint: str):
    try:
        r = requests.get(f"https://mercados.ambito.com/{endpoint}", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def get_dolares():
    cached = cache_get("dolares")
    if cached:
        return cached

    def parse(data):
        val = data.get('valor', 'N/A')
        var = str(data.get('variacion', '0')).replace('%', '').replace(',', '.').strip()
        return {"val": val, "var": var}

    result = {
        "ccl":     parse(_fetch_ambito("dolar/contadoconliqui/variacion")),
        "oficial": parse(_fetch_ambito("dolar/oficial/variacion")),
        "blue":    parse(_fetch_ambito("dolar/informal/variacion")),
    }
    cache_set("dolares", result, ttl=180)
    return result


def get_riesgo_pais():
    cached = cache_get("riesgo_pais")
    if cached:
        return cached
    data = _fetch_ambito("riesgo-pais/variacion")
    result = {
        "val": data.get('valor', 'N/A'),
        "var": str(data.get('variacion', '0')).replace('%', '').replace(',', '.').strip()
    }
    cache_set("riesgo_pais", result, ttl=300)
    return result


# ─────────────────────────────────────────────────────────────────
# SENTIMIENTO DE MERCADO  (score propio basado en datos reales)
# ─────────────────────────────────────────────────────────────────
def calcular_sentimiento(vix_val, vix_var, sp500_var, nasdaq_var, wti_var, ewz_val, ewz_var):
    score   = 0.0
    factores = []

    # VIX – principal gauge de volatilidad implícita
    if vix_val > 0:
        if vix_val > 30:
            score -= 3
            factores.append(f"🔴 VIX {vix_val:.2f} — zona de pánico extremo (>30). Mercado pricing un shock sistémico.")
        elif vix_val > 22:
            score -= 1.5
            factores.append(f"🟠 VIX {vix_val:.2f} — zona de stress elevado (>22). Coberturas activas en opciones.")
        elif vix_val > 16:
            score -= 0.5
            factores.append(f"🟡 VIX {vix_val:.2f} — volatilidad moderada. Mercado en modo cauteloso.")
        else:
            score += 1.5
            factores.append(f"🟢 VIX {vix_val:.2f} — planchado (<16). Volatilidad implícita pisada, ambiente favorable a risk-on.")

    # S&P 500 intraday
    if sp500_var != 0:
        if sp500_var > 1.0:
            score += 1.5
            factores.append(f"🟢 S&P500 +{sp500_var:.2f}% intraday — momentum alcista, compras institucionales.")
        elif sp500_var > 0:
            score += 0.5
            factores.append(f"🟢 S&P500 +{sp500_var:.2f}% — sesgo comprador, tendencia positiva.")
        elif sp500_var < -1.0:
            score -= 1.5
            factores.append(f"🔴 S&P500 {sp500_var:.2f}% — sell-off intraday. Rotación a defensivos o cash.")
        else:
            score -= 0.5
            factores.append(f"🟠 S&P500 {sp500_var:.2f}% — presión vendedora moderada.")

    # Nasdaq – proxy de apetito por riesgo / growth
    if nasdaq_var != 0:
        if nasdaq_var > 1.0:
            score += 0.5
            factores.append(f"🟢 Nasdaq +{nasdaq_var:.2f}% — tech liderando, risk-on en growth.")
        elif nasdaq_var < -1.0:
            score -= 0.5
            factores.append(f"🔴 Nasdaq {nasdaq_var:.2f}% — rotación fuera de tech/growth.")

    # WTI – proxy de expectativas de demanda global
    if wti_var != 0:
        if wti_var > 1.5:
            score += 0.5
            factores.append(f"🟢 WTI +{wti_var:.2f}% — repricing de demanda global, señal reflacionaria.")
        elif wti_var < -1.5:
            score -= 0.5
            factores.append(f"🔴 WTI {wti_var:.2f}% — temor a recesión o exceso de oferta.")

    # EWZ – proxy de EM/Brasil, correlacionado con Merval
    if ewz_val > 0 and ewz_var != 0:
        if ewz_var > 1.0:
            score += 0.5
            factores.append(f"🟢 EWZ +{ewz_var:.2f}% — apetito por emergentes. Flujos hacia LatAm.")
        elif ewz_var < -1.0:
            score -= 0.5
            factores.append(f"🔴 EWZ {ewz_var:.2f}% — salida de capitales de emergentes. Presión sobre activos ARG.")

    # Clasificación final
    if score >= 2.0:
        estado = "🟢 RISK-ON (Bullish)"
        color  = "green"
    elif score <= -2.0:
        estado = "🔴 RISK-OFF (Bearish)"
        color  = "red"
    elif score > 0:
        estado = "🟡 LEVEMENTE BULLISH"
        color  = "yellow"
    elif score < 0:
        estado = "🟠 LEVEMENTE BEARISH"
        color  = "orange"
    else:
        estado = "⚪ NEUTRAL / MIXTO"
        color  = "neutral"

    justificacion = " · ".join(factores) if factores else "Datos insuficientes para clasificar el régimen de mercado."
    return estado, color, round(score, 2), justificacion


# ─────────────────────────────────────────────────────────────────
# ENDPOINT PRINCIPAL
# ─────────────────────────────────────────────────────────────────
@app.get("/api/dashboard")
def get_dashboard_data():
    # Índices
    sp500_val,  sp500_var  = safe_ticker('^GSPC')
    nasdaq_val, nasdaq_var = safe_ticker('^IXIC')
    merval_val, merval_var = safe_ticker('^MERV')
    vix_val,    vix_var    = safe_ticker('^VIX')
    wti_val,    wti_var    = safe_ticker('CL=F')
    brent_val,  brent_var  = safe_ticker('BZ=F')
    ewz_val,    ewz_var    = safe_ticker('EWZ')

    # Noticias globales — Trump + macro
    rss_global = (
        "https://news.google.com/rss/search?q=Trump+"
        "(tariff+OR+fed+OR+powell+OR+market+OR+trade+OR+sanctions+OR+executive+order+OR+economy)"
        "&hl=en-US&gl=US&ceid=US:en"
    )
    noticias_globales = get_noticias(rss_global, "global", limit=7)

    # Noticias Argentina
    rss_arg = (
        "https://news.google.com/rss/search?q=economia+argentina+"
        "(bcra+OR+merval+OR+bonos+OR+inflacion+OR+licitacion+OR+reservas+OR+deuda+OR+FMI)"
        "&hl=es-419&gl=AR&ceid=AR:es-419"
    )
    noticias_arg = get_noticias(rss_arg, "argentina", limit=3)

    # Dólares y riesgo país
    dolares      = get_dolares()
    riesgo_pais  = get_riesgo_pais()

    # Sentimiento
    estado, color, score, just_sent = calcular_sentimiento(
        vix_val, vix_var, sp500_var, nasdaq_var, wti_var, ewz_val, ewz_var
    )

    return {
        "indices": {
            "sp500":       {"val": f"{sp500_val:,.2f}",  "var": f"{sp500_var:.2f}"},
            "nasdaq":      {"val": f"{nasdaq_val:,.2f}", "var": f"{nasdaq_var:.2f}"},
            "merval":      {"val": f"{merval_val:,.0f}", "var": f"{merval_var:.2f}"},
            "vix":         {"val": f"{vix_val:.2f}",    "var": f"{vix_var:.2f}"},
            "wti":         {"val": f"{wti_val:.2f}",    "var": f"{wti_var:.2f}"},
            "brent":       {"val": f"{brent_val:.2f}",  "var": f"{brent_var:.2f}"},
            "ewz":         {"val": f"{ewz_val:.2f}",    "var": f"{ewz_var:.2f}"},
            "riesgo_pais": riesgo_pais
        },
        "alerta_roja":  noticias_globales,
        "contexto_arg": {
            "dolares":  dolares,
            "noticias": noticias_arg
        },
        "sentimiento": {
            "estado":       estado,
            "color":        color,
            "score":        score,
            "justificacion": just_sent
        },
        "timestamp": datetime.now().isoformat()
    }


@app.get("/health")
def health():
    return {"status": "ok", "cache_keys": len(_cache)}
