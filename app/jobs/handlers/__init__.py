from app.jobs.handlers.echo import echo_handler
from app.jobs.handlers.country import country_refresh_handler
from app.jobs.handlers.industry import industry_refresh_handler
from app.jobs.handlers.company import company_refresh_handler
from app.jobs.handlers.data_sync import data_sync_handler
from app.jobs.handlers.add_companies import add_companies_by_market_cap_handler
from app.jobs.handlers.recommendation import recommendation_analysis_handler
from app.jobs.handlers.stock_screen import stock_screen_handler

HANDLERS = {
    "echo": echo_handler,
    "country_refresh": country_refresh_handler,
    "industry_refresh": industry_refresh_handler,
    "company_refresh": company_refresh_handler,
    "data_sync": data_sync_handler,
    "add_companies_by_market_cap": add_companies_by_market_cap_handler,
    "recommendation_analysis": recommendation_analysis_handler,
    "stock_screen": stock_screen_handler,
}
