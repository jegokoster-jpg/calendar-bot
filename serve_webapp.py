import asyncio
import logging
import os
from pathlib import Path

import aiohttp.web as web

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

WEBAPP_DIR = Path(__file__).parent / 'webapp'
INDEX_HTML = WEBAPP_DIR / 'index.html'


async def index_handler(request: web.Request) -> web.Response:
    if not INDEX_HTML.is_file():
        logger.error('index.html not found at %s', INDEX_HTML)
        raise web.HTTPInternalServerError(text='index.html not found')
    content = INDEX_HTML.read_text(encoding='utf-8')
    return web.Response(
        text=content,
        content_type='text/html; charset=utf-8'
    )


async def health_handler(request: web.Request) -> web.Response:
    return web.json_response({'status': 'ok'})


@web.middleware
async def cors_middleware(request: web.Request, handler) -> web.Response:
    if request.method == 'OPTIONS':
        return web.Response(
            status=200,
            headers={
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type'
            }
        )
    response = await handler(request)
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response


def create_app() -> web.Application:
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get('/', index_handler)
    app.router.add_get('/webapp', index_handler)
    app.router.add_get('/health', health_handler)
    return app


async def start_webapp_server() -> web.AppRunner:
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info('WebApp server started on port %s', port)
    return runner


async def main() -> None:
    await start_webapp_server()
    await asyncio.Event().wait()


if __name__ == '__main__':
    asyncio.run(main())