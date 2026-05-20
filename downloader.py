"""
DeepMirror WebSites - Fachada que mantém interface pública

Delegates to single_page.SinglePageService while preserving the
public contract used by app.py and CLI callers.
"""
import shutil

from core.path_safety import site_name_from_url
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
    return site_name_from_url(url)


def zip_directory(folder_path, output_path):
    """Create a zip file from a directory"""
    base_name = output_path.replace('.zip', '')
    shutil.make_archive(base_name, 'zip', folder_path)
    return base_name + '.zip'
