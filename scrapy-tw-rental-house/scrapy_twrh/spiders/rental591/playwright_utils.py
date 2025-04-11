import logging
import hashlib
from pathlib import Path
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
        
        # Configure JS caching
        self.js_cache_enabled = settings.getbool('BROWSER_JS_CACHE_ENABLED', True)
        self.js_cache_dir = Path(settings.get('BROWSER_JS_CACHE_DIR', 'js_cache'))
        if self.js_cache_enabled:
            self.js_cache_dir.mkdir(exist_ok=True, parents=True)
            logger.info('JS caching enabled, using directory: %s', self.js_cache_dir)
        
        # In-memory cache for faster access
        self._js_cache = {}

    def _get_cache_path(self, url):
        """Get cached JS file path with sharding for better filesystem performance"""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        # Use first 2 characters of hash as subdirectory
        shard = url_hash[:2]
        cache_dir = self.js_cache_dir / shard
        cache_dir.mkdir(exist_ok=True)
        return cache_dir / f"{url_hash}.js"

    async def init_page(self, page, request):
        # Add init script if configured
        if self.browser_init_script:
            await page.add_init_script(self.browser_init_script)

        # Block image requests
        async def handle_route(route):
            url = route.request.url
            resource_type = route.request.resource_type

            # Handle other resources as before
            if any(url.endswith(ext) for ext in self.skip_file_types):
                await route.abort()
            elif any(domain in url for domain in self.skip_domains):
                await route.abort()
                # Handle JavaScript resources
            elif resource_type == 'script' and self.js_cache_enabled:
                try:
                    cache_path = self._get_cache_path(url)
                    
                    # Check memory cache first
                    if url in self._js_cache:
                        await route.fulfill(body=self._js_cache[url], content_type='application/javascript')
                        return
                    
                    # Check file cache
                    if cache_path.exists():
                        js_content = cache_path.read_bytes()
                        self._js_cache[url] = js_content
                        await route.fulfill(body=js_content, content_type='application/javascript')
                        return
                    
                    # Cache miss - fetch and cache
                    response = await route.fetch()
                    if response.ok:
                        js_content = await response.body()
                        # Cache in memory and on disk
                        self._js_cache[url] = js_content
                        cache_path.write_bytes(js_content)
                        await route.fulfill(body=js_content, content_type='application/javascript')
                        return
                except Exception as e:
                    logger.error('Error handling JS cache for %s: %s', url, e)
                    await route.continue_()
                    return
            else:
                await route.continue_()

        # Enable request interception
        await page.route('**/*', handle_route)

    async def open_map(self, page: Page):
        await page.click('.address .load-map')