from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.exceptions import HTTPException
from fastapi.templating import Jinja2Templates


from web.routes.api_history import (
    router as api_history_router
)
from web.routes.api_season import (
    router as api_season_router
)
from web.routes.api_stats import (
    router as api_stats_router
)
from web.routes.home import router as home_router
from web.routes.search import router as search_router
from web.routes.api import router as api_router
from web.routes.ranking import router as ranking_router
from web.routes.player import router as player_router
from web.routes.history import router as history_router
from web.routes.match import router as match_router
from web.routes.season import router as season_router
from web.routes.compare import router as compare_router
from web.routes.analysis import router as analysis_router
from web.routes.room import router as room_router
from web.routes.api_room import router as api_room_router
from web.routes.stats import router as stats_router
from web.routes.api_home import router as api_home_router

app = FastAPI(
    title="꼬붕.gg",
    description="디스코드 롤 내전 전적 및 랭킹 웹사이트",
    version="1.0.0"
)

templates = Jinja2Templates(
    directory="web/templates"
)


app.mount(
    "/static",
    StaticFiles(
        directory="web/static"
    ),
    name="static"
)


app.include_router(
    home_router
)

app.include_router(
    search_router
)

app.include_router(
    ranking_router
)

app.include_router(
    player_router
)

app.include_router(
    history_router
)

app.include_router(
    match_router
)

app.include_router(
    season_router
)

app.include_router(
    compare_router
)

app.include_router(
    analysis_router
)

app.include_router(
    room_router
)

app.include_router(
    api_room_router
)

app.include_router(
    api_home_router
)

app.include_router(
    stats_router
)

app.include_router(
    api_router
)
app.include_router(
    api_history_router
)
app.include_router(
    api_season_router
)
app.include_router(
    api_stats_router
)

@app.exception_handler(404)
async def not_found_handler(
    request: Request,
    exc: HTTPException
):
    return templates.TemplateResponse(
        request=request,
        name="404.html",
        context={},
        status_code=404
    )
