"""
DeepMirror WebSites - Fachada que mantém interface pública

Delegates to single_page.SinglePageService while preserving the
public contract used by app.py and CLI callers.
"""
import re
import shutil
from urllib.parse import urlparse

from single_page.service import SinglePageService


class WebsiteDownloader:
    """
    Main downloader class - maintains public interface for app.py
    """
    def __init__(self, url, output_dir, log_callback=None):
        self._service = SinglePageService(url, output_dir, log_callback)

    def log(self, message):
        """Send log message to callback"""
        self._service.log(message)

    def process(self):
        """
        Main processing method - orchestrates the download flow
        """
        return self._service.process()


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
