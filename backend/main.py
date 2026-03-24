from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import feedparser
import requests

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def analizar_sentimiento_noticia(titulo):
    titulo = titulo.lower()
    bearish_kw = ['tariff', 'arancel', 'inflation', 'inflación', 'hike', 'war', 'crash', 'cepo', 'tensión', 'caída', 'default']
    bullish_kw = ['cut', 'baja', 'stimulus', 'rally', 'desregulación', 'superávit', 'acuerdo', 'record', 'growth']
    
    if any(k in titulo for k in bearish_kw):
        return "🔴 Bearish", "Keywords de restricción monetaria, riesgo geopolítico o trabas comerciales."
    elif any(k in titulo for k in bullish_kw):
        return "🟢 Bullish", "Drivers de liquidez, crecimiento o desregulación detectados."
    return "⚪ Neutral", "Sin direccionalidad técnica clara."

def get_ticker_data(symbol):
    try:
        data = yf.Ticker(symbol).history(period="2d")
        if len(data) < 2: return 0, 0
        close_hoy = data['Close'].iloc[-1]
        close_ayer = data['Close'].iloc[-2]
        var_pct = ((close_hoy - close_ayer) / close_ayer) * 100
        return close_hoy, var_pct
    except:
        return 0, 0

@app.get("/api/dashboard")
def get_dashboard_data():
    # --- 1. MONITOR DE ÍNDICES ---
    sp500_val, sp500_var = get_ticker_data('^GSPC')
    nasdaq_val, nasdaq_var = get_ticker_data('^IXIC')
    merval_val, merval_var = get_ticker_data('^MERV')
    vix_val, vix_var = get_ticker_data('^VIX')
    wti_val, wti_var = get_ticker_data('CL=F')
    brent_val, brent_var = get_ticker_data('BZ=F')
    ewz_val, ewz_var = get_ticker_data('EWZ')

    # --- 2. ALERTA ROJA (Global) ---
    rss_global = feedparser.parse("https://news.google.com/rss/search?q=Trump+(tariff+OR+fed+OR+powell+OR+deregulation)&hl=en-US&gl=US")
    noticias_globales = []
    for entry in rss_global.entries[:7]:
        sent, just = analizar_sentimiento_noticia(entry.title)
        noticias_globales.append({
            "titulo": entry.title,
            "fuente": entry.source.title if hasattr(entry, 'source') else "Global News",
            "impacto": sent,
            "justificacion": just
        })

    # --- 3. CONTEXTO ARGENTINO ---
    rss_arg = feedparser.parse("https://news.google.com/rss/search?q=economia+argentina+(bcra+OR+merval+OR+bonos+OR+inflacion)&hl=es-419&gl=AR")
    noticias_arg = []
    for entry in rss_arg.entries[:3]:
        sent, just = analizar_sentimiento_noticia(entry.title)
        noticias_arg.append({
            "titulo": entry.title,
            "fuente": entry.source.title if hasattr(entry, 'source') else "Medios Locales",
            "impacto": sent,
            "justificacion": just
        })

    # Dólares (Vía Ámbito)
    try:
        ccl_data = requests.get("https://mercados.ambito.com/dolar/contadoconliqui/variacion").json()
        oficial_data = requests.get("https://mercados.ambito.com/dolar/oficial/variacion").json()
        
        ccl_val = ccl_data.get('valor', '0')
        ccl_var = ccl_data.get('variacion', '0').replace('%', '')
        
        ofi_val = oficial_data.get('valor', '0')
        ofi_var = oficial_data.get('variacion', '0').replace('%', '')
    except:
        ccl_val, ccl_var, ofi_val, ofi_var = "N/A", "0", "N/A", "0"

    # --- 4. SENTIMIENTO DE MERCADO (Algoritmo propio) ---
    if vix_val > 20 and sp500_var < 0:
        sentimiento = "🔴 RISK-OFF (Bearish)"
        just_sent = f"VIX volando por encima de 20 pts ({vix_val:.2f}) y S&P500 ajustando ({sp500_var:.2f}%). Clima de aversión al riesgo y cobertura. Cash is king."
    elif vix_val < 15 and sp500_var > 0:
        sentimiento = "🟢 RISK-ON (Bullish)"
        just_sent = f"VIX planchado en {vix_val:.2f} pts y SPX traccionando ({sp500_var:.2f}%). Volatilidad pisada, mercado pagando duration y equity."
    else:
        sentimiento = "⚪ NEUTRAL / MIXTO"
        just_sent = f"VIX en {vix_val:.2f} pts. Dinámica errática en el SPX ({sp500_var:.2f}%). Esperando definición de tasa o shock de liquidez para rotar carteras."

    return {
        "indices": {
            "sp500": {"val": f"{sp500_val:.2f}", "var": f"{sp500_var:.2f}"},
            "nasdaq": {"val": f"{nasdaq_val:.2f}", "var": f"{nasdaq_var:.2f}"},
            "merval": {"val": f"{merval_val:.2f}", "var": f"{merval_var:.2f}"},
            "vix": {"val": f"{vix_val:.2f}", "var": f"{vix_var:.2f}"},
            "wti": {"val": f"{wti_val:.2f}", "var": f"{wti_var:.2f}"},
            "brent": {"val": f"{brent_val:.2f}", "var": f"{brent_var:.2f}"},
            "ewz": {"val": f"{ewz_val:.2f}", "var": f"{ewz_var:.2f}"}
        },
        "alerta_roja": noticias_globales,
        "contexto_arg": {
            "dolares": {
                "ccl": {"val": ccl_val, "var": ccl_var},
                "oficial": {"val": ofi_val, "var": ofi_var}
            },
            "noticias": noticias_arg
        },
        "sentimiento": {
            "estado": sentimiento,
            "justificacion": just_sent
        }
    }
