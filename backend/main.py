"""FastAPI backend для Kairos. Тонкий composer: только app + middleware + роутеры."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import (
    assistant as assistant_router,
    backtest as backtest_router,
    docs as docs_router,
    environments as environments_router,
    event_effect as event_effect_router,
    event_study as event_study_router,
    market as market_router,
    precedents as precedents_router,
    research as research_router,
    rules as rules_router,
    strategies as strategies_router,
)

app = FastAPI(title="Kairos API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market_router.router)
app.include_router(event_study_router.router)
app.include_router(event_effect_router.router)
app.include_router(precedents_router.router)
app.include_router(research_router.router)
app.include_router(rules_router.router)
app.include_router(strategies_router.router)
app.include_router(environments_router.router)
app.include_router(backtest_router.router)
app.include_router(docs_router.router)
app.include_router(assistant_router.router)
