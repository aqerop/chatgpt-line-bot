import requests
from icrawler import ImageDownloader
from icrawler.builtin import GoogleImageCrawler
from pathlib import Path
import random
from serpapi import search  # GoogleSearch 대신 search 사용


class CustomLinkPrinter(ImageDownloader):
    """Only get image urls instead of store
    
    References
    ----------
    [Issue#73](https://github.com/hellock/icrawler/issues/73)
    """
    file_urls = []

    def get_filename(self, task, default_ext):
        file_idx = self.fetched_num + self.file_idx_offset
        return '{:04d}.{}'.format(file_idx, default_ext)

    def download(self, task, default_ext, timeout=5, max_retry=3, overwrite=False, **kwargs):
        file_url = task['file_url']
        filename = self.get_filename(task, default_ext)

        task['success'] = True
        task['filename'] = filename

        if not self.signal.get('reach_max_num'):
            self.file_urls.append(file_url)

        self.fetched_num += 1

        if self.reach_max_num():
            self.signal.set(reach_max_num=True)

        return


class ImageCrawler:
    """Crawl the Image"""
    def __init__(self, engine: str = 'icrawler', nums: int = 1, api_key: str = None) -> None:
        self.engine = engine
        self.nums = nums
        self.api_key = api_key

    def get_url(self, query: str) -> str:
        """Get image url from different sources"""
        if self.engine == 'icrawler':
            return self._icrawler_search(query)
        elif self.engine == 'serpapi':
            return self._serpapi_search(query)
        return None

    def _icrawler_search(self, query: str) -> str:
        """Use icrawler to get images"""
        import tempfile
        import os
        import requests
        from urllib.parse import urlparse
        
        # 임시 디렉토리 생성
        with tempfile.TemporaryDirectory() as temp_dir:
            crawler = GoogleImageCrawler(
                downloader_cls=CustomLinkPrinter,
                storage={'root_dir': temp_dir},
                parser_threads=1,
                downloader_threads=1
            )
            
            # SSL 검증 비활성화 (필요한 경우)
            crawler.session.verify = False
            crawler.downloader.file_urls = []
            
            try:
                crawler.crawl(
                    keyword=query,
                    max_num=5  # 여러 개 시도
                )
                
                # 유효한 HTTPS URL 찾기
                for url in crawler.downloader.file_urls:
                    try:
                        # URL이 HTTPS가 아니면 변환 시도
                        if not url.startswith('https'):
                            url = url.replace('http:', 'https:', 1)
                        
                        # URL 유효성 검사
                        response = requests.head(url, timeout=5, verify=False)
                        if response.status_code == 200:
                            return url
                    except:
                        continue
                
                return None
                
            except Exception as e:
                print(f"iCrawler error: {e}")
                return None

    def _serpapi_search(self, query: str) -> str:
        """Use SerpAPI to get images"""
        if not self.api_key:
            return None
            
        try:
            params = {
                "engine": "google",
                "q": query,
                "tbm": "isch",
                "num": self.nums,
                "api_key": self.api_key,
                "ijn": "0",
                "gl": "kr",
                "hl": "ko",
                "safe": "active"
            }
            
            results = search(params)
            
            if 'images_results' in results and results['images_results']:
                for img in results['images_results']:
                    url = img.get('original')
                    if url:
                        # HTTPS 변환
                        if not url.startswith('https'):
                            url = url.replace('http:', 'https:', 1)
                        return url
                            
            return None
            
        except Exception as e:
            print(f"SerpAPI error: {e}")
            return None

    def _is_img_url(self, url) -> bool:
        """Check the image url is valid or invalid"""
        try:
            response = requests.head(url)
            content_type = response.headers['content-type']
            return content_type.startswith('image/')
        except requests.RequestException:
            return False
        except Exception as e:
            return False

    def _icrawler(self, search_query: str, prefix_name: str = 'tmp') -> list[str]:
        """Icrawler for google search images (Free)"""
        google_crawler = GoogleImageCrawler(
            downloader_cls=CustomLinkPrinter,
            storage={'root_dir': self.image_save_path},
            parser_threads=4,
            downloader_threads=4
        )

        # TODO: https://github.com/hellock/icrawler/issues/40
        google_crawler.session.verify = False
        google_crawler.downloader.file_urls = []

        google_crawler.crawl(
            keyword=search_query,
            max_num=self.nums,
            file_idx_offset=0
        )
        img_urls = google_crawler.downloader.file_urls
        print(f'Get image urls: {img_urls}')

        return img_urls[:self.nums]

    def _serpapi_search_multiple(self, query: str) -> list[str]:
        """Use SerpAPI to get multiple images"""
        if not self.api_key:
            return None
        
        try:
            params = {
                "engine": "google",
                "q": query,
                "tbm": "isch",
                "num": self.nums * 2,  # 여유있게 검색
                "api_key": self.api_key,
                "ijn": "0",
                "gl": "kr",
                "hl": "ko",
                "safe": "active"
            }
            
            results = search(params)
            
            if 'images_results' in results and results['images_results']:
                urls = []
                for img in results['images_results']:
                    url = img.get('original')
                    if url:
                        # HTTPS 변환
                        if not url.startswith('https'):
                            url = url.replace('http:', 'https:', 1)
                        urls.append(url)
                        if len(urls) >= self.nums:
                            break
                return urls if urls else None
                    
            return None
            
        except Exception as e:
            print(f"SerpAPI error: {e}")
            return None

    def _icrawler_search_multiple(self, query: str) -> list[str]:
        """Use icrawler to get multiple images"""
        import tempfile
        import os
        import requests
        from urllib.parse import urlparse
        
        # 임시 디렉토리 생성
        with tempfile.TemporaryDirectory() as temp_dir:
            crawler = GoogleImageCrawler(
                downloader_cls=CustomLinkPrinter,
                storage={'root_dir': temp_dir},
                parser_threads=1,
                downloader_threads=1
            )
            
            # SSL 검증 비활성화 (필요한 경우)
            crawler.session.verify = False
            crawler.downloader.file_urls = []
            
            try:
                crawler.crawl(
                    keyword=query,
                    max_num=self.nums * 3  # 여유있게 검색
                )
                
                # 유효한 HTTPS URL 찾기
                valid_urls = []
                for url in crawler.downloader.file_urls:
                    try:
                        # URL이 HTTPS가 아니면 변환 시도
                        if not url.startswith('https'):
                            url = url.replace('http:', 'https:', 1)
                        
                        # URL 유효성 검사
                        response = requests.head(url, timeout=5, verify=False)
                        if response.status_code == 200:
                            valid_urls.append(url)
                            if len(valid_urls) >= self.nums:
                                break
                    except:
                        continue
                
                return valid_urls if valid_urls else None
                
            except Exception as e:
                print(f"iCrawler error: {e}")
                return None
