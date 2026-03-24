from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import feedparser

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/dashboard")
def get_dashboard_data():
    # 1. Monitor de Índices (Yahoo Finance es gratis)
    tickers = yf.Tickers('^GSPC ^IXIC GGAL.BA') # GGAL como proxy Merval local para volumen
    sp500 = tickers.tickers['^GSPC'].history(period="1d")
    nasdaq = tickers.tickers['^IXIC'].history(period="1d")
    
    # 2. Alerta Roja (Trump / Fed) - Proxy: RSS de Investing o Yahoo
    rss_news = feedparser.parse("https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC,USDARS=X")
    alertas = [entry.title for entry in rss_news.entries if "Trump" in entry.title or "Fed" in entry.title][:2]

    # 3. Contexto Argentino (Faltan APIs oficiales del BCRA gratis y estables, se mockea la lógica de ingesta)
    # Lo ideal acá es parsear el JSON de la API de Dolarito o Ámbito
    brecha_ccl = 25.4 # % placeholder dinámico
    
    # 4. Sentimiento de Mercado (Lógica dura)
    sp_trend = sp500['Close'].iloc[-1] > sp500['Open'].iloc[-1]
    sentiment = "Risk-on (Bullish)" if sp_trend else "Risk-off (Bearish)"

    return {
        "alerta_roja": alertas if alertas else ["Sin drivers hawkish/dovish inmediatos en el radar."],
        "indices": {
            "sp500": f"{sp500['Close'].iloc[-1]:.2f}",
            "nasdaq": f"{nasdaq['Close'].iloc[-1]:.2f}",
            "merval_proxy": "Tendencia flat, volumen bajo."
        },
        "contexto_arg": {
            "brecha": f"Brecha CCL: {brecha_ccl}%",
            "bcra": "Licitación Bopreal sin novedades disruptivas. Esperando dato inflacionario."
        },
        "sentimiento": sentiment
    }

# Para correrlo: uvicorn main:app --reload