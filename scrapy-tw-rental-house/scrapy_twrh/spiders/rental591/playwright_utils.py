import logging
from playwright.async_api import Page

logger = logging.getLogger(__name__)

class PlaywrightUtils:
    def __init__(self, settings=None):
        self.browser_init_script = settings.get('BROWSER_INIT_SCRIPT', '')
        if not self.browser_init_script:
            logger.warning('BROWSER_INIT_SCRIPT not set in settings, some features may not work')

        self.skip_file_types = ['.jpg', '.jpeg', '.png', '.gif', '.css']
        self.skip_domains = settings.get('BROWSER_SKIP_DOMAINS', [
          "www.googletagmanager.com",
          "maps.googleapis.com",
          "oneid.addcn.com",
          "sentry.addcn.com",
        ])

        logger.info('PlaywrightUtils initialized with skip domains: %s', self.skip_domains)

    async def init_page(self, page, request):
        # Add init script if configured
        if self.browser_init_script:
            await page.add_init_script(self.browser_init_script)

        # Block image requests
        async def handle_route(route):
            url = route.request.url
            if any(url.endswith(ext) for ext in self.skip_file_types):
                await route.abort()
            elif any(domain in url for domain in self.skip_domains):
                await route.abort()
            else:
                await route.continue_()

        # Enable request interception
        await page.route('**/*', handle_route)

    async def open_map(self, page: Page):
        await page.click('.address .load-map')