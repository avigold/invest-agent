from app.jobs.handlers.echo import echo_handler
from app.jobs.handlers.country import country_refresh_handler
from app.jobs.handlers.industry import industry_refresh_handler

HANDLERS = {
    "echo": echo_handler,
    "country_refresh": country_refresh_handler,
    "industry_refresh": industry_refresh_handler,
}
