import os
import re
import html
import shutil
import hashlib
import requests
import urllib3
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import mimetypes

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class WebsiteDownloader:
    def __init__(self, url, output_dir, log_callback=None):
        self.url = url
        self.output_dir = output_dir
        self.assets_dir = os.path.join(output_dir, 'assets')
        self.resource_cache = {}  # url -> local_path
        self.network_resources = {}  # url -> {'body': bytes, 'content_type': str}
        self.base_url = url
        self.session = None  # Will be set with cookies from browser
        self.log_callback = log_callback or (lambda msg: print(msg))
        
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        os.makedirs(self.assets_dir)

    def log(self, message):
        """Send log message to callback"""
        self.log_callback(message)

    def _get_extension(self, url, content_type=''):
        """Get file extension from URL or content-type"""
        parsed = urlparse(url)
        path = parsed.path
        _, ext = os.path.splitext(path)
        
        if ext and len(ext) <= 6:
            return ext
        
        if content_type:
            mime = content_type.split(';')[0].strip()
            guessed = mimetypes.guess_extension(mime)
            if guessed:
                return guessed
        
        return ''

    def _generate_filename(self, url, content_type=''):
        """Generate a unique filename for a resource"""
        ext = self._get_extension(url, content_type)
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        
        parsed = urlparse(url)
        name = os.path.basename(parsed.path)
        if name:
            name = re.sub(r'[^a-zA-Z0-9_-]', '_', name.split('.')[0])[:30]
        else:
            name = 'resource'
        
        return f"{name}_{url_hash}{ext}"

    def _save_resource(self, url, content, content_type=''):
        """Save a resource to disk and return relative path"""
        if url in self.resource_cache:
            return self.resource_cache[url]
        
        if not content:
            return None
            
        filename = self._generate_filename(url, content_type)
        filepath = os.path.join(self.assets_dir, filename)
        
        with open(filepath, 'wb') as f:
            f.write(content if isinstance(content, bytes) else content.encode('utf-8'))
        
        rel_path = f"assets/{filename}"
        self.resource_cache[url] = rel_path
        return rel_path

    def _download_fallback(self, url):
        """Download a resource that wasn't captured during page load"""
        if url in self.resource_cache:
            return self.resource_cache[url]
        
        if not url or url.startswith('data:') or url.startswith('blob:') or url.startswith('#'):
            return url
            
        try:
            response = self.session.get(url, timeout=15, verify=False)
            if response.status_code == 200:
                content_type = response.headers.get('content-type', '')
                local_path = self._save_resource(url, response.content, content_type)
                return local_path
        except Exception as e:
            pass  # Silent fail for fallback
        
        return None

    def _get_resource(self, url, base=None):
        """Get a resource - from cache, network capture, or fallback download"""
        if not url or url.startswith('data:') or url.startswith('blob:') or url.startswith('#'):
            return url
        
        # Make absolute URL
        abs_url = urljoin(base or self.base_url, url)
        
        # Check cache first
        if abs_url in self.resource_cache:
            return self.resource_cache[abs_url]
        
        # Check network captures
        if abs_url in self.network_resources:
            res = self.network_resources[abs_url]
            return self._save_resource(abs_url, res['body'], res.get('content_type', ''))
        
        # Fallback download
        local_path = self._download_fallback(abs_url)
        if local_path:
            return local_path
        
        # Return original if all fails
        return url

    def _rewrite_css_urls(self, css_content, css_url):
        """Rewrite all url() references in CSS content"""
        def replacer(match):
            full_match = match.group(0)
            url_content = match.group(1).strip()
            
            # Remove quotes if present
            if url_content.startswith(("'", '"')) and url_content.endswith(("'", '"')):
                url_content = url_content[1:-1]
            
            if not url_content or url_content.startswith('data:'):
                return full_match
            
            # Make absolute URL relative to CSS file
            abs_url = urljoin(css_url, url_content)
            local_path = self._get_resource(abs_url)
            
            if local_path and local_path.startswith('assets/'):
                # CSS is in assets/, so reference sibling files directly
                return f'url("{os.path.basename(local_path)}")'
            
            return full_match
        
        return re.sub(r'url\(\s*([^)]+)\s*\)', replacer, css_content)

    def _detect_nextjs(self, soup):
        """Detect if page is built with Next.js even without #__next"""
        # Check for Next.js data script
        for script in soup.find_all('script'):
            script_id = script.get('id', '')
            script_text = script.string or ''
            if '__NEXT_DATA__' in script_id or '__NEXT_DATA__' in script_text:
                return True
            if 'self.__next' in script_text:
                return True
        
        # Check for Next.js script patterns in src
        for script in soup.find_all('script', src=True):
            src = script['src']
            if '_next/' in src or 'webpack' in src.lower():
                return True
        
        # Check for Next.js link patterns
        for link in soup.find_all('link'):
            href = link.get('href', '')
            if '_next/' in href:
                return True
        
        return False

    def _fix_scroll_blocking(self, soup):
        """Fix CSS and HTML issues that block scrolling in offline viewing"""
        self.log("🔧 Corrigindo problemas de scroll para visualização offline...")
        
        # 1. Fix html element
        html_elem = soup.find('html')
        if html_elem:
            html_classes = html_elem.get('class', [])
            if isinstance(html_classes, str):
                html_classes = html_classes.split()
            
            # Remove Lenis-specific classes that block scroll
            lenis_classes = ['lenis', 'lenis-smooth', 'lenis-scrolling', 'lenis-stopped', 
                           'has-scroll-smooth', 'has-scroll-init', 'locomotive-scroll']
            new_classes = [c for c in html_classes if c.lower() not in [lc.lower() for lc in lenis_classes]]
            if new_classes != html_classes:
                html_elem['class'] = new_classes
                self.log("   ✅ Removidas classes Lenis/Locomotive do html")
        
        # 2. Fix body element
        body = soup.find('body')
        if body:
            body_classes = body.get('class', [])
            if isinstance(body_classes, str):
                body_classes = body_classes.split()
            
            # Remove scroll-blocking classes
            blocking_classes = ['overflow-hidden', 'no-scroll', 'scroll-lock', 'fixed', 
                              'lenis', 'lenis-smooth', 'has-scroll-smooth']
            new_classes = [c for c in body_classes if c.lower() not in [bc.lower() for bc in blocking_classes]]
            
            # Fix flex centering that cuts off content
            if 'items-center' in new_classes and 'flex' in new_classes:
                new_classes = [c if c != 'items-center' else 'items-start' for c in new_classes]
                self.log("   ✅ Corrigida centralização vertical do body")
            
            if new_classes != body_classes:
                body['class'] = new_classes
        
        # 3. Fix main containers that might have height: 100vh with overflow hidden
        problematic_selectors = [
            '[data-scroll-container]',
            '.scroll-container', 
            '.smooth-scroll',
            '[data-lenis-prevent]',
            '.lenis-wrapper',
        ]
        
        for elem in soup.find_all(class_=lambda c: c and any(
            x in str(c).lower() for x in ['scroll-container', 'smooth-scroll', 'lenis', 'locomotive']
        )):
            # Remove data attributes that control smooth scroll
            for attr in list(elem.attrs.keys()):
                if 'scroll' in attr.lower() or 'lenis' in attr.lower():
                    del elem[attr]
        
        # 4. Remove/fix inline styles that block scroll
        for elem in soup.find_all(attrs={'style': True}):
            style = elem['style']
            if 'overflow' in style.lower() and 'hidden' in style.lower():
                # Remove overflow: hidden from inline styles
                new_style = re.sub(r'overflow\s*:\s*hidden\s*;?', '', style, flags=re.IGNORECASE)
                elem['style'] = new_style.strip()
        
        # 5. Inject CSS overrides to ensure scrolling works
        scroll_fix_css = """
        /* Scroll fixes for offline viewing */
        html, body {
            overflow: auto !important;
            overflow-x: hidden !important;
            height: auto !important;
            min-height: 100% !important;
            scroll-behavior: auto !important;
            opacity: 1 !important;
            visibility: visible !important;
        }
        
        /* Force visibility - many sites use JS animations for initial display */
        body, .wrapper, main, #__next, #app, .page, .content {
            opacity: 1 !important;
            visibility: visible !important;
            transform: none !important;
        }
        
        /* Disable loader/preloader overlays */
        .loader, .preloader, .loading, [class*="loader"], [class*="preloader"] {
            display: none !important;
            opacity: 0 !important;
        }
        
        /* Show elements that might be hidden for animation */
        .word-inner, .char, .line, [data-aos], [data-scroll],
        .hero-text span, .hero-fade, [class*="hero"] span {
            opacity: 1 !important;
            transform: none !important;
            visibility: visible !important;
        }
        
        /* Reset Tailwind animation utility classes */
        .translate-y-full, .translate-x-full, .-translate-y-full, .-translate-x-full,
        .translate-y-1\/2, .-translate-y-1\/2, .translate-y-\[100\%\], .translate-y-\[110\%\] {
            transform: none !important;
        }
        
        /* Force visibility on common hidden-for-animation patterns */
        .opacity-0, [class*="opacity-0"] {
            opacity: 1 !important;
        }
        
        /* Reset scale transforms used for animations */
        .scale-0, .scale-50, .scale-75 {
            transform: none !important;
        }
        
        html.lenis, html.lenis-smooth, 
        body.lenis, body.lenis-smooth,
        .lenis-wrapper, .lenis-content,
        [data-lenis-prevent], [data-scroll-container] {
            overflow: visible !important;
            height: auto !important;
        }
        
        /* Fix flex containers that might cut off content */
        body.flex.items-center,
        body.flex.justify-center {
            align-items: flex-start !important;
            min-height: 100vh;
            height: auto !important;
        }
        
        /* Ensure main content scrolls */
        main, #__next, #__nuxt, #app, .main-content {
            overflow: visible !important;
            height: auto !important;
        }
        """
        
        # Add the fix CSS as a style tag at the end of head
        head = soup.find('head')
        if head:
            fix_style = soup.new_tag('style')
            fix_style['data-scroll-fix'] = 'true'
            fix_style.string = scroll_fix_css
            head.append(fix_style)
            self.log("   ✅ Injetado CSS para corrigir scroll")
        
        # 6. Remove Lenis/Locomotive script tags that might interfere
        scripts_removed = 0
        for script in soup.find_all('script'):
            src = script.get('src', '') or ''
            script_text = script.string or ''
            
            # Check for smooth scroll libraries
            if any(x in src.lower() for x in ['lenis', 'locomotive', 'smooth-scroll']):
                script.decompose()
                scripts_removed += 1
            elif any(x in script_text.lower() for x in ['new lenis', 'new locomotivescroll', 'smoothscroll']):
                script.decompose()
                scripts_removed += 1
        
        if scripts_removed > 0:
            self.log(f"   ✅ Removidos {scripts_removed} scripts de smooth scroll")

    def _process_srcset(self, srcset, base=None):
        """Process a srcset attribute and return the rewritten version"""
        if not srcset:
            return srcset
        
        new_parts = []
        parts = srcset.split(',')
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            tokens = part.split()
            if not tokens:
                continue
            
            url = tokens[0]
            descriptor = ' '.join(tokens[1:]) if len(tokens) > 1 else ''
            
            if url.startswith('data:'):
                new_parts.append(part)
                continue
            
            local_path = self._get_resource(url, base)
            if local_path and local_path != url:
                new_parts.append(f"{local_path} {descriptor}".strip())
            else:
                new_parts.append(part)
        
        return ', '.join(new_parts) if new_parts else srcset

    def _extract_iframe_content(self, page):
        """
        Check if the page content is inside an iframe (common in site builders like Aura, Webflow, etc.)
        and extract the actual content if found.
        """
        # Check for srcdoc iframes (content embedded in attribute)
        srcdoc_iframe = page.query_selector('iframe[srcdoc]')
        if srcdoc_iframe:
            self.log("🔍 Detectado iframe com srcdoc - extraindo conteúdo real...")
            srcdoc = srcdoc_iframe.get_attribute('srcdoc')
            if srcdoc:
                # Decode HTML entities
                decoded_content = html.unescape(srcdoc)
                return decoded_content, True
        
        # Check for preview frames (common in site builders)
        preview_selectors = [
            'iframe[class*="preview"]',
            'iframe[class*="site-frame"]',
            'iframe[class*="canvas"]',
            'iframe[id*="preview"]',
            '#preview-iframe',
            '.preview-frame iframe',
            '[role="tabpanel"] iframe',  # Aura-style tab panels
            '[data-testid*="preview"] iframe',
        ]
        
        for selector in preview_selectors:
            iframe = page.query_selector(selector)
            if iframe:
                # Try to get the frame content
                frames = page.frames
                for frame in frames:
                    if frame != page.main_frame and frame.url and frame.url != 'about:blank':
                        try:
                            self.log(f"🔍 Detectado iframe de preview - extraindo de {frame.url[:50]}...")
                            content = frame.content()
                            if len(content) > 500:  # Has substantial content
                                self.base_url = frame.url
                                return content, True
                        except:
                            pass
        
        # Check all frames including those with srcdoc (about:srcdoc URL)
        for frame in page.frames:
            if frame != page.main_frame:
                try:
                    frame_url = frame.url
                    # Handle frames with srcdoc (they have about:srcdoc URL)
                    if frame_url == 'about:srcdoc':
                        content = frame.content()
                        if len(content) > 1000:  # Substantial content
                            self.log("🔍 Detectado iframe srcdoc via frame - extraindo conteúdo...")
                            return content, True
                except:
                    pass
        
        # Check if main content is suspiciously small (might be a wrapper)
        main_content = page.content()
        body = page.query_selector('body')
        if body:
            # Check if body has very few elements but contains an iframe
            direct_children = page.query_selector_all('body > *')
            iframes = page.query_selector_all('iframe')
            
            if len(direct_children) <= 5 and len(iframes) > 0:
                # Page might be a wrapper - try to get iframe content
                for frame in page.frames:
                    if frame != page.main_frame:
                        try:
                            content = frame.content()
                            if len(content) > len(main_content) * 0.3:
                                self.log("🔍 Detectado wrapper com iframe - usando conteúdo do frame...")
                                if frame.url and frame.url not in ['about:blank', 'about:srcdoc']:
                                    self.base_url = frame.url
                                return content, True
                        except:
                            pass
        
        return None, False

    def process(self):
        with sync_playwright() as p:
            self.log("🚀 Iniciando navegador...")
            browser = p.chromium.launch(headless=True)
            
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080},
                device_scale_factor=1,
            )
            
            page = context.new_page()
            
            # Capture network responses (including redirects)
            def capture_response(response):
                try:
                    url = response.url
                    if response.status == 200 and not url.startswith(('data:', 'blob:')):
                        try:
                            body = response.body()
                            resource_data = {
                                'body': body,
                                'content_type': response.headers.get('content-type', '')
                            }
                            # Store by final URL
                            self.network_resources[url] = resource_data
                            
                            # Also store by original request URL (handles redirects)
                            request_url = response.request.url
                            if request_url != url:
                                self.network_resources[request_url] = resource_data
                        except:
                            pass
                except:
                    pass
            
            page.on("response", capture_response)
            
            self.log(f"🌐 Carregando {self.url}...")
            try:
                page.goto(self.url, wait_until='networkidle', timeout=120000)
            except Exception as e:
                self.log(f"⚠️ Aviso de carregamento: {str(e)[:50]}...")
            
            self.base_url = page.url
            
            # Wait for dynamic content
            page.wait_for_timeout(2000)
            
            # Check for iframe content (site builders like Aura, Webflow, etc.)
            iframe_content, is_iframe = self._extract_iframe_content(page)
            
            if not is_iframe:
                self.log("📜 Rolando página para carregar conteúdo lazy...")
                self._scroll_page(page)
                page.wait_for_timeout(3000)
            
            # Get cookies from browser for fallback downloads
            cookies = context.cookies()
            
            # Setup requests session with browser cookies
            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': self.base_url,
            })
            for cookie in cookies:
                self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain', ''))
            
            # Get final HTML - use iframe content if detected
            if is_iframe and iframe_content:
                html_content = iframe_content
                self.log("✨ Usando conteúdo extraído do iframe")
            else:
                html_content = page.content()
            
            self.log(f"📦 Capturados {len(self.network_resources)} recursos de rede")
            
            browser.close()
        
        # Process HTML
        self.log("🔧 Processando HTML e assets...")
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Fix scroll-blocking issues for offline viewing
        self._fix_scroll_blocking(soup)
        
        # Remove any remaining iframes that are wrappers (like Aura preview frames)
        for iframe in soup.find_all('iframe'):
            # Keep only essential iframes (videos, maps, etc.)
            src = iframe.get('src', '') or ''
            srcdoc = iframe.get('srcdoc', '')
            
            # Remove preview/wrapper iframes
            if srcdoc or 'preview' in str(iframe.get('class', '')).lower():
                iframe.decompose()
        
        # 1. Process external stylesheets
        self.log("🎨 Processando stylesheets...")
        for link in soup.find_all('link', rel='stylesheet'):
            href = link.get('href')
            if not href or href.startswith('data:'):
                continue
            
            abs_url = urljoin(self.base_url, href)
            
            # Try to get CSS content
            css_content = None
            if abs_url in self.network_resources:
                try:
                    css_content = self.network_resources[abs_url]['body'].decode('utf-8', errors='ignore')
                except:
                    pass
            
            if not css_content:
                # Fallback download
                try:
                    response = self.session.get(abs_url, timeout=15, verify=False)
                    if response.status_code == 200:
                        css_content = response.text
                except:
                    pass
            
            if css_content:
                css_content = self._rewrite_css_urls(css_content, abs_url)
                local_path = self._save_resource(abs_url, css_content.encode('utf-8'), 'text/css')
                if local_path:
                    link['href'] = local_path
        
        # 2. Process inline <style> tags
        self.log("✨ Processando estilos inline...")
        for style_tag in soup.find_all('style'):
            if style_tag.string:
                style_tag.string = self._rewrite_css_urls(style_tag.string, self.base_url)
        
        # 3. Process scripts
        self.log("📝 Processando scripts...")
        for script in soup.find_all('script', src=True):
            src = script.get('src')
            if not src or src.startswith('data:'):
                continue
            
            local_path = self._get_resource(src)
            if local_path and local_path != src:
                script['src'] = local_path
                for attr in ['integrity', 'crossorigin', 'nonce']:
                    if script.has_attr(attr):
                        del script[attr]
        
        # 4. Process all image-related elements
        self.log("🖼️ Processando imagens...")
        for elem in soup.find_all(['img', 'source', 'video', 'audio', 'picture', 'input']):
            # Process src
            src = elem.get('src')
            
            # Check lazy loading attributes first
            for attr in ['data-src', 'data-original', 'data-lazy-src', 'data-url', 'data-image', 'data-bg']:
                if elem.get(attr):
                    lazy_src = elem[attr]
                    local_path = self._get_resource(lazy_src)
                    if local_path and local_path != lazy_src:
                        elem['src'] = local_path
                        del elem[attr]
                        src = None  # Already handled
                    break
            
            if src and not src.startswith('data:'):
                local_path = self._get_resource(src)
                if local_path and local_path != src:
                    elem['src'] = local_path
            
            # Process srcset
            srcset = elem.get('srcset')
            if srcset:
                elem['srcset'] = self._process_srcset(srcset)
            
            # Process data-srcset
            data_srcset = elem.get('data-srcset')
            if data_srcset:
                elem['data-srcset'] = self._process_srcset(data_srcset)
            
            # Process poster for video
            if elem.name == 'video' and elem.get('poster'):
                poster = elem['poster']
                local_path = self._get_resource(poster)
                if local_path and local_path != poster:
                    elem['poster'] = local_path
        
        # 5. Process inline style attributes
        self.log("🔗 Processando atributos de estilo inline...")
        for elem in soup.find_all(attrs={'style': True}):
            style = elem['style']
            if 'url(' in style:
                elem['style'] = self._rewrite_css_urls(style, self.base_url)
        
        # 6. Process favicons and other link tags with URLs
        for link in soup.find_all('link'):
            if link.get('href') and link.get('rel'):
                rel = link['rel']
                if isinstance(rel, list):
                    rel = ' '.join(rel)
                if 'icon' in rel.lower() or 'apple-touch' in rel.lower() or 'manifest' in rel.lower():
                    href = link['href']
                    if not href.startswith('data:'):
                        local_path = self._get_resource(href)
                        if local_path and local_path != href:
                            link['href'] = local_path
        
        # 7. Process meta tags with image URLs (og:image, etc.)
        for meta in soup.find_all('meta', attrs={'content': True}):
            prop = meta.get('property', '') or meta.get('name', '')
            if 'image' in prop.lower():
                content = meta['content']
                if content and not content.startswith('data:') and ('http' in content or content.startswith('/')):
                    local_path = self._get_resource(content)
                    if local_path and local_path != content:
                        meta['content'] = local_path
        
        # 8. Process background images in divs and other elements
        for elem in soup.find_all(attrs={'data-background': True}):
            bg = elem['data-background']
            if bg and not bg.startswith('data:'):
                local_path = self._get_resource(bg)
                if local_path and local_path != bg:
                    elem['data-background'] = local_path
        
        # 9. Fix navigation links that won't work locally
        # Convert "/" to "#" or "index.html" so they don't break when opened offline
        self.log("🔗 Corrigindo links de navegação...")
        for a in soup.find_all('a', href=True):
            href = a['href']
            # Convert root links to stay on page
            if href == '/':
                a['href'] = '#'
            # Convert other relative paths to anchors (they won't work offline anyway)
            elif href.startswith('/') and not href.startswith('//'):
                # Keep as anchor to prevent navigation errors
                a['href'] = '#'
        
        # 10. Handle SPA frameworks (Gatsby, Next.js, Nuxt, etc.)
        # These frameworks use client-side routing that doesn't work offline
        # The HTML is already server-rendered, so we remove ALL framework scripts
        is_gatsby = soup.find(id='___gatsby') is not None
        is_nextjs = soup.find(id='__next') is not None or self._detect_nextjs(soup)
        is_nuxt = soup.find(id='__nuxt') is not None
        
        if is_gatsby or is_nextjs or is_nuxt:
            framework = 'Gatsby' if is_gatsby else ('Next.js' if is_nextjs else 'Nuxt')
            self.log(f"🛡️ Detectado {framework} - removendo scripts do framework...")
            
            scripts_removed = 0
            # Safe third-party scripts to keep
            safe_keywords = ['google', 'analytics', 'gtm', 'gtag', 'facebook', 'pixel', 
                           'elfsight', 'hubspot', 'intercom', 'crisp', 'drift', 'hotjar',
                           'clarity', 'segment', 'mixpanel', 'amplitude', 'adobe', 'privacy']
            
            for script in soup.find_all('script'):
                src = script.get('src', '')
                script_text = script.string or ''
                
                # Check if this is a safe third-party script
                is_safe = any(safe in src.lower() for safe in safe_keywords)
                
                if not is_safe:
                    # Remove framework-specific scripts
                    should_remove = False
                    
                    # Gatsby patterns
                    if is_gatsby and ('framework-' in src or 'app-' in src or 
                                     'commons-' in src or 'component-' in src or
                                     'webpack-runtime' in src or 'polyfill' in src):
                        should_remove = True
                    
                    # Next.js patterns - be more aggressive
                    if is_nextjs:
                        # Remove any local script (likely framework code)
                        if src and not src.startswith(('http://', 'https://', '//')):
                            should_remove = True
                        # Remove scripts with _next paths (may be rewritten to assets/)
                        if '_next/' in src or 'webpack' in src or 'polyfill' in src:
                            should_remove = True
                        if '__next' in script_text or 'self.__next' in script_text:
                            should_remove = True
                        # Remove chunk loading scripts
                        if '-' in src and src.endswith('.js') and 'assets/' in src:
                            # Pattern like: assets/1517-7693bd4fa37b021c_xxx.js
                            should_remove = True
                    
                    # Nuxt patterns
                    if is_nuxt and ('_nuxt/' in src or '__NUXT__' in script_text or
                                   'nuxt' in src.lower()):
                        should_remove = True
                    
                    # Remove inline hydration scripts
                    if ('hydrate' in script_text.lower() or 
                        'window.__' in script_text or
                        'GATSBY' in script_text or
                        'pageData' in script_text or
                        'self.__next' in script_text or
                        '__NEXT_DATA__' in script_text):
                        should_remove = True
                    
                    if should_remove:
                        script.decompose()
                        scripts_removed += 1
            
            # Also remove preload/prefetch links that point to framework resources
            links_removed = 0
            for link in soup.find_all('link', rel=lambda r: r and any(x in r for x in ['preload', 'prefetch', 'modulepreload'])):
                href = link.get('href', '')
                if '_next/' in href or (href.startswith('assets/') and '-' in href):
                    link.decompose()
                    links_removed += 1
            
            self.log(f"   ✅ Removidos {scripts_removed} scripts e {links_removed} preloads do framework")
        
        # Save HTML
        html_output = str(soup)
        with open(os.path.join(self.output_dir, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(html_output)
        
        self.log(f"✅ Concluído! {len(self.resource_cache)} assets salvos")
        return True

    def _scroll_page(self, page):
        """Scroll the page to trigger lazy loading"""
        try:
            # First, try to disable smooth scroll libraries (Lenis, Locomotive, etc.)
            page.evaluate("""
                () => {
                    // Disable Lenis smooth scroll
                    if (window.lenis) {
                        try { window.lenis.destroy(); } catch(e) {}
                    }
                    // Disable Locomotive Scroll
                    if (window.locomotiveScroll) {
                        try { window.locomotiveScroll.destroy(); } catch(e) {}
                    }
                    // Reset any scroll-behavior smooth
                    document.documentElement.style.scrollBehavior = 'auto';
                    document.body.style.scrollBehavior = 'auto';
                    
                    // Remove overflow hidden that might prevent scrolling
                    if (getComputedStyle(document.body).overflow === 'hidden') {
                        document.body.style.overflow = 'auto';
                    }
                    if (getComputedStyle(document.documentElement).overflow === 'hidden') {
                        document.documentElement.style.overflow = 'auto';
                    }
                }
            """)
            
            # Find the actual scroll container (some sites use custom containers)
            scroll_container = page.evaluate("""
                () => {
                    // Check for common scroll container patterns
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
                self.log(f"🔍 Detectado container de scroll customizado: {scroll_container}")
            
            total_height = page.evaluate("Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)")
            viewport_height = page.evaluate("window.innerHeight")
            
            # Limit scroll iterations to prevent infinite loops
            max_iterations = 20
            iteration = 0
            
            current = 0
            while current < total_height and iteration < max_iterations:
                # Scroll using multiple methods for better compatibility
                page.evaluate(f"""
                    (pos) => {{
                        window.scrollTo(0, pos);
                        document.documentElement.scrollTop = pos;
                        document.body.scrollTop = pos;
                        
                        // Also try scrolling custom containers
                        const containers = document.querySelectorAll('[data-scroll-container], .scroll-container, main');
                        containers.forEach(c => {{ c.scrollTop = pos; }});
                    }}
                """, current)
                
                page.wait_for_timeout(600)
                current += viewport_height
                iteration += 1
                
                new_height = page.evaluate("Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)")
                if new_height > total_height:
                    total_height = new_height
            
            # Scroll back to top
            page.evaluate("""
                () => {
                    window.scrollTo(0, 0);
                    document.documentElement.scrollTop = 0;
                    document.body.scrollTop = 0;
                }
            """)
            page.wait_for_timeout(1000)
        except Exception as e:
            self.log(f"⚠️ Erro no scroll: {e}")


def get_site_name(url):
    """Extract a clean site name from URL for the zip filename"""
    parsed = urlparse(url)
    # Get domain without www
    domain = parsed.netloc.replace('www.', '')
    # Clean special characters
    clean_name = re.sub(r'[^a-zA-Z0-9.-]', '_', domain)
    # Add path info if present (cleaned)
    if parsed.path and parsed.path != '/':
        path_part = re.sub(r'[^a-zA-Z0-9]', '_', parsed.path.strip('/'))[:30]
        clean_name = f"{clean_name}_{path_part}"
    return clean_name


def zip_directory(folder_path, output_path):
    """Create a zip file from a directory"""
    base_name = output_path.replace('.zip', '')
    shutil.make_archive(base_name, 'zip', folder_path)
    return base_name + '.zip'
