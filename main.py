import asyncio
import logging
from serve_webapp import start_webapp_server
from bot import build_application

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    # 1. Стартуем веб-сервер (неблокирующий)
    await start_webapp_server()
    logger.info('WebApp server started')

    # 2. Стартуем бота в том же event loop
    application = build_application()
    async with application:
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        logger.info('Bot started')
        # Держим процесс живым
        await asyncio.Event().wait()
        await application.updater.stop()
        await application.stop()


if __name__ == '__main__':
    asyncio.run(main())
