"""
Browser Controller - Playwright operations
"""
import html
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from . import (
    BROWSER_TIMEOUT, BROWSER_ARGS, USER_AGENT, BROWSER_HEADLESS,
    NETWORK_IDLE_TIMEOUT, NETWORK_IDLE_SILENCE, CSS_INJECTION_TIMEOUT,
    MAX_SCROLL_ITERATIONS, INTERACTION_WAIT
)

class BrowserController:
    def play_all_videos(self, wait_time=8000):
        """
        Simula play em todos os <video> do DOM para forçar carregamento de HLS/chunks.
        """
        try:
            video_count = self.page.evaluate("""() => document.querySelectorAll('video').length""")
            if video_count == 0:
                self.log("Nenhum <video> encontrado para simular play.")
                return
            self.log(f"Simulando play em {video_count} <video>(s)...")
            self.page.evaluate("""
                () => {
                    document.querySelectorAll('video').forEach(v => {
                        try { v.muted = true; v.play(); } catch(e){}
                    });
                }
            """)
            self.page.wait_for_timeout(wait_time)
            self.log(f"Aguardou {wait_time/1000:.1f}s após play em vídeos.")
        except Exception as e:
            self.log(f"Erro ao simular play em vídeos: {e}")
    def __init__(self, log_callback, headless=None, browser_options=None):
        self.log = log_callback
        self.headless = headless if headless is not None else BROWSER_HEADLESS
        self.browser_options = browser_options or {}
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.base_url = None

    def launch(self):
        """Launch browser and create page"""
        self.log("Iniciando navegador...")
        self.playwright = sync_playwright().start()

        executable_path = self.browser_options.get('executable_path')
        channel = self.browser_options.get('channel')
        user_data_dir = self.browser_options.get('user_data_dir')
        profile_directory = self.browser_options.get('profile_directory')
        locale = self.browser_options.get('locale')
        timezone_id = self.browser_options.get('timezone_id')
        viewport = self.browser_options.get('viewport') or {'width': 1920, 'height': 1080}
        launch_args = list(BROWSER_ARGS)
        if profile_directory:
            launch_args.append(f'--profile-directory={profile_directory}')

        if user_data_dir:
            self.log(f"Usando perfil persistente do navegador: {user_data_dir}")
            launch_options = {
                'user_data_dir': str(Path(user_data_dir).expanduser()),
                'headless': self.headless,
                'args': launch_args,
                'viewport': viewport,
                'device_scale_factor': 1,
                'locale': locale,
                'timezone_id': timezone_id,
            }
            if executable_path:
                launch_options['executable_path'] = str(Path(executable_path).expanduser())
                self.log(f"Executável configurado: {launch_options['executable_path']}")
            elif channel:
                launch_options['channel'] = channel
                self.log(f"Canal configurado: {channel}")

            self.context = self.playwright.chromium.launch_persistent_context(**launch_options)
            self.browser = self.context.browser
        else:
            launch_options = {
                'headless': self.headless,
                'args': launch_args,
            }
            if executable_path:
                launch_options['executable_path'] = str(Path(executable_path).expanduser())
                self.log(f"Executável configurado: {launch_options['executable_path']}")
            elif channel:
                launch_options['channel'] = channel
                self.log(f"Canal configurado: {channel}")

            self.browser = self.playwright.chromium.launch(**launch_options)
            self.context = self.browser.new_context(
                user_agent=USER_AGENT,
                viewport=viewport,
                device_scale_factor=1,
                locale=locale,
                timezone_id=timezone_id,
            )

        # Stealth: remove automation markers that sites use to detect headless mode.
        # navigator.webdriver=true and SwiftShader renderer string are the most
        # common signals used by WebGL apps to abort initialization in headless.
        self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            const _getParam = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(p) {
                if (p === 37445) return 'Intel Inc.';
                if (p === 37446) return 'Intel Iris OpenGL Engine';
                return _getParam.apply(this, arguments);
            };
            const _getParam2 = WebGL2RenderingContext && WebGL2RenderingContext.prototype.getParameter;
            if (_getParam2) WebGL2RenderingContext.prototype.getParameter = function(p) {
                if (p === 37445) return 'Intel Inc.';
                if (p === 37446) return 'Intel Iris OpenGL Engine';
                return _getParam2.apply(this, arguments);
            };
        """)

        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self.page

    def goto(self, url):
        """Navigate to URL"""
        self.log(f"Carregando {url}...")
        try:
            self.page.goto(url, wait_until='load', timeout=BROWSER_TIMEOUT)
            self.log("- Página carregada (load)")
            self.page.wait_for_timeout(3000)
            self.log("- Recursos adicionais carregados")
        except Exception as e:
            self.log(f"Aviso de carregamento: {str(e)[:100]}")
            self.log("Tentando continuar mesmo assim...")

        self.base_url = self.page.url
        self.page.wait_for_timeout(2000)

    def extract_iframe_content(self):
        """
        Check if the page content is inside an iframe (common in site builders)
        and extract the actual content if found.
        """
        # Check for srcdoc iframes
        srcdoc_iframe = self.page.query_selector('iframe[srcdoc]')
        if srcdoc_iframe:
            self.log("Detectado iframe com srcdoc - extraindo conteúdo real...")
            srcdoc = srcdoc_iframe.get_attribute('srcdoc')
            if srcdoc:
                decoded_content = html.unescape(srcdoc)
                return decoded_content, True

        # Check for preview frames
        preview_selectors = [
            'iframe[class*="preview"]',
            'iframe[class*="site-frame"]',
            'iframe[class*="canvas"]',
            'iframe[id*="preview"]',
            '#preview-iframe',
            '.preview-frame iframe',
            '[role="tabpanel"] iframe',
            '[data-testid*="preview"] iframe',
        ]

        for selector in preview_selectors:
            iframe = self.page.query_selector(selector)
            if iframe:
                frames = self.page.frames
                for frame in frames:
                    if frame != self.page.main_frame and frame.url and frame.url != 'about:blank':
                        try:
                            self.log(f"Detectado iframe de preview - extraindo de {frame.url[:50]}...")
                            content = frame.content()
                            if len(content) > 500:
                                self.base_url = frame.url
                                return content, True
                        except:
                            pass

        # Check all frames including srcdoc
        for frame in self.page.frames:
            if frame != self.page.main_frame:
                try:
                    frame_url = frame.url
                    if frame_url == 'about:srcdoc':
                        content = frame.content()
                        if len(content) > 1000:
                            self.log("Detectado iframe srcdoc via frame - extraindo conteúdo...")
                            return content, True
                except:
                    pass

        # Check if main content is suspiciously small
        main_content = self.page.content()
        body = self.page.query_selector('body')
        if body:
            direct_children = self.page.query_selector_all('body > *')
            iframes = self.page.query_selector_all('iframe')

            if len(direct_children) <= 5 and len(iframes) > 0:
                for frame in self.page.frames:
                    if frame != self.page.main_frame:
                        try:
                            content = frame.content()
                            if len(content) > len(main_content) * 0.3:
                                self.log("Detectado wrapper com iframe - usando conteúdo do frame...")
                                if frame.url and frame.url not in ['about:blank', 'about:srcdoc']:
                                    self.base_url = frame.url
                                return content, True
                        except:
                            pass

        return None, False

    def force_eager_loading(self):
        """
        CRITICAL FIX: Force all lazy-loaded images/videos to load immediately.

        Removes loading="lazy" and converts data-src to src to prevent:
        1. GSAP ScrollTrigger calculating wrong page heights
        2. Images not loading before Playwright saves the page
        3. Layout shifts that break animations
        """
        self.log("Forçando carregamento eager de todos os recursos lazy...")

        try:
            modified = self.page.evaluate("""
                () => {
                    let count = 0;

                    // 1. Remove loading="lazy" from all images and iframes
                    document.querySelectorAll('img[loading="lazy"], iframe[loading="lazy"]').forEach(el => {
                        el.removeAttribute('loading');
                        count++;
                    });

                    // 2. Convert data-src/data-lazy to src (common lazy loading pattern)
                    document.querySelectorAll('img[data-src], img[data-lazy]').forEach(img => {
                        if (img.hasAttribute('data-src')) {
                            img.src = img.getAttribute('data-src');
                            count++;
                        } else if (img.hasAttribute('data-lazy')) {
                            img.src = img.getAttribute('data-lazy');
                            count++;
                        }
                    });

                    // 3. Convert data-srcset to srcset
                    document.querySelectorAll('img[data-srcset], source[data-srcset]').forEach(el => {
                        if (el.hasAttribute('data-srcset')) {
                            el.srcset = el.getAttribute('data-srcset');
                            count++;
                        }
                    });

                    // 4. Force video sources to load
                    document.querySelectorAll('video[data-src], source[data-src]').forEach(el => {
                        if (el.hasAttribute('data-src')) {
                            el.src = el.getAttribute('data-src');
                            count++;
                        }
                    });

                    // 5. Trigger IntersectionObserver for all images (force visibility)
                    document.querySelectorAll('img').forEach(img => {
                        if (img.loading) img.loading = 'eager';
                    });

                    return count;
                }
            """)

            if modified > 0:
                self.log(f"   {modified} elemento(s) lazy modificados para eager loading")
                # Wait for images to start loading
                self.page.wait_for_timeout(2000)

        except Exception as e:
            self.log(f"Erro ao forçar eager loading: {e}")

    def scroll_page(self):
        """Scroll the page to trigger lazy loading"""
        self.log("Rolando página para carregar conteúdo lazy...")
        try:
            # CRITICAL: Force eager loading BEFORE scrolling
            self.force_eager_loading()

            # Keep smooth scroll runtimes intact; only neutralize hard scroll locks.
            self.page.evaluate("""
                () => {
                    document.documentElement.style.scrollBehavior = 'auto';
                    document.body.style.scrollBehavior = 'auto';

                    if (getComputedStyle(document.body).overflow === 'hidden') {
                        document.body.style.overflow = 'auto';
                    }
                    if (getComputedStyle(document.documentElement).overflow === 'hidden') {
                        document.documentElement.style.overflow = 'auto';
                    }
                }
            """)

            # Find scroll container
            scroll_container = self.page.evaluate("""
                () => {
                    const selectors = [
                        '[data-scroll-container]',
                        '.scroll-container',
                        '.smooth-scroll',
                        'main',
                        '#__next',
                        '#__nuxt',
                        '#app'
                    ];

                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el && el.scrollHeight > window.innerHeight) {
                            return sel;
                        }
                    }
                    return null;
                }
            """)

            if scroll_container:
                self.log(f"Detectado container de scroll customizado: {scroll_container}")

            total_height = self.page.evaluate("Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)")
            viewport_height = self.page.evaluate("window.innerHeight")

            iteration = 0
            current = 0
            while current < total_height and iteration < MAX_SCROLL_ITERATIONS:
                self.page.evaluate("""
                    ({ selector, pos, step }) => {
                        requestAnimationFrame(() => {
                            const target = selector ? document.querySelector(selector) : null;
                            if (target) {
                                target.scrollTop = pos;
                            } else {
                                window.scrollTo(0, pos);
                                document.documentElement.scrollTop = pos;
                                document.body.scrollTop = pos;
                            }
                        });
                        return step;
                    }
                """, {"selector": scroll_container, "pos": current, "step": viewport_height})

                self.page.wait_for_timeout(600)
                current += viewport_height
                iteration += 1

                if not scroll_container:
                    new_height = self.page.evaluate("Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)")
                    if new_height > total_height:
                        total_height = new_height

            # Some fullpage/smooth-scroll sites only materialize the final section
            # after a bottom settle followed by a small upward bounce.
            self.page.evaluate("""
                async ({ selector }) => {
                    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                    const target = selector ? document.querySelector(selector) : null;

                    const getMaxScroll = () => {
                        if (target) {
                            return Math.max(0, target.scrollHeight - target.clientHeight);
                        }
                        const docHeight = Math.max(
                            document.body.scrollHeight,
                            document.documentElement.scrollHeight
                        );
                        return Math.max(0, docHeight - window.innerHeight);
                    };

                    const setScroll = (pos) => {
                        if (target) {
                            target.scrollTop = pos;
                        } else {
                            window.scrollTo(0, pos);
                            document.documentElement.scrollTop = pos;
                            document.body.scrollTop = pos;
                        }
                        document.dispatchEvent(new Event('scroll'));
                        window.dispatchEvent(new Event('scroll'));
                    };

                    const maxScroll = getMaxScroll();
                    const checkpoints = [
                        maxScroll,
                        maxScroll * 0.92,
                        maxScroll,
                        maxScroll * 0.82,
                        maxScroll,
                    ];

                    for (const pos of checkpoints) {
                        requestAnimationFrame(() => setScroll(pos));
                        await sleep(500);
                    }

                    window.dispatchEvent(new Event('resize'));
                }
            """, {"selector": scroll_container})
            self.page.wait_for_timeout(1200)

            # Scroll back to top
            self.page.evaluate("""
                ({ selector }) => {
                    requestAnimationFrame(() => {
                        const target = selector ? document.querySelector(selector) : null;
                        if (target) {
                            target.scrollTop = 0;
                        } else {
                            window.scrollTo(0, 0);
                            document.documentElement.scrollTop = 0;
                            document.body.scrollTop = 0;
                        }
                    });
                    setTimeout(() => {
                        document.dispatchEvent(new Event('scroll'));
                        window.dispatchEvent(new Event('resize'));
                        if (window.ScrollTrigger && typeof window.ScrollTrigger.refresh === 'function') {
                            try { window.ScrollTrigger.refresh(); } catch(e) {}
                        }
                        if (window.locomotiveScroll && typeof window.locomotiveScroll.update === 'function') {
                            try { window.locomotiveScroll.update(); } catch(e) {}
                        }
                        if (window.lenis && typeof window.lenis.resize === 'function') {
                            try { window.lenis.resize(); } catch(e) {}
                        }
                    }, 100);
                }
            """, {"selector": scroll_container})
            self.page.wait_for_timeout(1500)  # Extra wait for final recalculation
        except Exception as e:
            self.log(f"Erro no scroll: {e}")

    def simulate_interactions(self):
        """Simulate mouse movements and hovers to trigger lazy loading"""
        self.log("Simulando interações para carregar recursos dinâmicos...")

        try:
            viewport_height = self.page.evaluate("window.innerHeight")
            viewport_width = self.page.evaluate("window.innerWidth")

            # Move mouse to various positions to trigger hover effects
            positions = [
                (viewport_width * 0.5, viewport_height * 0.3),  # Center-top
                (viewport_width * 0.2, viewport_height * 0.5),  # Left-middle
                (viewport_width * 0.8, viewport_height * 0.5),  # Right-middle
                (viewport_width * 0.5, viewport_height * 0.7),  # Center-bottom
            ]

            for x, y in positions:
                try:
                    self.page.mouse.move(x, y)
                    self.page.wait_for_timeout(INTERACTION_WAIT)
                except:
                    pass

            # Hover over video elements to trigger player initialization
            try:
                videos = self.page.query_selector_all('video')
                for video in videos:
                    box = video.bounding_box()
                    if box and box['width'] > 50 and box['height'] > 50:
                        cx = box['x'] + box['width'] / 2
                        cy = box['y'] + box['height'] / 2
                        self.page.mouse.move(cx, cy)
                        self.page.wait_for_timeout(1000)
            except Exception:
                pass

            self.log("   Interações simuladas")
        except Exception as e:
            self.log(f"Erro ao simular interações: {e}")

    def interact_with_webgl_canvases(self):
        """Simulate focused interactions on WebGL canvas elements to trigger texture loading"""
        self.log("Detectando e interagindo com canvas WebGL...")

        try:
            # Find all canvas elements
            canvases = self.page.query_selector_all('canvas')

            if not canvases:
                self.log("   Nenhum canvas encontrado")
                return

            webgl_canvases = []
            for canvas in canvases:
                try:
                    box = canvas.bounding_box()
                    # Filter for substantial canvases (likely 3D scenes)
                    if box and box['width'] > 100 and box['height'] > 100:
                        webgl_canvases.append((canvas, box))
                except:
                    pass

            if not webgl_canvases:
                self.log("   Nenhum canvas WebGL significativo encontrado")
                return

            self.log(f"   Encontrados {len(webgl_canvases)} canvas para interação")

            # First pass: hover and center interaction
            for canvas, box in webgl_canvases:
                try:
                    center_x = box['x'] + box['width'] / 2
                    center_y = box['y'] + box['height'] / 2

                    # Hover over canvas center
                    self.page.mouse.move(center_x, center_y)
                    self.page.wait_for_timeout(1500)

                    # Sweep pattern: corners and center points
                    sweep_points = [
                        (0.2, 0.2),  # top-left
                        (0.8, 0.2),  # top-right
                        (0.5, 0.5),  # center
                        (0.2, 0.8),  # bottom-left
                        (0.8, 0.8),  # bottom-right
                    ]

                    for x_pct, y_pct in sweep_points:
                        x = box['x'] + box['width'] * x_pct
                        y = box['y'] + box['height'] * y_pct
                        self.page.mouse.move(x, y)
                        self.page.wait_for_timeout(500)

                    # Wait for texture fetches
                    self.page.wait_for_timeout(3000)
                except:
                    pass

            self.log("   Primeiro pass de interações concluído")

            # Wait for initial assets to load
            self.page.wait_for_timeout(5000)

            # Second pass: repeat center hovers (for assets that depend on first batch)
            for canvas, box in webgl_canvases:
                try:
                    center_x = box['x'] + box['width'] / 2
                    center_y = box['y'] + box['height'] / 2
                    self.page.mouse.move(center_x, center_y)
                    self.page.wait_for_timeout(2000)
                except:
                    pass

            self.log("   Segundo pass de interações concluído")

            # Extended wait for larger textures and async loads
            self.page.wait_for_timeout(8000)

            self.log("   Aguardando carregamento assíncrono de texturas...")

            # NOVO: Simular play em todos os vídeos após interações de canvas
            self.play_all_videos(wait_time=8000)

        except Exception as e:
            self.log(f"Erro ao interagir com canvas: {e}")

    def wait_for_css_injection(self, timeout=None):
        """
        Wait for CSS-in-JS libraries (styled-components, emotion, etc.) to inject styles.

        Next.js and modern SPAs use CSS-in-JS that injects <style> tags dynamically.
        We wait until we see substantive <style> tags in the DOM.
        """
        timeout = CSS_INJECTION_TIMEOUT if timeout is None else timeout
        self.log("Aguardando injeção de CSS-in-JS...")

        try:
            # Wait for <style> tags with data-styled or substantive content
            self.page.wait_for_function("""
                () => {
                    const styles = document.querySelectorAll('style');
                    if (styles.length === 0) return false;

                    // Check for styled-components
                    for (const style of styles) {
                        if (style.hasAttribute('data-styled') && style.textContent.length > 100) {
                            return true;
                        }
                    }

                    // Check for any substantive inline styles (CSS-in-JS injected)
                    let totalLength = 0;
                    for (const style of styles) {
                        totalLength += style.textContent.length;
                    }

                    // If we have >2KB of CSS injected, assume it's ready
                    return totalLength > 2000;
                }
            """, timeout=timeout)

            self.log("   CSS-in-JS detectado e carregado")
            # Extra wait for fonts and final rendering
            self.page.wait_for_timeout(2000)
        except:
            self.log("   Timeout aguardando CSS-in-JS (pode não usar styled-components)")

    def trigger_dynamic_imports(self):
        """
        Trigger Next.js/React dynamic imports by simulating route changes and component interactions.

        Next.js uses code splitting - CSS/JS chunks are loaded on-demand when:
        1. User navigates to a route (client-side routing)
        2. Components become visible (lazy loading)
        3. User interacts with dynamic features

        This method simulates these scenarios to force chunk loading.
        """
        self.log("Forçando carregamento de chunks dinâmicos (Next.js/React)...")

        try:
            # Step 1: Detect framework
            framework = self.page.evaluate("""
                () => {
                    if (window.__NEXT_DATA__) return 'nextjs';
                    if (window.__NUXT__) return 'nuxt';
                    if (window.Gatsby) return 'gatsby';
                    return 'unknown';
                }
            """)

            if framework != 'unknown':
                self.log(f"   Framework detectado: {framework}")

            # Step 2: Use REAL hover on visible interactive elements (Next.js prefetch trigger)
            # Collect visible links and buttons
            interactive_elements = self.page.evaluate("""
                () => {
                    const elements = [];
                    // Links (Next.js prefetches on hover)
                    document.querySelectorAll('a[href]').forEach(el => {
                        if (el.offsetParent !== null && el.href) {  // visible
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                elements.push({
                                    selector: `a[href="${el.getAttribute('href')}"]`,
                                    type: 'link'
                                });
                            }
                        }
                    });
                    // Buttons (might trigger dynamic imports)
                    document.querySelectorAll('button, [role="button"]').forEach((el, idx) => {
                        if (el.offsetParent !== null) {  // visible
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                // Use data attribute for unique selection
                                el.setAttribute('data-playwright-idx', idx);
                                elements.push({
                                    selector: `[data-playwright-idx="${idx}"]`,
                                    type: 'button'
                                });
                            }
                        }
                    });
                    return elements.slice(0, 50);  // Limit to first 50 elements
                }
            """)

            hover_count = 0
            for elem in interactive_elements:
                try:
                    # Use Playwright's real hover (not just dispatchEvent)
                    self.page.hover(elem['selector'], timeout=1000)
                    hover_count += 1
                    # Small delay to allow prefetch to trigger
                    self.page.wait_for_timeout(100)
                except Exception:
                    # Element might have disappeared or become hidden
                    pass

            if hover_count > 0:
                self.log(f"   {hover_count} elemento(s) interativo(s) receberam hover real")
                # Wait for prefetch requests to complete
                self.page.wait_for_timeout(2000)

            # Step 3: Expand all collapsed sections, accordions, tabs
            expanded = self.page.evaluate("""
                () => {
                    let count = 0;
                    // Open details/summary elements
                    document.querySelectorAll('details:not([open])').forEach(d => {
                        try {
                            d.open = true;
                            count++;
                        } catch(e) {}
                    });

                    // Expand elements with aria-expanded="false"
                    document.querySelectorAll('[aria-expanded="false"]').forEach(el => {
                        try {
                            if (el.offsetParent !== null) {  // visible
                                el.click();
                                count++;
                            }
                        } catch(e) {}
                    });

                    return count;
                }
            """)
            if expanded > 0:
                self.log(f"   {expanded} elemento(s) expansível(is) ativado(s)")
                self.page.wait_for_timeout(1500)

            # Step 4: Wait for lazy-loaded resources
            self.log("   Aguardando recursos lazy-loaded...")
            self.page.wait_for_timeout(3000)

        except Exception as e:
            self.log(f"   Erro ao forçar imports dinâmicos: {e}")

    def wait_for_network_idle(self, timeout=None, idle_time=None):
        """
        Wait for network activity to settle intelligently.
        Monitors network requests and waits for idle_time ms of silence.

        Args:
            timeout: Maximum time to wait
            idle_time: Time of silence to consider network idle
        """
        timeout = NETWORK_IDLE_TIMEOUT if timeout is None else timeout
        idle_time = NETWORK_IDLE_SILENCE if idle_time is None else idle_time
        self.log("Aguardando recursos adicionais (monitorando rede)...")

        import time
        start_time = time.time() * 1000  # Convert to milliseconds
        last_request_time = start_time
        request_count = 0

        # Track network requests
        def on_request(request):
            nonlocal last_request_time, request_count
            # Only track resource requests (not document/navigation)
            if request.resource_type in ['image', 'script', 'stylesheet', 'font', 'xhr', 'fetch', 'media', 'other']:
                last_request_time = time.time() * 1000
                request_count += 1

        # Attach listener
        self.page.on('request', on_request)

        # Wait loop
        while True:
            current_time = time.time() * 1000
            elapsed = current_time - start_time
            idle_duration = current_time - last_request_time

            # Check if we've been idle long enough
            if idle_duration >= idle_time:
                self.log(f"   Rede silenciosa por {idle_duration/1000:.1f}s ({request_count} requests capturados)")
                break

            # Check timeout
            if elapsed >= timeout:
                self.log(f"   Timeout atingido ({timeout/1000:.0f}s, {request_count} requests capturados)")
                break

            # Small sleep to avoid busy loop
            self.page.wait_for_timeout(100)

    def extract_framework_manifests(self):
        """
        CRITICAL FIX: Extract CSS paths from framework manifests (Next.js __BUILD_MANIFEST).

        Next.js doesn't hardcode CSS paths in JS - they're in a runtime manifest object.
        This method extracts ALL CSS paths directly from the framework before closing the browser.
        """
        self.log("Extraindo CSS de manifestos de frameworks (Next.js)...")

        try:
            css_urls = self.page.evaluate("""
                () => {
                    const css = new Set();

                    // Next.js Build Manifest
                    if (window.__BUILD_MANIFEST) {
                        Object.values(window.__BUILD_MANIFEST).flat().forEach(f => {
                            if (typeof f === 'string' && f.endsWith('.css')) {
                                css.add('/_next/' + f);
                            }
                        });
                    }

                    // Nuxt (if exists)
                    if (window.__NUXT__ && window.__NUXT__.config && window.__NUXT__.config.css) {
                        window.__NUXT__.config.css.forEach(f => css.add(f));
                    }

                    return Array.from(css);
                }
            """)

            if css_urls and len(css_urls) > 0:
                self.log(f"   {len(css_urls)} arquivo(s) CSS encontrados no manifest")
                return css_urls
            else:
                self.log("   Nenhum manifest de framework detectado")
                return []

        except Exception as e:
            self.log(f"   Erro ao extrair manifest: {e}")
            return []

    def collect_dynamic_asset_urls(self):
        """
        Coleta URLs relevantes presentes no DOM para fallback de download.

        Inclui assets clássicos e também páginas/support files same-origin que
        frameworks modernos requisitam em runtime (manifest, browserconfig,
        páginas de rotas top-level usadas por App Router/prefetch).
        """
        try:
            urls = self.page.evaluate("""
                () => {
                    const urls = new Set();
                    const extensionPattern = /\\.[a-z0-9]{1,8}$/i;
                    const inlineAssetPattern = /(?:^|["'`])((?:\\.?\\.\\/|\\/)?[A-Za-z0-9@_%./ -]+\\.(?:html?|css|js|mjs|json|webmanifest|png|jpe?g|svg|webp|avif|gif|woff2?|ttf|otf|eot|wasm|ico|xml|txt|mp4|webm|mov|bin|ktx2)(?:\\?[^"'`\\s<]*)?)/gi;

                    const addIfTruthy = (value) => {
                        if (value) urls.add(value);
                    };

                    const normalizeSameOriginTopLevelPage = (value) => {
                        if (!value) return null;
                        try {
                            const url = new URL(value, window.location.href);
                            if (!['http:', 'https:'].includes(url.protocol)) return null;
                            if (url.origin !== window.location.origin) return null;
                            if (url.hash && url.pathname === window.location.pathname && !url.search) return null;
                            if (extensionPattern.test(url.pathname)) return null;

                            const depth = url.pathname.split('/').filter(Boolean).length;
                            if (depth > 1) return null;

                            return url.href;
                        } catch (e) {
                            return null;
                        }
                    };

                    // Stylesheets
                    document.querySelectorAll('link[rel="stylesheet"]').forEach(l => addIfTruthy(l.href));
                    // Manifest / icons
                    document.querySelectorAll('link[rel="manifest"], link[rel*="icon"]').forEach(l => addIfTruthy(l.href));
                    // Scripts
                    document.querySelectorAll('script[src]').forEach(s => addIfTruthy(s.src));
                    // Imagens
                    document.querySelectorAll('img[src]').forEach(i => addIfTruthy(i.src));
                    // Vídeos e Áudios
                    document.querySelectorAll('video[src], audio[src]').forEach(m => addIfTruthy(m.src));
                    // <source src>
                    document.querySelectorAll('source[src]').forEach(s => addIfTruthy(s.src));
                    // <object data>
                    document.querySelectorAll('object[data]').forEach(o => addIfTruthy(o.data));
                    // <iframe src>
                    document.querySelectorAll('iframe[src]').forEach(f => addIfTruthy(f.src));
                    // <link rel="preload">
                    document.querySelectorAll('link[rel="preload"], link[rel="modulepreload"], link[rel="prefetch"]').forEach(l => addIfTruthy(l.href));
                    // Browser config
                    document.querySelectorAll('meta[name="msapplication-config"][content]').forEach(m => addIfTruthy(m.content));
                    // Same-origin top-level pages often requested later as RSC/prefetch payloads
                    document.querySelectorAll('a[href]').forEach(a => addIfTruthy(normalizeSameOriginTopLevelPage(a.getAttribute('href') || a.href)));
                    // <link rel="preload" as="image"> (srcset)
                    document.querySelectorAll('img[srcset], source[srcset]').forEach(el => {
                        if (el.srcset) {
                            el.srcset.split(',').forEach(src => {
                                const url = src.trim().split(' ')[0];
                                addIfTruthy(url);
                            });
                        }
                    });
                    // Inline runtime bootstraps often keep support pages and asset
                    // paths only as string literals instead of DOM attributes.
                    document.querySelectorAll('script:not([src]), style').forEach(el => {
                        const content = el.textContent || '';
                        if (!content) return;
                        inlineAssetPattern.lastIndex = 0;
                        for (const match of content.matchAll(inlineAssetPattern)) {
                            const value = (match[1] || '').trim();
                            if (value) addIfTruthy(value);
                        }
                    });
                    return Array.from(urls);
                }
            """)
            self.log(f"   {len(urls)} recurso(s) presentes no DOM para fallback")
            return urls
        except Exception as e:
            self.log(f"   Erro ao coletar assets do DOM: {e}")
            return []

    def get_cookies(self):
        """Get browser cookies for requests session"""
        return self.context.cookies()

    def _wait_for_next_stream_settle(self, timeout_ms=8000, stable_ms=1200, poll_ms=250):
        """
        Wait for Next.js app-router flight chunks to stop mutating before serialization.

        Some authenticated Next.js pages keep appending `self.__next_f.push(...)`
        scripts after `load`/network-idle. Capturing the DOM too early truncates the
        stream and breaks offline boot with "Connection closed".
        """
        try:
            has_next_stream = self.page.evaluate(
                "() => !!window.__next_f || !!document.querySelector('script:not([src])')"
            )
        except Exception:
            return

        if not has_next_stream:
            return

        deadline = time.time() + (timeout_ms / 1000.0)
        last_signature = None
        stable_since = None

        while time.time() < deadline:
            try:
                state = self.page.evaluate(
                    """
                    () => {
                        const scripts = Array.from(document.scripts || []).filter((script) => {
                            if (script.src) return false;
                            const text = script.textContent || '';
                            return text.includes('self.__next_f.push');
                        });

                        const chunks = scripts.map((script) => script.textContent || '');
                        const totalLength = chunks.reduce((acc, chunk) => acc + chunk.length, 0);
                        const lastChunk = chunks.length ? chunks[chunks.length - 1] : '';

                        return {
                            count: chunks.length,
                            totalLength,
                            hasTerminator: chunks.some((chunk) => /\\b[0-9a-z]+:null\\b/.test(chunk)),
                            lastTail: lastChunk.slice(-160),
                        };
                    }
                    """
                )
            except Exception:
                return

            signature = (
                state.get('count', 0),
                state.get('totalLength', 0),
                state.get('hasTerminator', False),
                state.get('lastTail', ''),
            )

            if signature == last_signature:
                if stable_since is None:
                    stable_since = time.time()

                stable_for_ms = (time.time() - stable_since) * 1000.0
                if state.get('hasTerminator') and stable_for_ms >= stable_ms:
                    self.log("Stream Next.js estabilizado antes da captura.")
                    return
                if stable_for_ms >= max(stable_ms * 2, 2500):
                    self.log("Stream Next.js estabilizado por timeout de segurança.")
                    return
            else:
                last_signature = signature
                stable_since = time.time()

            self.page.wait_for_timeout(poll_ms)

    def get_content(self):
        """Get page HTML content"""
        self._wait_for_next_stream_settle()

        try:
            self.page.evaluate("""
                () => {
                    for (const sheet of Array.from(document.styleSheets)) {
                        const ownerNode = sheet.ownerNode;
                        if (!ownerNode || ownerNode.tagName !== 'STYLE') continue;

                        let cssText = '';
                        try {
                            cssText = Array.from(sheet.cssRules || []).map(rule => rule.cssText).join('\\n');
                        } catch (e) {
                            continue;
                        }

                        if (!cssText || cssText.length < 50) continue;

                        if (!ownerNode.textContent || ownerNode.textContent.length < cssText.length) {
                            ownerNode.textContent = cssText;
                        }
                    }
                }
            """)
        except Exception as e:
            self.log(f"Erro ao serializar CSSOM antes de capturar HTML: {e}")

        return self.page.content()

    def close(self):
        """Close browser"""
        if self.context:
            try:
                self.context.close()
            except Exception:
                pass
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
        if self.playwright:
            self.playwright.stop()
