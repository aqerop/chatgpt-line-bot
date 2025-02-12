import os
from dotenv import load_dotenv

load_dotenv()

LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
SERPAPI_API_KEY = os.getenv('SERPAPI_API_KEY')
GPT_METHOD = os.getenv('GPT_METHOD', 'zhipuai')  # 기본값 설정
GPT_API_KEY = os.getenv('GPT_API_KEY')

# RAPID API 설정
RAPID = {
    "key": os.getenv('RAPID_API_KEY', '')
} 