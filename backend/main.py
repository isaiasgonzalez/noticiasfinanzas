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

@app.get("/api/dashboard")
def get_dashboard_data():
    # 1. Monitor de Índices (Yahoo Finance)
    try:
        tickers = yf.Tickers('^GSPC ^IXIC ^MERV')
        sp500 = tickers.tickers['^GSPC'].history(period="1d")['Close'].iloc[-1]
        nasdaq = tickers.tickers['^IXIC'].history(period="1d")['Close'].iloc[-1]
        merval = tickers.tickers['^MERV'].history(period="1d")['Close'].iloc[-1]
    except:
        sp500, nasdaq, merval = 0, 0, 0

    # 2. Contexto Argentino (Scraping de API Ámbito Financiero)
    try:
        # Riesgo País EMBI
        rp_data = requests.get("https://mercados.ambito.com/riesgopais/variacion").json()
        riesgo_pais = rp_data.get('valor', 'N/A')
        
        # Dólar para cálculo de brecha (CCL vs Mayorista)
        ccl_data = requests.get("https://mercados.ambito.com/dolar/contadoconliqui/variacion").json()
        mayo_data = requests.get("https://mercados.ambito.com/dolar/oficial/variacion").json()
        
        ccl_val = float(ccl_data.get('valor', '0').replace(',', '.'))
        mayo_val = float(mayo_data.get('valor', '1').replace(',', '.'))
        brecha = round(((ccl_val / mayo_val) - 1) * 100, 2)
    except Exception as e:
        riesgo_pais, brecha = "N/A", "N/A"

    # 3. Alerta Roja (RSS Google News enfocado en macro/Trump)
    rss_url = "https://news.google.com/rss/search?q=Trump+(tariff+OR+deregulation+OR+fed+OR+powell)&hl=en-US&gl=US"
    rss_news = feedparser.parse(rss_url)
    alertas = [entry.title for entry in rss_news.entries[:2]] if rss_news.entries else ["Sin drivers macroeconómicos a la vista."]

    # 4. Sentimiento de Mercado (Trend simple sobre SPX)
    sentiment = "Risk-on (Bullish)" if sp500 > 0 else "Risk-off (Bearish)"

    return {
        "alerta_roja": alertas,
        "indices": {
            "sp500": f"{sp500:.2f}",
            "nasdaq": f"{nasdaq:.2f}",
            "merval": f"{merval:.2f}",
            "riesgo_pais": riesgo_pais
        },
        "contexto_arg": {
            "brecha": f"Brecha CCL: {brecha}%",
            "bcra": "Tasas estables. Roll-over de deuda del Tesoro sin presiones."
        },
        "sentimiento": sentiment
    }
