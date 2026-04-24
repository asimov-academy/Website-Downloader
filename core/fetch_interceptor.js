/**
 * Fetch/XHR Interceptor - Injected into downloaded sites to resolve remote URLs locally.
 *
 * This script is loaded as a template. Python replaces the placeholder comment below
 * with the actual resource map code before injecting into the page <head>.
 *
 * Placeholder: /* __RESOURCE_MAP_CODE__ * /
 */
(async function() {
    /* __RESOURCE_MAP_CODE__ */

    // Index 1: local-path basename -> [localPaths]  (for relative imports like ./chunk.js)
    const basenameIndex = {};
    // Index 2: original-url basename -> [localPaths]  (for requests using original filename before hash suffix)
    const originalBasenameIndex = {};
    // Index 3/4: basename stem -> [{ basename, localPath }] for extension-family fallback
    const localStemIndex = {};
    const originalStemIndex = {};

    const EXTENSION_FAMILIES = [
        ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif'],
        ['.mp4', '.webm', '.mov', '.m4v', '.ogv'],
        ['.mp3', '.wav', '.ogg', '.m4a', '.aac'],
        ['.woff', '.woff2', '.ttf', '.otf', '.eot'],
    ];

    function splitBasenameParts(filename) {
        const clean = String(filename || '').split('?')[0].split('#')[0];
        const dotIndex = clean.lastIndexOf('.');
        if (dotIndex <= 0) return { basename: clean, stem: clean, ext: '' };
        return {
            basename: clean,
            stem: clean.slice(0, dotIndex),
            ext: clean.slice(dotIndex).toLowerCase(),
        };
    }

    function stemCandidates(stem) {
        const candidates = [];
        if (stem) candidates.push(stem);
        for (const separator of ['.', '-']) {
            if (stem && stem.includes(separator)) {
                const prefix = stem.split(separator, 1)[0];
                if (prefix && !candidates.includes(prefix)) {
                    candidates.push(prefix);
                }
            }
        }
        return candidates;
    }

    function getExtensionFamily(ext) {
        for (const family of EXTENSION_FAMILIES) {
            if (family.includes(ext)) return family;
        }
        return null;
    }

    function areCompatibleExtensions(left, right) {
        if (!left || !right) return false;
        if (left === right) return true;
        const family = getExtensionFamily(left);
        return !!family && family.includes(right);
    }

    function pushStemIndex(index, basename, localPath) {
        const parts = splitBasenameParts(basename);
        if (!parts.stem || !parts.ext) return;
        for (const candidateStem of stemCandidates(parts.stem)) {
            if (!index[candidateStem]) index[candidateStem] = [];
            index[candidateStem].push({ basename: parts.basename, ext: parts.ext, localPath });
        }
    }

    function findEquivalentBasenameMatch(basename, index, withLeadingSlash) {
        const requested = splitBasenameParts(basename);
        if (!requested.stem || !requested.ext) return null;

        const compatible = [];
        const seen = new Set();
        for (const candidateStem of stemCandidates(requested.stem)) {
            const candidates = index[candidateStem] || [];
            for (const candidate of candidates) {
                if (!areCompatibleExtensions(requested.ext, candidate.ext)) continue;
                const key = `${candidate.localPath}::${candidate.ext}`;
                if (seen.has(key)) continue;
                seen.add(key);
                compatible.push(candidate);
            }
        }
        if (compatible.length !== 1) return null;

        const match = compatible[0].localPath;
        return withLeadingSlash ? '/' + match : match;
    }

    Object.entries(resourceMap).forEach(([originalUrl, localPath]) => {
        const normalizedLocalPath = String(localPath || '').replace(/^\/+/, '');
        // Build local basename index
        if (normalizedLocalPath.startsWith('assets/')) {
            const localBasename = normalizedLocalPath.split('/').pop();
            if (!basenameIndex[localBasename]) basenameIndex[localBasename] = [];
            basenameIndex[localBasename].push(normalizedLocalPath);
            pushStemIndex(localStemIndex, localBasename, normalizedLocalPath);
        }
        // Build original URL basename index
        try {
            const origBasename = originalUrl.split('/').pop().split('?')[0];
            if (origBasename) {
                if (!originalBasenameIndex[origBasename]) originalBasenameIndex[origBasename] = [];
                originalBasenameIndex[origBasename].push(localPath);
                pushStemIndex(originalStemIndex, origBasename, normalizedLocalPath || localPath);
            }
        } catch(e) {}
    });

    // Normalize any URL to absolute href
    function normalizeUrl(url, baseUrl) {
        if (!url) return url;
        if (typeof url === 'object' && url.url) url = url.url; // Request object
        if (url.startsWith('data:') || url.startsWith('blob:')) return url;
        try {
            return new URL(url, baseUrl || window.location.href).href;
        } catch(e) {
            return url;
        }
    }

    // Resolve relative paths (/chunk.js, ../utils.js) using referrer context
    function resolveRelativePath(url, referrer) {
        if (!url.startsWith('./') && !url.startsWith('../')) return null;
        try {
            const referrerUrl = new URL(referrer || window.location.href);
            const referrerDir = referrerUrl.pathname.substring(0, referrerUrl.pathname.lastIndexOf('/') + 1);
            const resolved = new URL(url, window.location.origin + referrerDir).pathname;
            const basename = resolved.split('/').pop();

            if (basenameIndex[basename]) {
                if (basenameIndex[basename].length === 1) return '/' + basenameIndex[basename][0];
                // Multiple matches: prefer same directory structure
                const referrerPath = referrer.replace(window.location.origin, '');
                for (const candidate of basenameIndex[basename]) {
                    if (referrerPath.includes('assets/') && candidate.includes(basename)) {
                        return '/' + candidate;
                    }
                }
                return '/' + basenameIndex[basename][0];
            }
            // Try original basename index too
            if (originalBasenameIndex[basename] && originalBasenameIndex[basename].length === 1) {
                return originalBasenameIndex[basename][0];
            }
            const originalStemMatch = findEquivalentBasenameMatch(basename, originalStemIndex, false);
            if (originalStemMatch) return originalStemMatch;
            const localStemMatch = findEquivalentBasenameMatch(basename, localStemIndex, true);
            if (localStemMatch) return localStemMatch;
        } catch(e) {
            console.warn('[Fetch Interceptor] Relative path resolution failed:', url, e);
        }
        return null;
    }

    // Main lookup: find local path for any URL
    function getLocalPath(url, referrer) {
        const rawUrl = typeof url === 'string'
            ? url
            : (url && typeof url === 'object' && url.url ? url.url : String(url || ''));

        // 1. Relative paths (/x, ../x) - resolve via referrer
        if (rawUrl.startsWith('./') || rawUrl.startsWith('../')) {
            const resolved = resolveRelativePath(rawUrl, referrer);
            if (resolved) return resolved;
        }

        const normalized = normalizeUrl(rawUrl, referrer);

        // 2. Exact match in resource map
        if (resourceMap[normalized]) return resourceMap[normalized];

        // 3. Protocol-relative variant (//domain.com/path)
        const withoutProtocol = normalized.replace(/^https?:/, '');
        if (resourceMap[withoutProtocol]) return resourceMap[withoutProtocol];

        // 4. Basename match against ORIGINAL URL basenames
        //    This handles cases where the saved file has a hash suffix appended:
        //    browser requests "chunk.js" but file was saved as "chunk_abc123.js"
        try {
            const basename = normalized.split('/').pop().split('?')[0];
            if (basename) {
                if (originalBasenameIndex[basename] && originalBasenameIndex[basename].length === 1) {
                    return originalBasenameIndex[basename][0];
                }
                // 5. Fallback: local path basename index
                if (basenameIndex[basename] && basenameIndex[basename].length === 1) {
                    return '/' + basenameIndex[basename][0];
                }
                const originalStemMatch = findEquivalentBasenameMatch(basename, originalStemIndex, false);
                if (originalStemMatch) {
                    return originalStemMatch;
                }
                const localStemMatch = findEquivalentBasenameMatch(basename, localStemIndex, true);
                if (localStemMatch) {
                    return localStemMatch;
                }
            }
        } catch(e) {}

        return null;
    }

    // Block requests to external CDNs that have no local copy
    function isExternalCDN(url) {
        try {
            const urlObj = new URL(normalizeUrl(url, window.location.href), window.location.href);
            if (urlObj.origin !== window.location.origin) {
                const hostname = urlObj.hostname.toLowerCase();
                const cdnMarkers = ['.b-cdn.', 'cdn.', '.cloudfront.', '.akamai', '.fastly.'];
                return cdnMarkers.some(marker => hostname.includes(marker));
            }
        } catch(e) {}
        return false;
    }

    // Check if URL is external (different origin)
    function isExternal(url) {
        try {
            const urlObj = new URL(normalizeUrl(url, window.location.href), window.location.href);
            return urlObj.origin !== window.location.origin;
        } catch(e) {
            return false;
        }
    }

    function isTrackingEndpoint(url) {
        try {
            const urlObj = new URL(normalizeUrl(url, window.location.href), window.location.href);
            const hostname = urlObj.hostname.toLowerCase();
            const path = (urlObj.pathname || '').toLowerCase();
            const combined = `${hostname}${path}`;
            const markers = [
                'monorail',
                'api/collect',
                '/collect',
                'web-pixels',
                'webpixels',
                'web-pixel',
                '/pixel',
                'pixel.',
                'shopifycloud/web-pixels-manager',
                'hotjar',
                'klaviyo',
                'cookiebot',
                'consentcdn',
            ];
            return markers.some(marker => combined.includes(marker));
        } catch(e) {
            return false;
        }
    }

    function buildMockResponse(url, method) {
        let mockData = {};
        if ((method || 'GET').toUpperCase() === 'GET' && String(url).includes('/rest/')) {
            mockData = [];
        }
        return new Response(JSON.stringify(mockData), {
            status: 200,
            statusText: 'OK (Mocked)',
            headers: { 'Content-Type': 'application/json' }
        });
    }

    function toComparableUrl(url) {
        if (!url) return '';
        try {
            return new URL(url, window.location.href).href;
        } catch (e) {
            return String(url);
        }
    }

    function comparableCandidates(urls) {
        const candidates = new Set();

        for (const url of urls) {
            if (!url) continue;
            const comparable = toComparableUrl(url);
            if (comparable) candidates.add(comparable);

            const localPath = getLocalPath(url, window.location.href);
            const comparableLocal = toComparableUrl(localPath);
            if (comparableLocal) candidates.add(comparableLocal);
        }

        candidates.delete('');
        return candidates;
    }

    function hasExistingAsset(tagName, attrName, urls) {
        const targetUrls = Array.isArray(urls) ? urls : [urls];
        const comparableTargets = comparableCandidates(targetUrls);
        if (!comparableTargets.size) return false;

        const elements = tagName === 'script'
            ? Array.from(document.scripts || [])
            : Array.from(document.querySelectorAll(tagName));

        return elements.some((element) => {
            const currentValue = element.getAttribute(attrName) || element[attrName] || '';
            if (!currentValue) return false;

            const currentComparable = toComparableUrl(currentValue);
            if (currentComparable && comparableTargets.has(currentComparable)) {
                return true;
            }

            const currentLocalPath = getLocalPath(currentValue, window.location.href);
            const currentComparableLocal = toComparableUrl(currentLocalPath);
            return currentComparableLocal && comparableTargets.has(currentComparableLocal);
        });
    }

    function neutralizeDuplicateNode(node, kind, url) {
        node.setAttribute('data-interceptor-duplicate', 'true');

        if (kind === 'script') {
            // Keep src intact so the app's onload callback can read it (avoids "Asset timed out undefined").
            // Changing type to a non-JS MIME prevents the browser from executing it again.
            node.type = 'application/json';
        } else if (kind === 'link') {
            node.setAttribute('data-interceptor-disabled', 'true');
            // Keep href intact to avoid browser warnings about invalid preload URLs.
            setTimeout(() => {
                if (node.parentNode) {
                    node.parentNode.removeChild(node);
                }
            }, 0);
        }

        // Use dispatchEvent so the browser sets event.target = node before calling onload.
        // Calling node.onload(event) directly leaves event.target = null, which causes
        // the app's load callback to read undefined as the asset URL → "Asset timed out undefined".
        setTimeout(() => {
            try { node.dispatchEvent(new Event('load')); } catch (e) {}
        }, 0);

        console.log('[DOM Interceptor] = Duplicate', kind, url);
        return node;
    }

    function isFrameworkChunkScript(url) {
        if (!url) return false;
        const value = String(url);
        return (
            value.includes('/_next/static/chunks/') ||
            value.includes('/_next/static/chunks/app/') ||
            value.includes('/assets/js/script_')
        );
    }

    const originalSetAttribute = Element.prototype.setAttribute;

    function toBrowserPath(localPath) {
        if (!localPath) return localPath;
        if (
            localPath.startsWith('/') ||
            localPath.startsWith('data:') ||
            localPath.startsWith('blob:') ||
            localPath.startsWith('http://') ||
            localPath.startsWith('https://') ||
            localPath.startsWith('//')
        ) {
            return localPath;
        }
        return '/' + localPath;
    }

    function encodeBrowserUrl(value) {
        if (!value || value.startsWith('data:') || value.startsWith('blob:')) {
            return value;
        }

        return value
            .replace(/ /g, '%20')
            .replace(/,/g, '%2C');
    }

    function rewriteSrcsetValue(srcset, referrer) {
        if (!srcset) return srcset;

        return srcset
            .split(',')
            .map((part) => {
                const trimmed = part.trim();
                if (!trimmed) return trimmed;

                const match = trimmed.match(/^(\S+)(?:\s+(.+))?$/);
                if (!match) return trimmed;

                const originalUrl = match[1];
                const descriptor = match[2] || '';
                const localPath = getLocalPath(originalUrl, referrer);
                const rewrittenUrl = localPath && localPath !== originalUrl
                    ? encodeBrowserUrl(toBrowserPath(localPath))
                    : encodeBrowserUrl(originalUrl);

                return descriptor ? `${rewrittenUrl} ${descriptor}` : rewrittenUrl;
            })
            .join(', ');
    }

    function rewriteMediaAttributeValue(tagName, attrName, value, referrer) {
        if (!value || typeof value !== 'string') return value;

        if (attrName === 'srcset') {
            return rewriteSrcsetValue(value, referrer);
        }

        const localPath = getLocalPath(value, referrer);
        if (localPath && localPath !== value) {
            return toBrowserPath(localPath);
        }

        return value;
    }

    function localizeMediaElement(node, referrer) {
        if (!node || !node.tagName) return node;

        const tagName = node.tagName.toLowerCase();
        if (!['img', 'source', 'video', 'audio', 'track'].includes(tagName)) {
            return node;
        }

        const mediaAttrs = ['src', 'srcset', 'poster'];
        for (const attrName of mediaAttrs) {
            const currentValue = node.getAttribute(attrName);
            if (!currentValue) continue;

            const rewrittenValue = rewriteMediaAttributeValue(
                tagName,
                attrName,
                currentValue,
                referrer || window.location.href
            );
            if (rewrittenValue && rewrittenValue !== currentValue) {
                originalSetAttribute.call(node, attrName, rewrittenValue);
                console.log('[DOM Interceptor] ✓', tagName, currentValue, '->', rewrittenValue);
            }
        }

        return node;
    }

    function localizeMediaTree(root, referrer) {
        if (!root || root.nodeType !== Node.ELEMENT_NODE) return;

        localizeMediaElement(root, referrer);
        if (typeof root.querySelectorAll !== 'function') return;

        root.querySelectorAll('img, source, video, audio, track').forEach((element) => {
            localizeMediaElement(element, referrer);
        });
    }

    function rewriteDynamicElement(node) {
        if (!node || !node.tagName) return node;

        const tagName = node.tagName.toLowerCase();
        if (['img', 'source', 'video', 'audio', 'track'].includes(tagName)) {
            return localizeMediaElement(node, window.location.href);
        }

        if (tagName === 'script') {
            const originalSrc = node.getAttribute('src') || node.src;
            if (!originalSrc) return node;

            const localPath = getLocalPath(originalSrc, window.location.href);
            const targetSrc = localPath || originalSrc;
            const allowFrameworkDuplicate = (
                isFrameworkChunkScript(originalSrc) || isFrameworkChunkScript(targetSrc)
            );
            if (!allowFrameworkDuplicate && hasExistingAsset('script', 'src', [originalSrc, targetSrc])) {
                return neutralizeDuplicateNode(node, 'script', targetSrc);
            }

            if (localPath && localPath !== originalSrc) {
                node.setAttribute('src', localPath);
                console.log('[DOM Interceptor] \u2713 script', originalSrc, '->', localPath);
                return node;
            }

            if (isTrackingEndpoint(originalSrc) || (isExternal(originalSrc) && isExternalCDN(originalSrc))) {
                node.removeAttribute('src');
                node.type = 'application/json';
                console.warn('[DOM Interceptor] \u2717 Blocked dynamic script:', originalSrc);
            }
            return node;
        }

        if (tagName === 'link') {
            const rel = (node.getAttribute('rel') || '').toLowerCase();
            if (!rel || !['preload', 'prefetch', 'modulepreload', 'stylesheet'].some(value => rel.includes(value))) {
                return node;
            }

            const originalHref = node.getAttribute('href') || node.href;
            if (!originalHref) return node;

            const localPath = getLocalPath(originalHref, window.location.href);
            const targetHref = localPath || originalHref;
            if (hasExistingAsset('link', 'href', [originalHref, targetHref])) {
                return neutralizeDuplicateNode(node, 'link', targetHref);
            }

            if (localPath && localPath !== originalHref) {
                node.setAttribute('href', localPath);
                console.log('[DOM Interceptor] \u2713 link', originalHref, '->', localPath);
                return node;
            }
        }

        return node;
    }

    const originalAppendChild = Node.prototype.appendChild;
    Node.prototype.appendChild = function(node) {
        return originalAppendChild.call(this, rewriteDynamicElement(node));
    };

    const originalInsertBefore = Node.prototype.insertBefore;
    Node.prototype.insertBefore = function(node, referenceNode) {
        return originalInsertBefore.call(this, rewriteDynamicElement(node), referenceNode);
    };

    const originalReplaceChild = Node.prototype.replaceChild;
    Node.prototype.replaceChild = function(newChild, oldChild) {
        return originalReplaceChild.call(this, rewriteDynamicElement(newChild), oldChild);
    };

    Element.prototype.setAttribute = function(name, value) {
        if (this && this.tagName && typeof name === 'string') {
            const tagName = this.tagName.toLowerCase();
            const attrName = name.toLowerCase();
            if (
                ['img', 'source', 'video', 'audio', 'track'].includes(tagName) &&
                ['src', 'srcset', 'poster'].includes(attrName)
            ) {
                const rewrittenValue = rewriteMediaAttributeValue(
                    tagName,
                    attrName,
                    String(value),
                    window.location.href
                );
                return originalSetAttribute.call(this, name, rewrittenValue);
            }
        }

        return originalSetAttribute.call(this, name, value);
    };

    function patchMediaProperty(proto, propertyName) {
        if (!proto) return;
        const descriptor = Object.getOwnPropertyDescriptor(proto, propertyName);
        if (!descriptor || typeof descriptor.set !== 'function') return;

        Object.defineProperty(proto, propertyName, {
            configurable: true,
            enumerable: descriptor.enumerable,
            get: descriptor.get
                ? function() {
                    return descriptor.get.call(this);
                }
                : undefined,
            set: function(value) {
                const tagName = this.tagName ? this.tagName.toLowerCase() : '';
                const rewrittenValue = rewriteMediaAttributeValue(
                    tagName,
                    propertyName.toLowerCase(),
                    String(value),
                    window.location.href
                );
                return descriptor.set.call(this, rewrittenValue);
            },
        });
    }

    patchMediaProperty(window.HTMLImageElement && window.HTMLImageElement.prototype, 'src');
    patchMediaProperty(window.HTMLImageElement && window.HTMLImageElement.prototype, 'srcset');
    patchMediaProperty(window.HTMLSourceElement && window.HTMLSourceElement.prototype, 'src');
    patchMediaProperty(window.HTMLSourceElement && window.HTMLSourceElement.prototype, 'srcset');
    patchMediaProperty(window.HTMLVideoElement && window.HTMLVideoElement.prototype, 'poster');
    patchMediaProperty(window.HTMLMediaElement && window.HTMLMediaElement.prototype, 'src');

    function observeMediaMutations() {
        const root = document.documentElement || document;
        if (!root || typeof MutationObserver === 'undefined') return;

        const observer = new MutationObserver((mutations) => {
            for (const mutation of mutations) {
                if (mutation.type === 'attributes') {
                    localizeMediaElement(mutation.target, window.location.href);
                    continue;
                }

                mutation.addedNodes.forEach((node) => {
                    localizeMediaTree(node, window.location.href);
                });
            }
        });

        observer.observe(root, {
            subtree: true,
            childList: true,
            attributes: true,
            attributeFilter: ['src', 'srcset', 'poster'],
        });
    }

    function installMediaLocalization() {
        localizeMediaTree(document.documentElement, window.location.href);
        observeMediaMutations();
    }

    const revealFallbackSeenAt = new WeakMap();

    function isNearViewport(element) {
        const rect = element.getBoundingClientRect();
        const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
        return rect.bottom >= -viewportHeight * 0.15 && rect.top <= viewportHeight * 1.15;
    }

    function releaseStaleRevealState() {
        if (!document.documentElement.classList.contains('sr')) return;

        const now = performance.now();
        document.querySelectorAll('[data-reveal]').forEach((element) => {
            if (!isNearViewport(element)) {
                revealFallbackSeenAt.delete(element);
                return;
            }

            const styles = getComputedStyle(element);
            const isHidden = styles.visibility === 'hidden' || Number(styles.opacity || '1') <= 0.01;
            if (!isHidden) {
                revealFallbackSeenAt.delete(element);
                return;
            }

            const firstSeenAt = revealFallbackSeenAt.get(element);
            if (typeof firstSeenAt !== 'number') {
                revealFallbackSeenAt.set(element, now);
                return;
            }

            if (now - firstSeenAt < 1800) {
                return;
            }

            element.style.visibility = 'visible';
            element.style.opacity = '1';
            element.removeAttribute('data-reveal');
            element.setAttribute('data-interceptor-reveal-fallback', 'true');
            revealFallbackSeenAt.delete(element);
            console.log('[DOM Interceptor] ✓ reveal fallback', element.tagName.toLowerCase(), element.className || element.id || '');
        });
    }

    let revealFallbackRaf = 0;
    function scheduleRevealFallback() {
        if (revealFallbackRaf) return;
        revealFallbackRaf = requestAnimationFrame(() => {
            revealFallbackRaf = 0;
            releaseStaleRevealState();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            installMediaLocalization();
            scheduleRevealFallback();
        }, { once: true });
    } else {
        installMediaLocalization();
        scheduleRevealFallback();
    }

    window.addEventListener('scroll', scheduleRevealFallback, { passive: true });
    window.addEventListener('resize', scheduleRevealFallback);
    window.addEventListener('load', () => {
        scheduleRevealFallback();
        setTimeout(scheduleRevealFallback, 1500);
        setTimeout(scheduleRevealFallback, 4000);
    });

    // Intercept fetch()
    const originalFetch = window.fetch;
    window.fetch = function(url, options) {
        const referrer = (options && options.referrer) || document.currentScript?.src || window.location.href;
        const method = (options && options.method) || 'GET';
        const localPath = getLocalPath(url, referrer);

        if (localPath) {
            console.log('[Fetch Interceptor] \u2713', url, '->', localPath);
            return originalFetch(localPath, options);
        }

        if (isTrackingEndpoint(url)) {
            console.warn('[Fetch Interceptor] \u2717 Blocked tracking call:', url);
            return Promise.resolve(buildMockResponse(url, method));
        }

        // CRITICAL FIX: Block all external requests that have no local mapping
        // This prevents 406/CORS errors from leaking to real APIs (Supabase, etc)
        if (isExternal(url)) {
            console.warn('[Fetch Interceptor] \u2717 Blocked external leak:', url);
            return Promise.resolve(buildMockResponse(url, method));
        }

        return originalFetch(url, options);
    };

    // Intercept XMLHttpRequest
    const originalOpen = XMLHttpRequest.prototype.open;
    const originalSend = XMLHttpRequest.prototype.send;

    XMLHttpRequest.prototype.open = function(method, url, ...args) {
        const referrer = document.currentScript?.src || window.location.href;
        const localPath = getLocalPath(url, referrer);

        // Store original URL for send() interception
        this._interceptedUrl = url;
        this._hasLocalMapping = !!localPath;

        if (localPath) {
            console.log('[XHR Interceptor] \u2713', url, '->', localPath);
            return originalOpen.call(this, method, localPath, ...args);
        }

        // CRITICAL FIX: Allow open() to proceed, but intercept send() for external URLs
        return originalOpen.call(this, method, url, ...args);
    };

    XMLHttpRequest.prototype.send = function(...args) {
        // If URL is external and has no local mapping, block and return mock
        if (this._interceptedUrl && !this._hasLocalMapping && (
            isTrackingEndpoint(this._interceptedUrl) || isExternal(this._interceptedUrl)
        )) {
            if (isTrackingEndpoint(this._interceptedUrl)) {
                console.warn('[XHR Interceptor] \u2717 Blocked tracking call:', this._interceptedUrl);
            } else {
                console.warn('[XHR Interceptor] \u2717 Blocked external leak:', this._interceptedUrl);
            }

            // Simulate successful response
            Object.defineProperty(this, 'status', { value: 200, writable: false });
            Object.defineProperty(this, 'statusText', { value: 'OK (Mocked)', writable: false });
            Object.defineProperty(this, 'responseText', {
                value: this._interceptedUrl.includes('/rest/') ? '[]' : '{}',
                writable: false
            });
            Object.defineProperty(this, 'response', {
                value: this._interceptedUrl.includes('/rest/') ? '[]' : '{}',
                writable: false
            });
            Object.defineProperty(this, 'readyState', { value: 4, writable: false });

            // Trigger load event asynchronously
            setTimeout(() => {
                if (this.onload) this.onload({ type: 'load', target: this });
                if (this.onreadystatechange) this.onreadystatechange({ type: 'readystatechange', target: this });
            }, 0);

            return;
        }

        return originalSend.apply(this, args);
    };

    console.log('[Fetch Interceptor] Installed with', Object.keys(resourceMap).length, 'mappings');
    console.log('[Fetch Interceptor] Basename index:', Object.keys(basenameIndex).length, 'files');
})();
