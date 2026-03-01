from app.jobs.handlers.echo import echo_handler
from app.jobs.handlers.country import country_refresh_handler
from app.jobs.handlers.industry import industry_refresh_handler
from app.jobs.handlers.company import company_refresh_handler
from app.jobs.handlers.data_sync import data_sync_handler

HANDLERS = {
    "echo": echo_handler,
    "country_refresh": country_refresh_handler,
    "industry_refresh": industry_refresh_handler,
    "company_refresh": company_refresh_handler,
    "data_sync": data_sync_handler,
}
