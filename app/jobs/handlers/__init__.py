from app.jobs.handlers.echo import echo_handler
from app.jobs.handlers.country import country_refresh_handler
from app.jobs.handlers.industry import industry_refresh_handler
from app.jobs.handlers.company import company_refresh_handler
from app.jobs.handlers.data_sync import data_sync_handler
from app.jobs.handlers.add_companies import add_companies_by_market_cap_handler
from app.jobs.handlers.recommendation import recommendation_analysis_handler
from app.jobs.handlers.stock_screen import stock_screen_handler
from app.jobs.handlers.screen_analysis import screen_analysis_handler
from app.jobs.handlers.prediction_train import prediction_train_handler
from app.jobs.handlers.prediction_score import prediction_score_handler
from app.jobs.handlers.fmp_sync import fmp_sync_handler
from app.jobs.handlers.price_sync import price_sync_handler
from app.jobs.handlers.score_sync import score_sync_handler
from app.jobs.handlers.macro_sync import macro_sync_handler
from app.jobs.handlers.discover_companies import discover_companies_handler

HANDLERS = {
    "echo": echo_handler,
    "country_refresh": country_refresh_handler,
    "industry_refresh": industry_refresh_handler,
    "company_refresh": company_refresh_handler,
    "data_sync": data_sync_handler,
    "add_companies_by_market_cap": add_companies_by_market_cap_handler,
    "recommendation_analysis": recommendation_analysis_handler,
    "stock_screen": stock_screen_handler,
    "screen_analysis": screen_analysis_handler,
    "prediction_train": prediction_train_handler,
    "prediction_score": prediction_score_handler,
    "fmp_sync": fmp_sync_handler,
    "price_sync": price_sync_handler,
    "score_sync": score_sync_handler,
    "macro_sync": macro_sync_handler,
    "discover_companies": discover_companies_handler,
}
