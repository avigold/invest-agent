from app.jobs.handlers.echo import echo_handler
from app.jobs.handlers.country import country_refresh_handler

HANDLERS = {
    "echo": echo_handler,
    "country_refresh": country_refresh_handler,
}
